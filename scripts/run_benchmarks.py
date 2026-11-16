#!/usr/bin/env python3
"""Orchestrateur des tests de charge (wrk) : produit les fichiers CSV de données brutes.

Protocole (dossier de référence, PARTIE 4) :
  pour chaque (endpoint, niveau de connexions, technologie) :
    1. redémarrage du serveur (un seul serveur tourne à la fois) ;
    2. échauffement (résultats ignorés) : 10 s, 30 s pour C# (JIT) ;
    3. N répétitions de D secondes, chacune mesurée avec wrk ;
       pendant chaque répétition, le CPU et la mémoire du serveur sont échantillonnés chaque seconde.

Sorties (dans results/<dossier>/) :
  raw_runs.csv          une ligne par répétition (débit, latences, erreurs, CPU, RSS)
  resource_samples.csv  un échantillon CPU/RSS par seconde et par répétition
  run_config.json       paramètres du test
  environment.txt       machine et versions des outils

L'exécution est REPRENABLE : relancez la même commande (même --out) après une
interruption ; les répétitions déjà enregistrées sont sautées.

Exemples :
  python3 scripts/run_benchmarks.py --profile smoke            # essai de 2 minutes
  python3 scripts/run_benchmarks.py --profile reduced          # ~2 h  (recommandé)
  python3 scripts/run_benchmarks.py --profile full             # ~42 h (protocole nominal)
  python3 scripts/run_benchmarks.py --profile reduced --techs php csharp --endpoints tasks
"""
import argparse
import csv
import json
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUN_DIR = ROOT / "run"
SCRIPTS = ROOT / "scripts"
PORTS = {"python": 8080, "php": 8081, "javascript": 8082, "csharp": 8083}
ENDPOINTS = {"tasks": "/tasks", "compute30": "/compute?n=30", "compute35": "/compute?n=35"}
PROFILES = {
    #            durée, échauffement, échauffement C#, répétitions, niveaux
    "full":    dict(duration=30, warmup=10, warmup_csharp=30, reps=10, conns=[10, 50, 100, 200]),
    "reduced": dict(duration=10, warmup=5, warmup_csharp=15, reps=10, conns=[10, 50, 100, 200]),
    "smoke":   dict(duration=3, warmup=2, warmup_csharp=4, reps=2, conns=[10, 50]),
}

RAW_FIELDS = [
    "timestamp", "tech", "endpoint", "connections", "rep", "duration_s", "wrk_threads",
    "requests", "success_requests", "throughput_rps", "raw_rps", "transfer_mb_s",
    "lat_mean_ms", "lat_stdev_ms", "lat_min_ms", "lat_max_ms", "p50_ms", "p90_ms", "p95_ms", "p99_ms",
    "err_status", "err_timeout", "err_connect", "err_read", "err_write", "error_rate_pct",
    "cpu_pct_mean", "cpu_pct_max", "rss_mb_mean", "rss_mb_max", "pss_mb_mean", "pss_mb_max",
    "settle_wait_s", "restarted_before",
]
SAMPLE_FIELDS = ["tech", "endpoint", "connections", "rep", "t_s", "cpu_pct", "rss_mb", "pss_mb"]

CLK_TCK = os.sysconf("SC_CLK_TCK")
PAGE = os.sysconf("SC_PAGE_SIZE")


# --------------------------------------------------------------------------- /proc
def root_pids(tech):
    files = [RUN_DIR / "php" / "nginx.pid", RUN_DIR / "php" / "php-fpm.pid"] if tech == "php" else [RUN_DIR / f"{tech}.pid"]
    pids = []
    for f in files:
        try:
            pids.append(int(f.read_text().strip()))
        except (OSError, ValueError):
            pass
    return pids


def process_table():
    """{pid: (ppid, ticks_cpu)} pour tous les processus visibles."""
    table = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat") as fh:
                data = fh.read()
            fields = data.rpartition(")")[2].split()
            table[int(entry)] = (int(fields[1]), int(fields[11]) + int(fields[12]))
        except (OSError, IndexError, ValueError):
            continue
    return table


