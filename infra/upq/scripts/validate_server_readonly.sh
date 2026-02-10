#!/usr/bin/env bash
set -euo pipefail

HOST="${1:-qlib}"

echo "server=$HOST"
echo "timestamp_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo
echo "[paths]"
ssh -n "$HOST" '
  test -d /home/qlib/data/stock && echo "stock_path=ok" || echo "stock_path=missing";
  test -d /home/qlib/data/us_options_opra && echo "options_path=ok" || echo "options_path=missing";
  test -f /home/qlib/data/assets/treasury_yields.csv && echo "rates_path=ok" || echo "rates_path=missing";
'

echo
echo "[file_counts]"
ssh -n "$HOST" '
  echo -n "stock_day_csv_gz=";
  ls -1 /home/qlib/data/stock/us_stocks_sip_day_aggs_v1_*.csv.gz 2>/dev/null | wc -l | tr -d " ";
  echo -n "stock_minute_csv_gz=";
  ls -1 /home/qlib/data/stock/us_stocks_sip_minute_aggs_v1_*.csv.gz 2>/dev/null | wc -l | tr -d " ";
  echo -n "option_day_csv_gz=";
  find /home/qlib/data/us_options_opra/day_aggs_v1 -type f -name "*.csv.gz" 2>/dev/null | wc -l | tr -d " ";
  echo -n "option_minute_csv_gz=";
  find /home/qlib/data/us_options_opra/minute_aggs_v1 -type f -name "*.csv.gz" 2>/dev/null | wc -l | tr -d " ";
'

echo
echo "[python_baseline_routes]"
ssh -n "$HOST" '
  if [ -f /home/qlib/data/rest_endpoint.py ]; then
    grep -n "@app.route" /home/qlib/data/rest_endpoint.py || true
  else
    echo "rest_endpoint.py=missing"
  fi
'

echo
echo "[python_baseline_health]"
ssh -n "$HOST" '
  if curl -sS --max-time 3 http://127.0.0.1:8000/health >/tmp/upq_health.json 2>/dev/null; then
    echo "health=reachable"
    cat /tmp/upq_health.json
  else
    echo "health=unreachable"
  fi
'
