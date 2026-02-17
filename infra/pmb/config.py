from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 24444
    upq_base_url: str = "http://127.0.0.1:19350"
    log_level: str = "INFO"

    model_config = {"env_prefix": "PMB_"}


settings = Settings()