def tree(roots, table):
    """Racines + tous leurs descendants."""
    children = {}
    for pid, (ppid, _) in table.items():
        children.setdefault(ppid, []).append(pid)
    seen, stack = set(), [p for p in roots if p in table]
    while stack:
        p = stack.pop()
        if p in seen:
            continue
        seen.add(p)
        stack.extend(children.get(p, []))
    return seen


def memory_kb(pid):
    """(RSS en Ko, PSS en Ko). Le PSS répartit équitablement les pages partagées
    (utile pour PHP-FPM dont les processus partagent OPcache/APCu)."""
    rss = pss = 0
    try:
        with open(f"/proc/{pid}/statm") as fh:
            rss = int(fh.read().split()[1]) * PAGE // 1024
    except (OSError, IndexError, ValueError):
        pass
    try:
        with open(f"/proc/{pid}/smaps_rollup") as fh:
            for line in fh:
                if line.startswith("Pss:"):
                    pss = int(line.split()[1])
                    break
    except (OSError, ValueError):
        pss = rss  # repli : smaps_rollup indisponible
    return rss, pss


class ResourceSampler(threading.Thread):
    """Échantillonne CPU (% d'UN cœur, cumulé sur tout l'arbre de processus du
    serveur) et mémoire (RSS/PSS cumulés) une fois par seconde."""

    def __init__(self, tech, interval=1.0):
        super().__init__(daemon=True)
        self.tech, self.interval = tech, interval
        self.stop_evt = threading.Event()
        self.samples = []  # (t_s, cpu_pct, rss_mb, pss_mb)

    def run(self):
        t0 = time.monotonic()
        table = process_table()
        prev = {p: table[p][1] for p in tree(root_pids(self.tech), table)}
        prev_t = t0
        while not self.stop_evt.wait(self.interval):
            now = time.monotonic()
            table = process_table()
            pids = tree(root_pids(self.tech), table)
            cur = {p: table[p][1] for p in pids}
            dticks = sum(cur[p] - prev[p] for p in cur if p in prev)
            cpu = dticks / CLK_TCK / (now - prev_t) * 100.0
            mem = [memory_kb(p) for p in pids]
            rss = sum(m[0] for m in mem) / 1024.0
            pss = sum(m[1] for m in mem) / 1024.0
            self.samples.append((now - t0, cpu, rss, pss))
            prev, prev_t = cur, now

    def stop(self):
        self.stop_evt.set()
        self.join(timeout=5)


# --------------------------------------------------------------------------- serveurs & wrk
def server(action, tech, quiet=True):
    r = subprocess.run(["bash", str(SCRIPTS / "server.sh"), action, tech],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, stdin=subprocess.DEVNULL, timeout=180)
    if r.returncode != 0:
        raise RuntimeError(f"server.sh {action} {tech} a échoué :\n{r.stdout}")
    return r.stdout


def run_wrk(url, conns, duration, threads, timeout_s, cpuset=None):
    cmd = ["wrk", f"-t{min(threads, conns)}", f"-c{conns}", f"-d{duration}s", f"--timeout", f"{timeout_s}s",
           "-s", str(SCRIPTS / "report.lua"), url]
    if cpuset:
        cmd = ["taskset", "-c", cpuset] + cmd
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                       stdin=subprocess.DEVNULL, timeout=duration + timeout_s + 60)
    m = re.search(r"^WRKCSV (.*)$", r.stdout, re.M)
    if r.returncode != 0 or not m:
        raise RuntimeError(f"wrk a échoué (code {r.returncode}) :\n{r.stdout[-800:]}")
    return {k: float(v) for k, v in (kv.split("=") for kv in m.group(1).split())}


