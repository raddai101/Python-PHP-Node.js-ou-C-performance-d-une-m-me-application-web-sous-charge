#!/usr/bin/env bash
# Démarre / arrête / vérifie une version du serveur.
#   scripts/server.sh start  python|php|javascript|csharp|all
#   scripts/server.sh stop   python|php|javascript|csharp|all
#   scripts/server.sh status python|php|javascript|csharp|all
#   scripts/server.sh pids   python|php|javascript|csharp      (PID racines, pour la mesure CPU/RSS)
#
# Variables optionnelles :
#   SERVER_CPUSET="0,1"   restreint le serveur à ces cœurs (via taskset)
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN="$ROOT/run"
mkdir -p "$RUN"

declare -A PORT=( [python]=8080 [php]=8081 [javascript]=8082 [csharp]=8083 )
TASKSET=""
[[ -n "${SERVER_CPUSET:-}" ]] && TASKSET="taskset -c ${SERVER_CPUSET}"

PYTHON_BIN="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
PHPFPM_BIN="$(command -v php-fpm8.5 || command -v php-fpm || true)"

wait_ready() {  # $1 = techno
  local port=${PORT[$1]} i
  for i in $(seq 1 120); do
    if curl -fsS -o /dev/null --max-time 2 "http://127.0.0.1:${port}/health" 2>/dev/null; then return 0; fi
    sleep 0.5
  done
  echo "ERREUR : $1 ne répond pas sur le port $port (voir $RUN/$1.log)" >&2
  return 1
}

kill_pidfile() {  # $1 = fichier pid
  [[ -f "$1" ]] || return 0
  local pid; pid=$(cat "$1")
  if kill -0 "$pid" 2>/dev/null; then
    kill -TERM "$pid" 2>/dev/null
    for _ in $(seq 1 40); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
    kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" 2>/dev/null
  fi
  rm -f "$1"
}

start_python() {
  [[ -x "$PYTHON_BIN" ]] || { echo "ERREUR : venv absent (lancez scripts/setup.sh)" >&2; return 1; }
  ( cd "$ROOT/python" || exit 1; $TASKSET nohup "$PYTHON_BIN" -m uvicorn main:app --host 127.0.0.1 --port 8080 \
      --log-level warning --no-access-log > "$RUN/python.log" 2>&1 & echo $! > "$RUN/python.pid" )
}

start_javascript() {
  ( cd "$ROOT/javascript" || exit 1; $TASKSET nohup node server.js > "$RUN/javascript.log" 2>&1 & echo $! > "$RUN/javascript.pid" )
}

start_csharp() {
  local dll="$ROOT/csharp/publish/MiniTaskApi.dll"
  [[ -f "$dll" ]] || { echo "ERREUR : C# non compilé (lancez scripts/setup.sh)" >&2; return 1; }
  ( cd "$ROOT/csharp/publish" || exit 1; DOTNET_CLI_TELEMETRY_OPTOUT=1 $TASKSET nohup dotnet MiniTaskApi.dll \
      > "$RUN/csharp.log" 2>&1 & echo $! > "$RUN/csharp.pid" )
}

start_php() {
  [[ -n "$PHPFPM_BIN" ]] || { echo "ERREUR : php-fpm introuvable" >&2; return 1; }
  local d="$RUN/php"; mkdir -p "$d/tmp"
  local user_dir="" pool_user=""
  if [[ $(id -u) -eq 0 ]]; then user_dir="user nobody nogroup;"; pool_user=$'user = nobody\ngroup = nogroup'; fi
  sed -e "s|__RUN__|$RUN|g" -e "s|__ROOT__|$ROOT|g" -e "s|__USER_DIRECTIVE__|$user_dir|" \
      "$ROOT/php/conf/nginx.conf.tpl" > "$d/nginx.conf"
  sed -e "s|__RUN__|$RUN|g" -e "s|__POOL_USER__|${pool_user//$'\n'/\\n}|" \
      "$ROOT/php/conf/php-fpm.conf.tpl" > "$d/php-fpm.conf"
  # Droits d'accès au dossier temporaire quand on tourne en root
  [[ $(id -u) -eq 0 ]] && chmod -R 777 "$d"
  $TASKSET "$PHPFPM_BIN" -y "$d/php-fpm.conf" >"$RUN/php.log" 2>&1 </dev/null || return 1
  $TASKSET nginx -c "$d/nginx.conf" -p "$d/" >>"$RUN/php.log" 2>&1 </dev/null || return 1
}

start_one() {
  local t=$1
  stop_one "$t" >/dev/null 2>&1
  "start_$t" || return 1
  wait_ready "$t"
}

stop_one() {
  case "$1" in
    php) kill_pidfile "$RUN/php/nginx.pid"; kill_pidfile "$RUN/php/php-fpm.pid" ;;
    *)   kill_pidfile "$RUN/$1.pid" ;;
  esac
}

pids_one() {
  case "$1" in
    php) cat "$RUN/php/nginx.pid" "$RUN/php/php-fpm.pid" 2>/dev/null | tr '\n' ' ' ;;
    *)   cat "$RUN/$1.pid" 2>/dev/null ;;
  esac
  echo
}

status_one() {
  if curl -fsS -o /dev/null --max-time 2 "http://127.0.0.1:${PORT[$1]}/health" 2>/dev/null; then
    echo "$1 : en marche (port ${PORT[$1]})"; else echo "$1 : arrêté"; fi
}

action=${1:-}; target=${2:-}
techs=(python php javascript csharp)
[[ "$target" != "all" && -n "$target" ]] && techs=("$target")
[[ -z "$action" || -z "$target" ]] && { sed -n '2,8p' "$0"; exit 1; }

rc=0
for t in "${techs[@]}"; do
  [[ -n "${PORT[$t]:-}" ]] || { echo "technologie inconnue : $t" >&2; exit 1; }
  case "$action" in
    start)  start_one "$t" && echo "$t démarré (port ${PORT[$t]})" || rc=1 ;;
    stop)   stop_one "$t"; echo "$t arrêté" ;;
    status) status_one "$t" ;;
    pids)   pids_one "$t" ;;
    *) echo "action inconnue : $action" >&2; exit 1 ;;
  esac
done
exit $rc
