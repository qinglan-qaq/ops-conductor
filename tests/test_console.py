"""Tests for the server-rendered approval console."""

from datetime import UTC, datetime
from uuid import NAMESPACE_DNS, UUID, uuid5

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from opsconductor.api.main import app
from opsconductor.config import get_settings
from opsconductor.db import SessionLocal
from opsconductor.domain.models import (
    Approval,
    AuditLog,
    InventoryLedger,
    SalesOrder,
    Shipment,
    TaskRun,
    TraceSpan,
)
from opsconductor.domain.seed import TENANT_A, TENANT_B

TASK_URL = "/api/v1/tasks"
CONSOLE_URL = "/console/tasks"
BODY = {
    "instruction": "处理今天华东仓超时未发货的订单",
    "warehouse": "east",
    "cutoff": "2026-11-04T00:00:00Z",
}
OPERATOR_A = uuid5(NAMESPACE_DNS, "opsconductor.user-operator-a")


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _create_task(client: AsyncClient, key: str = "console-1") -> UUID:
    response = await client.post(
        TASK_URL,
        json=BODY,
        headers={"X-API-Key": "dev-operator-a", "Idempotency-Key": key},
    )
    assert response.status_code == 200
    return UUID(response.json()["id"])


async def _approvals(task_id: UUID) -> list[Approval]:
    async with SessionLocal() as session:
        return list(
            (
                await session.scalars(
                    select(Approval)
                    .where(Approval.task_id == task_id)
                    .order_by(Approval.id)
                )
            ).all()
        )


async def _task(task_id: UUID) -> TaskRun:
    async with SessionLocal() as session:
        task = await session.scalar(select(TaskRun).where(TaskRun.id == task_id))
    assert task is not None
    return task


async def _audit_count(task_id: UUID, action: str | None = None) -> int:
    statement = select(func.count()).select_from(AuditLog).where(AuditLog.task_id == task_id)
    if action is not None:
        statement = statement.where(AuditLog.action == action)
    async with SessionLocal() as session:
        return int(await session.scalar(statement) or 0)


async def _write_counts() -> tuple[int, int]:
    async with SessionLocal() as session:
        shipments = int(
            await session.scalar(select(func.count()).select_from(Shipment)) or 0
        )
        ledger = int(
            await session.scalar(select(func.count()).select_from(InventoryLedger)) or 0
        )
    return shipments, ledger


async def _add_span(task_id: UUID, name: str = "plan_task") -> str:
    async with SessionLocal() as session:
        span = TraceSpan(
            trace_id="trace-console-test",
            span_id="span-console-test",
            tenant_id=TENANT_A,
            task_id=task_id,
            name=name,
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
            attributes={"source": "test"},
        )
        session.add(span)
        await session.commit()
        return span.span_id


@pytest.mark.asyncio
async def test_task_list_shows_created_task_plan_and_summary(seeded_db):
    async with _client() as client:
        task_id = await _create_task(client, "console-list")
        response = await client.get(f"{CONSOLE_URL}?api_key=dev-operator-a")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert BODY["instruction"] in body
    assert "O1001" in body
    assert "共处理" in body
    assert f"/console/tasks/{task_id}" in body
    assert "awaiting_approval" in body


@pytest.mark.asyncio
async def test_task_detail_shows_plan_approvals_and_trace_sections(seeded_db):
    async with _client() as client:
        task_id = await _create_task(client, "console-detail")
        response = await client.get(f"{CONSOLE_URL}/{task_id}?api_key=dev-operator-a")

    assert response.status_code == 200
    body = response.text
    assert BODY["instruction"] in body
    assert "计划" in body
    assert "审批" in body
    assert "Trace" in body
    assert "O1001" in body
    assert "split_order" in body
    assert "L2" in body
    assert "pending" in body
    assert 'name="comment"' in body
    assert 'name="order_id"' in body
    assert f"/console/tasks/{task_id}/trace" in body


@pytest.mark.asyncio
async def test_trace_page_lists_spans_for_task(seeded_db):
    async with _client() as client:
        task_id = await _create_task(client, "console-trace")
        span_id = await _add_span(task_id)

        trace_page = await client.get(
            f"{CONSOLE_URL}/{task_id}/trace?api_key=dev-operator-a"
        )
        detail_page = await client.get(f"{CONSOLE_URL}/{task_id}?api_key=dev-operator-a")

    assert trace_page.status_code == 200
    assert span_id in trace_page.text
    assert "plan_task" in trace_page.text
    assert "trace-console-test" in trace_page.text

    assert detail_page.status_code == 200
    assert "plan_task" in detail_page.text
    assert f"/console/tasks/{task_id}/trace" in detail_page.text


@pytest.mark.asyncio
async def test_console_approve_redirects_and_moves_task_to_running(seeded_db):
    async with _client() as client:
        task_id = await _create_task(client, "console-approve")
        response = await client.post(
            f"{CONSOLE_URL}/{task_id}/approve?api_key=dev-operator-a",
            data={"comment": "console approved"},
        )

        assert response.status_code == 303
        assert response.headers["location"].startswith(
            f"/console/tasks/{task_id}?api_key=dev-operator-a"
        )

        detail = await client.get(response.headers["location"])

    assert detail.status_code == 200
    assert "approved" in detail.text

    approvals = await _approvals(task_id)
    assert len(approvals) == 4
    assert {approval.status for approval in approvals} == {"approved"}
    assert {approval.approver_id for approval in approvals} == {OPERATOR_A}
    assert {approval.comment for approval in approvals} == {"console approved"}
    assert (await _task(task_id)).status == "running"
    assert await _audit_count(task_id, "approval.approve") == 4


