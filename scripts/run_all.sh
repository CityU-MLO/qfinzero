#!/usr/bin/env bash
# QFinZero — Start all services
#
# Usage:
#   ./scripts/run_all.sh          # start all services
#   ./scripts/run_all.sh pmb npp  # start specific services
#
# Ports:
#   PMB  19320   Paper Money Broker
#   NPP  19330   News Pushing Pipeline
#   UPQ  19350   Unified Price Query

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

LOG_DIR="$ROOT_DIR/logs"
mkdir -p "$LOG_DIR"

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
    info "Starting PMB (Paper Money Broker) on port 19320..."
    cd "$ROOT_DIR/infra/pmb"
    python main.py > "$LOG_DIR/pmb.log" 2>&1 &
    echo $! > "$LOG_DIR/pmb.pid"
    info "PMB started (PID: $(cat "$LOG_DIR/pmb.pid"))"
}

start_npp() {
    info "Starting NPP (News Pushing Pipeline) on port 19330..."
    cd "$ROOT_DIR/infra/npp"
    python main.py > "$LOG_DIR/npp.log" 2>&1 &
    echo $! > "$LOG_DIR/npp.pid"
    info "NPP started (PID: $(cat "$LOG_DIR/npp.pid"))"
}

start_upq() {
    info "Starting UPQ (Unified Price Query) on port 19350..."
    cd "$ROOT_DIR/infra/upq"
    if [ -f "target/release/upq-service" ]; then
        ./target/release/upq-service > "$LOG_DIR/upq.log" 2>&1 &
    elif [ -f "target/debug/upq-service" ]; then
        ./target/debug/upq-service > "$LOG_DIR/upq.log" 2>&1 &
    else
        warn "UPQ binary not found. Run 'cargo build --release' in infra/upq first."
        return 1
    fi
    echo $! > "$LOG_DIR/upq.pid"
    info "UPQ started (PID: $(cat "$LOG_DIR/upq.pid"))"
}

# ── Main ─────────────────────────────────────────────────────────

SERVICES="${@:-pmb npp upq}"

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
        *)   warn "Unknown service: $svc (valid: pmb, npp, upq)" ;;
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
        pmb) PORT=19320 ;;
        npp) PORT=19330 ;;
        upq) PORT=19350 ;;
        *)   continue ;;
    esac
    SVC_UPPER=$(echo "$svc" | tr '[:lower:]' '[:upper:]')
    if curl -s "http://127.0.0.1:$PORT" > /dev/null 2>&1; then
        info "$SVC_UPPER :$PORT  UP"
    else
        warn "$SVC_UPPER :$PORT  starting..."
    fi
done
