import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from opsconductor.db import SessionLocal
from opsconductor.domain.address import normalized_address
from opsconductor.domain.models import SalesOrder
from opsconductor.domain.seed import SKU_IDS, TENANT_A, WAREHOUSE_EAST
from opsconductor.llm.gateway import StubChatModel
from opsconductor.orchestrator.planner import (
    LLMPlanner,
    PlanGenerationError,
    TemplatePlanner,
)
from opsconductor.schemas import PlanNode


def _task(**overrides):
    values = {
        "id": uuid4(),
        "tenant_id": TENANT_A,
        "instruction": "处理今天华东仓超时未发货的订单",
        "warehouse": "east",
        "cutoff": datetime(2026, 11, 4, tzinfo=UTC),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _order_id(order_no: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"opsconductor.order-{order_no}")


def _node_for(nodes: list[PlanNode], order_no: str) -> PlanNode | None:
    order_id = _order_id(order_no)
    return next((node for node in nodes if node.order_id == order_id), None)


def _valid_stub_plan(task) -> dict:
    return {
        "summary": "stub plan",
        "nodes": [
            {
                "node_id": "split-o1001",
                "order_id": str(_order_id("O1001")),
                "action": "split_order",
                "params": {
                    "shipments": [
                        {
                            "warehouse_id": str(WAREHOUSE_EAST),
                            "lines": [
                                {"sku_id": str(SKU_IDS["SKU-001"]), "qty": 2},
                                {"sku_id": str(SKU_IDS["SKU-002"]), "qty": 1},
                            ],
                        }
                    ]
                },
            }
        ],
    }


class _DecodeFailureModel:
    """Model double whose first response is invalid JSON bytes."""

    def __init__(self, valid_response: dict):
        self.valid_response = valid_response
        self.calls = 0

    async def complete_json(self, *, system: str, user: str) -> dict:
        self.calls += 1
        if self.calls == 1:
            raise json.JSONDecodeError("Expecting value", "", 0)
        return self.valid_response


@pytest.mark.asyncio
async def test_template_planner_blocks_stockout_and_plans_split(seeded_db):
    task = _task()
    async with SessionLocal() as session:
        plan = await TemplatePlanner(session).plan(task)

    actions = {node.action for node in plan.nodes}
    assert "split_order" in actions
    assert "block_order" in actions
    assert "change_address" in actions
    assert plan.task_id == str(task.id)


@pytest.mark.asyncio
async def test_template_planner_actions_for_seeded_orders(seeded_db):
    async with SessionLocal() as session:
        plan = await TemplatePlanner(session).plan(_task())

    split_node = _node_for(plan.nodes, "O1001")
    assert split_node is not None
    assert split_node.action == "split_order"
    assert len(split_node.params["shipments"]) == 2
    assert all(
        shipment["warehouse_id"] == str(WAREHOUSE_EAST)
        for shipment in split_node.params["shipments"]
    )
    shipped_lines = {
        (line["sku_id"], line["qty"])
        for shipment in split_node.params["shipments"]
        for line in shipment["lines"]
    }
    assert shipped_lines == {
        (str(SKU_IDS["SKU-001"]), 2),
        (str(SKU_IDS["SKU-002"]), 1),
    }

    address_node = _node_for(plan.nodes, "O1002")
    assert address_node is not None
    assert address_node.action == "change_address"
    assert address_node.params == {"address": "上海市浦东新区世纪大道100号"}

    stockout_node = _node_for(plan.nodes, "O1003")
    assert stockout_node is not None
    assert stockout_node.action == "block_order"
    assert stockout_node.reason == "insufficient_stock"
    shortages = stockout_node.evidence["shortages"]
    assert shortages == [
        {
            "sku_id": str(SKU_IDS["SKU-003"]),
            "required": 5,
            "available": 0,
        }
    ]

    assert _node_for(plan.nodes, "O1004").action == "split_order"
    assert _node_for(plan.nodes, "O1006").action == "split_order"


@pytest.mark.asyncio
async def test_template_planner_skips_already_split_order(seeded_db):
    async with SessionLocal() as session:
        plan = await TemplatePlanner(session).plan(_task())
        order = await session.scalar(
            select(SalesOrder).where(
                SalesOrder.tenant_id == TENANT_A,
                SalesOrder.order_no == "O1005",
            )
        )
        assert order is not None
        assert order.status == "split"

    assert _node_for(plan.nodes, "O1005") is None


@pytest.mark.asyncio
async def test_template_planner_blocks_order_that_already_has_shipment(seeded_db):
    async with SessionLocal() as session:
        order = await session.scalar(
            select(SalesOrder).where(
                SalesOrder.tenant_id == TENANT_A,
                SalesOrder.order_no == "O1005",
            )
        )
        assert order is not None
        # Simulate a stale status: an order that already has a shipment must still
        # never be split twice.
        order.status = "pending_shipment"
        await session.commit()

    async with SessionLocal() as session:
        plan = await TemplatePlanner(session).plan(_task())

    node = _node_for(plan.nodes, "O1005")
    assert node is not None
    assert node.action == "block_order"
    assert node.reason == "already_split"


def test_normalized_address_fills_missing_detail():
    order = SimpleNamespace(city="上海市", district="浦东新区", address_detail="")
    assert normalized_address(order) == "上海市浦东新区世纪大道100号"


def test_normalized_address_keeps_existing_detail():
    order = SimpleNamespace(city="上海市", district="浦东新区", address_detail=" 世纪大道 100 号 ")
    assert normalized_address(order) == "世纪大道 100 号"


@pytest.mark.asyncio
async def test_stub_chat_model_returns_queued_json():
    model = StubChatModel([{"ok": True}])
    assert await model.complete_json(system="s", user="u") == {"ok": True}
    with pytest.raises(RuntimeError, match="no stub response left"):
        await model.complete_json(system="s", user="u")


@pytest.mark.asyncio
async def test_llm_planner_accepts_valid_stub_response(seeded_db):
    task = _task()
    model = StubChatModel([_valid_stub_plan(task)])

    async with SessionLocal() as session:
        plan = await LLMPlanner(model, session).plan(task)

    assert plan.task_id == str(task.id)
    assert plan.summary == "stub plan"
    assert len(plan.nodes) == 1
    assert plan.nodes[0].order_id == _order_id("O1001")
    shipment = plan.nodes[0].params["shipments"][0]
    assert shipment["warehouse_id"] == str(WAREHOUSE_EAST)
    assert {(line["sku_id"], line["qty"]) for line in shipment["lines"]} == {
        (str(SKU_IDS["SKU-001"]), 2),
        (str(SKU_IDS["SKU-002"]), 1),
    }
    assert model.responses == []


@pytest.mark.asyncio
async def test_llm_planner_repairs_schema_invalid_response(seeded_db):
    task = _task()
    model = StubChatModel(
        [
            {
                "task_id": str(task.id),
                "nodes": [{"node_id": "a", "action": "drop_table"}],
            },
            _valid_stub_plan(task),
        ]
    )

    async with SessionLocal() as session:
        plan = await LLMPlanner(model, session).plan(task)

    assert [node.action for node in plan.nodes] == ["split_order"]
    assert model.responses == []


@pytest.mark.asyncio
async def test_llm_planner_repairs_semantically_invalid_response(seeded_db):
    task = _task()
    model = StubChatModel(
        [
            {
                "task_id": str(task.id),
                "nodes": [
                    {"node_id": "a", "action": "verify", "depends_on": ["b"]},
                    {"node_id": "b", "action": "verify", "depends_on": ["a"]},
                ],
            },
            _valid_stub_plan(task),
        ]
    )

    async with SessionLocal() as session:
        plan = await LLMPlanner(model, session).plan(task)

    assert [node.node_id for node in plan.nodes] == ["split-o1001"]
    assert model.responses == []


@pytest.mark.asyncio
async def test_llm_planner_raises_when_repair_also_invalid(seeded_db):
    task = _task()
    invalid = {
        "task_id": str(task.id),
        "nodes": [{"node_id": "a", "action": "drop_table"}],
    }
    model = StubChatModel([invalid, dict(invalid)])

    async with SessionLocal() as session:
        with pytest.raises(PlanGenerationError, match="invalid plan"):
            await LLMPlanner(model, session).plan(task)

    assert model.responses == []


@pytest.mark.asyncio
async def test_llm_planner_rejects_unknown_order_after_repair(seeded_db):
    task = _task()
    spoofed = _valid_stub_plan(task)
    spoofed["nodes"][0]["order_id"] = str(uuid4())
    repeated = _valid_stub_plan(task)
    repeated["nodes"][0]["order_id"] = spoofed["nodes"][0]["order_id"]
    model = StubChatModel([spoofed, repeated])

    async with SessionLocal() as session:
        with pytest.raises(PlanGenerationError, match="unknown order"):
            await LLMPlanner(model, session).plan(task)

    assert model.responses == []


@pytest.mark.asyncio
async def test_llm_planner_repairs_empty_shipments(seeded_db):
    task = _task()
    empty = _valid_stub_plan(task)
    empty["nodes"][0]["params"] = {"shipments": []}
    model = StubChatModel([empty, _valid_stub_plan(task)])

    async with SessionLocal() as session:
        plan = await LLMPlanner(model, session).plan(task)

    assert [node.node_id for node in plan.nodes] == ["split-o1001"]
    assert plan.nodes[0].params["shipments"][0]["lines"][0]["qty"] == 2
    assert model.responses == []


@pytest.mark.asyncio
async def test_llm_planner_repairs_empty_address(seeded_db):
    task = _task()
    invalid = {
        "summary": "bad address",
        "nodes": [
            {
                "node_id": "change-address-o1002",
                "order_id": str(_order_id("O1002")),
                "action": "change_address",
                "params": {"address": "   "},
            }
        ],
    }
    model = StubChatModel([invalid, _valid_stub_plan(task)])

    async with SessionLocal() as session:
        plan = await LLMPlanner(model, session).plan(task)

    assert plan.summary == "stub plan"
    assert [node.node_id for node in plan.nodes] == ["split-o1001"]
    assert model.responses == []


@pytest.mark.asyncio
async def test_llm_planner_repairs_json_decode_failure(seeded_db):
    task = _task()
    model = _DecodeFailureModel(_valid_stub_plan(task))

    async with SessionLocal() as session:
        plan = await LLMPlanner(model, session).plan(task)

    assert model.calls == 2
    assert [node.node_id for node in plan.nodes] == ["split-o1001"]
