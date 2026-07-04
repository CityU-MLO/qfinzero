#!/usr/bin/env bash
# QFinZero — Start all services
#
# Usage:
#   ./scripts/run_all.sh          # start all services
#   ./scripts/run_all.sh pmb esp  # start specific services
#
# Ports (defaults; override via environment or repo-root .env):
#   DASHBOARD  19300   Next.js Dashboard (production)
#   ESP        19330   News Pushing Pipeline
#   UPQ        19350   Unified Price Query
#   PMB        19380   Paper Money Broker

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

LOG_DIR="$ROOT_DIR/logs"
mkdir -p "$LOG_DIR"

# ── Global config ───────────────────────────────────────────────

load_env_defaults() {
    local env_file="$1"
    [ -f "$env_file" ] || return 0
    while IFS='=' read -r key value; do
        case "$key" in
            ''|\#*) continue ;;
        esac
        key="$(printf '%s' "$key" | xargs)"
        [ -n "$key" ] || continue
        if [ -z "${!key+x}" ]; then
            value="${value%$'\r'}"
            value="${value#\"}"
            value="${value%\"}"
            export "$key=$value"
        fi
    done < "$env_file"
}

load_env_defaults "$ROOT_DIR/.env"
load_env_defaults "$ROOT_DIR/config/qfinzero.env"

: "${QFZ_HOST:=127.0.0.1}"
: "${DASHBOARD_PORT:=19300}"
: "${PMB_PORT:=19380}"
: "${ESP_PORT:=19330}"
: "${UPQ_PORT:=19350}"
: "${QFZ_DATA_ROOT:=/data/qfinzero}"
: "${STORAGE_ROOT:=$QFZ_DATA_ROOT/upq}"

# ── Color helpers ────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ── Service definitions ─────────────────────────────────────────

start_pmb() {
    info "Starting PMB (Paper Money Broker) on port $PMB_PORT..."
    cd "$ROOT_DIR/infra/pmb"
    PMB_HOST="$QFZ_HOST" PMB_PORT="$PMB_PORT" python main.py > "$LOG_DIR/pmb.log" 2>&1 &
    echo $! > "$LOG_DIR/pmb.pid"
    info "PMB started (PID: $(cat "$LOG_DIR/pmb.pid"))"
}

start_esp() {
    info "Starting ESP (News Pushing Pipeline) on port $ESP_PORT..."
    cd "$ROOT_DIR/infra/esp"
    ESP_HOST="$QFZ_HOST" ESP_PORT="$ESP_PORT" python main.py > "$LOG_DIR/esp.log" 2>&1 &
    echo $! > "$LOG_DIR/esp.pid"
    info "ESP started (PID: $(cat "$LOG_DIR/esp.pid"))"
}

start_upq() {
    info "Starting UPQ (Unified Price Query) on port $UPQ_PORT..."
    cd "$ROOT_DIR/infra/upq"
    if [ -f "target/release/upq-service" ]; then
        PORT="$UPQ_PORT" STORAGE_ROOT="$STORAGE_ROOT" ./target/release/upq-service > "$LOG_DIR/upq.log" 2>&1 &
    elif [ -f "target/debug/upq-service" ]; then
        PORT="$UPQ_PORT" STORAGE_ROOT="$STORAGE_ROOT" ./target/debug/upq-service > "$LOG_DIR/upq.log" 2>&1 &
    else
        warn "UPQ binary not found. Run 'cargo build --release' in infra/upq first."
        return 1
    fi
    echo $! > "$LOG_DIR/upq.pid"
    info "UPQ started (PID: $(cat "$LOG_DIR/upq.pid"))"
}

start_data_admin() {
    info "Starting data-admin (data protocol control plane) on port ${DATA_ADMIN_PORT:-19340}..."
    cd "$ROOT_DIR/infra/data-admin"
    QFZ_HOST="$QFZ_HOST" DATA_ADMIN_PORT="${DATA_ADMIN_PORT:-19340}" python main.py > "$LOG_DIR/data-admin.log" 2>&1 &
    echo $! > "$LOG_DIR/data-admin.pid"
    info "data-admin started (PID: $(cat "$LOG_DIR/data-admin.pid"))"
}

start_dashboard() {
    info "Starting Dashboard (Next.js) on port $DASHBOARD_PORT..."
    cd "$ROOT_DIR/infra/dashboard-web"
    # The base conda `node` on this box is broken (libnode: undefined symbol
    # sqlite3session_attach), and `next`'s `#!/usr/bin/env node` shebang would pick it
    # up. Prefer the working `node` conda env if present so build/start don't crash.
    local NODE_ENV_BIN="${QFZ_NODE_BIN:-$HOME/miniconda3/envs/node/bin}"
    if [ -x "$NODE_ENV_BIN/node" ]; then
        local PATH="$NODE_ENV_BIN:$PATH"
    fi
    if [ ! -d ".next" ]; then
        warn "Next.js build not found. Running pnpm build first..."
        PMB_BASE_URL="http://$QFZ_HOST:$PMB_PORT" \
        ESP_BASE_URL="http://$QFZ_HOST:$ESP_PORT" \
        UPQ_BASE_URL="http://$QFZ_HOST:$UPQ_PORT" \
        DATA_ADMIN_BASE_URL="http://$QFZ_HOST:${DATA_ADMIN_PORT:-19340}" \
        pnpm build
    fi
    PMB_BASE_URL="http://$QFZ_HOST:$PMB_PORT" \
    ESP_BASE_URL="http://$QFZ_HOST:$ESP_PORT" \
    UPQ_BASE_URL="http://$QFZ_HOST:$UPQ_PORT" \
    DATA_ADMIN_BASE_URL="http://$QFZ_HOST:${DATA_ADMIN_PORT:-19340}" \
    node_modules/.bin/next start -p "$DASHBOARD_PORT" > "$LOG_DIR/dashboard.log" 2>&1 &
    echo $! > "$LOG_DIR/dashboard.pid"
    info "Dashboard started (PID: $(cat "$LOG_DIR/dashboard.pid"))"
    info "Open http://$QFZ_HOST:$DASHBOARD_PORT"
}

# ── Main ─────────────────────────────────────────────────────────

SERVICES="${@:-pmb esp upq data-admin dashboard}"

echo ""
echo "=========================================="
echo "  QFinZero — Starting Services"
echo "=========================================="
echo ""

for svc in $SERVICES; do
    case "$svc" in
        pmb) start_pmb ;;
        esp) start_esp ;;
        upq) start_upq ;;
        data-admin) start_data_admin ;;
        dashboard) start_dashboard ;;
        *)   warn "Unknown service: $svc (valid: pmb, esp, upq, data-admin, dashboard)" ;;
    esac
done

echo ""
info "Logs: $LOG_DIR/"
info "Stop all: ./scripts/stop_all.sh"
echo ""

# Wait a moment then show health
sleep 3
echo "Service Status:"
for svc in $SERVICES; do
    case "$svc" in
        pmb) PORT="$PMB_PORT" ;;
        esp) PORT="$ESP_PORT" ;;
        upq) PORT="$UPQ_PORT" ;;
        dashboard) PORT="$DASHBOARD_PORT" ;;
        *)   continue ;;
    esac
    SVC_UPPER=$(echo "$svc" | tr '[:lower:]' '[:upper:]')
    if curl -s "http://$QFZ_HOST:$PORT" > /dev/null 2>&1; then
        info "$SVC_UPPER :$PORT  UP"
    else
        warn "$SVC_UPPER :$PORT  starting..."
    fi
done
