#!/usr/bin/env bash
# test-env.sh — Manage feat/data-platform-frontend test services on the remote qlib server
#
# Usage:
#   ./scripts/test-env.sh start   [pmb|npp|upq]   — git pull, (re)build if needed, then start
#   ./scripts/test-env.sh stop    [pmb|npp|upq]   — stop service(s)
#   ./scripts/test-env.sh restart [pmb|npp|upq]   — stop then start
#   ./scripts/test-env.sh status                  — show running state + port + tail of log
#
# Services run on the remote host accessible via `ssh qlib`.
#   PMB  19701  /home/qlib/qfinzero/infra/pmb  (Python)
#   NPP  19702  /home/qlib/qfinzero/infra/npp  (Python)
#   UPQ  19703  /home/qlib/qfinzero/infra/upq  (Rust binary)

set -euo pipefail

# ── Constants ────────────────────────────────────────────────────────────────

SSH_HOST="qlib"
REMOTE_ROOT="/home/qlib/qfinzero"
REMOTE_BRANCH="feat/data-platform-frontend"

LOG_DIR="/tmp/efan"
PID_DIR="/tmp/efan"

# Service ports
PMB_PORT=19701
NPP_PORT=19702
UPQ_PORT=19703

# Python interpreter
PYTHON="/home/qlib/miniconda3/bin/python3.13"

# Service directories
PMB_DIR="$REMOTE_ROOT/infra/pmb"
NPP_DIR="$REMOTE_ROOT/infra/npp"
UPQ_DIR="$REMOTE_ROOT/infra/upq"

# Health check URLs
PMB_HEALTH="http://127.0.0.1:${PMB_PORT}/v1/health"
NPP_HEALTH="http://127.0.0.1:${NPP_PORT}/npp/health"
UPQ_HEALTH="http://127.0.0.1:${UPQ_PORT}/health"

# Environment variables per service
PMB_ENV="PMB_PORT=${PMB_PORT} PMB_UPQ_BASE_URL=http://127.0.0.1:${UPQ_PORT}"
NPP_ENV="NPP_PORT=${NPP_PORT} NPP_MONGO_URI=mongodb://localhost:27017 NPP_EARNINGS_DB=/home/qlib/news/benzinga_earnings.sqlite3 NPP_ECON_EVENTS_DB=/home/qlib/news/nasdaq_econ_events.sqlite3"
UPQ_ENV="PORT=${UPQ_PORT} STORAGE_ROOT=/home/qlib/upq_storage"

# ── Color helpers ────────────────────────────────────────────────────────────

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; }
section() { echo -e "\n${BOLD}${CYAN}=== $* ===${NC}"; }

# ── SSH helper ───────────────────────────────────────────────────────────────

# Run a command on the remote host and print it first for visibility
remote() {
    ssh "$SSH_HOST" "$@"
}

# ── Git pull ─────────────────────────────────────────────────────────────────

