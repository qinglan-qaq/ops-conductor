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
    llm_model_planner: str = "gpt-4o-mini"
    llm_model_router: str = "gpt-4o-mini"
    llm_model_verifier: str = "gpt-4o-mini"
    embedding_model: str = "BAAI/bge-m3"
    l3_batch_threshold: int = 10
    approval_timeout_minutes: int = 30
    stub_llm: bool = True
    mcp_server_command: str = "python"
    mcp_server_args: list[str] = ["-m", "opsconductor.tools.server"]


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
