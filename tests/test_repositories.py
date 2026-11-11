import uuid
from datetime import UTC, datetime

import pytest

from opsconductor.db import SessionLocal
from opsconductor.domain import repositories
from opsconductor.domain.seed import SKU_IDS, TENANT_A, TENANT_B, WAREHOUSE_EAST


def _order_id(order_no: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"opsconductor.order-{order_no}")


@pytest.mark.asyncio
async def test_list_overdue_orders_is_tenant_scoped(seeded_db):
    async with SessionLocal() as session:
        orders = await repositories.list_overdue_orders(session, TENANT_A, warehouse="east")
        assert {o.order_no for o in orders} >= {"O1001", "O1002", "O1003", "O1004"}
        assert all(o.tenant_id == TENANT_A for o in orders)


@pytest.mark.asyncio
async def test_list_overdue_orders_filters_status_and_tenant(seeded_db):
    async with SessionLocal() as session:
        tenant_a_orders = await repositories.list_overdue_orders(session, TENANT_A)
        assert "O1005" not in {o.order_no for o in tenant_a_orders}
        assert "O2001" not in {o.order_no for o in tenant_a_orders}

        tenant_b_orders = await repositories.list_overdue_orders(session, TENANT_B)
        assert [o.order_no for o in tenant_b_orders] == ["O2001"]


@pytest.mark.asyncio
async def test_list_overdue_orders_filters_warehouse_and_cutoff(seeded_db):
    async with SessionLocal() as session:
        assert await repositories.list_overdue_orders(session, TENANT_A, warehouse="west") == []
        assert (
            await repositories.list_overdue_orders(
                session, TENANT_A, cutoff=datetime(2026, 10, 31, tzinfo=UTC)
            )
            == []
        )
        orders = await repositories.list_overdue_orders(
            session, TENANT_A, cutoff=datetime(2026, 11, 2, tzinfo=UTC)
        )
        assert {o.order_no for o in orders} >= {"O1001", "O1002", "O1003", "O1004", "O1006"}


@pytest.mark.asyncio
async def test_get_order_is_tenant_scoped(seeded_db):
    async with SessionLocal() as session:
        order = await repositories.get_order(session, TENANT_A, _order_id("O1001"))
        assert order is not None
        assert order.order_no == "O1001"
        assert await repositories.get_order(session, TENANT_B, _order_id("O1001")) is None


@pytest.mark.asyncio
async def test_list_order_lines(seeded_db):
    async with SessionLocal() as session:
        lines = await repositories.list_order_lines(session, TENANT_A, _order_id("O1001"))
        assert {(str(line.sku_id), line.qty) for line in lines} == {
            (str(SKU_IDS["SKU-001"]), 2),
            (str(SKU_IDS["SKU-002"]), 1),
        }
        assert all(line.tenant_id == TENANT_A for line in lines)
        assert (
            await repositories.list_order_lines(session, TENANT_B, _order_id("O1001")) == []
        )


@pytest.mark.asyncio
async def test_get_inventory_is_tenant_scoped(seeded_db):
    async with SessionLocal() as session:
        inventory = await repositories.get_inventory(
            session, TENANT_A, SKU_IDS["SKU-003"], WAREHOUSE_EAST
        )
        assert inventory is not None
        assert inventory.available == 0
        assert (
            await repositories.get_inventory(
                session, TENANT_B, SKU_IDS["SKU-003"], WAREHOUSE_EAST
            )
            is None
        )


@pytest.mark.asyncio
async def test_list_shipments(seeded_db):
    async with SessionLocal() as session:
        shipments = await repositories.list_shipments(session, TENANT_A, _order_id("O1005"))
        assert len(shipments) == 1
        assert shipments[0].status == "created"
        assert shipments[0].tenant_id == TENANT_A
        assert await repositories.list_shipments(session, TENANT_A, _order_id("O1001")) == []
        assert (
            await repositories.list_shipments(session, TENANT_B, _order_id("O1005")) == []
        )
