"""Trace span recording backed by the ``trace_span`` table."""

import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opsconductor.domain.models import TraceSpan


class TraceRecorder:
    """Record trace spans on a caller-owned transaction.

    ``start`` returns an async context manager that yields the created span, so
    callers can pass ``span.span_id`` to child spans. The span is flushed on
    enter and on normal exit, but never committed; the caller must commit after
    the span exits for the final ``ended_at`` update to persist. When the traced
    block raises, the span's end time and attributes are set in memory, no
    flush is attempted, and the original exception propagates unchanged.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @asynccontextmanager
    async def start(
        self,
        name: str,
        task_id: uuid.UUID | None,
        tenant_id: uuid.UUID,
        parent_span_id: str | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[TraceSpan]:
        parent = await self._find_parent(tenant_id, parent_span_id)
        initial_attributes = dict(attributes or {})
        span = TraceSpan(
            trace_id=parent.trace_id if parent is not None else uuid.uuid4().hex,
            span_id=uuid.uuid4().hex,
            parent_span_id=parent_span_id if parent is not None else None,
            tenant_id=tenant_id,
            task_id=task_id,
            name=name,
            started_at=datetime.now(UTC),
            attributes=initial_attributes or None,
        )
        self.session.add(span)
        await self.session.flush()
        try:
            yield span
        except BaseException:
            self._finish(span, initial_attributes)
            raise
        else:
            self._finish(span, initial_attributes)
            await self.session.flush()

    @staticmethod
    def _finish(span: TraceSpan, initial_attributes: dict[str, Any]) -> None:
        span.ended_at = datetime.now(UTC)
        merged = {**initial_attributes, **(span.attributes or {})}
        span.attributes = merged or None

    async def _find_parent(
        self, tenant_id: uuid.UUID, parent_span_id: str | None
    ) -> TraceSpan | None:
        """Return the parent span only when it belongs to the same tenant."""

        if parent_span_id is None:
            return None
        return await self.session.scalar(
            select(TraceSpan).where(
                TraceSpan.tenant_id == tenant_id,
                TraceSpan.span_id == parent_span_id,
            )
        )
