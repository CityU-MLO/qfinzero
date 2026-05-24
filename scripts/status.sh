#!/usr/bin/env bash
# QFinZero — Check service status

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

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
: "${DASHBOARD_PORT:=19700}"
: "${PMB_PORT:=19701}"
: "${ESP_PORT:=19702}"
: "${UPQ_PORT:=19703}"

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
       curl -s "http://$QFZ_HOST:$port/esp/health" > /dev/null 2>&1 || \
       curl -s "http://$QFZ_HOST:$port/v1/health" > /dev/null 2>&1; then
        echo -e "  $name  :$port  ${GREEN}UP${NC}"
    else
        echo -e "  $name  :$port  ${RED}DOWN${NC}"
    fi
}

check "PMB" "$PMB_PORT"
check "ESP" "$ESP_PORT"
check "UPQ" "$UPQ_PORT"
echo ""
