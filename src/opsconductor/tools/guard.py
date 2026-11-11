"""OpsConductor MCP 写工具的审批上下文门禁。

读工具只需租户 ID 即可调用。每个写工具还必须携带拥有已审批计划节点的
``task_id``：门禁在调用方租户内重新加载该任务，查找与任务、订单、动作完全匹配
的 ``Approval`` 行，并要求状态为 ``approved``，之后写服务才允许执行。拒绝会在
抛出带类型的 403 之前写入审计与 trace。

Invariants:

- 审批必须同时匹配租户、任务、订单与写动作；任何缺失或不匹配都视为拒绝，绝不
  隐式放行。
- 拒绝路径会提交一条访问拒绝审计，且不会修改任何业务数据。
- ``tool`` 必须是 :data:`WRITE_APPROVAL_ACTIONS` 中的键，否则抛出 ``KeyError``。
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
    """携带 HTTP 风格 403 与稳定错误码的工具层拒绝异常。

    Attributes:
        status_code: HTTP 风格状态码，默认 403。
        code: 稳定的错误码，默认 ``PERMISSION_DENIED``。
    """

    status_code = 403
    code = "PERMISSION_DENIED"

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 403,
        code: str = "PERMISSION_DENIED",
    ) -> None:
        """构造拒绝异常。

        Args:
            message: 人类可读的拒绝原因。
            status_code: 覆盖默认的 403。
            code: 覆盖默认的错误码。
        """
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
    """返回已批准的审批行，或记录拒绝并抛出 403。

    任务必须存在于调用方租户中，审批必须精确匹配任务、订单与写动作。任何缺失
    或不匹配的上下文都视为拒绝，绝不隐式授权。

    Args:
        session: 用于查询任务与审批、并提交拒绝审计的会话。
        tenant_id: 调用方租户；任务与审批都必须属于该租户。
        task_id: 拥有已审批计划节点的任务；``None`` 会直接拒绝。
        order_id: 写入目标订单。
        tool: 写工具名，必须是 :data:`WRITE_APPROVAL_ACTIONS` 的键。
        actor_id: 调用方用户，用于审计；可为 ``None``。

    Returns:
        与租户、任务、订单、动作匹配且状态为 ``approved`` 的 ``Approval``。

    Raises:
        ToolAccessDenied: 任务缺失或属于其他租户、审批缺失或未批准；异常携带
            403 状态码。
        KeyError: ``tool`` 不是已登记的写工具。

    Warning:
        拒绝路径通过 :func:`write_access_denied` 提交审计，因此调用方事务可能
        已被提交；被拒绝的调用不会修改任何业务数据。

    Note:
        门禁只认持久化的审批行，不信任调用方传入的标志；这里只匹配
        ``approved`` 状态，过期审批不会被放行。
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
