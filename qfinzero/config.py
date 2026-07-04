"""
QFinZero — Global configuration.

Central port and path definitions for all services.
Precedence:
1. Process environment
2. Repo-root `.env` for local development overrides
3. Checked-in fallback config
4. Hardcoded defaults in this file

Port allocation (193xx block):
    19300  Dashboard
    19330  ESP   News Pushing Pipeline
    19350  UPQ   Unified Price Query
    19380  PMB   Paper Money Broker
    19390  Playground
"""

from __future__ import annotations

import os

from qfinzero.env import load_root_env_defaults


load_root_env_defaults()

# ── Helpers ─────────────────────────────────────────────────────


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


# ── Unified server (the one public entry point) ─────────────────
# QFinZero runs as a single hub on SERVER_PORT that fronts the Web UI, the
# REST API (/api/*), and the MCP server (/mcp). The per-service ports below
# are now INTERNAL children the hub supervises on localhost — you don't hit
# them directly anymore.

SERVER_HOST = os.getenv("QFZ_SERVER_HOST", "0.0.0.0")
SERVER_PORT = _env_int("QFZ_SERVER_PORT", 19777)

# ── Internal service ports (localhost children behind the hub) ──

DASHBOARD_PORT = _env_int("DASHBOARD_PORT", 19300)
PMB_PORT = _env_int("PMB_PORT", 19380)
ESP_PORT = _env_int("ESP_PORT", 19330)
UPQ_PORT = _env_int("UPQ_PORT", 19350)
PLAYGROUND_PORT = _env_int("PLAYGROUND_PORT", 19390)
DATA_ADMIN_PORT = _env_int("DATA_ADMIN_PORT", 19340)

# ── Service hosts ────────────────────────────────────────────────

DEFAULT_HOST = os.getenv("QFZ_HOST", "127.0.0.1")

# Public base for external REST clients / the MCP tools when reaching the hub.
SERVER_URL = os.getenv("QFZ_SERVER_URL", f"http://{DEFAULT_HOST}:{SERVER_PORT}")

# ── Default base URLs ───────────────────────────────────────────

PMB_URL = f"http://{DEFAULT_HOST}:{PMB_PORT}"
ESP_URL = f"http://{DEFAULT_HOST}:{ESP_PORT}"
UPQ_URL = f"http://{DEFAULT_HOST}:{UPQ_PORT}"
PLAYGROUND_URL = f"http://{DEFAULT_HOST}:{PLAYGROUND_PORT}"
DATA_ADMIN_URL = f"http://{DEFAULT_HOST}:{DATA_ADMIN_PORT}"

# ── Data root (all QFinZero-owned data lives here) ──────────────
# Single canonical home; override with QFZ_DATA_ROOT. Layout:
#   $QFZ_DATA_ROOT/upq/   UPQ price storage (STORAGE_ROOT)
#   $QFZ_DATA_ROOT/esp/   ESP event databases
#   $QFZ_DATA_ROOT/raw/   symlinks to shared raw vendor data (read in place)

QFZ_DATA_ROOT = os.getenv("QFZ_DATA_ROOT", "/data/qfinzero")

# DATA_DIR is kept as a back-compat alias for the data root.
DATA_DIR = os.getenv("DATA_DIR", QFZ_DATA_ROOT)

# ── ESP event databases ──────────────────────────────────────────

EARNINGS_DB = os.getenv("EARNINGS_DB", f"{QFZ_DATA_ROOT}/esp/benzinga_earnings.sqlite3")
ECON_EVENTS_DB = os.getenv("ECON_EVENTS_DB", f"{QFZ_DATA_ROOT}/esp/nasdaq_econ_events.sqlite3")

# ── Data pipeline (raw sources + UPQ storage) ───────────────────
# Raw vendor data is read IN PLACE (shared with other systems; never copied).
# The converter writes UPQ-format parquet into UPQ_STORAGE_ROOT, which the
# UPQ service reads via its STORAGE_ROOT env var.

RAW_MASSIVE_DIR = os.getenv("RAW_MASSIVE_DIR", "/data/massive_data")
RAW_TUSHARE_DIR = os.getenv("RAW_TUSHARE_DIR", "/data/tushare_data")
UPQ_STORAGE_ROOT = os.getenv("STORAGE_ROOT", f"{QFZ_DATA_ROOT}/upq")

# ── MongoDB ──────────────────────────────────────────────────────

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27018")
MONGO_DB = os.getenv("MONGO_DB", "market_news")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "ticker_news")

# ── LLM egress proxy ─────────────────────────────────────────────
# Route OUTBOUND LLM API calls (OpenAI/Anthropic/… over the public internet)
# through an HTTP proxy, while intra-cluster service calls (PMB/ESP/UPQ on
# localhost) stay direct. Set LLM_PROXY explicitly, or rely on the standard
# HTTPS_PROXY/HTTP_PROXY exports so an existing shell just works, e.g.:
#   export LLM_PROXY=http://aiuser:pass@localhost:3128
# Keep local hosts in NO_PROXY (localhost,127.0.0.1,…) so they bypass the proxy.

LLM_PROXY = (
    os.getenv("LLM_PROXY")
    or os.getenv("HTTPS_PROXY")
    or os.getenv("https_proxy")
    or os.getenv("HTTP_PROXY")
    or os.getenv("http_proxy")
    or ""
).strip()
