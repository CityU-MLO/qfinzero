#!/usr/bin/env bash
# test-env.sh — Manage qfinzero test services on the remote qlib server
#
# Usage:
#   ./scripts/test-env.sh start   [pmb|npp|upq|web|playground]   — git pull, build if needed, then start
#   ./scripts/test-env.sh stop    [pmb|npp|upq|web|playground]   — stop service(s)
#   ./scripts/test-env.sh restart [pmb|npp|upq|web|playground]   — stop then start
#   ./scripts/test-env.sh status                                  — show all services status
#
# Options:
#   -b <branch>   — use specific branch instead of default (main)
#
# Services run on the remote host accessible via `ssh qlib`.
#   PMB         19701  /home/qlib/qfinzero/infra/pmb          (Python)
#   NPP         19702  /home/qlib/qfinzero/infra/npp          (Python)
#   UPQ         19703  /home/qlib/qfinzero/infra/upq          (Rust binary)
#   PLAYGROUND  19704  /home/qlib/qfinzero/infra/playground   (Python / LangGraph)
#   WEB         19700  /home/qlib/qfinzero/infra/dashboard-web (Next.js)

set -euo pipefail

# ── Constants ─────────────────────────────────────────────────────────────────

SSH_HOST="qlib"
REMOTE_ROOT="/home/qlib/qfinzero"
DEFAULT_REMOTE_BRANCH="main"
WEB_REMOTE_BRANCH="main"

LOG_DIR="/tmp/efan"
PID_DIR="/tmp/efan"

PMB_PORT=19701
NPP_PORT=19702
UPQ_PORT=19703
PLAYGROUND_PORT=19704
WEB_PORT=19700

PYTHON="/home/qlib/miniconda3/bin/python3.13"
WEB_DIR="$REMOTE_ROOT/infra/dashboard-web"

PMB_DIR="$REMOTE_ROOT/infra/pmb"
NPP_DIR="$REMOTE_ROOT/infra/npp"
UPQ_DIR="$REMOTE_ROOT/infra/upq"
PLAYGROUND_DIR="$REMOTE_ROOT/infra/playground"

PMB_HEALTH="http://127.0.0.1:${PMB_PORT}/v1/health"
NPP_HEALTH="http://127.0.0.1:${NPP_PORT}/npp/health"
UPQ_HEALTH="http://127.0.0.1:${UPQ_PORT}/health"
PLAYGROUND_HEALTH="http://127.0.0.1:${PLAYGROUND_PORT}/health"
WEB_HEALTH="http://127.0.0.1:${WEB_PORT}"

# ── Color helpers ─────────────────────────────────────────────────────────────

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
section() { echo -e "\n${BOLD}${CYAN}=== $* ===${NC}"; }
uc()      { echo "$1" | tr 'a-z' 'A-Z'; }

# ── SSH helper — pipe script to remote bash via stdin ─────────────────────────
remote_run() {
    ssh "$SSH_HOST" bash
}

# ── Git pull ──────────────────────────────────────────────────────────────────

resolve_remote_branch() {
    local svcs="$1"
    if [ -n "$BRANCH_OVERRIDE" ]; then
        echo "$BRANCH_OVERRIDE"
    elif echo "$svcs" | grep -qw web; then
        echo "$WEB_REMOTE_BRANCH"
    else
        echo "$DEFAULT_REMOTE_BRANCH"
    fi
}

remote_git_pull() {
    local target_branch="$1"
    section "Git pull on remote ($target_branch)"
    remote_run <<EOF
set -e
cd '${REMOTE_ROOT}'
current_branch=\$(git rev-parse --abbrev-ref HEAD)
if [ "\$current_branch" != '${target_branch}' ]; then
    echo "WARNING: remote HEAD is on '\$current_branch', not '${target_branch}'."
    git checkout '${target_branch}'
fi
echo 'Pulling latest from origin/${target_branch}...'
git pull origin '${target_branch}'
echo "Now at: \$(git log --oneline -1)"
EOF
}