def to_row(tech, endpoint, conns, rep, duration, threads, w, sampler):
    dur = w["duration_us"] / 1e6
    ok = w["requests"] - w["err_status"]
    attempts = w["requests"] + w["err_timeout"] + w["err_connect"] + w["err_read"] + w["err_write"]
    errs = w["err_status"] + w["err_timeout"] + w["err_connect"] + w["err_read"] + w["err_write"]
    s = sampler.samples
    cpu = [x[1] for x in s] or [0.0]
    rss = [x[2] for x in s] or [0.0]
    pss = [x[3] for x in s] or [0.0]
    ms = lambda us: round(us / 1000.0, 3)
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"), "tech": tech, "endpoint": endpoint,
        "connections": conns, "rep": rep, "duration_s": round(dur, 3), "wrk_threads": min(threads, conns),
        "requests": int(w["requests"]), "success_requests": int(ok),
        "throughput_rps": round(ok / dur, 3), "raw_rps": round(w["requests"] / dur, 3),
        "transfer_mb_s": round(w["bytes"] / 1048576 / dur, 3),
        "lat_mean_ms": ms(w["lat_mean_us"]), "lat_stdev_ms": ms(w["lat_stdev_us"]),
        "lat_min_ms": ms(w["lat_min_us"]), "lat_max_ms": ms(w["lat_max_us"]),
        "p50_ms": ms(w["p50_us"]), "p90_ms": ms(w["p90_us"]), "p95_ms": ms(w["p95_us"]), "p99_ms": ms(w["p99_us"]),
        "err_status": int(w["err_status"]), "err_timeout": int(w["err_timeout"]), "err_connect": int(w["err_connect"]),
        "err_read": int(w["err_read"]), "err_write": int(w["err_write"]),
        "error_rate_pct": round(100.0 * errs / attempts, 4) if attempts else 0.0,
        "cpu_pct_mean": round(statistics.fmean(cpu), 2), "cpu_pct_max": round(max(cpu), 2),
        "rss_mb_mean": round(statistics.fmean(rss), 2), "rss_mb_max": round(max(rss), 2),
        "pss_mb_mean": round(statistics.fmean(pss), 2), "pss_mb_max": round(max(pss), 2),
    }


def tree_cpu_pct(tech, window=0.5):
    """CPU instantané (% d'un cœur) de l'arborescence du serveur sur `window` secondes."""
    t1 = process_table()
    before = {p: t1[p][1] for p in tree(root_pids(tech), t1)}
    t0 = time.monotonic()
    time.sleep(window)
    t2 = process_table()
    now = tree(root_pids(tech), t2)
    dt = time.monotonic() - t0
    return sum(t2[p][1] - before[p] for p in now if p in before) / CLK_TCK / dt * 100.0


def sequential_warmup(url, n=3):
    import http.client
    from urllib.parse import urlsplit
    u = urlsplit(url)
    for _ in range(n):
        try:
            c = http.client.HTTPConnection(u.hostname, u.port, timeout=180)
            c.request("GET", u.path + ("?" + u.query if u.query else ""))
            c.getresponse().read()
            c.close()
        except OSError:
            pass


def settle(tech, url, conns, cfg):
    """Attend que le serveur soit au repos (CPU < 5 % pendant 2 mesures de 0,5 s).

    Pourquoi : quand wrk s'arrête, les requêtes déjà envoyées continuent de s'exécuter côté serveur
    (surtout sur /compute?n=35 : des dizaines de requêtes de plusieurs secondes). Sans cette attente,
    ce travail résiduel polluerait la répétition suivante. Si le serveur n'est pas au repos après
    `settle_max` secondes, on le redémarre (état propre) et on le ré-échauffe brièvement ;
    la répétition est alors marquée restarted_before=1 dans le CSV.
    Retourne (secondes_attendues, redémarré)."""
    t0 = time.monotonic()
    calm = 0
    while True:
        calm = calm + 1 if tree_cpu_pct(tech) < 5.0 else 0
        if calm >= 2:
            return time.monotonic() - t0, False
        if time.monotonic() - t0 > cfg["settle_max"]:
            break
    print(f"   ! serveur encore occupé après {cfg['settle_max']} s : redémarrage", flush=True)
    server("stop", tech)
    server("start", tech)
    if tech == "csharp":   # C# : le JIT doit être réchauffé de nouveau
        run_wrk(url, min(conns, 10), 10, cfg["threads"], cfg["timeout_s"], cfg["wrk_cpuset"])
    else:
        sequential_warmup(url)
    return time.monotonic() - t0, True


