#!/usr/bin/env bash
# upq_flatfiles.sh — UPQ market data sync via Massive/Polygon Flat Files (AWS S3 API)
#
# Safety-first defaults:
# - Default mode writes only under /tmp/upq_flatfiles_test
# - Will NOT touch /home/qlib/data unless --prod is provided

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

S3_ENDPOINT="https://files.polygon.io"
S3_BUCKET="flatfiles"
DEFAULT_SCHEDULE="30 17 * * 1-5"
DEFAULT_FROM_DATE="2026-01-01"
DEFAULT_TO_DATE="$(date -u +%Y-%m-%d)"

TEST_BASE="/tmp/upq_flatfiles_test"
TEST_RAW_ROOT="$TEST_BASE/raw"
TEST_STORAGE_ROOT="$TEST_BASE/storage"
TEST_MANIFEST="$TEST_BASE/state/manifest.sqlite"
TEST_LOG_DIR="$TEST_BASE/logs"
TEST_STAGE_ROOT="$TEST_BASE/stage"
TEST_DATA_ROOT="$TEST_BASE/data"

PROD_RAW_ROOT="/home/qlib/upq_data"
PROD_STORAGE_ROOT="/home/qlib/upq_storage"
PROD_MANIFEST="/home/qlib/upq_state/manifest.sqlite"
PROD_LOG_DIR="/home/qlib/qfinzero/logs/upq_data"
PROD_STAGE_ROOT="/home/qlib/upq_stage"
PROD_DATA_ROOT="/home/qlib/data"

UPQ_INGEST_BIN="$REPO_ROOT/infra/upq/target/release/upq-ingest"
YIELD_SCRIPT="/home/qlib/news/download_yield.py"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
section() { echo -e "\n${BOLD}${CYAN}=== $* ===${NC}"; }

MODE="test"
RAW_ROOT="$TEST_RAW_ROOT"
STORAGE_ROOT="$TEST_STORAGE_ROOT"
MANIFEST_PATH="$TEST_MANIFEST"
LOG_DIR="$TEST_LOG_DIR"
STAGE_ROOT="$TEST_STAGE_ROOT"
DATA_ROOT="$TEST_DATA_ROOT"

RUN_INGEST=1
SYNC_RATES=1
DRY_RUN=0
SCHEDULE="$DEFAULT_SCHEDULE"
FROM_DATE="$DEFAULT_FROM_DATE"
TO_DATE="$DEFAULT_TO_DATE"
ONLY_STOCK=0

select_mode() {
  local mode="$1"
  MODE="$mode"
  if [[ "$mode" == "prod" ]]; then
    RAW_ROOT="$PROD_RAW_ROOT"
    STORAGE_ROOT="$PROD_STORAGE_ROOT"
    MANIFEST_PATH="$PROD_MANIFEST"
    LOG_DIR="$PROD_LOG_DIR"
    STAGE_ROOT="$PROD_STAGE_ROOT"
    DATA_ROOT="$PROD_DATA_ROOT"
  else
    RAW_ROOT="$TEST_RAW_ROOT"
    STORAGE_ROOT="$TEST_STORAGE_ROOT"
    MANIFEST_PATH="$TEST_MANIFEST"
    LOG_DIR="$TEST_LOG_DIR"
    STAGE_ROOT="$TEST_STAGE_ROOT"
    DATA_ROOT="$TEST_DATA_ROOT"
  fi
}

usage() {
  cat <<USAGE
Usage: $0 <command> [options]

Commands:
  update               Sync full flat files to stage/raw layout and run upq-ingest
  sync-data-range      Sync date range into /home/qlib/data-compatible hierarchy
  ingest-stock-range   Ingest stock files from data layout for a date range (incremental)
  daily-stock-update   Daily stock-only sync + incremental ingest
  status               Show status for raw/storage/data roots
  deploy-cron          Install a cron entry for daily update
  help                 Show this help message

Options:
  --prod                Use production directories (/home/qlib/upq_* and /home/qlib/data)
  --dry-run             Print planned actions without changes
  --no-ingest           Download only; skip upq-ingest
  --no-rates            Skip treasury yields refresh
  --schedule "<cron>"   Override cron schedule (deploy-cron only)
  --from YYYY-MM-DD     Start date for sync-data-range (default: $DEFAULT_FROM_DATE)
  --to YYYY-MM-DD       End date for sync-data-range (default: today UTC)
  --only-stock          For sync-data-range, sync stock datasets only (skip options/rates)

Environment (required for non-dry-run sync):
  POLYGON_S3_ACCESS_KEY_ID
  POLYGON_S3_SECRET_ACCESS_KEY

Safety:
  Default mode writes only to: $TEST_BASE
  This script does NOT write to /home/qlib/data unless --prod is set.
USAGE
}

