import uuid
from contextlib import asynccontextmanager

import pytest

from opsconductor.db import SessionLocal
from opsconductor.domain.seed import SKU_IDS, TENANT_A, TENANT_B, WAREHOUSE_EAST
from opsconductor.tools import client as client_module
from opsconductor.tools.client import ErpToolClient
from opsconductor.tools.service import ErpToolService, address_is_valid


def _order_id(order_no: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"opsconductor.order-{order_no}")


@pytest.mark.asyncio
async def test_order_list_overdue_returns_tool_payload(seeded_db):
    async with SessionLocal() as session:
        orders = await ErpToolService(session).order_list_overdue(TENANT_A, warehouse="east")
    assert {order["order_no"] for order in orders} >= {"O1001", "O1002", "O1003", "O1004"}
    assert all(set(order) == {"id", "order_no", "status"} for order in orders)


@pytest.mark.asyncio
async def test_order_get_includes_address_and_lines(seeded_db):
    async with SessionLocal() as session:
        order = await ErpToolService(session).order_get(TENANT_A, _order_id("O1001"))
    assert order["order_no"] == "O1001"
    assert order["receiver_name"] == "张三"
    assert order["address_detail"] == "世纪大道 100 号"
    assert {(line["sku_id"], line["qty"]) for line in order["lines"]} == {
        (str(SKU_IDS["SKU-001"]), 2),
        (str(SKU_IDS["SKU-002"]), 1),
    }


@pytest.mark.asyncio
async def test_order_get_rejects_other_tenant(seeded_db):
    async with SessionLocal() as session:
        with pytest.raises(ValueError, match="order not found"):
            await ErpToolService(session).order_get(TENANT_B, _order_id("O1001"))


@pytest.mark.asyncio
async def test_inventory_get_returns_stock(seeded_db):
    async with SessionLocal() as session:
        inventory = await ErpToolService(session).inventory_get(
            TENANT_A, SKU_IDS["SKU-003"], WAREHOUSE_EAST
        )
    assert inventory["available"] == 0
    assert inventory["reserved"] == 0
    assert inventory["sku_id"] == str(SKU_IDS["SKU-003"])


@pytest.mark.asyncio
async def test_inventory_get_rejects_other_tenant(seeded_db):
    async with SessionLocal() as session:
        with pytest.raises(ValueError, match="inventory not found"):
            await ErpToolService(session).inventory_get(
                TENANT_B, SKU_IDS["SKU-003"], WAREHOUSE_EAST
            )


@pytest.mark.asyncio
async def test_shipment_list(seeded_db):
    async with SessionLocal() as session:
        shipments = await ErpToolService(session).shipment_list(TENANT_A, _order_id("O1005"))
        assert len(shipments) == 1
        assert shipments[0]["status"] == "created"
        assert await ErpToolService(session).shipment_list(
            TENANT_A, _order_id("O1001")
        ) == []


@pytest.mark.asyncio
async def test_order_get_state(seeded_db):
    async with SessionLocal() as session:
        state = await ErpToolService(session).order_get_state(TENANT_A, _order_id("O1001"))
    assert state == {
        "order_id": str(_order_id("O1001")),
        "status": "pending_shipment",
        "version": 0,
    }


@pytest.mark.asyncio
async def test_address_validate(seeded_db):
    async with SessionLocal() as session:
        service = ErpToolService(session)
        valid = await service.address_validate(_order_id("O1001"), TENANT_A)
        invalid = await service.address_validate(_order_id("O1002"), TENANT_A)
    assert valid == {"valid": True, "order_id": str(_order_id("O1001"))}
    assert invalid == {"valid": False, "order_id": str(_order_id("O1002"))}


def test_address_is_valid_rules():
    class Order:
        receiver_name = "张三"
        phone = "13800138000"
        province = "上海市"
        city = "上海市"
        district = "浦东新区"
        address_detail = "世纪大道 100 号"

    order = Order()
    assert address_is_valid(order) is True
    order.phone = "12345"
    assert address_is_valid(order) is False
    order.phone = "13800138000"
    order.district = ""
    assert address_is_valid(order) is False
    order.district = "浦东新区"
    order.address_detail = "   "
    assert address_is_valid(order) is False


@pytest.mark.asyncio
async def test_erp_tool_client_closes_transport_when_initialize_fails(monkeypatch):
    transport_closed = False
    session_closed = False

    @asynccontextmanager
    async def fake_stdio_client(params):
        nonlocal transport_closed
        try:
            yield object(), object()
        finally:
            transport_closed = True

    class FailingSession:
        def __init__(self, read, write):
            self.read = read
            self.write = write

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            nonlocal session_closed
            session_closed = True

        async def initialize(self):
            raise RuntimeError("initialize failed")

    monkeypatch.setattr(client_module, "stdio_client", fake_stdio_client)
    monkeypatch.setattr(client_module, "ClientSession", FailingSession)

    with pytest.raises(RuntimeError, match="initialize failed"):
        async with ErpToolClient():
            pass

    assert session_closed is True
    assert transport_closed is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mcp_client_calls_read_tools_over_stdio(seeded_db):
    async with ErpToolClient() as client:
        overdue = await client.call(
            "order_list_overdue", {"tenant_id": str(TENANT_A), "warehouse": "east"}
        )
        order = await client.call(
            "order_get", {"tenant_id": str(TENANT_A), "order_id": str(_order_id("O1001"))}
        )
        tenant_b_orders = await client.call(
            "order_list_overdue", {"tenant_id": str(TENANT_B)}
        )
        with pytest.raises(RuntimeError, match="order_get failed"):
            await client.call(
                "order_get",
                {"tenant_id": str(TENANT_B), "order_id": str(_order_id("O1001"))},
            )
    assert {entry["order_no"] for entry in overdue["orders"]} >= {
        "O1001",
        "O1002",
        "O1003",
        "O1004",
    }
    assert order["order_no"] == "O1001"
    assert order["receiver_name"] == "张三"
    assert [entry["order_no"] for entry in tenant_b_orders["orders"]] == ["O2001"]
