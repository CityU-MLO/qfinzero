"""
QFinZero — Global configuration.

Central port and path definitions for all services.
Override any value via environment variables or config/qfinzero.env (used by scripts).

Port allocation:
    19320  PMB   Paper Money Broker
    19330  NPP   News Pushing Pipeline
    19350  UPQ   Unified Price Query
    19380  (reserved) Dashboard
"""

from __future__ import annotations

import os

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

PMB_PORT = _env_int("PMB_PORT", 19320)
NPP_PORT = _env_int("NPP_PORT", 19330)
UPQ_PORT = _env_int("UPQ_PORT", 19350)
DASHBOARD_PORT = _env_int("DASHBOARD_PORT", 19380)  # reserved

# ── Service hosts ────────────────────────────────────────────────

DEFAULT_HOST = os.getenv("QFZ_HOST", "127.0.0.1")

# ── Default base URLs ───────────────────────────────────────────

PMB_URL = f"http://{DEFAULT_HOST}:{PMB_PORT}"
NPP_URL = f"http://{DEFAULT_HOST}:{NPP_PORT}"
UPQ_URL = f"http://{DEFAULT_HOST}:{UPQ_PORT}"

# ── Data paths (relative to repo root) ──────────────────────────

DATA_DIR = os.getenv("DATA_DIR", "data")
EARNINGS_DB = os.getenv("EARNINGS_DB", f"{DATA_DIR}/benzinga_earnings.sqlite3")
ECON_EVENTS_DB = os.getenv("ECON_EVENTS_DB", f"{DATA_DIR}/nasdaq_econ_events.sqlite3")

# ── MongoDB ──────────────────────────────────────────────────────

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27018")
MONGO_DB = os.getenv("MONGO_DB", "market_news")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "ticker_news")