require_aws_cli() {
  if ! command -v aws >/dev/null 2>&1; then
    error "aws CLI not found. Install awscli first."
    error "Ubuntu: sudo apt-get update && sudo apt-get install -y awscli"
    return 1
  fi
}

require_s3_creds() {
  if [[ -z "${POLYGON_S3_ACCESS_KEY_ID:-}" || -z "${POLYGON_S3_SECRET_ACCESS_KEY:-}" ]]; then
    error "Missing S3 credentials."
    error "Set POLYGON_S3_ACCESS_KEY_ID and POLYGON_S3_SECRET_ACCESS_KEY in shell env."
    return 1
  fi
}

validate_date() {
  local d="$1"
  [[ "$d" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || return 1
  python3 - "$d" <<'PY' >/dev/null 2>&1
import datetime, sys
datetime.date.fromisoformat(sys.argv[1])
PY
}

date_in_range() {
  local d="$1"
  [[ "$d" < "$FROM_DATE" || "$d" > "$TO_DATE" ]] && return 1
  return 0
}

ensure_dirs() {
  mkdir -p "$RAW_ROOT/stock/day" "$RAW_ROOT/stock/minute" \
    "$RAW_ROOT/options/day" "$RAW_ROOT/options/minute" "$RAW_ROOT/assets" \
    "$STAGE_ROOT" "$(dirname "$MANIFEST_PATH")" "$LOG_DIR"
}

ensure_data_dirs() {
  mkdir -p "$DATA_ROOT/stock" \
    "$DATA_ROOT/us_options_opra/day_aggs_v1" \
    "$DATA_ROOT/us_options_opra/minute_aggs_v1" \
    "$DATA_ROOT/assets" \
    "$LOG_DIR"
}

aws_list_keys_recursive() {
  local prefix="$1"
  AWS_ACCESS_KEY_ID="${POLYGON_S3_ACCESS_KEY_ID}" \
  AWS_SECRET_ACCESS_KEY="${POLYGON_S3_SECRET_ACCESS_KEY}" \
    aws s3 ls "s3://$S3_BUCKET/$prefix" --recursive --endpoint-url "$S3_ENDPOINT" \
    | awk '{print $4}'
}

month_prefixes_in_range() {
  python3 - "$FROM_DATE" "$TO_DATE" <<'PY'
import datetime, sys
start = datetime.date.fromisoformat(sys.argv[1]).replace(day=1)
end = datetime.date.fromisoformat(sys.argv[2]).replace(day=1)
cur = start
while cur <= end:
    print(f"{cur.year:04d}/{cur.month:02d}")
    if cur.month == 12:
        cur = cur.replace(year=cur.year + 1, month=1)
    else:
        cur = cur.replace(month=cur.month + 1)
PY
}

iso_today_utc() {
  python3 - <<'PY'
import datetime
print(datetime.datetime.now(datetime.timezone.utc).date().isoformat())
PY
}

iso_add_days() {
  local d="$1"
  local n="$2"
  python3 - "$d" "$n" <<'PY'
import datetime, sys
base = datetime.date.fromisoformat(sys.argv[1])
delta = int(sys.argv[2])
print((base + datetime.timedelta(days=delta)).isoformat())
PY
}

latest_stock_daily_partition_date() {
  if [[ ! -d "$STORAGE_ROOT/stock_daily" ]]; then
    echo ""
    return
  fi
  local latest
  latest="$(ls -1 "$STORAGE_ROOT/stock_daily" 2>/dev/null | grep '^trade_date=' | sort | tail -n 1 || true)"
  if [[ -z "$latest" ]]; then
    echo ""
    return
  fi
  echo "${latest#trade_date=}"
}

aws_copy_key_to_file() {
  local key="$1"
  local out_file="$2"

  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[DRY-RUN] aws s3 cp s3://$S3_BUCKET/$key $out_file --endpoint-url $S3_ENDPOINT"
    return 0
  fi

  mkdir -p "$(dirname "$out_file")"
  if [[ -f "$out_file" ]]; then
    return 10
  fi

  local err_file
  err_file="$(mktemp)"
  if AWS_ACCESS_KEY_ID="${POLYGON_S3_ACCESS_KEY_ID}" \
    AWS_SECRET_ACCESS_KEY="${POLYGON_S3_SECRET_ACCESS_KEY}" \
    aws s3 cp "s3://$S3_BUCKET/$key" "$out_file" --endpoint-url "$S3_ENDPOINT" --no-progress 2>"$err_file"; then
    rm -f "$err_file"
    return 0
  fi

  if grep -qiE "(403|Forbidden)" "$err_file"; then
    rm -f "$err_file"
    return 11
  fi

  cat "$err_file" >&2
  rm -f "$err_file"
  return 1
}

extract_trade_date_from_key() {
  local key="$1"
  local base
  base="$(basename "$key")"
  if [[ "$base" =~ ([0-9]{4}-[0-9]{2}-[0-9]{2})\.csv\.gz$ ]]; then
    echo "${BASH_REMATCH[1]}"
  else
    echo ""
  fi
}

build_data_target_path() {
  local dataset="$1"
  local key="$2"
  local trade_date="$3"
  local yyyy="${trade_date:0:4}"
  local mm="${trade_date:5:2}"

  case "$dataset" in
    stock_day)
      echo "$DATA_ROOT/stock/us_stocks_sip_day_aggs_v1_${yyyy}_${mm}_${trade_date}.csv.gz"
      ;;
    stock_minute)
      echo "$DATA_ROOT/stock/us_stocks_sip_minute_aggs_v1_${yyyy}_${mm}_${trade_date}.csv.gz"
      ;;
    option_day)
      echo "$DATA_ROOT/us_options_opra/day_aggs_v1/${yyyy}/${mm}/$(basename "$key")"
      ;;
    option_minute)
      echo "$DATA_ROOT/us_options_opra/minute_aggs_v1/${yyyy}/${mm}/$(basename "$key")"
      ;;
    *)
      return 1
      ;;
  esac
}

