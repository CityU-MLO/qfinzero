#!/usr/bin/env bash
# QFinZero — Check service status

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

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

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo "QFinZero Service Status"
echo "======================="
echo ""

check() {
    local name=$1 port=$2
    if curl -s "http://$QFZ_HOST:$port" > /dev/null 2>&1 || \
       curl -s "http://$QFZ_HOST:$port/health" > /dev/null 2>&1 || \
       curl -s "http://$QFZ_HOST:$port/npp/health" > /dev/null 2>&1 || \
       curl -s "http://$QFZ_HOST:$port/v1/health" > /dev/null 2>&1; then
        echo -e "  $name  :$port  ${GREEN}UP${NC}"
    else
        echo -e "  $name  :$port  ${RED}DOWN${NC}"
    fi
}

check "PMB" "$PMB_PORT"
check "NPP" "$NPP_PORT"
check "UPQ" "$UPQ_PORT"
echo ""
