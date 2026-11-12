"""FastAPI 应用入口。

应用在此装配任务、审批与服务端渲染控制台路由，并暴露一个无认证的健康检查。
认证在各路由的依赖中完成，而不是在应用层全局执行。

Invariants:

- 业务路由统一挂载在 ``/api/v1``（控制台为 ``/console``），并在各自依赖中解析
  ``Identity``。
- ``/health`` 只返回版本与环境名，不访问数据库、工具子进程或外部服务。
"""

from fastapi import FastAPI

from opsconductor import __version__
from opsconductor.api.routes.approvals import router as approvals_router
from opsconductor.api.routes.console import router as console_router
from opsconductor.api.routes.tasks import router as tasks_router
from opsconductor.config import get_settings
from opsconductor.dispatch.adapters.api import router as dispatch_api_router
from opsconductor.dispatch.adapters.page import router as dispatch_page_router

app = FastAPI(
    title="OpsConductor",
    description="电商 ERP 多 Agent 运营系统",
    version=__version__,
)

app.include_router(tasks_router)
app.include_router(approvals_router)
app.include_router(console_router)
app.include_router(dispatch_api_router)
app.include_router(dispatch_page_router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """返回服务健康状态与当前运行环境。

    Returns:
        包含 ``status``、``version`` 与 ``env`` 的字典。

    Note:
        该端点不需要 API key，也不做依赖探测；它只表明进程可以响应请求。
    """

    settings = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "env": settings.app_env,
    }