remote_git_pull() {
    section "Git pull on remote ($REMOTE_BRANCH)"
    remote bash -c "
        set -e
        cd '${REMOTE_ROOT}'
        current_branch=\$(git rev-parse --abbrev-ref HEAD)
        if [ \"\$current_branch\" != '${REMOTE_BRANCH}' ]; then
            echo \"WARNING: remote HEAD is on '\$current_branch', not '${REMOTE_BRANCH}'.\"
            echo \"Checking out '${REMOTE_BRANCH}'...\"
            git checkout '${REMOTE_BRANCH}'
        fi
        echo 'Pulling latest from origin/${REMOTE_BRANCH}...'
        git pull origin '${REMOTE_BRANCH}'
        echo \"Now at: \$(git log --oneline -1)\"
    "
}

# ── UPQ build ────────────────────────────────────────────────────────────────

remote_build_upq_if_needed() {
    section "Checking UPQ binary freshness"
    remote bash -c "
        set -e
        source \"\$HOME/.cargo/env\"
        BINARY='${UPQ_DIR}/target/release/upq-service'
        SRC_DIR='${UPQ_DIR}/src'

        if [ ! -f \"\$BINARY\" ]; then
            echo 'Binary not found — building from scratch...'
            NEEDS_BUILD=1
        else
            # Find any src file newer than the binary
            NEWER=\$(find '\$SRC_DIR' -name '*.rs' -newer \"\$BINARY\" 2>/dev/null | head -1)
            if [ -n \"\$NEWER\" ]; then
                echo \"Source file newer than binary: \$NEWER\"
                NEEDS_BUILD=1
            else
                echo 'Binary is up-to-date, skipping rebuild.'
                NEEDS_BUILD=0
            fi
        fi

        if [ \"\$NEEDS_BUILD\" = '1' ]; then
            echo 'Running: cargo build --release ...'
            cd '${UPQ_DIR}'
            cargo build --release
            echo 'UPQ build complete.'
        fi
    "
}

# ── PID / process helpers (all run remotely) ─────────────────────────────────

# Returns 0 if service is running, 1 otherwise.
# Side-effect: prints the PID if running.
remote_is_running() {
    local svc="$1"
    local pid_file="${PID_DIR}/${svc}.pid"
    remote bash -c "
        set -e
        PID_FILE='${pid_file}'
        if [ ! -f \"\$PID_FILE\" ]; then
            exit 1
        fi
        PID=\$(cat \"\$PID_FILE\")
        if kill -0 \"\$PID\" 2>/dev/null; then
            echo \"\$PID\"
            exit 0
        else
            exit 1
        fi
    " 2>/dev/null
}

# ── Start individual services ─────────────────────────────────────────────────

start_service() {
    local svc="$1"
    local log_file="${LOG_DIR}/${svc}.log"
    local pid_file="${PID_DIR}/${svc}.pid"

    # Check if already running
    local running_pid
    running_pid=$(remote_is_running "$svc" 2>/dev/null || true)
    if [ -n "$running_pid" ]; then
        warn "${svc^^} is already running (PID $running_pid). Skipping start."
        return 0
    fi

    section "Starting ${svc^^}"

    case "$svc" in
        pmb)
            remote bash -c "
                set -e
                mkdir -p '${LOG_DIR}'
                cd '${PMB_DIR}'
                nohup env ${PMB_ENV} ${PYTHON} main.py \
                    > '${log_file}' 2>&1 &
                echo \$! > '${pid_file}'
                echo 'PMB started with PID '\$(cat '${pid_file}')
            "
            ;;
        npp)
            remote bash -c "
                set -e
                mkdir -p '${LOG_DIR}'
                cd '${NPP_DIR}'
                nohup env ${NPP_ENV} ${PYTHON} main.py \
                    > '${log_file}' 2>&1 &
                echo \$! > '${pid_file}'
                echo 'NPP started with PID '\$(cat '${pid_file}')
            "
            ;;
        upq)
            remote bash -c "
                set -e
                mkdir -p '${LOG_DIR}'
                cd '${UPQ_DIR}'
                nohup env ${UPQ_ENV} ./target/release/upq-service \
                    > '${log_file}' 2>&1 &
                echo \$! > '${pid_file}'
                echo 'UPQ started with PID '\$(cat '${pid_file}')
            "
            ;;
        *)
            error "Unknown service: $svc"
            return 1
            ;;
    esac

    # Wait a few seconds then health-check
    echo -n "  Waiting for ${svc^^} to become ready"
    local health_url
    case "$svc" in
        pmb) health_url="$PMB_HEALTH" ;;
        npp) health_url="$NPP_HEALTH" ;;
        upq) health_url="$UPQ_HEALTH" ;;
    esac

    local ok=0
    for i in $(seq 1 8); do
        sleep 2
        echo -n "."
        if remote bash -c "curl -sf '${health_url}' -o /dev/null" 2>/dev/null; then
            ok=1
            break
        fi
    done
    echo ""

    if [ "$ok" = "1" ]; then
        info "${svc^^} is healthy at ${health_url}"
    else
        warn "${svc^^} did not pass health check after 16 s — check logs: ${log_file}"
    fi
}

# ── Stop individual services ──────────────────────────────────────────────────

