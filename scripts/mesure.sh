#!/usr/bin/env bash
cd "$(dirname "${BASH_SOURCE[0]}")/.."
OUT=results/mesures_finales
python3 scripts/run_benchmarks.py --profile reduced --reps 5 --duration 8 --out "$OUT" || exit 1
python3 scripts/split_by_tech.py "$OUT"
python3 scripts/aggregate.py "$OUT"
echo "MESURES TERMINEES"
