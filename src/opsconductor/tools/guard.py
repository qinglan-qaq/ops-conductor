"""Approval-context enforcement for OpsConductor MCP write tools.

Read tools may be called with a tenant id alone. Every write tool must also
carry the ``task_id`` that owns the approved plan node: the guard reloads that
task in the caller's tenant, finds an ``Approval`` row for the exact
task/order/action, and requires ``approved`` status before any write service is
allowed to run. A denial is audited and traced before the typed 403 is raised.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opsconductor.domain.enums import ApprovalStatus
from opsconductor.domain.models import Approval, TaskRun
from opsconductor.observability.audit import write_access_denied

WRITE_APPROVAL_ACTIONS = {
    "order_split": "split_order",
    "order_change_address": "change_address",
}
TOOL_ACCESS_DENIED = "TOOL_ACCESS_DENIED"


class ToolAccessDenied(RuntimeError):
    """Tool-layer denial carrying an HTTP-style 403 and stable error code."""

    status_code = 403
    code = "PERMISSION_DENIED"

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 403,
        code: str = "PERMISSION_DENIED",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


async def require_approved_write(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    task_id: UUID | None,
    order_id: UUID,
    tool: str,
    actor_id: UUID | None = None,
) -> Approval:
    """Return the approved approval row or record a denial and raise 403.

    The task must exist in the caller tenant, and the approval must match the
    exact task, order, and write action. Any missing or mismatched context is a
    denial, never an implicit permission.
    """

    action = WRITE_APPROVAL_ACTIONS[tool]
    reason: str | None = None
    approval: Approval | None = None

    if task_id is None:
        reason = f"{tool} requires task_id"
    else:
        task = await session.scalar(
            select(TaskRun).where(
                TaskRun.id == task_id,
                TaskRun.tenant_id == tenant_id,
            )
        )
        if task is None:
            reason = f"task {task_id} not found for tenant"
        else:
            approval = await session.scalar(
                select(Approval).where(
                    Approval.tenant_id == tenant_id,
                    Approval.task_id == task_id,
                    Approval.order_id == order_id,
                    Approval.action == action,
                    Approval.status == ApprovalStatus.approved.value,
                )
            )
            if approval is None:
                reason = (
                    f"no approved approval for {action} on order {order_id} "
                    f"and task {task_id}"
                )

    if reason is not None:
        await write_access_denied(
            session,
            tenant_id=tenant_id,
            actor_id=actor_id,
            task_id=task_id,
            entity_type="tool",
            entity_id=tool,
            reason=reason,
            evidence={
                "tool": tool,
                "action": action,
                "order_id": str(order_id),
                "task_id": str(task_id) if task_id is not None else None,
            },
        )
        raise ToolAccessDenied(f"{TOOL_ACCESS_DENIED}: {reason}")

    assert approval is not None
    return approval
