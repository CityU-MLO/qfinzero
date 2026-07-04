#!/usr/bin/env bash
# QFinZero — the unified server.
#
# One process, one public port: Web UI (/), REST API (/api/*), and MCP (/mcp).
# The hub supervises the internal services (UPQ, ESP, PMB, playground,
# data-admin, dashboard) on localhost; you only ever hit the hub.
#
#   ./scripts/serve.sh                 # start the hub on :19777
#   QFZ_SERVER_PORT=19780 ./scripts/serve.sh
#   QFZ_SUPERVISE=0 ./scripts/serve.sh # gateway only (services managed elsewhere)
#   QFZ_SERVE_UI=0 ./scripts/serve.sh  # skip the Next.js web UI
#
# Override the interpreter with QFZ_PYTHON (needs the [server] extra installed).

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

# Layered env: checked-in defaults, then local .env overrides.
if [ -f config/qfinzero.env ]; then set -a; . config/qfinzero.env; set +a; fi
if [ -f .env ]; then set -a; . .env; set +a; fi

export PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}"
PY="${QFZ_PYTHON:-python}"

# Some hosts ship an outdated libsqlite3 that breaks Python's sqlite3 (ESP data)
# and Node/pnpm (dashboard build). Point QFZ_SQLITE_PRELOAD at a good libsqlite3
# (>= 3.45) to preload it for the hub and every child it spawns.
if [ -n "${QFZ_SQLITE_PRELOAD:-}" ] && [ -f "${QFZ_SQLITE_PRELOAD}" ]; then
    export LD_PRELOAD="${QFZ_SQLITE_PRELOAD}${LD_PRELOAD:+:$LD_PRELOAD}"
fi
# QFZ_NODE_BIN: dir of a working node/pnpm (so the hub can run the Next.js child).
if [ -n "${QFZ_NODE_BIN:-}" ] && [ -d "${QFZ_NODE_BIN}" ]; then
    export PATH="${QFZ_NODE_BIN}:$PATH"
fi

exec "$PY" -m qfinzero.server
