from pydantic_settings import BaseSettings

from qfinzero.config import EARNINGS_DB as _EARNINGS_DB, ECON_EVENTS_DB as _ECON_EVENTS_DB
from qfinzero.env import load_root_env_defaults


load_root_env_defaults()


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 19330

    # MongoDB
    mongo_uri: str = "mongodb://localhost:27018"
    mongo_db: str = "market_news"
    mongo_collection: str = "ticker_news"

    # SQLite paths — defaults from the canonical data root (qfinzero.config).
    # Absolute, so REPO_ROOT / earnings_db (in main.py) resolves to them unchanged.
    earnings_db: str = _EARNINGS_DB
    econ_events_db: str = _ECON_EVENTS_DB

    # Pagination
    default_page_size: int = 50
    max_page_size: int = 500

    log_level: str = "INFO"

    model_config = {"env_prefix": "ESP_"}


settings = Settings()