# ── UPQ build ─────────────────────────────────────────────────────────────────

remote_build_upq_if_needed() {
    section "Checking UPQ binary freshness"
    remote_run <<'ENDSSH'
set -e
source "$HOME/.cargo/env"
BINARY='/home/qlib/qfinzero/infra/upq/target/release/upq-service'
SRC_DIR='/home/qlib/qfinzero/infra/upq/crates'

if [ ! -f "$BINARY" ]; then
    echo 'Binary not found — building from scratch...'
    NEEDS_BUILD=1
else
    NEWER=$(find "$SRC_DIR" -name '*.rs' -newer "$BINARY" 2>/dev/null | head -1)
    if [ -n "$NEWER" ]; then
        echo "Source file newer than binary: $NEWER"
        NEEDS_BUILD=1
    else
        echo 'Binary is up-to-date, skipping rebuild.'
        NEEDS_BUILD=0
    fi
fi

if [ "$NEEDS_BUILD" = '1' ]; then
    echo 'Running: cargo build --release ...'
    cd '/home/qlib/qfinzero/infra/upq'
    cargo build --release
    echo 'UPQ build complete.'
fi
ENDSSH
}

# ── Web (Next.js) build ───────────────────────────────────────────────────────

remote_build_web_if_needed() {
    section "Building Next.js frontend"
    remote_run <<EOF
set -e
export NVM_DIR="\$HOME/.nvm"
source "\$NVM_DIR/nvm.sh"

WEB_DIR='${WEB_DIR}'
BUILD_MARKER="\$WEB_DIR/.next/BUILD_ID"

cd "\$WEB_DIR"

# Install deps if node_modules missing or package.json is newer
if [ ! -d node_modules ] || [ package.json -nt node_modules ]; then
    echo 'Installing dependencies...'
    pnpm install --frozen-lockfile
fi

# Build if .next missing or any src file is newer than BUILD_ID
NEEDS_BUILD=0
if [ ! -f "\$BUILD_MARKER" ]; then
    echo '.next/BUILD_ID not found — building from scratch...'
    NEEDS_BUILD=1
else
    NEWER=\$(find src -newer "\$BUILD_MARKER" 2>/dev/null | head -1)
    if [ -n "\$NEWER" ]; then
        echo "Source newer than last build: \$NEWER"
        NEEDS_BUILD=1
    else
        echo 'Build is up-to-date, skipping rebuild.'
    fi
fi

if [ "\$NEEDS_BUILD" = '1' ]; then
    echo 'Running: pnpm build ...'
    PMB_BASE_URL=http://127.0.0.1:${PMB_PORT} \
    NPP_BASE_URL=http://127.0.0.1:${NPP_PORT} \
    UPQ_BASE_URL=http://127.0.0.1:${UPQ_PORT} \
    pnpm build
    echo 'Next.js build complete.'
fi
EOF
}

# ── PID / process helper ──────────────────────────────────────────────────────

remote_get_pid() {
    local svc="$1"
    local pid_file="${PID_DIR}/${svc}.pid"
    remote_run <<EOF 2>/dev/null || true
if [ -f '${pid_file}' ]; then
    PID=\$(cat '${pid_file}')
    if kill -0 "\$PID" 2>/dev/null; then echo "\$PID"; fi
fi
EOF
}

# ── Start individual service ──────────────────────────────────────────────────

start_service() {
    local svc="$1"
    local log_file="${LOG_DIR}/${svc}.log"
    local pid_file="${PID_DIR}/${svc}.pid"

    local running_pid
    running_pid=$(remote_get_pid "$svc")
    if [ -n "$running_pid" ]; then
        warn "$(uc "$svc") is already running (PID $running_pid). Skipping start."
        return 0
    fi

    section "Starting $(uc "$svc")"

    case "$svc" in
        pmb)
            remote_run <<EOF
