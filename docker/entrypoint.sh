#!/bin/sh
# Container entry point: optional sample data, then the hub.
set -e
if [ "${QFZ_SAMPLE:-0}" = "1" ] && [ ! -d "$QFZ_DATA_ROOT/upq/stock_daily" ]; then
  echo "qfinzero: generating the synthetic sample into $QFZ_DATA_ROOT"
  qfz-sample generate --out "$QFZ_DATA_ROOT" > /dev/null
fi
exec python -m qfinzero.server "$@"
