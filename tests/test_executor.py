"""Tests for the LangGraph execution path, verifier, and compensation."""

from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid4, uuid5

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

from opsconductor.api.main import app
from opsconductor.db import SessionLocal
from opsconductor.domain.models import (
    Approval,
    AuditLog,
    Inventory,
    OrderLine,
    SalesOrder,
    Shipment,
    ShipmentLine,
    TaskRun,
    TaskStep,
)
from opsconductor.domain.seed import (
    SHOP_A,
    SKU_IDS,
    TENANT_A,
    TENANT_B,
    WAREHOUSE_EAST,
)
from opsconductor.domain.write_service import split_order
from opsconductor.orchestrator.executor import ExecutionResult, TaskExecutor
from opsconductor.orchestrator.verifier import VerificationResult, Verifier
from opsconductor.tools.service import ErpToolService

TASK_URL = "/api/v1/tasks"
BODY = {
    "instruction": "处理今天华东仓超时未发货的订单",
    "warehouse": "east",
    "cutoff": "2026-11-04T00:00:00Z",
}
OPERATOR_A = uuid5(NAMESPACE_DNS, "opsconductor.user-operator-a")
ORDER_O1001 = uuid5(NAMESPACE_DNS, "opsconductor.order-O1001")
ORDER_O1002 = uuid5(NAMESPACE_DNS, "opsconductor.order-O1002")
ORDER_O1004 = uuid5(NAMESPACE_DNS, "opsconductor.order-O1004")
ORDER_O1006 = uuid5(NAMESPACE_DNS, "opsconductor.order-O1006")
WRITE_TOOLS = {"order_split", "order_change_address"}
COMPENSATION_TOOLS = {"order_revert_split", "order_revert_address"}


class FakeToolClient:
    """In-process MCP substitute that records calls and executes real writes."""

    def __init__(
        self,
        fail_on: set[str] | None = None,
        fail_dry_run_keys: set[str] | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_on = set(fail_on or ())
        self.fail_dry_run_keys = set(fail_dry_run_keys or ())

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, dict(arguments)))
        if name in self.fail_on:
            raise RuntimeError(f"injected tool failure: {name}")
        if (
            arguments.get("dry_run") is True
            and arguments.get("idempotency_key") in self.fail_dry_run_keys
        ):
            raise RuntimeError(f"injected dry-run failure: {name}")

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


class FailingVerifier:
    """Verifier double that always reports a deterministic failure."""

    def __init__(self, reason: str = "forced verification failure") -> None:
        self.reason = reason

    async def verify(self, task: Any, plan: Any, results: Any) -> VerificationResult:
        return VerificationResult(passed=False, reason=self.reason)


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


async def _decide(task_id: UUID, endpoint: str = "approve") -> str:
    async with _client() as client:
        response = await client.post(
            f"{TASK_URL}/{task_id}/{endpoint}", headers=_auth()
        )
    assert response.status_code == 200
    return response.json()["status"]


async def _approved_task(key: str = "exec-approved") -> UUID:
    async with _client() as client:
        task_id = await _create_task(client, key)
    assert await _decide(task_id) == "running"
    return task_id


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