set -e
mkdir -p '${LOG_DIR}'
cd '${PMB_DIR}'
nohup env PMB_PORT=${PMB_PORT} PMB_UPQ_BASE_URL=http://127.0.0.1:${UPQ_PORT} \
    ${PYTHON} main.py > '${log_file}' 2>&1 &
echo \$! > '${pid_file}'
echo "PMB started with PID \$(cat '${pid_file}')"
EOF
            ;;
        npp)
            remote_run <<EOF
set -e
mkdir -p '${LOG_DIR}'
cd '${NPP_DIR}'
nohup env NPP_PORT=${NPP_PORT} \
    NPP_MONGO_URI=mongodb://localhost:27017 \
    NPP_EARNINGS_DB=/home/qlib/news/benzinga_earnings.sqlite3 \
    NPP_ECON_EVENTS_DB=/home/qlib/news/nasdaq_econ_events.sqlite3 \
    ${PYTHON} main.py > '${log_file}' 2>&1 &
echo \$! > '${pid_file}'
echo "NPP started with PID \$(cat '${pid_file}')"
EOF
            ;;
        upq)
            remote_run <<EOF
set -e
mkdir -p '${LOG_DIR}'
cd '${UPQ_DIR}'
nohup env PORT=${UPQ_PORT} STORAGE_ROOT=/home/qlib/upq_storage \
    ./target/release/upq-service > '${log_file}' 2>&1 &
echo \$! > '${pid_file}'
echo "UPQ started with PID \$(cat '${pid_file}')"
EOF
            ;;
        web)
            remote_run <<EOF
set -e
export NVM_DIR="\$HOME/.nvm"
source "\$NVM_DIR/nvm.sh"
mkdir -p '${LOG_DIR}'
cd '${WEB_DIR}'
nohup env PORT=${WEB_PORT} \
    PMB_BASE_URL=http://127.0.0.1:${PMB_PORT} \
    NPP_BASE_URL=http://127.0.0.1:${NPP_PORT} \
    UPQ_BASE_URL=http://127.0.0.1:${UPQ_PORT} \
    PLAYGROUND_SERVICE_URL=http://127.0.0.1:${PLAYGROUND_PORT} \
    node_modules/.bin/next start -p ${WEB_PORT} > '${log_file}' 2>&1 &
echo \$! > '${pid_file}'
echo "WEB started with PID \$(cat '${pid_file}')"
EOF
            ;;
        playground)
            remote_run <<EOF
set -e
mkdir -p '${LOG_DIR}'
cd '${PLAYGROUND_DIR}'
nohup env PLAYGROUND_PORT=${PLAYGROUND_PORT} \
    QFINZERO_UPQ_URL=http://127.0.0.1:${UPQ_PORT} \
    QFINZERO_NPP_URL=http://127.0.0.1:${NPP_PORT} \
    QFINZERO_PMB_URL=http://127.0.0.1:${PMB_PORT} \
    ${PYTHON} main.py > '${log_file}' 2>&1 &
echo \$! > '${pid_file}'
echo "PLAYGROUND started with PID \$(cat '${pid_file}')"
EOF
            ;;
        *)
            error "Unknown service: $svc"
            return 1
            ;;
    esac

    # Poll health endpoint
    local health_url
    case "$svc" in
        pmb)        health_url="$PMB_HEALTH" ;;
        npp)        health_url="$NPP_HEALTH" ;;
        upq)        health_url="$UPQ_HEALTH" ;;
        playground) health_url="$PLAYGROUND_HEALTH" ;;
        web)        health_url="$WEB_HEALTH" ;;
    esac

    echo -n "  Waiting for $(uc "$svc") to become ready"
    local ok=0
    for _ in $(seq 1 15); do
        sleep 2
        echo -n "."
        if remote_run <<EOF 2>/dev/null
