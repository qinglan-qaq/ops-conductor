"""OpsConductor 的运行时配置，从环境加载。

配置值来自 ``.env`` 以及带 ``OPSCONDUCTOR_`` 前缀的环境变量（例如
``OPSCONDUCTOR_DATABASE_URL``）；真实环境变量优先于 dotenv 文件。无法识别的
变量会被忽略，因此一份共享环境即可服务于多个部署。

请导入 :func:`get_settings`，而不是直接构造 ``Settings``：缓存实例可让所有
子系统使用同一份一致的配置。
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """单个 OpsConductor 部署的配置。

    每个字段都有默认值，因此服务无需环境文件即可启动；真实 LLM 提供方的凭据
    是例外，保持可选。启动后请将实例视为只读，因为数据库引擎、客户端与缓存都
    基于首次创建的实例构建。

    Attributes:
        app_env: 部署标签；``development`` 会选择本地默认值。
        database_url: 进程级引擎使用的 SQLAlchemy 异步 URL。
        redis_url: 用于共享协调状态的 Redis 端点。
        llm_api_key: 提供方凭据；未设置时使用 stub LLM。
        llm_base_url: LLM 提供方的 OpenAI 兼容基础 URL。
        llm_model_planner: 将指令转换为计划的模型。
        llm_model_router: 对指令进行分类或路由的模型。
        llm_model_verifier: 检查写入后条件的模型。
        l3_batch_threshold: 达到或超过该拆分数量时，批次升级为 L3。
        approval_timeout_minutes: 待审批项过期前的分钟数。
        stub_llm: 改为由确定性 stub 提供 LLM 调用。
        mcp_server_command: 启动 MCP stdio 服务器的可执行文件。
        mcp_server_args: 传给 ``mcp_server_command`` 的参数。
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
    """返回进程级设置实例。

    结果由 :func:`functools.lru_cache` 缓存，因此首次调用即确定该进程生命周期
    内的配置。需要不同配置的测试必须先调用 ``get_settings.cache_clear()``。

    Returns:
        基于环境构建的单例设置对象。
    """
    return Settings()
