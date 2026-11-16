#!/usr/bin/env python3
"""Agrège raw_runs.csv en summary.csv : une ligne par (endpoint, connexions, technologie)
avec moyenne, écart-type et intervalle de confiance à 95 % sur les répétitions.

    python3 scripts/aggregate.py results/run_YYYYMMDD_HHMM

Sorties dans le même dossier : summary.csv (+ affichage d'un résumé lisible).
Bibliothèque standard uniquement.
"""
import csv
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

# t de Student bilatéral 95 %, par degrés de liberté
T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262,
       10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110,
       18: 2.101, 19: 2.093, 20: 2.086, 25: 2.060, 30: 2.042, 40: 2.021, 60: 2.000}

METRICS = ["throughput_rps", "lat_mean_ms", "p50_ms", "p95_ms", "p99_ms", "error_rate_pct",
           "cpu_pct_mean", "rss_mb_mean", "rss_mb_max", "pss_mb_mean"]
TECH_ORDER = ["python", "php", "javascript", "csharp"]
TECH_LABEL = {"python": "Python/FastAPI", "php": "PHP-FPM", "javascript": "JS natif (Node)", "csharp": "C#/ASP.NET Core"}


def t_crit(df):
    if df < 1:
        return float("nan")
    keys = sorted(T95)
    for k in keys:
        if df <= k:
            return T95[k]
    return 1.96


def ci95(values):
    n = len(values)
    if n < 2:
        return float("nan")
    return t_crit(n - 1) * statistics.stdev(values) / math.sqrt(n)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    folder = Path(sys.argv[1])
    raw = folder / "raw_runs.csv"
    groups = defaultdict(list)
    with open(raw, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            groups[(r["endpoint"], int(r["connections"]), r["tech"])].append(r)

    fields = ["endpoint", "connections", "tech", "n_reps"]
    for m in METRICS:
        fields += [f"{m}_mean", f"{m}_std", f"{m}_ci95"]
    rows = []
    for (endpoint, conns, tech), runs in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1], TECH_ORDER.index(kv[0][2]))):
        row = {"endpoint": endpoint, "connections": conns, "tech": tech, "n_reps": len(runs)}
        for m in METRICS:
            vals = [float(r[m]) for r in runs]
            row[f"{m}_mean"] = round(statistics.fmean(vals), 3)
            row[f"{m}_std"] = round(statistics.stdev(vals), 3) if len(vals) > 1 else ""
            c = ci95(vals)
            row[f"{m}_ci95"] = round(c, 3) if c == c else ""
        rows.append(row)

    out = folder / "summary.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=fields)
        wr.writeheader()
        wr.writerows(rows)
    print(f"{len(rows)} configurations -> {out}\n")

    # Résumé lisible
    cur = None
    for r in rows:
        key = (r["endpoint"], r["connections"])
        if key != cur:
            cur = key
            print(f"\n[{r['endpoint']}] {r['connections']} connexions")
            print(f"  {'technologie':<18}{'req/s':>11}{'± IC95':>10}{'p50 ms':>10}{'p95 ms':>10}{'p99 ms':>10}{'err %':>8}{'CPU %':>8}{'RSS Mo':>9}  n")
        ci = r["throughput_rps_ci95"]
        print(f"  {TECH_LABEL[r['tech']]:<18}{r['throughput_rps_mean']:>11.1f}{(ci if ci != '' else float('nan')):>10.1f}"
              f"{r['p50_ms_mean']:>10.2f}{r['p95_ms_mean']:>10.2f}{r['p99_ms_mean']:>10.2f}"
              f"{r['error_rate_pct_mean']:>8.2f}{r['cpu_pct_mean_mean']:>8.0f}{r['rss_mb_mean_mean']:>9.0f}  {r['n_reps']}")


if __name__ == "__main__":
    main()
