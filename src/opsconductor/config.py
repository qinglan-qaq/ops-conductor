"""Runtime configuration for OpsConductor, loaded from the environment.

Values come from ``.env`` and from ``OPSCONDUCTOR_``-prefixed environment
variables (for example ``OPSCONDUCTOR_DATABASE_URL``); real environment
variables win over the dotenv file. Unrecognized variables are ignored so one
shared environment can serve several deployments.

Import :func:`get_settings` instead of constructing ``Settings`` directly: the
cached instance keeps every subsystem on one consistent configuration.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for a single OpsConductor deployment.

    Every field has a default so the service can start without an environment
    file; credentials for a real LLM provider are the exception and stay
    optional. Treat an instance as read-only after startup because the database
    engine, clients, and caches are built from the first instance created.

    Attributes:
        app_env: Deployment label; ``development`` selects local defaults.
        database_url: SQLAlchemy async URL used by the process-wide engine.
        redis_url: Redis endpoint used for shared coordination state.
        llm_api_key: Provider credential; when unset, the stub LLM is used.
        llm_base_url: OpenAI-compatible base URL for the LLM provider.
        llm_model_planner: Model that turns an instruction into a plan.
        llm_model_router: Model that classifies or routes an instruction.
        llm_model_verifier: Model that checks post-write conditions.
        l3_batch_threshold: Split count at or above which a batch becomes L3.
        approval_timeout_minutes: Minutes before a pending approval expires.
        stub_llm: Serve LLM calls from the deterministic stub instead.
        mcp_server_command: Executable that launches the MCP stdio server.
        mcp_server_args: Arguments passed to ``mcp_server_command``.
    """

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
    """Return the process-wide settings instance.

    The result is cached with :func:`functools.lru_cache`, so the first call
    fixes the configuration for the lifetime of the process. Tests that need
    different settings must call ``get_settings.cache_clear()`` first.

    Returns:
        The singleton settings object built from the environment.
    """
    return Settings()