sync_dataset_range() {
  local dataset="$1"
  local base_prefix="$2"

  section "Sync dataset=$dataset base_prefix=$base_prefix range=$FROM_DATE..$TO_DATE"

  local considered=0
  local copied=0
  local existed=0
  local forbidden=0
  local skipped_date=0
  local parse_failed=0

  while IFS= read -r ym; do
    [[ -z "$ym" ]] && continue
    local month_prefix="$base_prefix/$ym"

    if [[ "$DRY_RUN" -eq 1 ]]; then
      echo "[DRY-RUN] would list recursively: s3://$S3_BUCKET/$month_prefix"
      continue
    fi

    local keys
    keys="$(aws_list_keys_recursive "$month_prefix" || true)"
    while IFS= read -r key; do
      [[ -z "$key" ]] && continue
      local trade_date
      trade_date="$(extract_trade_date_from_key "$key")"
      if [[ -z "$trade_date" ]]; then
        parse_failed=$((parse_failed + 1))
        continue
      fi
      if ! date_in_range "$trade_date"; then
        skipped_date=$((skipped_date + 1))
        continue
      fi

      considered=$((considered + 1))

      local out_file
      out_file="$(build_data_target_path "$dataset" "$key" "$trade_date")"

      if aws_copy_key_to_file "$key" "$out_file"; then
        copied=$((copied + 1))
      else
        local rc=$?
        if [[ "$rc" -eq 10 ]]; then
          existed=$((existed + 1))
        elif [[ "$rc" -eq 11 ]]; then
          forbidden=$((forbidden + 1))
          warn "forbidden key skipped: $key"
        else
          error "Failed to copy key=$key"
          return 1
        fi
      fi
    done <<< "$keys"
  done < <(month_prefixes_in_range)

  info "dataset=$dataset considered=$considered copied=$copied existed=$existed forbidden=$forbidden skipped_out_of_range=$skipped_date parse_failed=$parse_failed"
}