stop_service() {
    local svc="$1"
    local pid_file="${PID_DIR}/${svc}.pid"

    section "Stopping ${svc^^}"

    remote bash -c "
        set -e
        PID_FILE='${pid_file}'
        SVC='${svc}'

        if [ ! -f \"\$PID_FILE\" ]; then
            echo '  No PID file found for '\"\$SVC\"' — assuming not running.'
            exit 0
        fi

        PID=\$(cat \"\$PID_FILE\")
        if ! kill -0 \"\$PID\" 2>/dev/null; then
            echo '  '\"\$SVC\"' (PID '\"\$PID\"') is not running.'
            rm -f \"\$PID_FILE\"
            exit 0
        fi

        echo '  Sending SIGTERM to '\"\$SVC\"' (PID '\"\$PID\"')...'
        kill \"\$PID\"

        # Wait up to 10 s for the process to exit
        for i in \$(seq 1 10); do
            sleep 1
            if ! kill -0 \"\$PID\" 2>/dev/null; then
                echo '  '\"\$SVC\"' stopped cleanly.'
                rm -f \"\$PID_FILE\"
                exit 0
            fi
        done

        # Force-kill if still alive
        echo '  '\"\$SVC\"' did not exit after 10 s — sending SIGKILL...'
        kill -9 \"\$PID\" 2>/dev/null || true
        sleep 1
        if kill -0 \"\$PID\" 2>/dev/null; then
            echo '  ERROR: could not kill '\"\$SVC\"' (PID '\"\$PID\"').'
            exit 1
        fi
        echo '  '\"\$SVC\"' force-killed.'
        rm -f \"\$PID_FILE\"
    "
}

# ── Status ────────────────────────────────────────────────────────────────────

show_status() {
    section "Service Status"

    for svc in pmb npp upq; do
        local port health_url log_file pid_file
        pid_file="${PID_DIR}/${svc}.pid"
        log_file="${LOG_DIR}/${svc}.log"

        case "$svc" in
            pmb) port=$PMB_PORT; health_url="$PMB_HEALTH" ;;
            npp) port=$NPP_PORT; health_url="$NPP_HEALTH" ;;
            upq) port=$UPQ_PORT; health_url="$UPQ_HEALTH" ;;
        esac

        echo ""
        echo -e "${BOLD}${svc^^}${NC}  (port ${port})"

        # PID / process state
        local pid_status
        pid_status=$(remote bash -c "
            PID_FILE='${pid_file}'
            if [ ! -f \"\$PID_FILE\" ]; then
                echo 'no_pid_file'
            else
                PID=\$(cat \"\$PID_FILE\")
                if kill -0 \"\$PID\" 2>/dev/null; then
                    echo \"running:\$PID\"
                else
                    echo \"stale:\$PID\"
                fi
            fi
        " 2>/dev/null || echo "ssh_error")

        case "$pid_status" in
            running:*)
                local pid="${pid_status#running:}"
                echo -e "  Process : ${GREEN}running${NC} (PID $pid)"
                ;;
            stale:*)
                local pid="${pid_status#stale:}"
                echo -e "  Process : ${YELLOW}stale PID file${NC} (PID $pid no longer alive)"
                ;;
            no_pid_file)
                echo -e "  Process : ${RED}stopped${NC} (no PID file)"
                ;;
            ssh_error)
                echo -e "  Process : ${RED}SSH error${NC}"
                ;;
        esac

        # Port listening check
        local port_status
        port_status=$(remote bash -c "
            if ss -tlnp 2>/dev/null | grep -q ':${port}\\b'; then
                echo 'listening'
            else
                echo 'not_listening'
            fi
        " 2>/dev/null || echo "ssh_error")

        case "$port_status" in
            listening)
                echo -e "  Port    : ${GREEN}:${port} listening${NC}"
                ;;
            not_listening)
                echo -e "  Port    : ${RED}:${port} not listening${NC}"
                ;;
            *)
                echo -e "  Port    : ${YELLOW}unknown${NC}"
                ;;
        esac

        # Health check
        local health_status
        health_status=$(remote bash -c "
            if curl -sf '${health_url}' -o /dev/null 2>/dev/null; then
                echo 'ok'
            else
                echo 'fail'
            fi
        " 2>/dev/null || echo "ssh_error")

        case "$health_status" in
            ok)
                echo -e "  Health  : ${GREEN}OK${NC}  ($health_url)"
                ;;
            fail)
                echo -e "  Health  : ${RED}FAIL${NC} ($health_url)"
                ;;
            *)
                echo -e "  Health  : ${YELLOW}unknown${NC}"
                ;;
        esac

        # Last few lines of log
        echo "  Log ($log_file) — last 5 lines:"
        remote bash -c "
            if [ -f '${log_file}' ]; then
                tail -5 '${log_file}' | sed 's/^/    /'
            else
                echo '    (no log file yet)'
            fi
        " 2>/dev/null || echo "    (ssh error reading log)"

    done
    echo ""
}

# ── Command dispatch ──────────────────────────────────────────────────────────

usage() {
    echo ""
    echo "Usage: $0 <command> [service]"
    echo ""
    echo "Commands:"
    echo "  start   [pmb|npp|upq]   — git pull, rebuild UPQ if needed, then start"
    echo "  stop    [pmb|npp|upq]   — stop service(s)"
    echo "  restart [pmb|npp|upq]   — stop then start"
    echo "  status                  — show all services status"
    echo ""
    echo "If no service is specified, all three services (pmb, npp, upq) are targeted."
    echo ""
}

# Resolve the list of services from an optional argument
resolve_services() {
    local arg="${1:-}"
    case "$arg" in
        pmb|npp|upq)
            echo "$arg"
            ;;
        "")
            echo "pmb npp upq"
            ;;
        *)
            error "Unknown service: '$arg'. Valid values: pmb, npp, upq"
            exit 1
            ;;
    esac
}

CMD="${1:-}"
SVC_ARG="${2:-}"

case "$CMD" in
    start)
        SERVICES=$(resolve_services "$SVC_ARG")
        remote_git_pull
        # Build UPQ only when it is being started
        if echo "$SERVICES" | grep -qw upq; then
            remote_build_upq_if_needed
        fi
        for svc in $SERVICES; do
            start_service "$svc"
        done
        ;;

    stop)
        SERVICES=$(resolve_services "$SVC_ARG")
        for svc in $SERVICES; do
            stop_service "$svc"
        done
        ;;

    restart)
        SERVICES=$(resolve_services "$SVC_ARG")
        for svc in $SERVICES; do
            stop_service "$svc"
        done
        remote_git_pull
        if echo "$SERVICES" | grep -qw upq; then
            remote_build_upq_if_needed
        fi
        for svc in $SERVICES; do
            start_service "$svc"
        done
        ;;

    status)
        show_status
        ;;

    ""|--help|-h|help)
        usage
        exit 0
        ;;

    *)
        error "Unknown command: '$CMD'"
        usage
        exit 1
        ;;
esac
