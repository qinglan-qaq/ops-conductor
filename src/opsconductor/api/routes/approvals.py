"""计划任务的审批决策端点。

审批的角色门禁与租户限定都委托给
:class:`opsconductor.orchestrator.approval.ApprovalService`：``operator``、
``approver`` 与 ``admin`` 可以裁决普通审批，L3 审批额外要求 ``approver`` 或
``admin``。路由只负责解析调用方、转发决策，并把服务错误映射为 HTTP 状态码。

Invariants:

- 每个请求都通过 ``get_identity`` 解析租户与角色；路由不信任请求体中的租户信息。
- 路由不直接写审批或任务行；成功决策由审批服务提交。
- 服务异常按 ``ApprovalError.status_code`` 映射，路由不重新解释业务规则。
"""

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
    """审批决策的可选上下文。

    Attributes:
        comment: 最多 500 字符的备注，写入审批行与审计。
        order_id: 只裁决该订单的审批；``None`` 表示任务的全部待处理审批。
    """

    comment: str | None = Field(default=None, max_length=500)
    order_id: UUID | None = None


async def _decide(
    task_id: UUID,
    payload: ApprovalRequest | None,
    approved: bool,
    identity: Identity,
    session: AsyncSession,
) -> TaskRead:
    """把一次批准或拒绝转发给审批服务。

    Args:
        task_id: 目标任务。
        payload: 可选的备注与订单范围。
        approved: ``True`` 表示批准，``False`` 表示拒绝。
        identity: 已认证调用方；租户与角色都由服务校验。
        session: 请求会话。

    Returns:
        决策后的任务视图。

    Raises:
        HTTPException: 服务抛出 :class:`ApprovalError` 时按其 ``status_code``
            返回，例如 403、404 或 409。

    Note:
        带 ``order_id`` 时只裁决该订单的审批；否则裁决任务的全部待处理审批。
    """

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
    """批准任务的待处理审批，可只限一个订单。

    Args:
        task_id: 目标任务。
        identity: 已认证调用方。
        session: 请求会话。
        payload: 可选的备注与订单范围。

    Returns:
        决策后的任务视图。

    Raises:
        HTTPException: 审批不存在、跨租户、角色无权或状态冲突时，分别按服务
            返回的状态码（404、403、409）响应。

    Note:
        角色门禁（普通审批要求 ``operator``、``approver`` 或 ``admin``，L3 审批
        额外要求 ``approver`` 或 ``admin``）与租户限定都由审批服务执行。
    """

    return await _decide(task_id, payload, True, identity, session)


@router.post("/api/v1/tasks/{task_id}/reject", response_model=TaskRead)
async def reject_task(
    task_id: UUID,
    identity: Annotated[Identity, Depends(get_identity)],
    session: Annotated[AsyncSession, Depends(get_session)],
    payload: ApprovalRequest | None = None,
) -> TaskRead:
    """拒绝任务的待处理审批，可只限一个订单。

    Args:
        task_id: 目标任务。
        identity: 已认证调用方。
        session: 请求会话。
        payload: 可选的备注与订单范围。

    Returns:
        决策后的任务视图。

    Raises:
        HTTPException: 审批不存在、跨租户、角色无权或状态冲突时，分别按服务
            返回的状态码（404、403、409）响应。

    Note:
        角色门禁与租户限定都由审批服务执行；路由本身不写审批行。
    """

    return await _decide(task_id, payload, False, identity, session)