aws_sync_prefix() {
  local prefix="$1"
  local dest="$2"
  local cmd=(aws s3 sync "s3://$S3_BUCKET/$prefix" "$dest" \
    --endpoint-url "$S3_ENDPOINT" \
    --exclude "*" --include "*.csv.gz" --no-progress)

  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[DRY-RUN] ${cmd[*]}"
    return 0
  fi

  AWS_ACCESS_KEY_ID="${POLYGON_S3_ACCESS_KEY_ID}" \
  AWS_SECRET_ACCESS_KEY="${POLYGON_S3_SECRET_ACCESS_KEY}" \
    "${cmd[@]}"
}

flatten_csv_gz() {
  local src="$1"
  local dst="$2"
  mkdir -p "$dst"

  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[DRY-RUN] flatten $src -> $dst"
    return 0
  fi

  while IFS= read -r -d '' f; do
    cp -n "$f" "$dst/"
  done < <(find "$src" -type f -name "*.csv.gz" -print0)
}

refresh_rates_raw() {
  if [[ "$SYNC_RATES" -eq 0 ]]; then
    warn "Skipping treasury yields refresh (--no-rates)"
    return 0
  fi
  if [[ ! -f "$YIELD_SCRIPT" ]]; then
    warn "Yield script not found: $YIELD_SCRIPT (skip rates)"
    return 0
  fi

  section "Refreshing treasury yields (raw)"
  local out_csv="$RAW_ROOT/assets/treasury_yields.csv"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[DRY-RUN] python3 $YIELD_SCRIPT && copy treasury_yields.csv -> $out_csv"
    return 0
  fi

  (
    cd "$(dirname "$YIELD_SCRIPT")"
    python3 "$(basename "$YIELD_SCRIPT")"
    [[ -f "treasury_yields.csv" ]] || { error "download_yield.py missing output"; exit 1; }
    cp "treasury_yields.csv" "$out_csv"
  )
}

refresh_rates_data() {
  if [[ "$SYNC_RATES" -eq 0 ]]; then
    warn "Skipping treasury yields refresh (--no-rates)"
    return 0
  fi
  if [[ ! -f "$YIELD_SCRIPT" ]]; then
    warn "Yield script not found: $YIELD_SCRIPT (skip rates)"
    return 0
  fi

  section "Refreshing treasury yields (data layout)"
  local out_csv="$DATA_ROOT/assets/treasury_yields.csv"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[DRY-RUN] python3 $YIELD_SCRIPT && copy treasury_yields.csv -> $out_csv"
    return 0
  fi

  (
    cd "$(dirname "$YIELD_SCRIPT")"
    python3 "$(basename "$YIELD_SCRIPT")"
    [[ -f "treasury_yields.csv" ]] || { error "download_yield.py missing output"; exit 1; }
    cp "treasury_yields.csv" "$out_csv"
  )
}

run_ingest() {
  if [[ "$RUN_INGEST" -eq 0 ]]; then
    warn "Skipping ingest (--no-ingest)"
    return 0
  fi
  if [[ ! -x "$UPQ_INGEST_BIN" ]]; then
    error "upq-ingest binary not found or not executable: $UPQ_INGEST_BIN"
    error "Build first: cd $REPO_ROOT/infra/upq && cargo build --release -p upq-ingest"
    return 1
  fi

  section "Running upq-ingest"
  local cmd=("$UPQ_INGEST_BIN" ingest
    --raw-root "$RAW_ROOT"
    --storage-root "$STORAGE_ROOT"
    --manifest "$MANIFEST_PATH")

  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[DRY-RUN] ${cmd[*]}"
    return 0
  fi
  "${cmd[@]}"
}

show_latest_file_pattern() {
  local dir="$1"
  local glob="$2"
  if [[ ! -d "$dir" ]]; then
    echo "missing"
    return
  fi
  local latest
  latest="$(find "$dir" -maxdepth 1 -type f -name "$glob" | sort | tail -n 1 || true)"
  [[ -z "$latest" ]] && echo "none" || basename "$latest"
}

