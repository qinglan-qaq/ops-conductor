"""Audit log helpers for actions performed by tasks and operators."""

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
    """Stage an audit record on the caller's transaction and flush it.

    The caller owns the transaction: this helper never commits, so the audit
    row is visible exactly when the surrounding business change is committed.
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
    """Commit a security denial audit row and trace span.

    Denials are committed even though the surrounding request fails: an
    attempted cross-tenant read or an unapproved write must leave an
    attributable trail. ``tenant_id`` is the tenant that owns the targeted
    resource (or the caller tenant for tool denials).
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
