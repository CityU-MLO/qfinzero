#!/usr/bin/env bash
# QFinZero — Start all services
#
# Usage:
#   ./scripts/run_all.sh          # start all services
#   ./scripts/run_all.sh pmb npp  # start specific services
#
# Ports (defaults; override via config/qfinzero.env):
#   PMB        19320   Paper Money Broker
#   NPP        19330   News Pushing Pipeline
#   UPQ        19350   Unified Price Query
#   DASHBOARD  19380   Next.js Dashboard (production)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

LOG_DIR="$ROOT_DIR/logs"
mkdir -p "$LOG_DIR"

# ── Global config ───────────────────────────────────────────────

CONFIG_FILE="$ROOT_DIR/config/qfinzero.env"
if [ -f "$CONFIG_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$CONFIG_FILE"
    set +a
fi

: "${QFZ_HOST:=127.0.0.1}"
: "${PMB_PORT:=19320}"
: "${NPP_PORT:=19330}"
: "${UPQ_PORT:=19350}"
: "${DASHBOARD_PORT:=19380}"

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

start_npp() {
    info "Starting NPP (News Pushing Pipeline) on port $NPP_PORT..."
    cd "$ROOT_DIR/infra/npp"
    NPP_HOST="$QFZ_HOST" NPP_PORT="$NPP_PORT" python main.py > "$LOG_DIR/npp.log" 2>&1 &
    echo $! > "$LOG_DIR/npp.pid"
    info "NPP started (PID: $(cat "$LOG_DIR/npp.pid"))"
}

start_upq() {
    info "Starting UPQ (Unified Price Query) on port $UPQ_PORT..."
    cd "$ROOT_DIR/infra/upq"
    if [ -f "target/release/upq-service" ]; then
        PORT="$UPQ_PORT" ./target/release/upq-service > "$LOG_DIR/upq.log" 2>&1 &
    elif [ -f "target/debug/upq-service" ]; then
        PORT="$UPQ_PORT" ./target/debug/upq-service > "$LOG_DIR/upq.log" 2>&1 &
    else
        warn "UPQ binary not found. Run 'cargo build --release' in infra/upq first."
        return 1
    fi
    echo $! > "$LOG_DIR/upq.pid"
    info "UPQ started (PID: $(cat "$LOG_DIR/upq.pid"))"
}

start_dashboard() {
    info "Starting Dashboard (Next.js) on port $DASHBOARD_PORT..."
    cd "$ROOT_DIR/infra/dashboard-web"
    if [ ! -d ".next" ]; then
        warn "Next.js build not found. Running pnpm build first..."
        PMB_BASE_URL="http://$QFZ_HOST:$PMB_PORT" \
        NPP_BASE_URL="http://$QFZ_HOST:$NPP_PORT" \
        UPQ_BASE_URL="http://$QFZ_HOST:$UPQ_PORT" \
        pnpm build
    fi
    PMB_BASE_URL="http://$QFZ_HOST:$PMB_PORT" \
    NPP_BASE_URL="http://$QFZ_HOST:$NPP_PORT" \
    UPQ_BASE_URL="http://$QFZ_HOST:$UPQ_PORT" \
    node_modules/.bin/next start -p "$DASHBOARD_PORT" > "$LOG_DIR/dashboard.log" 2>&1 &
    echo $! > "$LOG_DIR/dashboard.pid"
    info "Dashboard started (PID: $(cat "$LOG_DIR/dashboard.pid"))"
    info "Open http://$QFZ_HOST:$DASHBOARD_PORT"
}

# ── Main ─────────────────────────────────────────────────────────

SERVICES="${@:-pmb npp upq dashboard}"

echo ""
echo "=========================================="
echo "  QFinZero — Starting Services"
echo "=========================================="
echo ""

for svc in $SERVICES; do
    case "$svc" in
        pmb) start_pmb ;;
        npp) start_npp ;;
        upq) start_upq ;;
        dashboard) start_dashboard ;;
        *)   warn "Unknown service: $svc (valid: pmb, npp, upq, dashboard)" ;;
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
        npp) PORT="$NPP_PORT" ;;
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