show_latest_nested_file() {
  local dir="$1"
  if [[ ! -d "$dir" ]]; then
    echo "missing"
    return
  fi
  local latest
  latest="$(find "$dir" -type f -name "*.csv.gz" | sort | tail -n 1 || true)"
  [[ -z "$latest" ]] && echo "none" || echo "$latest" | sed "s|^$DATA_ROOT/||"
}

show_latest_partition() {
  local base="$1"
  if [[ ! -d "$base" ]]; then
    echo "missing"
    return
  fi
  local latest
  latest="$(ls -1 "$base" 2>/dev/null | grep '^trade_date=' | sort | tail -n 1 || true)"
  [[ -z "$latest" ]] && echo "none" || echo "$latest"
}

cmd_update() {
  section "UPQ Flat Files Update (mode=$MODE)"
  ensure_dirs
  if [[ "$DRY_RUN" -eq 0 ]]; then
    require_aws_cli
    require_s3_creds
  else
    warn "dry-run mode: skip aws/credentials runtime checks"
  fi

  section "Syncing from Flat Files S3"
  aws_sync_prefix "us_stocks_sip/day_aggs_v1" "$STAGE_ROOT/us_stocks_sip/day_aggs_v1"
  aws_sync_prefix "us_stocks_sip/minute_aggs_v1" "$STAGE_ROOT/us_stocks_sip/minute_aggs_v1"
  aws_sync_prefix "us_options_opra/day_aggs_v1" "$STAGE_ROOT/us_options_opra/day_aggs_v1"
  aws_sync_prefix "us_options_opra/minute_aggs_v1" "$STAGE_ROOT/us_options_opra/minute_aggs_v1"

  section "Flattening into upq-ingest raw layout"
  flatten_csv_gz "$STAGE_ROOT/us_stocks_sip/day_aggs_v1" "$RAW_ROOT/stock/day"
  flatten_csv_gz "$STAGE_ROOT/us_stocks_sip/minute_aggs_v1" "$RAW_ROOT/stock/minute"
  flatten_csv_gz "$STAGE_ROOT/us_options_opra/day_aggs_v1" "$RAW_ROOT/options/day"
  flatten_csv_gz "$STAGE_ROOT/us_options_opra/minute_aggs_v1" "$RAW_ROOT/options/minute"

  refresh_rates_raw
  run_ingest

  section "Done"
  info "mode         : $MODE"
  info "raw_root     : $RAW_ROOT"
  info "storage_root : $STORAGE_ROOT"
  info "manifest     : $MANIFEST_PATH"
}

cmd_sync_data_range() {
  if ! validate_date "$FROM_DATE" || ! validate_date "$TO_DATE"; then
    error "--from/--to must be valid YYYY-MM-DD"
    return 2
  fi
  if [[ "$FROM_DATE" > "$TO_DATE" ]]; then
    error "--from cannot be later than --to"
    return 2
  fi

  section "Sync Flat Files to data layout (mode=$MODE, range=$FROM_DATE..$TO_DATE)"
  ensure_data_dirs

  if [[ "$DRY_RUN" -eq 0 ]]; then
    require_aws_cli
    require_s3_creds
  else
    warn "dry-run mode: skip aws/credentials runtime checks"
  fi

  sync_dataset_range "stock_day" "us_stocks_sip/day_aggs_v1"
  sync_dataset_range "stock_minute" "us_stocks_sip/minute_aggs_v1"

  if [[ "$ONLY_STOCK" -eq 0 ]]; then
    sync_dataset_range "option_day" "us_options_opra/day_aggs_v1"
    sync_dataset_range "option_minute" "us_options_opra/minute_aggs_v1"
    refresh_rates_data
  else
    warn "only-stock mode: skip options and rates in sync-data-range"
  fi

  section "Data layout sync done"
  info "mode      : $MODE"
  info "data_root : $DATA_ROOT"
}

