import pytest
from sqlalchemy import func, select

from opsconductor.db import SessionLocal
from opsconductor.domain.models import (
    Inventory,
    OrderLine,
    Product,
    SalesOrder,
    Shipment,
    ShipmentLine,
    Shop,
    Sku,
    Tenant,
    User,
    Warehouse,
)
from opsconductor.domain.seed import SHOP_A, SHOP_B, SKU_IDS, TENANT_A, TENANT_B, seed


@pytest.mark.asyncio
async def test_seed_is_idempotent(seeded_db):
    async with SessionLocal() as session:
        await seed(session)
        count = await session.scalar(select(func.count()).select_from(Tenant))
        assert count == 2
        orders = (await session.scalars(select(SalesOrder))).all()
        assert any(o.order_no == "O1001" for o in orders)


@pytest.mark.asyncio
async def test_seed_twice_does_not_duplicate_rows(seeded_db):
    async with SessionLocal() as session:
        await seed(session)
        expected = {
            Tenant: 2,
            User: 4,
            Shop: 2,
            Warehouse: 1,
            Product: 10,
            Sku: 10,
            Inventory: 10,
            SalesOrder: 7,
            OrderLine: 7,
            Shipment: 1,
            ShipmentLine: 1,
        }
        for model, expected_count in expected.items():
            count = await session.scalar(select(func.count()).select_from(model))
            assert count == expected_count, model.__tablename__


@pytest.mark.asyncio
async def test_seed_tenant_isolation_and_order_constraints(seeded_db):
    async with SessionLocal() as session:
        orders = {
            order.order_no: order
            for order in (await session.scalars(select(SalesOrder))).all()
        }
        for order_no in ("O1001", "O1002", "O1003", "O1004", "O1005", "O1006"):
            assert orders[order_no].tenant_id == TENANT_A
            assert orders[order_no].shop_id == SHOP_A
        assert orders["O2001"].tenant_id == TENANT_B
        assert orders["O2001"].shop_id == SHOP_B

        assert orders["O1002"].address_detail == ""
        assert orders["O1005"].status == "split"

        low_stock = await session.scalar(
            select(Inventory).where(Inventory.sku_id == SKU_IDS["SKU-003"])
        )
        assert low_stock is not None
        assert low_stock.available == 0

        shipment = await session.scalar(
            select(Shipment).where(Shipment.order_id == orders["O1005"].id)
        )
        assert shipment is not None
        shipment_line = await session.scalar(
            select(ShipmentLine).where(ShipmentLine.shipment_id == shipment.id)
        )
        assert shipment_line is not None
        assert shipment_line.sku_id == SKU_IDS["SKU-005"]
        assert shipment_line.qty == 1

        tenant_b_lines = (
            await session.scalars(
                select(OrderLine)
                .join(SalesOrder, OrderLine.order_id == SalesOrder.id)
                .where(SalesOrder.tenant_id == TENANT_B)
            )
        ).all()
        assert tenant_b_lines == []
