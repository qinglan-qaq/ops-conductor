"""Tests for POST /api/v1/tasks/{task_id}/execute.

The endpoint is exercised with the production ``TaskExecutor`` and approval
service; only the MCP transport is replaced by an in-process fake that calls
the real write services, matching the pattern used by the executor tests.
"""

from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid4, uuid5

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from opsconductor.api.main import app
from opsconductor.api.routes.tasks import get_tool_client
from opsconductor.db import SessionLocal
from opsconductor.domain.models import (
    AuditLog,
    Inventory,
    SalesOrder,
    Shipment,
    TaskRun,
    TaskStep,
    TraceSpan,
)
from opsconductor.domain.seed import SKU_IDS, TENANT_A, WAREHOUSE_EAST
from opsconductor.tools.service import ErpToolService

TASK_URL = "/api/v1/tasks"
BODY = {
    "instruction": "处理今天华东仓超时未发货的订单",
    "warehouse": "east",
    "cutoff": "2026-11-04T00:00:00Z",
}
OPERATOR_A = uuid5(NAMESPACE_DNS, "opsconductor.user-operator-a")
ORDER_O1001 = uuid5(NAMESPACE_DNS, "opsconductor.order-O1001")


class FakeToolClient:
    """In-process MCP transport that executes the real write services."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, dict(arguments)))
        async with SessionLocal() as session:
            service = ErpToolService(session)
            tenant_id = UUID(arguments["tenant_id"])
            order_id = UUID(arguments["order_id"])
            task_id = (
                UUID(arguments["task_id"]) if arguments.get("task_id") else None
            )
            actor_id = (
                UUID(arguments["actor_id"]) if arguments.get("actor_id") else None
            )
            key = arguments["idempotency_key"]

            if name == "order_split":
                return await service.order_split(
                    tenant_id,
                    order_id,
                    arguments["shipments"],
                    key,
                    dry_run=arguments.get("dry_run", False),
                    actor_id=actor_id,
                    task_id=task_id,
                )
            if name == "order_change_address":
                return await service.order_change_address(
                    tenant_id,
                    order_id,
                    arguments["address"],
                    key,
                    dry_run=arguments.get("dry_run", False),
                    actor_id=actor_id,
                    task_id=task_id,
                )
            if name == "order_revert_split":
                return await service.order_revert_split(
                    tenant_id, order_id, key, task_id=task_id
                )
            if name == "order_revert_address":
                return await service.order_revert_address(
                    tenant_id,
                    order_id,
                    arguments["before_address"],
                    key,
                    task_id=task_id,
                )
        raise AssertionError(f"unexpected tool: {name}")


@pytest.fixture
def fake_tool_client():
    fake = FakeToolClient()

    async def override() -> Any:
        yield fake

    app.dependency_overrides[get_tool_client] = override
    try:
        yield fake
    finally:
        app.dependency_overrides.pop(get_tool_client, None)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _auth(api_key: str = "dev-operator-a") -> dict[str, str]:
    return {"X-API-Key": api_key}


async def _create_task(client: AsyncClient, key: str) -> UUID:
    response = await client.post(
        TASK_URL,
        json=BODY,
        headers={**_auth(), "Idempotency-Key": key},
    )
    assert response.status_code == 200
    return UUID(response.json()["id"])


async def _task(task_id: UUID) -> TaskRun:
    async with SessionLocal() as session:
        task = await session.get(TaskRun, task_id)
    assert task is not None
    return task


async def _steps(task_id: UUID) -> list[TaskStep]:
    async with SessionLocal() as session:
        return list(
            (
                await session.scalars(
                    select(TaskStep)
                    .where(TaskStep.task_id == task_id)
                    .order_by(TaskStep.node_id)
                )
            ).all()
        )


async def _order(order_no: str) -> SalesOrder:
    async with SessionLocal() as session:
        order = await session.scalar(
            select(SalesOrder).where(
                SalesOrder.tenant_id == TENANT_A,
                SalesOrder.order_no == order_no,
            )
        )
    assert order is not None
    return order


async def _inventory(sku_code: str) -> Inventory:
    async with SessionLocal() as session:
        inventory = await session.scalar(
            select(Inventory).where(
                Inventory.tenant_id == TENANT_A,
                Inventory.sku_id == SKU_IDS[sku_code],
                Inventory.warehouse_id == WAREHOUSE_EAST,
            )
        )
    assert inventory is not None
    return inventory


async def _spans(task_id: UUID) -> list[TraceSpan]:
    async with SessionLocal() as session:
        return list(
            (
                await session.scalars(
                    select(TraceSpan).where(TraceSpan.task_id == task_id)
                )
            ).all()
        )


@pytest.mark.asyncio
async def test_execute_waits_for_approval_then_executes_approved_writes(
    seeded_db, fake_tool_client
):
    async with _client() as client:
        task_id = await _create_task(client, "execute-main")
        before = await client.post(
            f"{TASK_URL}/{task_id}/execute", headers=_auth()
        )
        assert before.status_code == 200
        assert before.json()["status"] == "awaiting_approval"
        assert before.json()["result"] is None
        assert fake_tool_client.calls == []
        assert await _steps(task_id) == []

        approved = await client.post(
            f"{TASK_URL}/{task_id}/approve",
            headers=_auth("dev-approver-a"),
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "running"

        executed = await client.post(
            f"{TASK_URL}/{task_id}/execute", headers=_auth()
        )

    assert executed.status_code == 200
    payload = executed.json()
    assert payload["id"] == str(task_id)
    assert payload["status"] == "succeeded"
    assert payload["result"] is not None
    assert payload["result"]["status"] == "succeeded"
    assert payload["result"]["verified"] is True
    assert payload["result"]["failed"] == []

    task = await _task(task_id)
    assert task.status == "succeeded"
    assert task.error is None

    writes = [
        (name, args)
        for name, args in fake_tool_client.calls
        if name in {"order_split", "order_change_address"}
    ]
    assert len(writes) == 8
    assert sum(1 for _, args in writes if args["dry_run"] is True) == 4
    assert sum(1 for _, args in writes if args["dry_run"] is False) == 4
    assert {args["tenant_id"] for _, args in writes} == {str(TENANT_A)}
    assert {args["actor_id"] for _, args in writes} == {str(OPERATOR_A)}

    assert (await _order("O1001")).status == "split"
    assert (await _inventory("SKU-001")).available == 98
    assert (await _inventory("SKU-001")).reserved == 2

    steps = await _steps(task_id)
    assert {step.node_id for step in steps} == {
        node["node_id"] for node in task.plan["nodes"]
    }
    for step in steps:
        if step.status == "succeeded":
            assert step.output is not None
        else:
            assert step.status == "skipped"

    production = {
        span.name
        for span in await _spans(task_id)
        if (span.attributes or {}).get("source") == "production"
    }
    assert {
        "plan_task",
        "approval",
        "executor.load",
        "executor.dry_run",
        "executor.execute",
        "executor.verify",
        "executor.report",
    } <= production
    assert any(name.startswith("tool.") for name in production)


@pytest.mark.asyncio
async def test_execute_rejects_cross_tenant_callers_and_audits(seeded_db, fake_tool_client):
    async with _client() as client:
        task_id = await _create_task(client, "execute-tenant")
        response = await client.post(
            f"{TASK_URL}/{task_id}/execute", headers=_auth("dev-operator-b")
        )

    assert response.status_code == 403
    assert "O1001" not in response.text
    assert fake_tool_client.calls == []
    assert await _steps(task_id) == []
    assert (await _task(task_id)).status == "awaiting_approval"
    assert (await _order("O1001")).status == "pending_shipment"

    async with SessionLocal() as session:
        denial = await session.scalar(
            select(AuditLog).where(
                AuditLog.tenant_id == TENANT_A,
                AuditLog.task_id == task_id,
                AuditLog.action == "security.access_denied",
                AuditLog.entity_type == "task",
            )
        )
    assert denial is not None
    assert denial.evidence is not None
    assert denial.evidence["path"] == "POST /api/v1/tasks/{task_id}/execute"


@pytest.mark.asyncio
async def test_execute_unknown_task_returns_404(seeded_db, fake_tool_client):
    async with _client() as client:
        response = await client.post(
            f"{TASK_URL}/{uuid4()}/execute", headers=_auth()
        )

    assert response.status_code == 404
    assert fake_tool_client.calls == []


@pytest.mark.asyncio
async def test_execute_is_idempotent_after_success(seeded_db, fake_tool_client):
    async with _client() as client:
        task_id = await _create_task(client, "execute-repeat")
        approved = await client.post(
            f"{TASK_URL}/{task_id}/approve", headers=_auth("dev-approver-a")
        )
        assert approved.status_code == 200
        first = await client.post(f"{TASK_URL}/{task_id}/execute", headers=_auth())
        calls_after_first = len(fake_tool_client.calls)
        second = await client.post(f"{TASK_URL}/{task_id}/execute", headers=_auth())

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "succeeded"
    assert second.json()["status"] == "succeeded"
    assert len(fake_tool_client.calls) == calls_after_first
    assert (await _task(task_id)).status == "succeeded"

    async with SessionLocal() as session:
        shipments = list(
            (
                await session.scalars(
                    select(Shipment).where(Shipment.order_id == ORDER_O1001)
                )
            ).all()
        )
    assert len(shipments) == 2


@pytest.mark.asyncio
async def test_execute_after_rejection_skips_writes(seeded_db, fake_tool_client):
    async with _client() as client:
        task_id = await _create_task(client, "execute-rejected")
        rejected = await client.post(
            f"{TASK_URL}/{task_id}/reject", headers=_auth("dev-approver-a")
        )
        assert rejected.status_code == 200
        response = await client.post(f"{TASK_URL}/{task_id}/execute", headers=_auth())

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "partially_succeeded"
    assert payload["result"]["skipped"]
    assert fake_tool_client.calls == []
    assert (await _task(task_id)).status == "partially_succeeded"
    assert (await _order("O1001")).status == "pending_shipment"
    assert (await _inventory("SKU-001")).available == 100

    statuses = {step.node_id: step.status for step in await _steps(task_id)}
    assert set(statuses.values()) == {"skipped"}
    assert (await _task(task_id)).result["status"] == "partially_succeeded"
