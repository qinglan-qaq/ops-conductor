"""任务、计划、审批与 trace 的服务端渲染控制台。

认证快捷方式（仅限本地演示）
----------------------------
浏览器无法为表单提交附加自定义请求头，因此控制台路由除了可选的 ``X-API-Key``
请求头外，还接受 ``api_key`` 查询参数。仅当 ``app_env == "development"`` 时允许
省略 key，此时回退到预置的 ``dev-operator-a`` 操作者；其他环境一律以 401 拒绝
无 key 请求。这是本地演示便利，生产 SSO 与安全控制台认证不在范围内。所有控制台
查询仍然通过解析出的 ``Identity`` 限定租户。

Invariants:

- 每个任务、审批与 trace 查询都按解析出的租户限定。
- 控制台只渲染只读视图并转发审批决策；它不装配执行器，也不触发任务执行。
- 重定向会保留 ``api_key`` 查询参数，以免浏览器在表单提交后丢失凭据。
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
    """从查询参数或请求头解析控制台调用方。

    参见模块文档中的仅开发环境无 key 回退。

    Args:
        session: 用于按 key 哈希查找用户的会话。
        api_key: ``api_key`` 查询参数；浏览器表单提交使用。
        x_api_key: 可选的 ``X-API-Key`` 请求头。

    Returns:
        与该 key 关联的不可变 :class:`Identity`。

    Raises:
        HTTPException: 非开发环境且未提供 key、或 key 未知时返回 401。

    Note:
        查询参数优先于请求头；两者都会去除首尾空白。生产环境不存在无 key 的
        快捷路径。
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
    """返回在重定向中保留浏览器 key 的查询后缀。

    Args:
        request: 当前请求。

    Returns:
        含 URL 编码 ``api_key`` 的查询串；没有该参数时返回空字符串。
    """

    api_key = request.query_params.get("api_key")
    if not api_key:
        return ""
    return f"?api_key={quote(api_key, safe='')}"


