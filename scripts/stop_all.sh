#!/usr/bin/env bash
# QFinZero — Stop all services

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$ROOT_DIR/logs"

GREEN='\033[0;32m'
NC='\033[0m'
info() { echo -e "${GREEN}[INFO]${NC} $1"; }

echo ""
echo "=========================================="
echo "  QFinZero — Stopping Services"
echo "=========================================="
echo ""

for svc in pmb npp upq; do
    PID_FILE="$LOG_DIR/$svc.pid"
    SVC_UPPER=$(echo "$svc" | tr '[:lower:]' '[:upper:]')
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID"
            info "$SVC_UPPER stopped (PID: $PID)"
        else
            info "$SVC_UPPER was not running"
        fi
        rm -f "$PID_FILE"
    else
        info "$SVC_UPPER not tracked (no PID file)"
    fi
done

echo ""
info "All services stopped."