def append_csv(path, fields, rows):
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=fields)
        if new:
            wr.writeheader()
        wr.writerows(rows)
        fh.flush()
        os.fsync(fh.fileno())


def already_done(path):
    done = set()
    if path.exists():
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                done.add((r["tech"], r["endpoint"], int(r["connections"]), int(r["rep"])))
    return done


def fmt_duration(sec):
    h, rem = divmod(int(sec), 3600)
    return f"{h} h {rem // 60:02d} min"


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", choices=PROFILES, default="reduced")
    ap.add_argument("--techs", nargs="+", choices=PORTS, default=list(PORTS))
    ap.add_argument("--endpoints", nargs="+", choices=ENDPOINTS, default=list(ENDPOINTS))
    ap.add_argument("--conns", nargs="+", type=int, help="niveaux de connexions (défaut : selon le profil)")
    ap.add_argument("--reps", type=int, help="répétitions par configuration")
    ap.add_argument("--duration", type=int, help="durée d'une répétition en secondes")
    ap.add_argument("--warmup", type=int, help="échauffement (s), toutes technologies sauf C#")
    ap.add_argument("--warmup-csharp", type=int, help="échauffement (s) pour C#")
    ap.add_argument("--threads", type=int, default=2, help="threads wrk (défaut 2)")
    ap.add_argument("--timeout", type=int, default=30, help="timeout wrk par requête en s (défaut 30)")
    ap.add_argument("--settle-max", type=int, default=20, help="attente max (s) du retour au repos du serveur entre deux répétitions, avant redémarrage (défaut 20)")
    ap.add_argument("--out", default=None, help="dossier de sortie (défaut : results/run_<date>)")
    ap.add_argument("--wrk-cpuset", default=os.environ.get("WRK_CPUSET"), help='ex. "0" : épingle wrk à ces cœurs')
    ap.add_argument("--seed", type=int, default=42, help="graine de l'ordre aléatoire des technologies")
    ap.add_argument("--skip-verify", action="store_true", help="ne pas lancer la vérification d'équivalence")
    ap.add_argument("--dry-run", action="store_true", help="affiche le plan et la durée estimée, sans rien lancer")
    a = ap.parse_args()

    p = PROFILES[a.profile]
    cfg = dict(
        profile=a.profile, duration=a.duration or p["duration"], warmup=a.warmup if a.warmup is not None else p["warmup"],
        warmup_csharp=a.warmup_csharp if a.warmup_csharp is not None else p["warmup_csharp"],
        reps=a.reps or p["reps"], conns=a.conns or p["conns"], threads=a.threads, timeout_s=a.timeout,
        techs=a.techs, endpoints=a.endpoints, seed=a.seed, settle_max=a.settle_max, wrk_cpuset=a.wrk_cpuset,
        server_cpuset=os.environ.get("SERVER_CPUSET"),
    )

    out = Path(a.out) if a.out else ROOT / "results" / f"run_{datetime.now():%Y%m%d_%H%M}"
    out = out if out.is_absolute() else ROOT / out
    raw_csv, samples_csv = out / "raw_runs.csv", out / "resource_samples.csv"

    blocks = [(e, c, t) for e in cfg["endpoints"] for c in cfg["conns"] for t in cfg["techs"]]
    per_block = lambda t: 6 + (cfg["warmup_csharp"] if t == "csharp" else cfg["warmup"]) + cfg["reps"] * (cfg["duration"] + 3)
    est = sum(per_block(t) for _, _, t in blocks)
    print(f"Plan : {len(blocks)} configurations × {cfg['reps']} répétitions de {cfg['duration']} s "
          f"= {len(blocks) * cfg['reps']} essais ; durée estimée {fmt_duration(est)}")
    print(f"Sortie : {out}")
    if a.dry_run:
        return

    if shutil.which("wrk") is None:
        sys.exit("wrk est introuvable (sudo apt install wrk).")
    out.mkdir(parents=True, exist_ok=True)
    (out / "run_config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    subprocess.run(["bash", str(SCRIPTS / "env_info.sh")], stdout=subprocess.DEVNULL, check=False)
    shutil.copyfile(ROOT / "results" / "environment.txt", out / "environment.txt")

    if not a.skip_verify:
        print("Vérification d'équivalence préalable…")
        for t in cfg["techs"]:
            server("start", t)
        v = subprocess.run([sys.executable, str(SCRIPTS / "verify_equivalence.py")], text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        print(v.stdout)
        for t in cfg["techs"]:
            server("stop", t)
        if v.returncode != 0:
            sys.exit("Équivalence non vérifiée : test de charge annulé.")

    done = already_done(raw_csv)
    total = len(blocks) * cfg["reps"]
    counter = len(done)
    t_start = time.monotonic()
    try:
        # Ordre des technologies mélangé (graine fixe) dans chaque (endpoint, niveau) pour éviter qu'une
        # technologie soit systématiquement mesurée à un moment (température, bruit) particulier.
        for e in cfg["endpoints"]:
            for c in cfg["conns"]:
                order = list(cfg["techs"])
                random.Random(f"{cfg['seed']}-{e}-{c}").shuffle(order)
                for tech in order:
                    missing = [r for r in range(1, cfg["reps"] + 1) if (tech, e, c, r) not in done]
                    if not missing:
                        continue
                    url = f"http://127.0.0.1:{PORTS[tech]}{ENDPOINTS[e]}"
                    print(f"\n== {tech} | {e} | {c} connexions : redémarrage + échauffement ==", flush=True)
                    for other in PORTS:
                        server("stop", other)
                    server("start", tech)
                    warm = cfg["warmup_csharp"] if tech == "csharp" else cfg["warmup"]
                    run_wrk(url, c, warm, cfg["threads"], cfg["timeout_s"], cfg["wrk_cpuset"])
                    for rep in missing:
                        waited, restarted = settle(tech, url, c, cfg)
                        sampler = ResourceSampler(tech)
                        sampler.start()
                        try:
                            w = run_wrk(url, c, cfg["duration"], cfg["threads"], cfg["timeout_s"], cfg["wrk_cpuset"])
                        finally:
                            sampler.stop()
                        row = to_row(tech, e, c, rep, cfg["duration"], cfg["threads"], w, sampler)
                        row["settle_wait_s"], row["restarted_before"] = round(waited, 1), int(restarted)
                        append_csv(raw_csv, RAW_FIELDS, [row])
                        append_csv(samples_csv, SAMPLE_FIELDS, [
                            dict(tech=tech, endpoint=e, connections=c, rep=rep, t_s=round(s[0], 1),
                                 cpu_pct=round(s[1], 2), rss_mb=round(s[2], 2), pss_mb=round(s[3], 2))
                            for s in sampler.samples])
                        counter += 1
                        elapsed = time.monotonic() - t_start
                        print(f"[{counter}/{total}] rep {rep}/{cfg['reps']}  {row['throughput_rps']:>10.1f} req/s  "
                              f"p50 {row['p50_ms']:.2f} ms  p99 {row['p99_ms']:.2f} ms  err {row['error_rate_pct']:.2f} %  "
                              f"CPU {row['cpu_pct_mean']:.0f} %  RSS {row['rss_mb_mean']:.0f} Mo"
                              + (f"  [attente {waited:.0f} s{', REDÉMARRÉ' if restarted else ''}]" if waited > 3 else ""), flush=True)
                    server("stop", tech)
    except KeyboardInterrupt:
        print("\nInterrompu : relancez la même commande pour reprendre.")
    finally:
        for t in PORTS:
            server("stop", t)
    print(f"\nTerminé. Données : {raw_csv}\nPuis : python3 scripts/aggregate.py {out}")


if __name__ == "__main__":
    main()
