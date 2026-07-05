#!/usr/bin/env bash
# QFinZero — stop any running QFinZero services and (re)start the unified hub.
#
# Only ever touches processes whose working directory is inside THIS repo, so
# other projects on the same machine (e.g. unrelated servers on nearby ports)
# are left untouched. Cleans up the hub, its children, and any older run_all /
# adopted strays sitting on the canonical 193xx ports.
#
#   ./scripts/restart.sh            # stop everything QFinZero, then start the hub
#   ./scripts/restart.sh --build    # rebuild the Next.js UI first, then restart
#   ./scripts/restart.sh stop       # just stop
#   ./scripts/restart.sh start      # just start (optionally with --build)
#   ./scripts/restart.sh status     # show hub health
#
# Honors the same env as serve.sh: QFZ_SERVER_PORT, DASHBOARD_PORT, ESP_PORT,
# DATA_ADMIN_PORT, UPQ_PORT, PMB_PORT, PLAYGROUND_PORT, QFZ_NODE_BIN,
# QFZ_SQLITE_PRELOAD, QFZ_PYTHON (from config/qfinzero.env then .env).
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

# Layered env: checked-in defaults, then local .env overrides.
if [ -f config/qfinzero.env ]; then set -a; . config/qfinzero.env; set +a; fi
if [ -f .env ]; then set -a; . .env; set +a; fi

: "${QFZ_SERVER_PORT:=19777}"
: "${DASHBOARD_PORT:=19300}"
: "${ESP_PORT:=19330}"
: "${DATA_ADMIN_PORT:=19340}"
: "${UPQ_PORT:=19350}"
: "${PMB_PORT:=19380}"
: "${PLAYGROUND_PORT:=19390}"
PORTS="$QFZ_SERVER_PORT $DASHBOARD_PORT $ESP_PORT $DATA_ADMIN_PORT $UPQ_PORT $PMB_PORT $PLAYGROUND_PORT"

LOG_DIR="${QFZ_LOG_DIR:-$ROOT_DIR/.run}"
mkdir -p "$LOG_DIR"
HUB_LOG="$LOG_DIR/hub.log"
HUB_PID_FILE="$LOG_DIR/hub.pid"

# ── helpers ────────────────────────────────────────────────────────────────
is_ours() {  # pid → 0 if its working directory is inside this repo
  local pid="$1" cwd
  cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null)" || return 1
  case "$cwd" in "$ROOT_DIR" | "$ROOT_DIR"/*) return 0 ;; *) return 1 ;; esac
}

pids_on_port() {  # port → listening pids
  if command -v ss >/dev/null 2>&1; then
    ss -ltnp 2>/dev/null | grep -E ":$1 " | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u
  elif command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null | sort -u
  fi
}

stop_qfz() {
  echo "Stopping QFinZero services (repo: $ROOT_DIR)…"
  # 1. the hub, by command line (its cwd is the repo root)
  for pid in $(pgrep -f "[q]finzero[.]server" 2>/dev/null); do
    is_ours "$pid" && { echo "  stop hub pid $pid"; kill "$pid" 2>/dev/null; }
  done
  sleep 3
  # 2. anything still on our canonical ports that belongs to this repo
  #    (hub children, adopted strays, old run_all main.py, dashboard, …)
  for port in $PORTS; do
    for pid in $(pids_on_port "$port"); do
      if is_ours "$pid"; then
        echo "  stop :$port pid $pid"; kill "$pid" 2>/dev/null
      else
        echo "  skip :$port pid $pid (not this repo — left running)"
      fi
    done
  done
  sleep 2
  # 3. force any survivors
  for port in $PORTS; do
    for pid in $(pids_on_port "$port"); do
      is_ours "$pid" && { kill -9 "$pid" 2>/dev/null && echo "  kill -9 :$port pid $pid"; }
    done
  done
  rm -f "$HUB_PID_FILE"
}

build_web() {
  echo "Building dashboard-web…"
  (
    cd "$ROOT_DIR/infra/dashboard-web"
    [ -n "${QFZ_NODE_BIN:-}" ] && [ -d "${QFZ_NODE_BIN}" ] && export PATH="${QFZ_NODE_BIN}:$PATH"
    [ -n "${QFZ_SQLITE_PRELOAD:-}" ] && [ -f "${QFZ_SQLITE_PRELOAD}" ] && \
      export LD_PRELOAD="${QFZ_SQLITE_PRELOAD}${LD_PRELOAD:+:$LD_PRELOAD}"
    pnpm build
  ) || { echo "  web build FAILED — aborting."; return 1; }
}

status_qfz() {
  local out
  out="$(curl -s -m4 "http://127.0.0.1:$QFZ_SERVER_PORT/health" 2>/dev/null)" \
    && echo "$out" || echo "hub not responding on :$QFZ_SERVER_PORT"
}

start_qfz() {
  echo "Starting unified hub on :$QFZ_SERVER_PORT…"
  nohup "$ROOT_DIR/scripts/serve.sh" >"$HUB_LOG" 2>&1 &
  echo $! >"$HUB_PID_FILE"
  for i in $(seq 1 60); do
    sleep 2
    if curl -s -m3 "http://127.0.0.1:$QFZ_SERVER_PORT/health" >/dev/null 2>&1; then
      echo "Hub healthy after ~$((i * 2))s:"
      status_qfz
      echo "Open: http://127.0.0.1:$QFZ_SERVER_PORT/  ·  Broker: /broker  ·  Logs: $HUB_LOG"
      return 0
    fi
  done
  echo "Hub did not become healthy in time. Last log lines:"
  tail -20 "$HUB_LOG"
  return 1
}

# ── arg parsing ────────────────────────────────────────────────────────────
CMD="restart"; BUILD=0
for a in "$@"; do
  case "$a" in
    --build) BUILD=1 ;;
    stop | start | status | restart) CMD="$a" ;;
    -h | --help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown arg: $a"; echo "usage: $0 [restart|stop|start|status] [--build]"; exit 1 ;;
  esac
done

maybe_build() { [ "$BUILD" = 1 ] || return 0; build_web; }

case "$CMD" in
  stop) stop_qfz ;;
  status) status_qfz ;;
  start) maybe_build && start_qfz ;;
  restart) stop_qfz; maybe_build && start_qfz ;;
esac
