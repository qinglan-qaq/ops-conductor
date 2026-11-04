"""Audit log helpers for actions performed by tasks and operators."""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from opsconductor.domain.models import AuditLog


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
