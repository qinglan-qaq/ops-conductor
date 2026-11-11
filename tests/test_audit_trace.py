"""Tests for audit logging and trace span recording."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from opsconductor.db import SessionLocal
from opsconductor.domain.models import AuditLog, SalesOrder, TraceSpan, User
from opsconductor.domain.seed import TENANT_A, TENANT_B
from opsconductor.observability.audit import write_audit
from opsconductor.observability.trace import TraceRecorder


@pytest.mark.asyncio
async def test_write_audit_records_fields_without_committing(seeded_db):
    task_id = uuid4()
    async with SessionLocal() as session:
        actor = await session.scalar(select(User).where(User.name == "operator-a"))
        order = await session.scalar(
            select(SalesOrder).where(SalesOrder.order_no == "O1001")
        )
        assert actor is not None
        assert order is not None

        audit = await write_audit(
            session,
            tenant_id=TENANT_A,
            task_id=task_id,
            actor_id=actor.id,
            action="order.address.changed",
            entity_type="sales_order",
            entity_id=str(order.id),
            before={"address_detail": "", "version": 0},
            after={"address_detail": "上海市浦东新区世纪大道 1 号", "version": 1},
            evidence={"source": "task-8-test", "confidence": 0.97},
        )

        assert audit.id is not None
        assert audit.tenant_id == TENANT_A
        assert audit.task_id == task_id
        assert audit.actor_id == actor.id
        assert audit.action == "order.address.changed"
        assert audit.entity_type == "sales_order"
        assert audit.entity_id == str(order.id)
        assert audit.before == {"address_detail": "", "version": 0}
        assert audit.after == {
            "address_detail": "上海市浦东新区世纪大道 1 号",
            "version": 1,
        }
        assert audit.evidence == {"source": "task-8-test", "confidence": 0.97}

        # write_audit flushes but does not commit the caller's transaction.
        async with SessionLocal() as observer:
            assert (await observer.scalars(select(AuditLog))).all() == []

        await session.commit()

    async with SessionLocal() as session:
        rows = (
            await session.scalars(select(AuditLog).where(AuditLog.tenant_id == TENANT_A))
        ).all()
        assert len(rows) == 1
        stored = rows[0]
        assert stored.id == audit.id
        assert stored.task_id == task_id
        assert stored.actor_id == actor.id
        assert stored.before == {"address_detail": "", "version": 0}
        assert stored.after == {
            "address_detail": "上海市浦东新区世纪大道 1 号",
            "version": 1,
        }
        assert stored.evidence == {"source": "task-8-test", "confidence": 0.97}

        foreign = (
            await session.scalars(select(AuditLog).where(AuditLog.tenant_id == TENANT_B))
        ).all()
        assert foreign == []


@pytest.mark.asyncio
async def test_trace_span_has_ids_and_ends_after_context(seeded_db):
    async with SessionLocal() as session:
        recorder = TraceRecorder(session)
        async with recorder.start(
            "plan_task",
            task_id=None,
            tenant_id=TENANT_A,
            attributes={"planner": "template"},
        ) as span:
            assert span.trace_id
            assert span.span_id
            assert span.parent_span_id is None
            assert span.tenant_id == TENANT_A
            assert span.started_at is not None
            assert span.started_at.tzinfo is not None
            assert span.ended_at is None
            span.attributes = {**(span.attributes or {}), "nodes": 3}

        assert span.ended_at is not None
        assert span.ended_at >= span.started_at
        await session.commit()

    async with SessionLocal() as session:
        stored = await session.scalar(
            select(TraceSpan).where(TraceSpan.span_id == span.span_id)
        )
        assert stored is not None
        assert stored.trace_id == span.trace_id
        assert stored.started_at is not None
        assert stored.ended_at is not None
        assert stored.ended_at >= stored.started_at
        assert stored.attributes == {"planner": "template", "nodes": 3}


@pytest.mark.asyncio
async def test_child_span_inherits_parent_trace(seeded_db):
    async with SessionLocal() as session:
        recorder = TraceRecorder(session)
        async with recorder.start(
            "parent", task_id=None, tenant_id=TENANT_A
        ) as parent:
            async with recorder.start(
                "child",
                task_id=None,
                tenant_id=TENANT_A,
                parent_span_id=parent.span_id,
            ) as child:
                assert child.trace_id == parent.trace_id
                assert child.parent_span_id == parent.span_id
        await session.commit()

    assert parent.span_id != child.span_id
    assert parent.parent_span_id is None
    assert child.trace_id == parent.trace_id
    assert child.parent_span_id == parent.span_id

    async with SessionLocal() as session:
        stored = {
            row.span_id: row
            for row in (await session.scalars(select(TraceSpan))).all()
        }
        assert stored[parent.span_id].trace_id == stored[child.span_id].trace_id
        assert stored[child.span_id].parent_span_id == parent.span_id


@pytest.mark.asyncio
async def test_parent_span_from_another_tenant_starts_new_trace(seeded_db):
    async with SessionLocal() as session:
        recorder = TraceRecorder(session)
        async with recorder.start(
            "foreign-parent", task_id=None, tenant_id=TENANT_B
        ) as foreign:
            assert foreign.tenant_id == TENANT_B

        async with recorder.start(
            "local-child",
            task_id=None,
            tenant_id=TENANT_A,
            parent_span_id=foreign.span_id,
        ) as child:
            assert child.tenant_id == TENANT_A

        await session.commit()

    assert foreign.trace_id
    assert child.trace_id
    assert child.trace_id != foreign.trace_id
    assert child.parent_span_id is None

    async with SessionLocal() as session:
        stored = {
            row.span_id: row
            for row in (await session.scalars(select(TraceSpan))).all()
        }
        assert stored[foreign.span_id].trace_id == foreign.trace_id
        assert stored[child.span_id].trace_id == child.trace_id
        assert stored[child.span_id].parent_span_id is None


@pytest.mark.asyncio
async def test_span_exception_propagates_without_flushing(seeded_db, monkeypatch):
    async with SessionLocal() as session:
        recorder = TraceRecorder(session)

        with pytest.raises(RuntimeError, match="boom"):
            async with recorder.start(
                "failing", task_id=None, tenant_id=TENANT_A
            ) as span:
                # The span row is flushed on enter, before the traced block runs.
                stored = await session.scalar(
                    select(TraceSpan).where(TraceSpan.span_id == span.span_id)
                )
                assert stored is span
                span.attributes = {"phase": "failing"}

                def explode(*args, **kwargs):
                    raise AssertionError("flush must not run while an exception is active")

                monkeypatch.setattr(session, "flush", explode)
                raise RuntimeError("boom")

        assert span.ended_at is not None
        assert span.attributes == {"phase": "failing"}
        await session.rollback()
