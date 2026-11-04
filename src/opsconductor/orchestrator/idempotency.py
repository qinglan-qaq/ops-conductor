"""Idempotency records for task creation."""

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opsconductor.domain.models import IdempotencyKey

TASK_CREATE_SCOPE = "task.create"


class IdempotencyConflict(Exception):
    """Raised when an idempotency key is reused with a different request."""


def request_hash(payload: Any) -> str:
    """Return a stable SHA-256 hash for a Pydantic model or JSON-like mapping."""

    if hasattr(payload, "model_dump"):
        payload = payload.model_dump()
    encoded = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def get_existing_record(
    session: AsyncSession,
    tenant_id: UUID,
    scope: str,
    key: str,
    fingerprint: str,
) -> IdempotencyKey | None:
    """Look up a stored response, raising if the request hash differs."""

    record = await session.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.tenant_id == tenant_id,
            IdempotencyKey.scope == scope,
            IdempotencyKey.key == key,
        )
    )
    if record is None:
        return None
    if record.request_hash != fingerprint:
        raise IdempotencyConflict(f"idempotency key {key!r} was used with another request")
    if record.response is None:
        raise IdempotencyConflict(f"idempotency key {key!r} is still in progress")
    return record


def build_record(
    *,
    tenant_id: UUID,
    scope: str,
    key: str,
    fingerprint: str,
    response: dict[str, Any],
) -> IdempotencyKey:
    """Create a completed idempotency record for the first successful response."""

    return IdempotencyKey(
        tenant_id=tenant_id,
        scope=scope,
        key=key,
        request_hash=fingerprint,
        response=response,
        status="completed",
    )
