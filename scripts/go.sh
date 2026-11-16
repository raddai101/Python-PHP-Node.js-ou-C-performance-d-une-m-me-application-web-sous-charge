#!/usr/bin/env bash
cd "$(dirname "${BASH_SOURCE[0]}")/.."
pkill -f run_benchmarks; bash scripts/server.sh stop all > /dev/null 2>&1
pkill -f qbittorrent; pkill -f brave
rm -rf results/mesures_finales results/run.log
bash scripts/check_power.sh || { echo "BRANCHEZ LE PC SUR SECTEUR"; exit 1; }
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor > /dev/null
bash scripts/env_info.sh > /dev/null
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing' 2>/dev/null
gsettings set org.gnome.desktop.session idle-delay 0 2>/dev/null
echo "Attente du calme de la machine (max 10 min)..."
for i in $(seq 40); do awk '{exit !($1 < 0.5)}' /proc/loadavg && break; sleep 15; done
uptime; ps -eo pcpu,comm --sort=-pcpu | head -4
INH=""; systemd-inhibit --what=sleep:idle true 2>/dev/null && INH="systemd-inhibit --what=sleep:idle"
nohup $INH bash scripts/mesure.sh > results/run.log 2>&1 &
sleep 30
if pgrep -f run_benchmarks.py > /dev/null; then
  echo; echo ">>> LE TEST TOURNE (≈ 54 min). Ne touchez plus au PC."
  tail -4 results/run.log
else
  echo; echo ">>> ECHEC. Envoyez-moi ceci :"; cat results/run.log
fi