async def _approvals(task_id: UUID) -> list[Approval]:
    async with SessionLocal() as session:
        return list(
            (
                await session.scalars(
                    select(Approval).where(Approval.task_id == task_id)
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


async def _shipments(order_id: UUID) -> list[Shipment]:
    async with SessionLocal() as session:
        return list(
            (
                await session.scalars(
                    select(Shipment).where(
                        Shipment.tenant_id == TENANT_A,
                        Shipment.order_id == order_id,
                    )
                )
            ).all()
        )


def _shipments_o1001() -> list[dict[str, Any]]:
    return [
        {
            "warehouse_id": str(WAREHOUSE_EAST),
            "lines": [{"sku_id": str(SKU_IDS["SKU-001"]), "qty": 2}],
        },
        {
            "warehouse_id": str(WAREHOUSE_EAST),
            "lines": [{"sku_id": str(SKU_IDS["SKU-002"]), "qty": 1}],
        },
    ]


async def _run(
    task_id: UUID,
    fake: FakeToolClient,
    verifier: Any = None,
    tenant_id: UUID = TENANT_A,
) -> ExecutionResult:
    async with SessionLocal() as session:
        executor = TaskExecutor(
            session, fake, tenant_id, verifier=verifier
        )
        return await executor.start(task_id)


@pytest.mark.asyncio
async def test_approved_task_executes_writes_and_succeeds(seeded_db):
    task_id = await _approved_task("exec-success")
    fake = FakeToolClient()

    result = await _run(task_id, fake)

    assert result.status == "succeeded"
    assert result.verified is True
    assert result.compensated == []
    assert result.failed == []

    writes = [(name, args) for name, args in fake.calls if name in WRITE_TOOLS]
    assert len(writes) == 8
    assert sum(1 for _, args in writes if args["dry_run"] is True) == 4
    assert sum(1 for _, args in writes if args["dry_run"] is False) == 4
    assert not [name for name, _ in fake.calls if name in COMPENSATION_TOOLS]
    plan = (await _task(task_id)).plan
    expected_keys = {
        f"{task_id}:{node['node_id']}"
        for node in plan["nodes"]
        if node["action"] in {"split_order", "change_address"}
    }
    assert {args["idempotency_key"] for _, args in writes} == expected_keys
    for _, args in writes:
        assert args["task_id"] == str(task_id)

    assert (await _order("O1001")).status == "split"
    assert (await _order("O1004")).status == "split"
    assert (await _order("O1006")).status == "split"
    assert (await _order("O1002")).address_detail == "上海市浦东新区世纪大道100号"
    assert (await _inventory("SKU-001")).available == 98
    assert (await _inventory("SKU-001")).reserved == 2

    task = await _task(task_id)
    assert task.status == "succeeded"
    assert task.result is not None
    assert task.result["status"] == "succeeded"
    assert task.result["verified"] is True

    steps = await _steps(task_id)
    assert {step.node_id for step in steps} == {
        node["node_id"] for node in task.plan["nodes"]
    }
    plan_actions = {node["node_id"]: node["action"] for node in task.plan["nodes"]}
    for step in steps:
        if plan_actions[step.node_id] in {"split_order", "change_address"}:
            assert step.status == "succeeded"
            assert step.output is not None
            assert step.started_at is not None
            assert step.finished_at is not None
        else:
            assert step.status == "skipped"


@pytest.mark.asyncio
async def test_pending_approvals_return_awaiting_and_write_nothing(seeded_db):
    async with _client() as client:
        task_id = await _create_task(client, "exec-pending")

    fake = FakeToolClient()
    result = await _run(task_id, fake)

    assert result.status == "awaiting_approval"
    assert result.reason
    assert fake.calls == []
    assert await _steps(task_id) == []
    assert (await _task(task_id)).status == "awaiting_approval"
    assert await _order("O1001") is not None
    assert (await _order("O1001")).status == "pending_shipment"


@pytest.mark.asyncio
async def test_dry_run_failure_aborts_before_any_write(seeded_db):
    task_id = await _approved_task("exec-dry-run-failure")
    plan = (await _task(task_id)).plan
    split_node = next(
        node for node in plan["nodes"] if node["action"] == "split_order"
    )
    fake = FakeToolClient(
        fail_dry_run_keys={f"{task_id}:{split_node['node_id']}"}
    )

    result = await _run(task_id, fake)

    assert result.status == "failed"
    assert split_node["node_id"] in result.failed
    assert [
        (name, args)
        for name, args in fake.calls
        if args.get("dry_run") is False
    ] == []

    assert (await _task(task_id)).status == "failed"
    assert (await _order("O1001")).status == "pending_shipment"
    assert (await _order("O1002")).address_detail == ""
    assert (await _inventory("SKU-001")).available == 100

    statuses = {step.node_id: step.status for step in await _steps(task_id)}
    assert set(statuses) == {node["node_id"] for node in plan["nodes"]}
    assert statuses[split_node["node_id"]] == "failed"
    for node in plan["nodes"]:
        if node["action"] in {"split_order", "change_address"}:
            if node["node_id"] != split_node["node_id"]:
                assert statuses[node["node_id"]] == "skipped"


@pytest.mark.asyncio
async def test_tenant_b_executor_cannot_start_tenant_a_task(seeded_db):
    task_id = await _approved_task("exec-tenant-isolation")
    fake = FakeToolClient()

    result = await _run(task_id, fake, tenant_id=TENANT_B)

    assert result.status == "failed"
    assert "not found" in result.reason
    assert fake.calls == []
    assert await _steps(task_id) == []
    assert (await _task(task_id)).status == "running"
    assert (await _order("O1001")).status == "pending_shipment"


@pytest.mark.asyncio
async def test_rejected_approvals_skip_writes_and_partially_succeed(seeded_db):
    async with _client() as client:
        task_id = await _create_task(client, "exec-rejected")
    assert await _decide(task_id, "reject") == "running"

    fake = FakeToolClient()
    result = await _run(task_id, fake)

    assert result.status == "partially_succeeded"
    assert fake.calls == []
    assert (await _task(task_id)).status == "partially_succeeded"
    assert (await _order("O1001")).status == "pending_shipment"
    assert (await _order("O1002")).address_detail == ""
    assert (await _inventory("SKU-001")).available == 100
    assert (await _inventory("SKU-001")).reserved == 0

    task = await _task(task_id)
    plan_actions = {node["node_id"]: node["action"] for node in task.plan["nodes"]}
    steps = await _steps(task_id)
    assert {step.node_id for step in steps} == set(plan_actions)
    assert {
        step.node_id
        for step in steps
        if plan_actions[step.node_id] in {"split_order", "change_address"}
    } == set(result.skipped)


@pytest.mark.asyncio
async def test_mixed_approvals_execute_only_approved_nodes(seeded_db):
    async with _client() as client:
        task_id = await _create_task(client, "exec-mixed")

    approvals = await _approvals(task_id)
    address = next(row for row in approvals if row.action == "change_address")
    async with _client() as client:
        approved = await client.post(
            f"{TASK_URL}/{task_id}/approve",
            headers=_auth(),
            json={"order_id": str(address.order_id)},
        )
        assert approved.status_code == 200
        for approval in approvals:
            if approval.id == address.id:
                continue
            rejected = await client.post(
                f"{TASK_URL}/{task_id}/reject",
                headers=_auth(),
                json={"order_id": str(approval.order_id)},
            )
            assert rejected.status_code == 200
        assert rejected.json()["status"] == "running"

    fake = FakeToolClient()
    result = await _run(task_id, fake)

    assert result.status == "partially_succeeded"
    assert {name for name, _ in fake.calls} == {"order_change_address"}
    assert len(result.skipped) == 3
    assert (await _task(task_id)).status == "partially_succeeded"

    assert (await _order("O1002")).address_detail == "上海市浦东新区世纪大道100号"
    assert (await _order("O1001")).status == "pending_shipment"
    assert (await _order("O1004")).status == "pending_shipment"
    assert (await _order("O1006")).status == "pending_shipment"
    assert (await _inventory("SKU-001")).available == 100

    task = await _task(task_id)
    statuses = {step.node_id: step.status for step in await _steps(task_id)}
    for node in task.plan["nodes"]:
        expected = (
            "succeeded" if node["action"] == "change_address" else "skipped"
        )
        assert statuses[node["node_id"]] == expected


@pytest.mark.asyncio
async def test_verifier_failure_compensates_all_completed_writes(seeded_db):
    task_id = await _approved_task("exec-compensate")
    fake = FakeToolClient()

    result = await _run(task_id, fake, verifier=FailingVerifier())

    assert result.status == "partially_succeeded"
    assert result.verified is False
    assert len(result.compensated) == 4

    executed = [
        (name, args["order_id"])
        for name, args in fake.calls
        if name in WRITE_TOOLS and args["dry_run"] is False
    ]
    expected_compensation = [
        ("order_revert_split" if name == "order_split" else "order_revert_address", oid)
        for name, oid in reversed(executed)
    ]
    compensation_calls = [
        (name, args["order_id"])
        for name, args in fake.calls
        if name in COMPENSATION_TOOLS
    ]
    assert compensation_calls == expected_compensation
    assert all(
        args["idempotency_key"].endswith(":compensate")
        for name, args in fake.calls
        if name in COMPENSATION_TOOLS
    )

    assert (await _order("O1001")).status == "pending_shipment"
    assert (await _order("O1004")).status == "pending_shipment"
    assert (await _order("O1006")).status == "pending_shipment"
    assert (await _order("O1002")).address_detail == ""
    assert {shipment.status for shipment in await _shipments(ORDER_O1001)} == {
        "cancelled"
    }
    assert (await _inventory("SKU-001")).available == 100
    assert (await _inventory("SKU-001")).reserved == 0
    assert (await _inventory("SKU-002")).reserved == 0
    assert (await _inventory("SKU-004")).reserved == 0
    assert (await _inventory("SKU-006")).reserved == 0

    assert (await _task(task_id)).status == "partially_succeeded"
    steps = await _steps(task_id)
    compensated = [step for step in steps if step.status == "compensated"]
    assert len(compensated) == 4
    assert all(step.output["compensation"] for step in compensated)


@pytest.mark.asyncio
async def test_repeated_execution_skips_succeeded_steps_without_tool_calls(seeded_db):
    task_id = await _approved_task("exec-repeat")
    fake = FakeToolClient()

    first = await _run(task_id, fake)
    assert first.status == "succeeded"
    first_call_count = len(fake.calls)
    first_steps = await _steps(task_id)
    assert first_call_count == 8

    second = await _run(task_id, fake)

    assert second.status == "succeeded"
    assert len(fake.calls) == first_call_count
    assert (await _task(task_id)).status == "succeeded"
    second_steps = await _steps(task_id)
    assert [(step.node_id, step.status) for step in second_steps] == [
        (step.node_id, step.status) for step in first_steps
    ]
    assert all(
        step.status in {"succeeded", "skipped"}
        for step in second_steps
    )


@pytest.mark.asyncio
async def test_compensation_failure_marks_task_partially_compensated(seeded_db):
    task_id = await _approved_task("exec-compensation-failure")
    fake = FakeToolClient(fail_on={"order_revert_split"})

    result = await _run(task_id, fake, verifier=FailingVerifier())

    assert result.status == "partially_compensated"
    assert result.verified is False
    assert result.failed_compensations
    assert len(result.failed_compensations) == 3
    assert (await _task(task_id)).status == "partially_compensated"

    assert (await _order("O1002")).address_detail == ""
    assert (await _order("O1001")).status == "split"
    assert (await _order("O1004")).status == "split"
    assert (await _order("O1006")).status == "split"

    steps = await _steps(task_id)
    statuses = {step.node_id: step.status for step in steps}
    task = await _task(task_id)
    for node in task.plan["nodes"]:
        if node["action"] == "split_order":
            assert statuses[node["node_id"]] == "failed"
        elif node["action"] == "change_address":
            assert statuses[node["node_id"]] == "compensated"


@pytest.mark.asyncio
async def test_resume_reenters_execution_after_approval(seeded_db):
    async with _client() as client:
        task_id = await _create_task(client, "exec-resume")
    assert await _decide(task_id) == "running"

    fake = FakeToolClient()
    async with SessionLocal() as session:
        executor = TaskExecutor(session, fake, TENANT_A)
        result = await executor.resume(task_id, approved=True)

    assert result.status == "succeeded"
    assert (await _task(task_id)).status == "succeeded"
    assert (await _order("O1001")).status == "split"


@pytest.mark.asyncio
async def test_resume_does_not_execute_write_without_approval_row(seeded_db):
    task_id = uuid4()
    node_id = "orphan-split"
    plan = {
        "nodes": [
            {
                "node_id": node_id,
                "order_id": str(ORDER_O1001),
                "action": "split_order",
                "requires_approval": True,
                "params": {"shipments": _shipments_o1001()},
            }
        ]
    }
    async with SessionLocal() as session:
        session.add(
            TaskRun(
                id=task_id,
                tenant_id=TENANT_A,
                user_id=OPERATOR_A,
                task_type="order_exception",
                instruction="no approval row fixture",
                status="running",
                plan=plan,
            )
        )
        await session.commit()

    fake = FakeToolClient()
    async with SessionLocal() as session:
        executor = TaskExecutor(session, fake, TENANT_A)
        result = await executor.resume(task_id, approved=True)

    assert result.status == "partially_succeeded"
    assert node_id in result.skipped
    assert fake.calls == []
    assert (await _order("O1001")).status == "pending_shipment"
    assert (await _task(task_id)).status == "partially_succeeded"
    statuses = {step.node_id: step.status for step in await _steps(task_id)}
    assert statuses == {node_id: "skipped"}


async def _split_for_verifier(
    key: str = "verifier-split",
) -> tuple[UUID, dict[str, Any], dict[str, Any]]:
    task_id = uuid4()
    async with SessionLocal() as session:
        session.add(
            TaskRun(
                id=task_id,
                tenant_id=TENANT_A,
                user_id=OPERATOR_A,
                task_type="order_exception",
                instruction="verifier fixture",
                status="running",
            )
        )
        await session.commit()
        response = await split_order(
            session,
            TENANT_A,
            ORDER_O1001,
            _shipments_o1001(),
            key,
            actor_id=OPERATOR_A,
            task_id=task_id,
        )
    plan = {
        "nodes": [
            {
                "node_id": "split-node",
                "order_id": str(ORDER_O1001),
                "action": "split_order",
                "params": {"shipments": _shipments_o1001()},
            }
        ]
    }
    return task_id, plan, {"split-node": response}


async def _verify(task_id: UUID, plan: dict[str, Any], results: dict[str, Any]):
    async with SessionLocal() as session:
        task = await session.get(TaskRun, task_id)
        assert task is not None
        verifier = Verifier(session)
        return await verifier.verify(task, plan, results)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["quantity", "sku"])
async def test_verifier_rejects_shipment_line_mismatch(seeded_db, mutation):
    task_id, plan, results = await _split_for_verifier(
        f"verifier-mismatch-{mutation}"
    )

    baseline = await _verify(task_id, plan, results)
    assert baseline.passed is True

    async with SessionLocal() as session:
        line = await session.scalar(
            select(ShipmentLine).where(
                ShipmentLine.tenant_id == TENANT_A,
                ShipmentLine.sku_id == SKU_IDS["SKU-001"],
            )
        )
        assert line is not None
        if mutation == "quantity":
            line.qty = line.qty - 1
            await session.commit()
        else:
            session.add(
                ShipmentLine(
                    tenant_id=TENANT_A,
                    shipment_id=line.shipment_id,
                    sku_id=SKU_IDS["SKU-004"],
                    qty=1,
                )
            )
            await session.commit()

    result = await _verify(task_id, plan, results)
    assert result.passed is False
    assert "shipment" in result.reason


@pytest.mark.asyncio
async def test_verifier_accepts_per_sku_totals_across_shipment_lines(seeded_db):
    order_id = uuid5(NAMESPACE_DNS, "opsconductor.order-O1100")
    task_id = uuid4()
    shipments = [
        {
            "warehouse_id": str(WAREHOUSE_EAST),
            "lines": [{"sku_id": str(SKU_IDS["SKU-005"]), "qty": 2}],
        },
        {
            "warehouse_id": str(WAREHOUSE_EAST),
            "lines": [{"sku_id": str(SKU_IDS["SKU-005"]), "qty": 1}],
        },
    ]
    async with SessionLocal() as session:
        session.add(
            TaskRun(
                id=task_id,
                tenant_id=TENANT_A,
                user_id=OPERATOR_A,
                task_type="order_exception",
                instruction="per-SKU totals fixture",
                status="running",
            )
        )
        session.add(
            SalesOrder(
                id=order_id,
                tenant_id=TENANT_A,
                shop_id=SHOP_A,
                warehouse_id=WAREHOUSE_EAST,
                order_no="O1100",
                status="pending_shipment",
                receiver_name="张三",
                phone="13800138000",
                province="上海市",
                city="上海市",
                district="浦东新区",
                address_detail="世纪大道 100 号",
            )
        )
        await session.flush()
        session.add(
            OrderLine(
                tenant_id=TENANT_A,
                order_id=order_id,
                sku_id=SKU_IDS["SKU-005"],
                qty=3,
            )
        )
        await session.commit()
        response = await split_order(
            session,
            TENANT_A,
            order_id,
            shipments,
            "verifier-sku-totals",
            actor_id=OPERATOR_A,
            task_id=task_id,
        )

    plan = {
        "nodes": [
            {
                "node_id": "split-node",
                "order_id": str(order_id),
                "action": "split_order",
                "params": {"shipments": shipments},
            }
        ]
    }
    result = await _verify(task_id, plan, {"split-node": response})
    assert result.passed is True

    async with SessionLocal() as session:
        order_shipments = list(
            (
                await session.scalars(
                    select(Shipment).where(
                        Shipment.tenant_id == TENANT_A,
                        Shipment.order_id == order_id,
                    )
                )
            ).all()
        )
        assert len(order_shipments) == 2
        lines = list(
            (
                await session.scalars(
                    select(ShipmentLine).where(
                        ShipmentLine.tenant_id == TENANT_A,
                        ShipmentLine.shipment_id.in_(
                            [shipment.id for shipment in order_shipments]
                        ),
                    )
                )
            ).all()
        )
        assert sorted(line.qty for line in lines) == [1, 2]
        assert {line.sku_id for line in lines} == {SKU_IDS["SKU-005"]}


@pytest.mark.asyncio
async def test_verifier_rejects_negative_inventory_and_missing_audit(seeded_db):
    task_id, plan, results = await _split_for_verifier("verifier-guards")

    async with SessionLocal() as session:
        inventory = await session.scalar(
            select(Inventory).where(
                Inventory.tenant_id == TENANT_A,
                Inventory.sku_id == SKU_IDS["SKU-001"],
                Inventory.warehouse_id == WAREHOUSE_EAST,
            )
        )
        assert inventory is not None
        inventory.available = -1
        await session.commit()

    negative = await _verify(task_id, plan, results)
    assert negative.passed is False
    assert "inventory" in negative.reason

    async with SessionLocal() as session:
        inventory = await session.scalar(
            select(Inventory).where(
                Inventory.tenant_id == TENANT_A,
                Inventory.sku_id == SKU_IDS["SKU-001"],
                Inventory.warehouse_id == WAREHOUSE_EAST,
            )
        )
        assert inventory is not None
        inventory.available = 98
        await session.execute(
            delete(AuditLog).where(
                AuditLog.tenant_id == TENANT_A,
                AuditLog.task_id == task_id,
                AuditLog.action == "order.split",
            )
        )
        await session.commit()

    missing = await _verify(task_id, plan, results)
    assert missing.passed is False
    assert "audit" in missing.reason


@pytest.mark.asyncio
async def test_verifier_checks_relocated_address(seeded_db):
    task_id = uuid4()
    async with SessionLocal() as session:
        session.add(
            TaskRun(
                id=task_id,
                tenant_id=TENANT_A,
                user_id=OPERATOR_A,
                task_type="order_exception",
                instruction="address verifier fixture",
                status="running",
            )
        )
        await session.commit()
        response = await ErpToolService(session).order_change_address(
            TENANT_A,
            ORDER_O1002,
            "新地址 88 号",
            "verifier-address",
            actor_id=OPERATOR_A,
            task_id=task_id,
        )

    plan = {
        "nodes": [
            {
                "node_id": "address-node",
                "order_id": str(ORDER_O1002),
                "action": "change_address",
                "params": {"address": "新地址 88 号"},
            }
        ]
    }
    results = {"address-node": response}

    passed = await _verify(task_id, plan, results)
    assert passed.passed is True

    async with SessionLocal() as session:
        await session.execute(
            update(SalesOrder)
            .where(SalesOrder.id == ORDER_O1002)
            .values(address_detail="别的地址")
        )
        await session.commit()

    mismatch = await _verify(task_id, plan, results)
    assert mismatch.passed is False
    assert "address" in mismatch.reason
