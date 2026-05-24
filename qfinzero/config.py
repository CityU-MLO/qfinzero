"""
QFinZero — Global configuration.

Central port and path definitions for all services.
Precedence:
1. Process environment
2. Repo-root `.env` for local development overrides
3. Checked-in fallback config
4. Hardcoded defaults in this file

Port allocation:
    19700  Dashboard
    19701  PMB   Paper Money Broker
    19702  ESP   News Pushing Pipeline
    19703  UPQ   Unified Price Query
    19704  Playground
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


# ── Service ports ────────────────────────────────────────────────

DASHBOARD_PORT = _env_int("DASHBOARD_PORT", 19700)
PMB_PORT = _env_int("PMB_PORT", 19701)
ESP_PORT = _env_int("ESP_PORT", 19702)
UPQ_PORT = _env_int("UPQ_PORT", 19703)
PLAYGROUND_PORT = _env_int("PLAYGROUND_PORT", 19704)

# ── Service hosts ────────────────────────────────────────────────

DEFAULT_HOST = os.getenv("QFZ_HOST", "127.0.0.1")

# ── Default base URLs ───────────────────────────────────────────

PMB_URL = f"http://{DEFAULT_HOST}:{PMB_PORT}"
ESP_URL = f"http://{DEFAULT_HOST}:{ESP_PORT}"
UPQ_URL = f"http://{DEFAULT_HOST}:{UPQ_PORT}"
PLAYGROUND_URL = f"http://{DEFAULT_HOST}:{PLAYGROUND_PORT}"

# ── Data paths (relative to repo root) ──────────────────────────

DATA_DIR = os.getenv("DATA_DIR", "data")
EARNINGS_DB = os.getenv("EARNINGS_DB", f"{DATA_DIR}/benzinga_earnings.sqlite3")
ECON_EVENTS_DB = os.getenv("ECON_EVENTS_DB", f"{DATA_DIR}/nasdaq_econ_events.sqlite3")

# ── MongoDB ──────────────────────────────────────────────────────

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27018")
MONGO_DB = os.getenv("MONGO_DB", "market_news")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "ticker_news")
