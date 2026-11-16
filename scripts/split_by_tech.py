import csv, sys
from pathlib import Path

run = Path(sys.argv[1])
for name in ("raw_runs.csv", "resource_samples.csv"):
    with open(run / name, newline="", encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        fields, rows = rd.fieldnames, list(rd)
    for tech in sorted({r["tech"] for r in rows}):
        d = run / tech
        d.mkdir(exist_ok=True)
        with open(d / name, "w", newline="", encoding="utf-8") as out:
            wr = csv.DictWriter(out, fieldnames=fields)
            wr.writeheader()
            wr.writerows(r for r in rows if r["tech"] == tech)
        print(f"{tech:11s} {name:22s} {sum(r['tech'] == tech for r in rows)} lignes")