curl -sf '${health_url}' -o /dev/null
EOF
        then
            ok=1
            break
        fi
    done
    echo ""

    if [ "$ok" = "1" ]; then
        info "$(uc "$svc") is healthy at ${health_url}"
    else
        warn "$(uc "$svc") did not pass health check after 30 s — check logs: ${log_file}"
    fi
}

# ── Stop individual service ───────────────────────────────────────────────────

stop_service() {
    local svc="$1"
    local pid_file="${PID_DIR}/${svc}.pid"

    section "Stopping $(uc "$svc")"

    remote_run <<EOF
set -e
PID_FILE='${pid_file}'
SVC='${svc}'

if [ ! -f "\$PID_FILE" ]; then
    echo "  No PID file found for \$SVC — assuming not running."
    exit 0
fi

PID=\$(cat "\$PID_FILE")
if ! kill -0 "\$PID" 2>/dev/null; then
    echo "  \$SVC (PID \$PID) is not running."
    rm -f "\$PID_FILE"
    exit 0
fi

echo "  Sending SIGTERM to \$SVC (PID \$PID)..."
kill "\$PID"

for i in \$(seq 1 10); do
    sleep 1
    if ! kill -0 "\$PID" 2>/dev/null; then
        echo "  \$SVC stopped cleanly."
        rm -f "\$PID_FILE"
        exit 0
    fi
done

echo "  \$SVC did not exit after 10 s — sending SIGKILL..."
kill -9 "\$PID" 2>/dev/null || true
sleep 1
if kill -0 "\$PID" 2>/dev/null; then
    echo "  ERROR: could not kill \$SVC (PID \$PID)."
    exit 1
fi
echo "  \$SVC force-killed."
rm -f "\$PID_FILE"
EOF
}

# ── Status ────────────────────────────────────────────────────────────────────

show_status() {
    section "Service Status"

    for svc in pmb npp upq playground web; do
        local port health_url log_file pid_file
        pid_file="${PID_DIR}/${svc}.pid"
        log_file="${LOG_DIR}/${svc}.log"
        case "$svc" in
            pmb)        port=$PMB_PORT;        health_url="$PMB_HEALTH" ;;
            npp)        port=$NPP_PORT;        health_url="$NPP_HEALTH" ;;
            upq)        port=$UPQ_PORT;        health_url="$UPQ_HEALTH" ;;
            playground) port=$PLAYGROUND_PORT; health_url="$PLAYGROUND_HEALTH" ;;
            web)        port=$WEB_PORT;        health_url="$WEB_HEALTH" ;;
        esac

        echo ""
        echo -e "${BOLD}$(uc "$svc")${NC}  (port ${port})"

        local pid_status
        pid_status=$(remote_run <<EOF 2>/dev/null || echo "ssh_error"
PID_FILE='${pid_file}'
if [ ! -f "\$PID_FILE" ]; then
    echo 'no_pid_file'
else
    PID=\$(cat "\$PID_FILE")
    if kill -0 "\$PID" 2>/dev/null; then
        echo "running:\$PID"
    else
        echo "stale:\$PID"
    fi
fi
EOF
)
        case "$pid_status" in
            running:*) echo -e "  Process : ${GREEN}running${NC} (PID ${pid_status#running:})" ;;
            stale:*)   echo -e "  Process : ${YELLOW}stale PID${NC} (PID ${pid_status#stale:} no longer alive)" ;;
            no_pid_file) echo -e "  Process : ${RED}stopped${NC} (no PID file)" ;;
            *)         echo -e "  Process : ${RED}SSH error${NC}" ;;
        esac

        local port_status
        port_status=$(remote_run <<EOF 2>/dev/null || echo "ssh_error"
if ss -tlnp 2>/dev/null | grep -q ':${port}[^0-9]'; then
    echo 'listening'
else
    echo 'not_listening'
fi
EOF
)
        case "$port_status" in
            listening)     echo -e "  Port    : ${GREEN}:${port} listening${NC}" ;;
            not_listening) echo -e "  Port    : ${RED}:${port} not listening${NC}" ;;
            *)             echo -e "  Port    : ${YELLOW}unknown${NC}" ;;
        esac

        local health_status
        health_status=$(remote_run <<EOF 2>/dev/null || echo "fail"
if curl -sf '${health_url}' -o /dev/null 2>/dev/null; then echo 'ok'; else echo 'fail'; fi
EOF
)
        case "$health_status" in
            ok)   echo -e "  Health  : ${GREEN}OK${NC}  ($health_url)" ;;
            fail) echo -e "  Health  : ${RED}FAIL${NC} ($health_url)" ;;
            *)    echo -e "  Health  : ${YELLOW}unknown${NC}" ;;
        esac

        echo "  Log (${log_file}) — last 5 lines:"
        remote_run <<EOF 2>/dev/null || echo "    (ssh error reading log)"
