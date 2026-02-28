#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$ROOT_DIR/scripts/upq_flatfiles.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    fail "expected output to contain: $needle"
  fi
}

[[ -f "$SCRIPT" ]] || fail "missing script: $SCRIPT"
[[ -x "$SCRIPT" ]] || fail "script is not executable: $SCRIPT"

help_out="$("$SCRIPT" help 2>&1)" || fail "help command failed"
assert_contains "$help_out" "update"
assert_contains "$help_out" "deploy-cron"
assert_contains "$help_out" "sync-data-range"
assert_contains "$help_out" "--from YYYY-MM-DD"

status_out="$("$SCRIPT" status 2>&1)" || fail "status command failed"
assert_contains "$status_out" "UPQ Flat Files"
assert_contains "$status_out" "data_root"

tmpd="$(mktemp -d)"
trap 'rm -rf "$tmpd"' EXIT
mkdir -p "$tmpd/bin"
cat > "$tmpd/bin/aws" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "s3" && "${2:-}" == "ls" ]]; then
  target="${3:-}"
  if [[ "$target" == *"us_options_opra/minute_aggs_v1/2026/02"* ]]; then
    echo "2026-02-27 07:40:29   23569792 us_options_opra/minute_aggs_v1/2026/02/2026-02-18.csv.gz"
  fi
  exit 0
fi
if [[ "${1:-}" == "s3" && "${2:-}" == "cp" ]]; then
  echo "fatal error: An error occurred (403) when calling the HeadObject operation: Forbidden" >&2
  exit 1
fi
exit 0
MOCK
chmod +x "$tmpd/bin/aws"

set +e
mock_out="$(PATH="$tmpd/bin:$PATH" POLYGON_S3_ACCESS_KEY_ID=dummy POLYGON_S3_SECRET_ACCESS_KEY=dummy "$SCRIPT" sync-data-range --from 2026-02-18 --to 2026-02-18 --no-rates 2>&1)"
mock_rc=$?
set -e
[[ "$mock_rc" -eq 0 ]] || fail "script should not fail on single forbidden object"
assert_contains "$mock_out" "dataset=option_minute"
assert_contains "$mock_out" "forbidden=1"

echo "PASS: upq_flatfiles_test"
