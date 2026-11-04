"""Server-rendered approval console for tasks, plans, approvals, and traces.

Authentication shortcut (local demo only)
-----------------------------------------
Browsers cannot attach custom headers to form submissions, so the console
routes accept the API key as an ``api_key`` query parameter in addition to the
optional ``X-API-Key`` header. Omitting the key is allowed only when
``app_env == "development"`` and then falls back to the seeded
``dev-operator-a`` operator. Any other environment rejects keyless requests
with 401. This is a local-demo convenience; production SSO and secure console
authentication are out of scope. Every console query remains tenant-scoped
through the resolved ``Identity``.
"""

from pathlib import Path
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.templating import Jinja2Templates

from opsconductor.api.deps import Identity
from opsconductor.config import get_settings
from opsconductor.db import get_session
from opsconductor.domain.models import Approval, SalesOrder, TaskRun, TraceSpan, User
from opsconductor.domain.security import hash_api_key
from opsconductor.observability.audit import write_access_denied
from opsconductor.orchestrator.approval import ApprovalError, ApprovalService

DEV_DEFAULT_API_KEY = "dev-operator-a"
TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"

templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(tags=["console"])


async def get_console_identity(
    session: Annotated[AsyncSession, Depends(get_session)],
    api_key: Annotated[str | None, Query()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> Identity:
    """Resolve the console caller from the query parameter or header.

    See the module docstring for the development-only keyless fallback.
    """

    candidate = (api_key or x_api_key or "").strip()
    if not candidate:
        if get_settings().app_env != "development":
            raise HTTPException(status_code=401, detail="api key required")
        candidate = DEV_DEFAULT_API_KEY
    user = await session.scalar(
        select(User).where(User.api_key_hash == hash_api_key(candidate))
    )
    if user is None:
        raise HTTPException(status_code=401, detail="invalid api key")
    return Identity(tenant_id=user.tenant_id, user_id=user.id, role=user.role)


def _auth_query(request: Request) -> str:
    """Return the query suffix that keeps the browser key across redirects."""

    api_key = request.query_params.get("api_key")
    if not api_key:
        return ""
    return f"?api_key={quote(api_key, safe='')}"


async def _load_task(
    session: AsyncSession, identity: Identity, task_id: UUID
) -> TaskRun:
    task = await session.get(TaskRun, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    if task.tenant_id != identity.tenant_id:
        await write_access_denied(
            session,
            tenant_id=task.tenant_id,
            actor_id=identity.user_id,
            task_id=task.id,
            entity_type="task",
            entity_id=str(task.id),
            reason="cross-tenant console task access",
            evidence={
                "caller_tenant_id": str(identity.tenant_id),
                "path": "GET /console/tasks/{task_id}",
            },
        )
        raise HTTPException(status_code=403, detail="forbidden")
    return task


def _plan_order_ids(plan: dict | None) -> set[UUID]:
    order_ids: set[UUID] = set()
    for node in (plan or {}).get("nodes", []):
        try:
            order_ids.add(UUID(node["order_id"]))
        except (KeyError, TypeError, ValueError):
            continue
    return order_ids


async def _order_numbers(
    session: AsyncSession, tenant_id: UUID, order_ids: set[UUID]
) -> dict[UUID, str]:
    if not order_ids:
        return {}
    orders = (
        await session.scalars(
            select(SalesOrder).where(
                SalesOrder.tenant_id == tenant_id,
                SalesOrder.id.in_(order_ids),
            )
        )
    ).all()
    return {order.id: order.order_no for order in orders}


def _plan_nodes(plan: dict | None, order_numbers: dict[UUID, str]) -> list[dict]:
    nodes: list[dict] = []
    for raw in (plan or {}).get("nodes", []):
        node = dict(raw)
        raw_order_id = node.get("order_id")
        try:
            order_id = UUID(raw_order_id) if raw_order_id else None
        except (TypeError, ValueError):
            order_id = None
        node["order_no"] = (
            order_numbers.get(order_id) if order_id is not None else None
        )
        nodes.append(node)
    return nodes


async def _approval_rows(
    session: AsyncSession,
    task: TaskRun,
    order_numbers: dict[UUID, str],
) -> list[dict]:
    approvals = (
        await session.scalars(
            select(Approval)
            .where(
                Approval.task_id == task.id,
                Approval.tenant_id == task.tenant_id,
            )
            .order_by(Approval.id)
        )
    ).all()
    approver_ids = {
        approval.approver_id
        for approval in approvals
        if approval.approver_id is not None
    }
    approver_names: dict[UUID, str] = {}
    if approver_ids:
        users = (
            await session.scalars(
                select(User).where(
                    User.tenant_id == task.tenant_id,
                    User.id.in_(approver_ids),
                )
            )
        ).all()
        approver_names = {user.id: user.name for user in users}
    return [
        {
            "approval": approval,
            "order_no": (
                order_numbers.get(approval.order_id)
                if approval.order_id is not None
                else None
            ),
            "approver": (
                approver_names.get(approval.approver_id)
                if approval.approver_id is not None
                else None
            ),
        }
        for approval in approvals
    ]


async def _trace_spans(session: AsyncSession, task: TaskRun) -> list[TraceSpan]:
    return list(
        (
            await session.scalars(
                select(TraceSpan)
                .where(
                    TraceSpan.tenant_id == task.tenant_id,
                    TraceSpan.task_id == task.id,
                )
                .order_by(TraceSpan.started_at, TraceSpan.id)
            )
        ).all()
    )


@router.get("/console/tasks", response_class=HTMLResponse)
async def list_tasks(
    request: Request,
    identity: Annotated[Identity, Depends(get_console_identity)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    """Render the tenant's task list with plan summaries and order numbers."""

    tasks = (
        await session.scalars(
            select(TaskRun)
            .where(TaskRun.tenant_id == identity.tenant_id)
            .order_by(TaskRun.created_at.desc(), TaskRun.id)
        )
    ).all()

    all_order_ids: set[UUID] = set()
    for task in tasks:
        all_order_ids |= _plan_order_ids(task.plan)
    order_numbers = await _order_numbers(session, identity.tenant_id, all_order_ids)

    rows = []
    for task in tasks:
        plan = task.plan or {}
        nodes = _plan_nodes(task.plan, order_numbers)
        order_nos = sorted({node["order_no"] for node in nodes if node["order_no"]})
        rows.append(
            {
                "task": task,
                "summary": plan.get("summary") or "暂无计划摘要。",
                "order_nos": order_nos,
            }
        )

    return templates.TemplateResponse(
        request,
        "console/tasks.html",
        {
            "rows": rows,
            "auth_query": _auth_query(request),
        },
    )


@router.get("/console/tasks/{task_id}", response_class=HTMLResponse)
async def task_detail(
    task_id: UUID,
    request: Request,
    identity: Annotated[Identity, Depends(get_console_identity)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    """Render one task's plan nodes, approvals, and trace timeline."""

    task = await _load_task(session, identity, task_id)
    plan = task.plan or {}
    order_ids = _plan_order_ids(task.plan) | {
        approval.order_id
        for approval in (
            await session.scalars(
                select(Approval).where(
                    Approval.task_id == task.id,
                    Approval.tenant_id == task.tenant_id,
                )
            )
        ).all()
        if approval.order_id is not None
    }
    order_numbers = await _order_numbers(session, identity.tenant_id, order_ids)
    return templates.TemplateResponse(
        request,
        "console/task_detail.html",
        {
            "task": task,
            "plan": plan,
            "nodes": _plan_nodes(task.plan, order_numbers),
            "approval_rows": await _approval_rows(session, task, order_numbers),
            "spans": await _trace_spans(session, task),
            "auth_query": _auth_query(request),
        },
    )


@router.get("/console/tasks/{task_id}/trace", response_class=HTMLResponse)
async def task_trace(
    task_id: UUID,
    request: Request,
    identity: Annotated[Identity, Depends(get_console_identity)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    """Render every trace span recorded for one tenant-scoped task."""

    task = await _load_task(session, identity, task_id)
    return templates.TemplateResponse(
        request,
        "console/trace.html",
        {
            "task": task,
            "spans": await _trace_spans(session, task),
            "auth_query": _auth_query(request),
        },
    )


def _parse_order_id(raw: str | None) -> UUID | None:
    if raw is None or not raw.strip():
        return None
    try:
        return UUID(raw.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid order_id") from exc


async def _decide(
    request: Request,
    task_id: UUID,
    identity: Identity,
    session: AsyncSession,
    approved: bool,
    comment: str | None,
    order_id: UUID | None,
) -> RedirectResponse:
    service = ApprovalService(session)
    try:
        await service.decide(
            task_id,
            identity,
            approved,
            comment=(comment or "").strip() or None,
            order_id=order_id,
        )
    except ApprovalError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return RedirectResponse(
        url=f"/console/tasks/{task_id}{_auth_query(request)}",
        status_code=303,
    )


@router.post("/console/tasks/{task_id}/approve")
async def approve_task(
    task_id: UUID,
    request: Request,
    identity: Annotated[Identity, Depends(get_console_identity)],
    session: Annotated[AsyncSession, Depends(get_session)],
    comment: Annotated[str | None, Form()] = None,
    order_id: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    """Approve all pending approvals, or only one order's, then redirect back."""

    return await _decide(
        request, task_id, identity, session, True, comment, _parse_order_id(order_id)
    )


@router.post("/console/tasks/{task_id}/reject")
async def reject_task(
    task_id: UUID,
    request: Request,
    identity: Annotated[Identity, Depends(get_console_identity)],
    session: Annotated[AsyncSession, Depends(get_session)],
    comment: Annotated[str | None, Form()] = None,
    order_id: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    """Reject all pending approvals, or only one order's, then redirect back."""

    return await _decide(
        request, task_id, identity, session, False, comment, _parse_order_id(order_id)
    )