async def _load_task(
    session: AsyncSession, identity: Identity, task_id: UUID
) -> TaskRun:
    """加载租户拥有的任务；跨租户访问写审计并拒绝。

    Args:
        session: 请求会话。
        identity: 解析出的控制台调用方。
        task_id: 目标任务。

    Returns:
        属于调用方租户的任务。

    Raises:
        HTTPException: 任务不存在时 404；任务属于其他租户时 403。

    Note:
        拒绝审计由 ``write_access_denied`` 提交，因此会话可能已被提交。
    """

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
    """收集计划节点引用的订单 ID，忽略缺失或非法的值。

    Args:
        plan: 计划载荷；``None`` 或缺少 ``nodes`` 时视为空计划。

    Returns:
        去重后的订单 UUID 集合。
    """

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
    """批量查询订单号，用于控制台展示。

    Args:
        session: 请求会话。
        tenant_id: 查询范围；不会返回其他租户的订单。
        order_ids: 待查询的订单 ID。

    Returns:
        订单 ID 到 ``order_no`` 的映射；不存在的 ID 不会出现在结果中。
    """

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
    """复制计划节点并为每个节点补充 ``order_no``。

    Args:
        plan: 计划载荷；``None`` 或缺少 ``nodes`` 时返回空列表。
        order_numbers: 订单 ID 到订单号的映射。

    Returns:
        新的节点字典列表；原始计划不会被修改，无法解析的 ``order_id`` 对应
        ``order_no`` 为 ``None``。
    """

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
    """加载任务的审批行及展示所需的订单号与审批人名称。

    Args:
        session: 请求会话。
        task: 已按租户校验的任务。
        order_numbers: 订单 ID 到订单号的映射。

    Returns:
        每项包含 ``approval``、``order_no`` 与 ``approver`` 的列表，按审批 ID
        排序；没有审批人时 ``approver`` 为 ``None``。

    Note:
        审批查询再次按任务的 ``tenant_id`` 限定，审批人查询也限定同一租户。
    """

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
    """加载任务的全部 trace span。

    Args:
        session: 请求会话。
        task: 已按租户校验的任务。

    Returns:
        按开始时间与 ID 排序的 span 列表；查询限定任务的租户。

    Note:
        trace 只包含已提交的 span；控制台本身不触发任务执行，审批决策产生的
        span 由审批服务记录。
    """

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
    """渲染租户的任务列表，附带计划摘要与订单号。

    Args:
        request: 当前请求，用于模板与保留 key。
        identity: 解析出的控制台调用方。
        session: 请求会话。

    Returns:
        任务列表 HTML 响应。

    Note:
        只查询调用方租户的任务；不会启动执行器。
    """

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
    """渲染一个任务的计划节点、审批与 trace 时间线。

    Args:
        task_id: 目标任务。
        request: 当前请求，用于模板与保留 key。
        identity: 解析出的控制台调用方。
        session: 请求会话。

    Returns:
        任务详情 HTML 响应。

    Raises:
        HTTPException: 任务不存在时 404，跨租户时 403。

    Note:
        任务、审批与 trace 都按解析出的租户限定；控制台不装配执行器。
    """

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
    """渲染一个租户限定任务的全部 trace span。

    Args:
        task_id: 目标任务。
        request: 当前请求，用于模板与保留 key。
        identity: 解析出的控制台调用方。
        session: 请求会话。

    Returns:
        trace 时间线 HTML 响应。

    Raises:
        HTTPException: 任务不存在时 404，跨租户时 403。

    Note:
        只渲染已提交的 span；控制台本身不执行任务，审批决策产生的 trace 由
        审批服务记录。
    """

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
    """解析表单中的可选订单 ID。

    Args:
        raw: 原始表单值；``None`` 或空白表示未限定订单。

    Returns:
        解析后的 UUID；未提供时返回 ``None``。

    Raises:
        HTTPException: 值不是合法 UUID 时返回 422。
    """

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
    """转发控制台审批决策并重定向回任务详情页。

    Args:
        request: 当前请求，用于保留 key 与构造重定向。
        task_id: 目标任务。
        identity: 解析出的控制台调用方。
        session: 请求会话。
        approved: ``True`` 表示批准，``False`` 表示拒绝。
        comment: 可选备注；空白会被视为 ``None``。
        order_id: 只裁决单个订单的审批。

    Returns:
        指向任务详情页的 303 重定向，并保留 ``api_key`` 查询参数。

    Raises:
        HTTPException: 审批服务抛出 :class:`ApprovalError` 时按其
            ``status_code`` 返回。

    Note:
        角色门禁与租户限定由审批服务执行；路由本身不写审批行，也不触发执行。
    """

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
    """批准全部待处理审批或某个订单的审批，然后重定向回去。

    Args:
        task_id: 目标任务。
        request: 当前请求，用于保留 key 与构造重定向。
        identity: 解析出的控制台调用方。
        session: 请求会话。
        comment: 可选的表单备注。
        order_id: 可选的目标订单表单值。

    Returns:
        指向任务详情页的 303 重定向。

    Raises:
        HTTPException: 订单 ID 非法时 422；审批服务拒绝时按其状态码返回。

    Note:
        角色门禁与租户限定由审批服务执行；控制台不触发执行。
    """

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
    """拒绝全部待处理审批或某个订单的审批，然后重定向回去。

    Args:
        task_id: 目标任务。
        request: 当前请求，用于保留 key 与构造重定向。
        identity: 解析出的控制台调用方。
        session: 请求会话。
        comment: 可选的表单备注。
        order_id: 可选的目标订单表单值。

    Returns:
        指向任务详情页的 303 重定向。

    Raises:
        HTTPException: 订单 ID 非法时 422；审批服务拒绝时按其状态码返回。

    Note:
        角色门禁与租户限定由审批服务执行；控制台不触发执行。
    """

    return await _decide(
        request, task_id, identity, session, False, comment, _parse_order_id(order_id)
    )
