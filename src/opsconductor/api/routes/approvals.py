"""Approval decision endpoints for planned tasks."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from opsconductor.api.deps import Identity, get_identity
from opsconductor.db import get_session
from opsconductor.orchestrator.approval import ApprovalError, ApprovalService
from opsconductor.schemas import TaskRead

router = APIRouter(tags=["approvals"])


class ApprovalRequest(BaseModel):
    """Optional decision context for an approve or reject call."""

    comment: str | None = Field(default=None, max_length=500)
    order_id: UUID | None = None


async def _decide(
    task_id: UUID,
    payload: ApprovalRequest | None,
    approved: bool,
    identity: Identity,
    session: AsyncSession,
) -> TaskRead:
    service = ApprovalService(session)
    try:
        task = await service.decide(
            task_id,
            identity,
            approved,
            comment=payload.comment if payload is not None else None,
            order_id=payload.order_id if payload is not None else None,
        )
    except ApprovalError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return TaskRead(
        id=task.id,
        status=task.status,
        instruction=task.instruction,
        plan=task.plan,
        result=task.result,
    )


@router.post("/api/v1/tasks/{task_id}/approve", response_model=TaskRead)
async def approve_task(
    task_id: UUID,
    identity: Annotated[Identity, Depends(get_identity)],
    session: Annotated[AsyncSession, Depends(get_session)],
    payload: ApprovalRequest | None = None,
) -> TaskRead:
    """Approve pending approvals for a task, optionally scoped to one order."""

    return await _decide(task_id, payload, True, identity, session)


@router.post("/api/v1/tasks/{task_id}/reject", response_model=TaskRead)
async def reject_task(
    task_id: UUID,
    identity: Annotated[Identity, Depends(get_identity)],
    session: Annotated[AsyncSession, Depends(get_session)],
    payload: ApprovalRequest | None = None,
) -> TaskRead:
    """Reject pending approvals for a task, optionally scoped to one order."""

    return await _decide(task_id, payload, False, identity, session)
