"""为任务与操作者执行的动作写审计记录。

本模块的辅助函数只在调用方会话上暂存审计行并 flush，提交由调用方负责。唯一
的例外是安全拒绝记录 :func:`write_access_denied`：它自行提交，保证拒绝行为
即使在请求失败时也留下可追溯的记录。

Invariants:

- 每条审计行都携带 ``tenant_id``；``task_id`` 与 ``actor_id`` 可为 ``None``，
  分别表示非任务动作与系统动作。
- :func:`write_audit` 从不提交，审计行与外层业务变更同时可见或同时回滚。
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from opsconductor.domain.models import AuditLog
from opsconductor.observability.trace import TraceRecorder

ACCESS_DENIED_ACTION = "security.access_denied"
ACCESS_DENIED_SPAN = "security.denied"


async def write_audit(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    task_id: UUID | None,
    actor_id: UUID | None,
    action: str,
    entity_type: str,
    entity_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    evidence: dict[str, Any] | None,
) -> AuditLog:
    """在调用方事务上暂存一条审计记录并 flush。

    Args:
        session: 调用方拥有的会话。
        tenant_id: 审计行归属的租户。
        task_id: 触发动作的任务；非任务动作可为 ``None``。
        actor_id: 触发动作的用户；系统动作可为 ``None``。
        action: 稳定的动作名，例如 ``order.split``。
        entity_type: 被操作实体的类型名。
        entity_id: 被操作实体的标识（通常是字符串化 UUID）。
        before: 变更前快照；不适用时为 ``None``。
        after: 变更后快照；不适用时为 ``None``。
        evidence: 附加证据，例如来源、置信度或错误码。

    Returns:
        已加入会话的 :class:`AuditLog`，其 ``id`` 在 flush 后可用。

    Note:
        本函数从不提交。审计行恰好在外层业务变更提交时可见；调用方回滚时
        审计行一并丢弃。
    """

    entry = AuditLog(
        tenant_id=tenant_id,
        task_id=task_id,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=before,
        after=after,
        evidence=evidence,
    )
    session.add(entry)
    await session.flush()
    return entry


async def write_access_denied(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    task_id: UUID | None,
    entity_type: str,
    entity_id: str,
    reason: str,
    evidence: dict[str, Any] | None = None,
) -> AuditLog:
    """提交一条安全拒绝审计行，并记录对应的 trace span。

    Args:
        session: 调用方会话；本函数会在返回前提交它。
        tenant_id: 目标资源所属租户；工具拒绝时为调用方租户。
        actor_id: 被拒绝的调用方；匿名拒绝可为 ``None``。
        task_id: 关联任务；与被拒绝请求无关时为 ``None``。
        entity_type: 被访问实体的类型名。
        entity_id: 被访问实体的标识。
        reason: 拒绝原因。
        evidence: 附加证据，会并入固定字段并覆盖同名默认值。

    Returns:
        已提交的 :class:`AuditLog`。

    Note:
        拒绝记录在请求失败时也必须保留：跨租户读取或未审批写入都要留下可归因
        的痕迹。``evidence`` 中的同名键会覆盖默认的 ``code``、``denied`` 与
        ``status_code``。本函数提交会话，调用方不应再依赖原事务状态。
    """

    entry = await write_audit(
        session,
        tenant_id=tenant_id,
        task_id=task_id,
        actor_id=actor_id,
        action=ACCESS_DENIED_ACTION,
        entity_type=entity_type,
        entity_id=entity_id,
        before=None,
        after={"reason": reason},
        evidence={
            "code": "PERMISSION_DENIED",
            "denied": True,
            "status_code": 403,
            **(evidence or {}),
        },
    )
    async with TraceRecorder(session).start(
        ACCESS_DENIED_SPAN,
        task_id=task_id,
        tenant_id=tenant_id,
        attributes={
            "source": "production",
            "reason": reason,
            "entity_type": entity_type,
            "entity_id": entity_id,
        },
    ):
        pass
    await session.commit()
    return entry
