"""Task submission and lookup endpoints."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from opsconductor.api.deps import Identity, get_identity
from opsconductor.config import Settings, get_settings
from opsconductor.db import get_session
from opsconductor.domain.enums import RiskLevel
from opsconductor.domain.models import Approval, TaskRun
from opsconductor.llm.gateway import HttpChatModel
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
from opsconductor.schemas import Plan, TaskCreate, TaskRead, validate_plan

TASK_TYPE = "order_exception"
WRITE_ACTIONS = {"split_order", "change_address"}

router = APIRouter(tags=["tasks"])


@dataclass(frozen=True)
class PlannerTask:
    """Planning input assembled from the persisted TaskRun and request context."""

    id: UUID
    tenant_id: UUID
    instruction: str
    warehouse: str | None
    cutoff: str | None


def _build_planner(session: AsyncSession) -> TemplatePlanner | LLMPlanner:
    settings = get_settings()
    if settings.stub_llm or not settings.llm_api_key or not settings.llm_base_url:
        return TemplatePlanner(session)
    model = HttpChatModel(
        settings.llm_base_url, settings.llm_api_key, settings.llm_model_planner
    )
    return LLMPlanner(model, session)


async def _generate_plan(session: AsyncSession, task: PlannerTask) -> Plan:
    planner = _build_planner(session)
    if isinstance(planner, LLMPlanner):
        try:
            return await planner.plan(task)
        except PlanGenerationError:
            return await TemplatePlanner(session).plan(task)
    return await planner.plan(task)


def _apply_risks(plan: Plan, settings: Settings) -> None:
    """Derive risk level and approval needs that planners do not set themselves."""

    split_nodes = [node for node in plan.nodes if node.action == "split_order"]
    split_risk = (
        RiskLevel.L3
        if len(split_nodes) >= settings.l3_batch_threshold
        else RiskLevel.L2
    )
    for node in plan.nodes:
        if node.action == "split_order":
            node.risk = split_risk
            node.requires_approval = True
        elif node.action == "change_address":
            node.risk = RiskLevel.L2
            node.requires_approval = True
        else:
            node.risk = RiskLevel.L0
            node.requires_approval = False
    plan.requires_l3 = any(node.risk == RiskLevel.L3 for node in plan.nodes)


def _build_approvals(
    plan: Plan,
    *,
    tenant_id: UUID,
    task_id: UUID,
    settings: Settings,
    now: datetime,
) -> list[Approval]:
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
    """Create a planned task with approvals, returning the stored response on replay."""

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
    _apply_risks(plan, settings)

    plan_payload = plan.model_dump(mode="json")
    plan_payload["request"] = {
        "warehouse": payload.warehouse,
        "cutoff": payload.cutoff,
    }
    task.plan = plan_payload
    task.status = "awaiting_approval"
    now = datetime.now(UTC)
    session.add_all(
        _build_approvals(
            plan,
            tenant_id=identity.tenant_id,
            task_id=task.id,
            settings=settings,
            now=now,
        )
    )

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
    try:
        return await create_task(session, identity, payload, idempotency_key)
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail="idempotency key conflict") from exc


@router.get("/api/v1/tasks/{task_id}", response_model=TaskRead)
async def get_task(
    task_id: UUID,
    identity: Annotated[Identity, Depends(get_identity)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TaskRead:
    task = await session.scalar(
        select(TaskRun).where(
            TaskRun.id == task_id,
            TaskRun.tenant_id == identity.tenant_id,
        )
    )
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return TaskRead(
        id=task.id,
        status=task.status,
        instruction=task.instruction,
        plan=task.plan,
        result=task.result,
    )
