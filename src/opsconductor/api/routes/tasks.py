"""任务提交、查询与执行端点。

提交是幂等的：``Idempotency-Key`` 加请求指纹决定是创建新任务还是重放已存储的
响应。创建流程先持久化 ``TaskRun``，再生成计划、应用风险策略、为需要审批的写入
节点创建 ``pending`` 审批行，最后写入幂等记录并提交。

Invariants:

- 所有任务与审批查询都按 ``Identity.tenant_id`` 限定；跨租户访问会写审计并返回
  403。
- 只有 ``requires_approval`` 且动作属于 ``WRITE_ACTIONS`` 的节点才创建审批行；
  无审批行的任务直接进入 ``planned``，否则进入 ``awaiting_approval``。
- 执行入口只解析任务并构造执行器；审批、dry-run 与写入的权威判定在执行器与
  MCP 门禁内部完成。
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from opsconductor.api.deps import Identity, get_identity
from opsconductor.config import Settings, get_settings
from opsconductor.db import get_session
from opsconductor.domain.models import Approval, TaskRun
from opsconductor.llm.gateway import HttpChatModel
from opsconductor.observability.audit import write_access_denied
from opsconductor.observability.trace import TraceRecorder
from opsconductor.orchestrator.executor import TaskExecutor, ToolClient
from opsconductor.orchestrator.idempotency import (
    TASK_CREATE_SCOPE,
    IdempotencyConflict,
    build_record,
    get_existing_record,
    request_hash,
)
from opsconductor.orchestrator.planner import (
    LLMPlanner,
    PlanGenerationError,
    TemplatePlanner,
)
from opsconductor.orchestrator.policy import RiskPolicy
from opsconductor.schemas import Plan, TaskCreate, TaskRead, validate_plan
from opsconductor.tools.client import ErpToolClient

TASK_TYPE = "order_exception"
WRITE_ACTIONS = {"split_order", "change_address"}

router = APIRouter(tags=["tasks"])


@dataclass(frozen=True)
class PlannerTask:
    """由持久化 ``TaskRun`` 与请求上下文组装出的计划输入。

    Attributes:
        id: 任务 ID。
        tenant_id: 任务所属租户。
        instruction: 运营指令原文。
        warehouse: 可选的仓库范围。
        cutoff: 可选的时间截止条件。
    """

    id: UUID
    tenant_id: UUID
    instruction: str
    warehouse: str | None
    cutoff: str | None


def _build_planner(session: AsyncSession) -> TemplatePlanner | LLMPlanner:
    """按配置选择模板 planner 或基于 HTTP 的 LLM planner。

    Args:
        session: 供 planner 读取订单与库存上下文。

    Returns:
        启用 ``stub_llm``、未提供 LLM 凭据或模型地址时返回
        :class:`TemplatePlanner`，否则返回 :class:`LLMPlanner`。
    """

    settings = get_settings()
    if settings.stub_llm or not settings.llm_api_key or not settings.llm_base_url:
        return TemplatePlanner(session)
    model = HttpChatModel(
        settings.llm_base_url, settings.llm_api_key, settings.llm_model_planner
    )
    return LLMPlanner(model, session)


async def _generate_plan(session: AsyncSession, task: PlannerTask) -> Plan:
    """生成计划；LLM 计划失败时回退到模板 planner。

    Args:
        session: 供 planner 读取上下文。
        task: 计划输入。

    Returns:
        尚未经过 ``validate_plan`` 的 :class:`Plan`。

    Raises:
        PlanGenerationError: 模板 planner 自身失败时向上抛出。

    Note:
        只有 :class:`LLMPlanner` 的 :class:`PlanGenerationError` 会触发回退；
        回退使用同一会话。
    """

    planner = _build_planner(session)
    if isinstance(planner, LLMPlanner):
        try:
            return await planner.plan(task)
        except PlanGenerationError:
            return await TemplatePlanner(session).plan(task)
    return await planner.plan(task)


def _build_approvals(
    plan: Plan,
    *,
    tenant_id: UUID,
    task_id: UUID,
    settings: Settings,
    now: datetime,
) -> list[Approval]:
    """为计划中需要审批的写节点创建 ``pending`` 审批行。

    Args:
        plan: 已通过校验并应用风险策略的计划。
        tenant_id: 审批行归属租户。
        task_id: 审批行关联任务。
        settings: 提供审批超时分钟数。
        now: 计算到期时间的基础时刻。

    Returns:
        每个 ``requires_approval`` 且动作属于 ``WRITE_ACTIONS`` 的节点对应一条
        未持久化的 ``Approval``；到期时间为 ``now + approval_timeout_minutes``。
    """

    expires_at = now + timedelta(minutes=settings.approval_timeout_minutes)
    return [
        Approval(
            tenant_id=tenant_id,
            task_id=task_id,
            order_id=node.order_id,
            action=node.action,
            risk_level=node.risk.value,
            status="pending",
            expires_at=expires_at,
        )
        for node in plan.nodes
        if node.requires_approval and node.action in WRITE_ACTIONS
    ]


async def create_task(
    session: AsyncSession,
    identity: Identity,
    payload: TaskCreate,
    idempotency_key: str,
) -> TaskRead:
    """创建带计划与审批的任务，并在幂等重放时返回已存储响应。

    Args:
        session: 请求会话；本函数在成功路径上提交它。
        identity: 已认证调用方；任务与审批都归入其租户。
        payload: 任务创建请求。
        idempotency_key: ``Idempotency-Key`` 请求头值。

    Returns:
        新建任务的 ``TaskRead``；幂等重放时返回首次存储的响应。

    Raises:
        IdempotencyConflict: 同一键已用于不同请求指纹。
        PlanGenerationError: LLM 与模板 planner 都无法生成计划。

    Note:
        幂等记录与任务在同一事务中提交。若并发请求抢先写入同一键，提交会触发
        ``IntegrityError``；此时回滚并重新读取已提交的响应，而不是重复创建
        任务。同键且指纹不同时，第二次读取会抛出 :class:`IdempotencyConflict`。
    """

    settings = get_settings()
    fingerprint = request_hash(payload)
    existing = await get_existing_record(
        session,
        identity.tenant_id,
        TASK_CREATE_SCOPE,
        idempotency_key,
        fingerprint,
    )
    if existing is not None:
        return TaskRead.model_validate(existing.response)

    task = TaskRun(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        task_type=TASK_TYPE,
        instruction=payload.instruction,
        status="received",
    )
    session.add(task)
    await session.flush()

    planner_task = PlannerTask(
        id=task.id,
        tenant_id=identity.tenant_id,
        instruction=payload.instruction,
        warehouse=payload.warehouse,
        cutoff=payload.cutoff,
    )
    plan = await _generate_plan(session, planner_task)
    validate_plan(plan)
    RiskPolicy(settings).apply(plan)

    plan_payload = plan.model_dump(mode="json")
    plan_payload["request"] = {
        "warehouse": payload.warehouse,
        "cutoff": payload.cutoff,
    }
    task.plan = plan_payload
    now = datetime.now(UTC)
    approvals = _build_approvals(
        plan,
        tenant_id=identity.tenant_id,
        task_id=task.id,
        settings=settings,
        now=now,
    )
    if approvals:
        task.status = "awaiting_approval"
        session.add_all(approvals)
    else:
        task.status = "planned"

    async with TraceRecorder(session).start(
        "plan_task",
        task_id=task.id,
        tenant_id=identity.tenant_id,
        attributes={
            "source": "production",
            "status": task.status,
            "nodes": len(plan.nodes),
            "requires_l3": plan.requires_l3,
        },
    ):
        pass

    read = TaskRead(
        id=task.id,
        status=task.status,
        instruction=task.instruction,
        plan=plan_payload,
        result=None,
    )
    session.add(
        build_record(
            tenant_id=identity.tenant_id,
            scope=TASK_CREATE_SCOPE,
            key=idempotency_key,
            fingerprint=fingerprint,
            response=read.model_dump(mode="json"),
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await get_existing_record(
            session,
            identity.tenant_id,
            TASK_CREATE_SCOPE,
            idempotency_key,
            fingerprint,
        )
        if existing is None:
            raise
        return TaskRead.model_validate(existing.response)
    return read


@router.post("/api/v1/tasks", response_model=TaskRead)
async def submit_task(
    payload: TaskCreate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    identity: Annotated[Identity, Depends(get_identity)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TaskRead:
    """接收任务创建请求，并把幂等冲突映射为 409。

    Args:
        payload: 任务创建请求体。
        idempotency_key: 必填的 ``Idempotency-Key`` 请求头。
        identity: 已认证调用方。
        session: 请求会话。

    Returns:
        任务读取模型。

    Raises:
        HTTPException: 幂等键已用于不同请求时返回 409。
    """

    try:
        return await create_task(session, identity, payload, idempotency_key)
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail="idempotency key conflict") from exc


async def _load_tenant_task(
    session: AsyncSession,
    identity: Identity,
    task_id: UUID,
    *,
    path: str,
) -> TaskRun:
    """返回租户拥有的任务；对外租户访问写审计并拒绝。

    Args:
        session: 请求会话。
        identity: 已认证调用方。
        task_id: 目标任务。
        path: 用于审计证据的端点路径。

    Returns:
        属于调用方租户的任务。

    Raises:
        HTTPException: 任务不存在时 404；任务属于其他租户时 403。

    Note:
        ``write_access_denied`` 会提交审计，因此被拒绝请求的会话可能已被提交。
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
            reason="cross-tenant task access",
            evidence={
                "caller_tenant_id": str(identity.tenant_id),
                "path": path,
            },
        )
        raise HTTPException(status_code=403, detail="forbidden")
    return task