cmd_ingest_stock_range() {
  if ! validate_date "$FROM_DATE" || ! validate_date "$TO_DATE"; then
    error "--from/--to must be valid YYYY-MM-DD"
    return 2
  fi
  if [[ "$FROM_DATE" > "$TO_DATE" ]]; then
    error "--from cannot be later than --to"
    return 2
  fi
  if [[ ! -x "$UPQ_INGEST_BIN" ]]; then
    error "upq-ingest binary not found or not executable: $UPQ_INGEST_BIN"
    return 1
  fi

  local tmp_root
  tmp_root="$(mktemp -d /tmp/upq_stock_raw_XXXXXX)"
  trap "rm -rf '$tmp_root'" EXIT
  mkdir -p "$tmp_root/stock/day" "$tmp_root/stock/minute"

  local copied_day=0
  local copied_minute=0
  while IFS= read -r d; do
    local yyyy="${d:0:4}"
    local mm="${d:5:2}"
    local day_file="$DATA_ROOT/stock/us_stocks_sip_day_aggs_v1_${yyyy}_${mm}_${d}.csv.gz"
    local minute_file="$DATA_ROOT/stock/us_stocks_sip_minute_aggs_v1_${yyyy}_${mm}_${d}.csv.gz"
    if [[ -f "$day_file" ]]; then
      cp -n "$day_file" "$tmp_root/stock/day/" || true
      copied_day=$((copied_day + 1))
    fi
    if [[ -f "$minute_file" ]]; then
      cp -n "$minute_file" "$tmp_root/stock/minute/" || true
      copied_minute=$((copied_minute + 1))
    fi
  done < <(python3 - "$FROM_DATE" "$TO_DATE" <<'PY'
import datetime, sys
start = datetime.date.fromisoformat(sys.argv[1])
end = datetime.date.fromisoformat(sys.argv[2])
cur = start
while cur <= end:
    print(cur.isoformat())
    cur += datetime.timedelta(days=1)
PY
)

  if [[ "$copied_day" -eq 0 && "$copied_minute" -eq 0 ]]; then
    warn "No stock files found for range $FROM_DATE..$TO_DATE under $DATA_ROOT/stock"
    trap - EXIT
    rm -rf "$tmp_root"
    return 0
  fi

  section "Run stock-only incremental ingest"
  info "range=$FROM_DATE..$TO_DATE day_files=$copied_day minute_files=$copied_minute"

  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[DRY-RUN] $UPQ_INGEST_BIN ingest --raw-root $tmp_root --storage-root $STORAGE_ROOT --manifest $MANIFEST_PATH"
    return 0
  fi

  "$UPQ_INGEST_BIN" ingest \
    --raw-root "$tmp_root" \
    --storage-root "$STORAGE_ROOT" \
    --manifest "$MANIFEST_PATH"

  trap - EXIT
  rm -rf "$tmp_root"
}

cmd_daily_stock_update() {
  section "Daily stock-only update (mode=$MODE)"
  ensure_data_dirs
  if [[ "$DRY_RUN" -eq 0 ]]; then
    require_aws_cli
    require_s3_creds
  else
    warn "dry-run mode: skip aws/credentials runtime checks"
  fi

  local latest
  latest="$(latest_stock_daily_partition_date)"
  local from_date
  if [[ -n "$latest" ]]; then
    from_date="$(iso_add_days "$latest" 1)"
  else
    from_date="$DEFAULT_FROM_DATE"
  fi
  local to_date
  to_date="$(iso_today_utc)"

  if [[ "$from_date" > "$to_date" ]]; then
    info "No new stock dates to process (latest=$latest, today=$to_date)"
    return 0
  fi

  FROM_DATE="$from_date"
  TO_DATE="$to_date"
  ONLY_STOCK=1
  SYNC_RATES=0

  info "computed range=$FROM_DATE..$TO_DATE (latest_partition=$latest)"
  cmd_sync_data_range
  cmd_ingest_stock_range
}

