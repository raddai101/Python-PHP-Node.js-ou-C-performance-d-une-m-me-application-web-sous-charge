#!/usr/bin/env python3
"""Vérifie que les quatre versions respectent EXACTEMENT le même contrat.

Pour chaque cas de test, on compare : le code HTTP, le Content-Type et le corps
(octet pour octet) avec la réponse attendue, calculée indépendamment à partir
de data/tasks.json. Une version est « OK » si tous ses cas passent.

À lancer sur des serveurs fraîchement démarrés (les tests POST créent les
tâches 1001 et 1002) :
    scripts/server.sh start all
    python3 scripts/verify_equivalence.py            # tous les cas
    python3 scripts/verify_equivalence.py --full     # ajoute /compute?n=35
    python3 scripts/verify_equivalence.py --only php # une seule version

Code de sortie : 0 si les quatre versions sont OK, 1 sinon.
"""
import argparse
import http.client
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORTS = {"python": 8080, "php": 8081, "javascript": 8082, "csharp": 8083}
CT = "application/json; charset=utf-8"


def dumps(obj) -> bytes:
    """Sérialisation de référence : JSON compact, UTF-8 non échappé."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def fib(n):
    return n if n < 2 else fib(n - 1) + fib(n - 2)


TASKS = json.loads((ROOT / "data" / "tasks.json").read_text(encoding="utf-8"))
NOT_FOUND = (404, dumps({"error": "not found"}))
BAD_PAYLOAD = (400, dumps({"error": "invalid payload"}))
BAD_N = (400, dumps({"error": "invalid n"}))


def build_cases(full: bool):
    """Liste de (libellé, méthode, chemin, corps_requête, (statut, corps_attendu))."""
    c = []
    c.append(("GET /health", "GET", "/health", None, (200, dumps({"status": "ok"}))))
    c.append(("GET /tasks (1000 tâches, octet pour octet)", "GET", "/tasks", None, (200, dumps(TASKS))))
    for i in (1, 2, 500, 1000):
        c.append((f"GET /tasks/{i}", "GET", f"/tasks/{i}", None, (200, dumps(TASKS[i - 1]))))
    for bad in ("0", "1001", "abc", "-1", "1.5", "99999999999999999999999"):
        c.append((f"GET /tasks/{bad} -> 404", "GET", f"/tasks/{bad}", None, NOT_FOUND))

    ns = [0, 1, 2, 10, 20, 30] + ([35] if full else [])
    for n in ns:
        c.append((f"GET /compute?n={n}", "GET", f"/compute?n={n}", None, (200, dumps({"n": n, "result": fib(n)}))))
    for bad in ("", "abc", "-1", "41", "3.5", "1e2"):
        c.append((f"GET /compute?n={bad!r} -> 400", "GET", f"/compute?n={bad}", None, BAD_N))
    c.append(("GET /compute (sans n) -> 400", "GET", "/compute", None, BAD_N))

    # POST valides (ordre important : ids 1001 puis 1002)
    t1 = {"id": 1001, "title": "Test é à ç — UTF-8 \"guillemets\"", "done": False, "priority": 3}
    t2 = {"id": 1002, "title": "Deuxième", "done": True, "priority": 5}
    c.append(("POST /tasks valide (done omis) -> 201", "POST", "/tasks",
              json.dumps({"title": t1["title"], "priority": 3}, ensure_ascii=False).encode(), (201, dumps(t1))))
    c.append(("POST /tasks valide (done=true) -> 201", "POST", "/tasks",
              json.dumps({"title": "Deuxième", "priority": 5, "done": True, "extra": 1}).encode(), (201, dumps(t2))))
    c.append(("GET /tasks/1001 après création", "GET", "/tasks/1001", None, (200, dumps(t1))))
    c.append(("GET /tasks/1002 après création", "GET", "/tasks/1002", None, (200, dumps(t2))))
    c.append(("GET /tasks après création (1002 tâches)", "GET", "/tasks", None, (200, dumps(TASKS + [t1, t2]))))

    # POST invalides
    invalid_bodies = {
        "JSON invalide": b"{",
        "corps vide": b"",
        "tableau": b"[]",
        "null": b"null",
        "nombre": b"42",
        "title manquant": b'{"priority":3}',
        "priority manquant": b'{"title":"x"}',
        "title vide": b'{"title":"","priority":3}',
        "title non texte": b'{"title":5,"priority":3}',
        "priority 0": b'{"title":"x","priority":0}',
        "priority 6": b'{"title":"x","priority":6}',
        "priority texte": b'{"title":"x","priority":"3"}',
        "priority décimal": b'{"title":"x","priority":3.5}',
        "priority booléen": b'{"title":"x","priority":true}',
        "done texte": b'{"title":"x","priority":3,"done":"oui"}',
        "done null": b'{"title":"x","priority":3,"done":null}',
        "UTF-8 invalide": b'{"title":"\xff\xfe","priority":3}',
    }
    for label, body in invalid_bodies.items():
        c.append((f"POST /tasks {label} -> 400", "POST", "/tasks", body, BAD_PAYLOAD))

    # Routes / méthodes inconnues
    c.append(("GET /inconnu -> 404", "GET", "/inconnu", None, NOT_FOUND))
    c.append(("DELETE /tasks -> 404", "DELETE", "/tasks", None, NOT_FOUND))
    c.append(("PUT /tasks/1 -> 404", "PUT", "/tasks/1", b"{}", NOT_FOUND))
    c.append(("POST /health -> 404", "POST", "/health", b"{}", NOT_FOUND))
    # Un POST invalide n'a rien créé : la liste fait toujours 1002 tâches
    c.append(("GET /tasks/1003 -> 404 (rien créé par les POST invalides)", "GET", "/tasks/1003", None, NOT_FOUND))
    return c


def request(port, method, path, body):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
    try:
        headers = {"Content-Type": "application/json"} if body is not None else {}
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        return resp.status, resp.getheader("Content-Type"), resp.read()
    finally:
        conn.close()


def fresh(port) -> bool:
    status, _, _ = request(port, "GET", "/tasks/1001", None)
    return status == 404


def run_tech(name, port, cases, verbose):
    failures = []
    try:
        if not fresh(port):
            return None, ["serveur non « frais » : /tasks/1001 existe déjà. Redémarrez-le (scripts/server.sh start " + name + ")."]
        for label, method, path, body, (exp_status, exp_body) in cases:
            status, ctype, data = request(port, method, path, body)
            problems = []
            if status != exp_status:
                problems.append(f"statut {status} au lieu de {exp_status}")
            if ctype != CT:
                problems.append(f"Content-Type {ctype!r} au lieu de {CT!r}")
            if data != exp_body:
                problems.append(f"corps différent : {data[:100]!r} au lieu de {exp_body[:100]!r}")
            if problems:
                failures.append(f"{label} : " + " ; ".join(problems))
            elif verbose:
                print(f"    ok  {label}")
    except OSError as exc:
        return None, [f"serveur injoignable sur le port {port} ({exc})"]
    return len(cases), failures


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--full", action="store_true", help="teste aussi /compute?n=35 (plus lent)")
    ap.add_argument("--only", choices=PORTS, help="ne teste qu'une version")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    cases = build_cases(args.full)
    techs = {args.only: PORTS[args.only]} if args.only else PORTS
    all_ok = True
    print(f"{len(cases)} cas de test par version\n")
    for name, port in techs.items():
        total, failures = run_tech(name, port, cases, args.verbose)
        if failures:
            all_ok = False
            print(f"[KO] {name} (port {port})")
            for f in failures:
                print(f"       - {f}")
        else:
            print(f"[OK] {name} (port {port}) : {total}/{total} cas conformes")
    print()
    print("RÉSULTAT : OK — les versions sont équivalentes." if all_ok
          else "RÉSULTAT : ÉCHEC — corrigez avant tout test de charge.")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