def _task_read(task: TaskRun) -> TaskRead:
    """把持久化任务转换为 API 响应模型。"""

    return TaskRead(
        id=task.id,
        status=task.status,
        instruction=task.instruction,
        plan=task.plan,
        result=task.result,
    )


@router.get("/api/v1/tasks/{task_id}", response_model=TaskRead)
async def get_task(
    task_id: UUID,
    identity: Annotated[Identity, Depends(get_identity)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TaskRead:
    """返回一个租户限定的任务。

    Args:
        task_id: 目标任务。
        identity: 已认证调用方。
        session: 请求会话。

    Returns:
        任务的当前状态、计划与结果。

    Raises:
        HTTPException: 任务不存在时 404，跨租户时 403。
    """

    task = await _load_tenant_task(
        session,
        identity,
        task_id,
        path="GET /api/v1/tasks/{task_id}",
    )
    return _task_read(task)


async def get_tool_client() -> AsyncIterator[ToolClient]:
    """为单次执行请求产出生产 MCP stdio 客户端。

    Yields:
        已启动的 :class:`ErpToolClient`；请求结束后上下文管理器关闭会话与
        子进程。

    Note:
        每个执行请求启动一个子进程；不要在请求之间复用该依赖。
    """

    async with ErpToolClient() as client:
        yield client


async def get_execution_target(
    task_id: UUID,
    identity: Annotated[Identity, Depends(get_identity)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TaskRun:
    """在执行开始前解析并限定目标任务的租户。

    Args:
        task_id: 目标任务。
        identity: 已认证调用方。
        session: 请求会话。

    Returns:
        属于调用方租户的任务。

    Raises:
        HTTPException: 任务不存在时 404，跨租户时 403。

    Note:
        该依赖先于 MCP 子进程启动执行，因此未授权的请求不会创建子进程。
    """

    return await _load_tenant_task(
        session,
        identity,
        task_id,
        path="POST /api/v1/tasks/{task_id}/execute",
    )


@router.post("/api/v1/tasks/{task_id}/execute", response_model=TaskRead)
async def execute_task(
    task: Annotated[TaskRun, Depends(get_execution_target)],
    identity: Annotated[Identity, Depends(get_identity)],
    session: Annotated[AsyncSession, Depends(get_session)],
    tool_client: Annotated[ToolClient, Depends(get_tool_client)],
) -> TaskRead:
    """通过真实 ERP MCP 服务器执行任务的已审批写入节点。

    持久化的审批行才是权威。``pending`` 或 ``expired`` 审批会让任务保持
    ``awaiting_approval`` 且不调用任何工具；被拒绝的节点会跳过；已成功的任务
    步骤在重入时不会重复执行。

    Args:
        task: 已按租户解析的任务。
        identity: 已认证调用方；其租户绑定执行器。
        session: 请求会话；执行器在其中记录步骤、审计与 trace。
        tool_client: 本次请求专用的 MCP 工具客户端。

    Returns:
        执行后重新加载的任务视图。

    Note:
        端点本身不裁决审批，也不直接写业务数据；这些行为由
        :class:`TaskExecutor` 与 MCP 审批门禁负责。
    """

    executor = TaskExecutor(session, tool_client, identity.tenant_id)
    await executor.start(task.id)
    await session.refresh(task)
    return _task_read(task)
