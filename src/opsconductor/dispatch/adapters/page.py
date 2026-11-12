"""调度台静态页路由：优先托管 Vue 构建产物，保留旧页作视觉参考。

路由：

- ``GET /dispatch`` → ``frontend/dist/index.html``；
- ``GET /dispatch/{path}`` → SPA fallback，仍返回同一 index；
- ``GET /assets/{path}`` → Vite 构建的静态资源；
- ``GET /dispatch/legacy`` 或 ``OPSCONDUCTOR_DISPATCH_UI=legacy`` → 旧单文件页。

``frontend/dist`` 缺失时返回 503 并提示构建命令，不静默回退旧页面。这样
Demo 启动失败是可发现的，而不是悄悄跑在两个不同 UI 上。
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

ROOT = Path(__file__).resolve().parents[4]
LEGACY_PAGE = ROOT / "design" / "cross-border-dispatch" / "index.html"
DIST = ROOT / "frontend" / "dist"
DIST_INDEX = DIST / "index.html"
ASSETS = DIST / "assets"

_BUILD_HINT = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>调度台尚未构建</title></head>
<body style="font-family:serif;background:#F7F3E9;color:#17130F;padding:48px">
<h1>调度台尚未构建</h1>
<p>请先在仓库根目录运行：</p>
<pre>bash scripts/build_frontend.sh</pre>
<p>随后刷新本页。若只想查看旧设计稿，可访问 <code>/dispatch/legacy</code>。</p>
</body></html>"""

router = APIRouter(tags=["dispatch"])


def _legacy_mode() -> bool:
    """返回是否通过环境变量强制使用旧单文件页。"""
    return os.environ.get("OPSCONDUCTOR_DISPATCH_UI", "").strip().lower() == "legacy"


def _resolve_dist_file(relative: str) -> Path | None:
    """安全解析 dist 内文件，阻止目录穿越。"""
    if not relative or not DIST.exists():
        return None
    root = DIST.resolve()
    candidate = (DIST / relative).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    return candidate


def _serve_vue_index() -> Response:
    """返回 Vue index；dist 缺失时 503 并给出构建提示。"""
    if not DIST_INDEX.is_file():
        return HTMLResponse(_BUILD_HINT, status_code=503)
    return FileResponse(DIST_INDEX, media_type="text/html")


@router.get("/dispatch", include_in_schema=False)
def dispatch_page() -> Response:
    """返回 Vue 调度台；``legacy`` 模式返回旧设计稿。"""
    if _legacy_mode():
        if not LEGACY_PAGE.exists():
            raise HTTPException(status_code=404, detail="legacy dispatch page not found")
        return FileResponse(LEGACY_PAGE, media_type="text/html")
    return _serve_vue_index()


@router.get("/dispatch/legacy", include_in_schema=False)
def dispatch_legacy_page() -> FileResponse:
    """返回旧单文件页，仅用于视觉对照与迁移排查。"""
    if not LEGACY_PAGE.exists():
        raise HTTPException(status_code=404, detail="legacy dispatch page not found")
    return FileResponse(LEGACY_PAGE, media_type="text/html")


@router.get("/dispatch/{full_path:path}", include_in_schema=False)
def dispatch_spa_fallback(full_path: str) -> Response:
    """Vue Router 的 SPA fallback；真实静态文件优先原样返回。"""
    if full_path == "legacy":
        return dispatch_legacy_page()
    if _legacy_mode():
        raise HTTPException(status_code=404, detail="not found")
    static_file = _resolve_dist_file(full_path)
    if static_file is not None:
        return FileResponse(static_file)
    return _serve_vue_index()


@router.get("/assets/{asset_path:path}", include_in_schema=False)
def dispatch_asset(asset_path: str) -> FileResponse:
    """返回 Vite 构建的 JS/CSS 等静态资源。"""
    candidate = _resolve_dist_file(f"assets/{asset_path}")
    if candidate is None or not candidate.is_relative_to(ASSETS.resolve()):
        raise HTTPException(status_code=404, detail="asset not found")
    return FileResponse(candidate)


@router.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    """把根路径 307 重定向到 ``/dispatch``。"""
    return RedirectResponse("/dispatch", status_code=307)


__all__ = ["DIST", "LEGACY_PAGE", "ROOT", "router"]
