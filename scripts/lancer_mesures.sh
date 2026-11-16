#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
OUT=results/mesures_finales

echo "== 1. Préparation de la machine =="
bash scripts/check_power.sh || { echo "ERREUR : PC non branché sur secteur"; exit 1; }
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor > /dev/null
echo "gouverneur CPU : $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor)"
sudo systemctl stop nginx php8.5-fpm apache2 2>/dev/null || true
bash scripts/server.sh stop all > /dev/null || true
pkill -f uvicorn || true
pkill -f "node server.js" || true
pkill -f MiniTaskApi.dll || true
sleep 5
echo "charge système : $(cut -d' ' -f1-3 /proc/loadavg)"
awk '{exit !($1 < 0.7)}' /proc/loadavg || { echo "ATTENTION : la machine n'est pas au repos. Processus les plus gourmands :"; ps -eo pcpu,comm --sort=-pcpu | head -6; }
bash scripts/env_info.sh > /dev/null
echo "environnement noté dans results/environment.txt"

echo; echo "== 2. Essai rapide (smoke, ~5 min) =="
rm -rf results/smoke_test
python3 scripts/run_benchmarks.py --profile smoke --out results/smoke_test
test -s results/smoke_test/raw_runs.csv || { echo "ERREUR : pas de données"; exit 1; }
column -s, -t < results/smoke_test/raw_runs.csv | cut -c1-170 | head -6

echo; echo "== 3. Durée estimée des vraies mesures =="
python3 scripts/run_benchmarks.py --dry-run --profile reduced | tail -15

echo
read -rp "Smoke correct et durée acceptable ? Entrée pour LANCER, Ctrl+C pour annuler "

echo "== 4. Lancement des vraies mesures (en arrière-plan) =="
mkdir -p results
setsid nohup systemd-inhibit --what=sleep:idle:handle-lid-switch bash -c "
  python3 scripts/run_benchmarks.py --profile reduced --out $OUT &&
  python3 scripts/split_by_tech.py $OUT &&
  python3 scripts/aggregate.py $OUT
" > results/run.log 2>&1 &
echo "Lancé (PID $!). Suivi : tail -f results/run.log"
