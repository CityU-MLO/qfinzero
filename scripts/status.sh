#!/usr/bin/env bash
# QFinZero — Check service status

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo "QFinZero Service Status"
echo "======================="
echo ""

check() {
    local name=$1 port=$2
    if curl -s "http://127.0.0.1:$port" > /dev/null 2>&1 || \
       curl -s "http://127.0.0.1:$port/health" > /dev/null 2>&1 || \
       curl -s "http://127.0.0.1:$port/npp/health" > /dev/null 2>&1 || \
       curl -s "http://127.0.0.1:$port/v1/health" > /dev/null 2>&1; then
        echo -e "  $name  :$port  ${GREEN}UP${NC}"
    else
        echo -e "  $name  :$port  ${RED}DOWN${NC}"
    fi
}

check "PMB" 19320
check "NPP" 19330
check "UPQ" 19350
echo ""
