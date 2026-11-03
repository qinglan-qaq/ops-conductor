"""Runtime configuration loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for a single OpsConductor deployment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="OPSCONDUCTOR_",
        extra="ignore",
    )

    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://ops:ops@localhost:5432/opsconductor"
    redis_url: str = "redis://localhost:6379/0"
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    embedding_model: str = "BAAI/bge-m3"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
