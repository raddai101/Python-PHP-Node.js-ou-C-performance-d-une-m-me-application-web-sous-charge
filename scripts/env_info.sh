#!/usr/bin/env bash
# Enregistre la configuration de la machine et les versions des outils dans
# results/environment.txt (à citer dans la section « Environnement de test »).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT/results"
OUT="$ROOT/results/environment.txt"
{
  echo "date            : $(date -Is)"
  echo "noyau           : $(uname -srm)"
  echo "os              : $(grep PRETTY_NAME /etc/os-release | cut -d= -f2- | tr -d '\"')"
  echo "cpu             : $(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2- | sed 's/^ //')"
  echo "coeurs logiques : $(nproc)"
  echo "memoire         : $(free -m | awk '/Mem:/ {print $2" Mo"}')"
  echo "gouverneur CPU  : $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo n/a)"
  echo "python          : $(python3 --version 2>&1)"
  [[ -x "$ROOT/.venv/bin/python" ]] && echo "fastapi/uvicorn : $("$ROOT/.venv/bin/python" -c 'import fastapi,uvicorn;print(fastapi.__version__, uvicorn.__version__)')"
  echo "php             : $(php -v 2>&1 | head -1)"
  echo "php-fpm         : $( (php-fpm8.5 -v || php-fpm -v) 2>&1 | head -1)"
  echo "nginx           : $(nginx -v 2>&1)"
  echo "node            : $(node --version 2>&1)"
  echo "dotnet          : $(dotnet --version 2>&1)"
  echo "wrk             : $(wrk --version 2>&1 | head -1)"
  echo "tasks.json sha  : $(sha256sum "$ROOT/data/tasks.json" 2>/dev/null | cut -c1-64)"
} | tee "$OUT"
