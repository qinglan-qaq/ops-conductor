"""FastAPI entrypoint."""

from fastapi import FastAPI

from opsconductor import __version__
from opsconductor.api.routes.tasks import router as tasks_router
from opsconductor.config import get_settings

app = FastAPI(
    title="OpsConductor",
    description="电商 ERP 多 Agent 运营系统",
    version=__version__,
)

app.include_router(tasks_router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Return service health and the active environment."""
    settings = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "env": settings.app_env,
    }
