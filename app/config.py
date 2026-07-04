from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "sqlite:///./events.db"
    redis_url: str = "redis://localhost:6379/0"
    redis_stream_name: str = "events"
    redis_consumer_group: str = "event-deliverers"
    redis_consumer_name: str = "worker-1"
    consumer_enabled: bool = True
    webhook_timeout_seconds: float = 10.0
    webhook_max_retries: int = 3
    webhook_retry_base_seconds: float = 1.0
    webhook_retry_max_seconds: float = 30.0
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"


settings = Settings()