@pytest.mark.asyncio
async def test_console_reject_records_decision_without_writes(seeded_db):
    async with _client() as client:
        task_id = await _create_task(client, "console-reject")
        before = await _write_counts()
        response = await client.post(
            f"{CONSOLE_URL}/{task_id}/reject?api_key=dev-operator-a",
            data={"comment": "console rejected"},
        )

    assert response.status_code == 303
    approvals = await _approvals(task_id)
    assert {approval.status for approval in approvals} == {"rejected"}
    assert {approval.comment for approval in approvals} == {"console rejected"}
    task = await _task(task_id)
    assert task.status == "running"
    assert task.result is None
    assert await _audit_count(task_id, "approval.reject") == 4
    assert await _audit_count(task_id) == 4
    assert await _write_counts() == before

    async with SessionLocal() as session:
        order = await session.scalar(
            select(SalesOrder).where(
                SalesOrder.tenant_id == TENANT_A,
                SalesOrder.order_no == "O1001",
            )
        )
    assert order is not None
    assert order.status == "pending_shipment"
    assert order.version == 0


@pytest.mark.asyncio
async def test_console_is_tenant_scoped(seeded_db):
    async with _client() as client:
        task_id = await _create_task(client, "console-tenant")

        foreign_detail = await client.get(
            f"{CONSOLE_URL}/{task_id}?api_key=dev-operator-b"
        )
        foreign_trace = await client.get(
            f"{CONSOLE_URL}/{task_id}/trace?api_key=dev-operator-b"
        )
        foreign_approve = await client.post(
            f"{CONSOLE_URL}/{task_id}/approve?api_key=dev-operator-b"
        )
        foreign_reject = await client.post(
            f"{CONSOLE_URL}/{task_id}/reject?api_key=dev-operator-b"
        )
        foreign_list = await client.get(f"{CONSOLE_URL}?api_key=dev-operator-b")

    assert foreign_detail.status_code == 404
    assert foreign_trace.status_code == 404
    assert foreign_approve.status_code == 404
    assert foreign_reject.status_code == 404
    assert "O1001" not in foreign_detail.text
    assert foreign_list.status_code == 200
    assert "O1001" not in foreign_list.text

    approvals = await _approvals(task_id)
    assert {approval.status for approval in approvals} == {"pending"}
    assert (await _task(task_id)).status == "awaiting_approval"
    assert await _audit_count(task_id) == 0

    async with SessionLocal() as session:
        tenant_b_tasks = (
            await session.scalars(select(TaskRun).where(TaskRun.tenant_id == TENANT_B))
        ).all()
    assert tenant_b_tasks == []


@pytest.mark.asyncio
async def test_development_defaults_to_operator_a(seeded_db):
    async with _client() as client:
        task_id = await _create_task(client, "console-default")
        response = await client.get(f"{CONSOLE_URL}/{task_id}")

    assert response.status_code == 200
    assert BODY["instruction"] in response.text


@pytest.mark.asyncio
async def test_console_requires_api_key_outside_development(seeded_db, monkeypatch):
    monkeypatch.setattr(get_settings(), "app_env", "production")

    async with _client() as client:
        missing = await client.get(CONSOLE_URL)
        invalid = await client.get(f"{CONSOLE_URL}?api_key=not-a-real-key")
        valid = await client.get(f"{CONSOLE_URL}?api_key=dev-operator-a")
        header = await client.get(
            CONSOLE_URL, headers={"X-API-Key": "dev-operator-a"}
        )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert valid.status_code == 200
    assert header.status_code == 200


@pytest.mark.asyncio
async def test_console_detail_rejects_unknown_task(seeded_db):
    async with _client() as client:
        response = await client.get(
            f"{CONSOLE_URL}/{uuid5(NAMESPACE_DNS, 'missing-task')}?api_key=dev-operator-a"
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_console_approval_on_unknown_task_returns_404(seeded_db):
    async with _client() as client:
        response = await client.post(
            f"{CONSOLE_URL}/{uuid5(NAMESPACE_DNS, 'missing-task')}/approve"
            "?api_key=dev-operator-a"
        )

    assert response.status_code == 404
    assert await _audit_count(uuid5(NAMESPACE_DNS, "missing-task")) == 0


@pytest.mark.asyncio
async def test_console_approval_can_target_one_order(seeded_db):
    async with _client() as client:
        task_id = await _create_task(client, "console-targeted")
        approval = (await _approvals(task_id))[0]
        assert approval.order_id is not None

        response = await client.post(
            f"{CONSOLE_URL}/{task_id}/approve?api_key=dev-operator-a",
            data={"comment": "one order", "order_id": str(approval.order_id)},
        )

    assert response.status_code == 303
    approvals = await _approvals(task_id)
    target = next(row for row in approvals if row.id == approval.id)
    assert target.status == "approved"
    assert target.comment == "one order"
    assert sum(row.status == "pending" for row in approvals) == 3
    assert (await _task(task_id)).status == "awaiting_approval"
    assert await _audit_count(task_id) == 1
