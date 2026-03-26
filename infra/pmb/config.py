from pydantic_settings import BaseSettings

from qfinzero.env import load_root_env_defaults


load_root_env_defaults()


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 19701
    upq_base_url: str = "http://127.0.0.1:19703"
    log_level: str = "INFO"

    model_config = {"env_prefix": "PMB_"}


settings = Settings()
