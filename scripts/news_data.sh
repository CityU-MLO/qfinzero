#!/usr/bin/env bash
# news_data.sh — News data pipeline management
#
# Must be run ON the qlib server (not via SSH wrapper).
# Deploy: git pull in /home/qlib/qfinzero, then run directly.
#
# Usage:
#   ./scripts/news_data.sh init          # Full historical download of all sources to today
#   ./scripts/news_data.sh update        # Daily incremental update (idempotent, run via cron)
#   ./scripts/news_data.sh deploy-cron   # Install crontab entry for daily update at 06:00 UTC
#   ./scripts/news_data.sh status        # Show latest date / counts for each data source

set -euo pipefail

# ── Constants ─────────────────────────────────────────────────────────────────

NEWS_DIR="/home/qlib/news"
LOG_DIR="$NEWS_DIR/logs"
CONDA="/home/qlib/miniconda3/bin/conda"
PYTHON="$CONDA run -n base python"
SQLITE3="$CONDA run -n base python -c"

# API key used by all Massive.com scrapers
MASSIVE_API_KEY="ngkWLCluaLo4xfda5htLqYc5mNQ9j6Uk"

# Cron schedule: 06:00 UTC daily
CRON_SCHEDULE="0 6 * * *"
SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
CRON_ENTRY="$CRON_SCHEDULE $SCRIPT_PATH update >> $LOG_DIR/cron.log 2>&1"

# ── Color helpers ─────────────────────────────────────────────────────────────

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
section() { echo -e "\n${BOLD}${CYAN}=== $* ===${NC}"; }

# ── Guards ────────────────────────────────────────────────────────────────────

check_server() {
    if [ ! -d "$NEWS_DIR" ]; then
        error "NEWS_DIR not found: $NEWS_DIR"
        error "This script must be run on the qlib server."
        exit 1
    fi
}

# ── Run a Python scraper ──────────────────────────────────────────────────────

run_scraper() {
    local label="$1"
    local script="$2"
    local log_file="$LOG_DIR/$(basename "${script%.py}")_$(date -u +%Y%m%d_%H%M%S).log"

    section "$label"
    info "Script : $NEWS_DIR/$script"
    info "Log    : $log_file"

    mkdir -p "$LOG_DIR"

    # Run in a subshell so cd does not mutate caller's working directory.
    # PIPESTATUS[0] captures the Python exit code; tee's exit code is ignored.
    local py_exit
    (
        cd "$NEWS_DIR"
        MASSIVE_API_KEY="$MASSIVE_API_KEY" \
        $PYTHON "$script" 2>&1 | tee "$log_file"
        exit "${PIPESTATUS[0]}"
    ) && py_exit=0 || py_exit=$?

    if [ "$py_exit" -eq 0 ]; then
        info "$label — DONE"
    else
        error "$label — FAILED (exit $py_exit; see $log_file)"
        return 1
    fi
}

# ── Commands ──────────────────────────────────────────────────────────────────

cmd_init() {
    section "News Data — Full Initialization"
    info "Downloading all historical data through today ($(date -u +%Y-%m-%d))."
    info "This will take a while. Existing files are skipped (resume-safe)."
    echo ""

    run_scraper "1/4  Market News (Massive API → output_news_by_day/)" \
        "massive_download_all.py"

    run_scraper "2/4  Market News → MongoDB (ticker_news collection)" \
        "insert_mongodb.py"

    run_scraper "3/4  NASDAQ Economic Calendar → sqlite3" \
        "scrape_nasdaq_econ_events.py"

    run_scraper "4/4  Benzinga Earnings Calendar → sqlite3" \
        "benzinga_calendar.py"

    echo ""
    info "Init complete. Run './scripts/news_data.sh status' to verify."
}

cmd_update() {
    section "News Data — Daily Update ($(date -u +%Y-%m-%dT%H:%M:%SZ))"

    run_scraper "1/4  Market News (Massive API → output_news_by_day/)" \
        "massive_download_all.py"

    run_scraper "2/4  Market News → MongoDB (ticker_news collection)" \
        "insert_mongodb.py"

    run_scraper "3/4  NASDAQ Economic Calendar → sqlite3" \
        "scrape_nasdaq_econ_events.py"

    run_scraper "4/4  Benzinga Earnings Calendar → sqlite3" \
        "benzinga_calendar.py"

    echo ""
    info "Update complete."
}

