"""调度静态页路由。

``GET /dispatch`` 直接返回设计稿 HTML，``GET /`` 307 跳转到该页面。页面文件
不存在时返回 404，便于在只部署后端时快速发现资源缺失。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

ROOT = Path(__file__).resolve().parents[4]
PAGE = ROOT / "design" / "cross-border-dispatch" / "index.html"

router = APIRouter(tags=["dispatch"])


@router.get("/dispatch", include_in_schema=False)
def dispatch_page() -> FileResponse:
    """返回跨境调度设计稿页面；文件缺失时 404。"""
    if not PAGE.exists():
        raise HTTPException(status_code=404, detail="dispatch page not found")
    return FileResponse(PAGE, media_type="text/html")


@router.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    """把根路径 307 重定向到 ``/dispatch``。"""
    return RedirectResponse("/dispatch", status_code=307)


__all__ = ["PAGE", "ROOT", "router"]
