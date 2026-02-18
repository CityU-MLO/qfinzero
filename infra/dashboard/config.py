from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 19380
    poll_interval: int = 5

    pmb_url: str = "http://127.0.0.1:19320"
    npp_url: str = "http://127.0.0.1:19330"
    upq_url: str = "http://127.0.0.1:19350"

    log_level: str = "INFO"

    model_config = {"env_prefix": "DASHBOARD_"}


settings = Settings()
