from pydantic_settings import BaseSettings

from qfinzero.env import load_root_env_defaults


load_root_env_defaults()


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 19702

    # MongoDB
    mongo_uri: str = "mongodb://localhost:27018"
    mongo_db: str = "market_news"
    mongo_collection: str = "ticker_news"

    # SQLite paths (relative to repo root or absolute)
    earnings_db: str = "data/benzinga_earnings.sqlite3"
    econ_events_db: str = "data/nasdaq_econ_events.sqlite3"

    # Pagination
    default_page_size: int = 50
    max_page_size: int = 500

    log_level: str = "INFO"

    model_config = {"env_prefix": "ESP_"}


settings = Settings()