cmd_deploy_cron() {
    section "Deploy Cron Job"
    info "Entry: $CRON_ENTRY"
    echo ""

    mkdir -p "$LOG_DIR"

    # Check if already installed (crontab -l exits 1 when empty — use || true to avoid pipefail)
    local existing
    existing=$(crontab -l 2>/dev/null || true)
    if echo "$existing" | grep -qF "$SCRIPT_PATH"; then
        warn "Cron entry already exists. No changes made."
        echo ""
        echo "$existing"
        return 0
    fi

    # Backup existing crontab
    local backup="$LOG_DIR/crontab.backup.$(date -u +%Y%m%d_%H%M%S)"
    echo "$existing" > "$backup"
    info "Existing crontab backed up to: $backup"

    # Install new entry
    (echo "$existing"; echo "$CRON_ENTRY") | crontab -

    info "Cron entry installed successfully."
    echo ""
    echo "Current crontab:"
    crontab -l
}

cmd_status() {
    section "News Data — Status"

    # Market news JSON files
    local json_dir="$NEWS_DIR/output_news_by_day"
    if [ -d "$json_dir" ]; then
        local count latest
        count=$(ls "$json_dir"/*.json 2>/dev/null | wc -l || echo 0)
        latest=$(ls "$json_dir"/*.json 2>/dev/null | sort | tail -1 | xargs basename 2>/dev/null | sed 's/.json//' || echo "none")
        echo -e "  ${BOLD}Market News JSON${NC}   : $count files, latest day = $latest"
    else
        echo -e "  ${BOLD}Market News JSON${NC}   : ${RED}directory not found${NC}"
    fi

    # MongoDB ticker_news
    local mongo_count
    mongo_count=$(mongosh --quiet --eval \
        'db.getSiblingDB("market_news").ticker_news.estimatedDocumentCount()' \
        2>/dev/null || echo "N/A")
    echo -e "  ${BOLD}MongoDB ticker_news${NC}: $mongo_count documents"

    # NASDAQ econ events sqlite3
    local econ_db="$NEWS_DIR/nasdaq_econ_events.sqlite3"
    if [ -f "$econ_db" ]; then
        local econ_count econ_latest
        econ_count=$($SQLITE3 "import sqlite3; c=sqlite3.connect('$econ_db'); print(c.execute('SELECT COUNT(*) FROM econ_events').fetchone()[0])" 2>/dev/null || echo "N/A")
        econ_latest=$($SQLITE3 "import sqlite3; c=sqlite3.connect('$econ_db'); print(c.execute('SELECT MAX(date) FROM econ_events').fetchone()[0])" 2>/dev/null || echo "N/A")
        echo -e "  ${BOLD}NASDAQ Econ Events${NC} : $econ_count rows, latest date = $econ_latest"
    else
        echo -e "  ${BOLD}NASDAQ Econ Events${NC} : ${YELLOW}db not found${NC}"
    fi

    # Benzinga earnings sqlite3
    local benz_db="$NEWS_DIR/benzinga_earnings.sqlite3"
    if [ -f "$benz_db" ]; then
        local benz_count benz_latest
        benz_count=$($SQLITE3 "import sqlite3; c=sqlite3.connect('$benz_db'); print(c.execute('SELECT COUNT(*) FROM earnings').fetchone()[0])" 2>/dev/null || echo "N/A")
        benz_latest=$($SQLITE3 "import sqlite3; c=sqlite3.connect('$benz_db'); print(c.execute('SELECT MAX(date) FROM earnings').fetchone()[0])" 2>/dev/null || echo "N/A")
        echo -e "  ${BOLD}Benzinga Earnings${NC}  : $benz_count rows, latest date = $benz_latest"
    else
        echo -e "  ${BOLD}Benzinga Earnings${NC}  : ${YELLOW}db not found${NC}"
    fi

    echo ""
}

# ── Usage ─────────────────────────────────────────────────────────────────────

usage() {
    echo ""
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  init          Full historical download of all data sources through today"
    echo "  update        Daily incremental update (idempotent; suitable for cron)"
    echo "  deploy-cron   Install crontab entry: runs 'update' daily at 06:00 UTC"
    echo "  status        Show file counts, row counts, and latest dates for each source"
    echo ""
    echo "Data sources:"
    echo "  1. Market news      (Massive API → output_news_by_day/ + MongoDB)"
    echo "  2. NASDAQ econ cal  (nasdaq.com → nasdaq_econ_events.sqlite3)"
    echo "  3. Benzinga earnings (Massive API → benzinga_earnings.sqlite3)"
    echo ""
    echo "Must be run on the qlib server. Logs written to: $LOG_DIR/"
    echo ""
}

# ── Dispatch ──────────────────────────────────────────────────────────────────

check_server

CMD="${1:-}"
case "$CMD" in
    init)         cmd_init ;;
    update)       cmd_update ;;
    deploy-cron)  cmd_deploy_cron ;;
    status)       cmd_status ;;
    ""|--help|-h|help) usage; exit 0 ;;
    *) error "Unknown command: '$CMD'"; usage; exit 1 ;;
esac