if [ -f '${log_file}' ]; then
    tail -5 '${log_file}' | sed 's/^/    /'
else
    echo '    (no log file yet)'
fi
EOF
    done
    echo ""
}

# ── Command dispatch ──────────────────────────────────────────────────────────

usage() {
    echo ""
    echo "Usage: $0 [-b <branch>] <command> [service]"
    echo ""
    echo "Options:"
    echo "  -b <branch>   Use specific git branch (default: main)"
    echo ""
    echo "Commands:"
    echo "  start   [pmb|npp|upq|playground|web]   — git pull, build if needed, then start"
    echo "  stop    [pmb|npp|upq|playground|web]   — stop service(s)"
    echo "  restart [pmb|npp|upq|playground|web]   — stop then start (with git pull + rebuild)"
    echo "  status                                  — show all services status"
    echo ""
    echo "Omit [service] to target all five services."
    echo ""
    echo "Examples:"
    echo "  $0 restart upq                          — restart UPQ on main branch"
    echo "  $0 -b dev/tools-unit-tests restart upq  — restart UPQ on specific branch"
    echo ""
}

resolve_services() {
    case "${1:-}" in
        pmb|npp|upq|playground|web) echo "$1" ;;
        "")              echo "pmb npp upq playground web" ;;
        *)               error "Unknown service: '${1}'. Valid: pmb, npp, upq, playground, web"; exit 1 ;;
    esac
}

# ── Parse options ─────────────────────────────────────────────────────────────

BRANCH_OVERRIDE=""
while getopts "b:" opt; do
    case "$opt" in
        b) BRANCH_OVERRIDE="$OPTARG" ;;
        *) usage; exit 1 ;;
    esac
done
shift $((OPTIND - 1))

CMD="${1:-}"
SVC_ARG="${2:-}"

case "$CMD" in
    start)
        SVCS=$(resolve_services "$SVC_ARG")
        TARGET_BRANCH=$(resolve_remote_branch "$SVCS")
        remote_git_pull "$TARGET_BRANCH"
        if echo "$SVCS" | grep -qw upq; then remote_build_upq_if_needed; fi
        if echo "$SVCS" | grep -qw web; then remote_build_web_if_needed; fi
        for svc in $SVCS; do start_service "$svc"; done
        ;;
    stop)
        SVCS=$(resolve_services "$SVC_ARG")
        for svc in $SVCS; do stop_service "$svc"; done
        ;;
    restart)
        SVCS=$(resolve_services "$SVC_ARG")
        for svc in $SVCS; do stop_service "$svc"; done
        TARGET_BRANCH=$(resolve_remote_branch "$SVCS")
        remote_git_pull "$TARGET_BRANCH"
        if echo "$SVCS" | grep -qw upq; then remote_build_upq_if_needed; fi
        if echo "$SVCS" | grep -qw web; then remote_build_web_if_needed; fi
        for svc in $SVCS; do start_service "$svc"; done
        ;;
    status)
        show_status
        ;;
    ""|--help|-h|help)
        usage; exit 0
        ;;
    *)
        error "Unknown command: '$CMD'"; usage; exit 1
        ;;
esac