cmd_status() {
  section "UPQ Flat Files Status (mode=$MODE)"
  echo "raw_root      : $RAW_ROOT"
  echo "stage_root    : $STAGE_ROOT"
  echo "storage_root  : $STORAGE_ROOT"
  echo "manifest_path : $MANIFEST_PATH"
  echo "data_root     : $DATA_ROOT"
  echo ""
  echo "Raw files:"
  echo "  stock/day latest      : $(show_latest_file_pattern "$RAW_ROOT/stock/day" "*.csv.gz")"
  echo "  stock/minute latest   : $(show_latest_file_pattern "$RAW_ROOT/stock/minute" "*.csv.gz")"
  echo "  options/day latest    : $(show_latest_file_pattern "$RAW_ROOT/options/day" "*.csv.gz")"
  echo "  options/minute latest : $(show_latest_file_pattern "$RAW_ROOT/options/minute" "*.csv.gz")"
  if [[ -f "$RAW_ROOT/assets/treasury_yields.csv" ]]; then
    echo "  rates file            : present"
  else
    echo "  rates file            : missing"
  fi
  echo ""
  echo "Storage partitions:"
  echo "  stock_daily   : $(show_latest_partition "$STORAGE_ROOT/stock_daily")"
  echo "  stock_minute  : $(show_latest_partition "$STORAGE_ROOT/stock_minute")"
  echo "  option_day    : $(show_latest_partition "$STORAGE_ROOT/option_day")"
  echo "  option_minute : $(show_latest_partition "$STORAGE_ROOT/option_minute")"
  echo ""
  echo "Data-layout files:"
  echo "  stock day latest file      : $(show_latest_file_pattern "$DATA_ROOT/stock" "us_stocks_sip_day_aggs_v1_*.csv.gz")"
  echo "  stock minute latest file   : $(show_latest_file_pattern "$DATA_ROOT/stock" "us_stocks_sip_minute_aggs_v1_*.csv.gz")"
  echo "  option day latest file     : $(show_latest_nested_file "$DATA_ROOT/us_options_opra/day_aggs_v1")"
  echo "  option minute latest file  : $(show_latest_nested_file "$DATA_ROOT/us_options_opra/minute_aggs_v1")"
  if [[ -f "$DATA_ROOT/assets/treasury_yields.csv" ]]; then
    echo "  data rates file            : present"
  else
    echo "  data rates file            : missing"
  fi
}

cmd_deploy_cron() {
  section "Deploy UPQ Flat Files Cron (mode=$MODE)"
  ensure_dirs
  local script_path="$SCRIPT_DIR/$(basename "$0")"
  local cron_entry="$SCHEDULE $script_path update $( [[ "$MODE" == "prod" ]] && echo "--prod" ) >> $LOG_DIR/cron.log 2>&1"
  local existing
  existing="$(crontab -l 2>/dev/null || true)"

  if echo "$existing" | grep -qF "$script_path update"; then
    warn "Cron entry already exists for this script. No changes made."
    echo "$existing"
    return 0
  fi

  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[DRY-RUN] install cron:"
    echo "$cron_entry"
    return 0
  fi

  (echo "$existing"; echo "$cron_entry") | crontab -
  info "Cron installed: $cron_entry"
}

parse_common_flags() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --prod)
        select_mode "prod"
        shift
        ;;
      --dry-run)
        DRY_RUN=1
        shift
        ;;
      --no-ingest)
        RUN_INGEST=0
        shift
        ;;
      --no-rates)
        SYNC_RATES=0
        shift
        ;;
      --schedule)
        [[ $# -ge 2 ]] || { error "--schedule requires a value"; exit 2; }
        SCHEDULE="$2"
        shift 2
        ;;
      --from)
        [[ $# -ge 2 ]] || { error "--from requires YYYY-MM-DD"; exit 2; }
        FROM_DATE="$2"
        shift 2
        ;;
      --to)
        [[ $# -ge 2 ]] || { error "--to requires YYYY-MM-DD"; exit 2; }
        TO_DATE="$2"
        shift 2
        ;;
      --only-stock)
        ONLY_STOCK=1
        shift
        ;;
      *)
        error "Unknown option: $1"
        usage
        exit 2
        ;;
    esac
  done
}

main() {
  local cmd="${1:-help}"
  shift || true

  select_mode "test"
  parse_common_flags "$@"

  case "$cmd" in
    update) cmd_update ;;
    sync-data-range) cmd_sync_data_range ;;
    ingest-stock-range) cmd_ingest_stock_range ;;
    daily-stock-update) cmd_daily_stock_update ;;
    status) cmd_status ;;
    deploy-cron) cmd_deploy_cron ;;
    help|-h|--help) usage ;;
    *)
      error "Unknown command: $cmd"
      usage
      exit 2
      ;;
  esac
}

main "$@"
