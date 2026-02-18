"""
QFinZero — Global configuration.

Central port and path definitions for all services.
Individual services read from here and can be overridden via environment variables.

Port allocation:
    19320  PMB   Paper Money Broker
    19330  NPP   News Pushing Pipeline
    19350  UPQ   Unified Price Query
    19380  (reserved) Dashboard
"""

# ── Service ports ────────────────────────────────────────────────

PMB_PORT = 19320
NPP_PORT = 19330
UPQ_PORT = 19350
DASHBOARD_PORT = 19380  # reserved

# ── Service hosts ────────────────────────────────────────────────

DEFAULT_HOST = "127.0.0.1"

# ── Default base URLs ───────────────────────────────────────────

PMB_URL = f"http://{DEFAULT_HOST}:{PMB_PORT}"
NPP_URL = f"http://{DEFAULT_HOST}:{NPP_PORT}"
UPQ_URL = f"http://{DEFAULT_HOST}:{UPQ_PORT}"

# ── Data paths (relative to repo root) ──────────────────────────

DATA_DIR = "data"
EARNINGS_DB = f"{DATA_DIR}/benzinga_earnings.sqlite3"
ECON_EVENTS_DB = f"{DATA_DIR}/nasdaq_econ_events.sqlite3"

# ── MongoDB ──────────────────────────────────────────────────────

MONGO_URI = "mongodb://localhost:27018"
MONGO_DB = "market_news"
MONGO_COLLECTION = "ticker_news"
