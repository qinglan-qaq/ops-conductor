"""Tenant-scoped read-only queries for ERP entities."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opsconductor.domain.models import Inventory, OrderLine, SalesOrder, Shipment, Warehouse


async def list_overdue_orders(
    session: AsyncSession,
    tenant_id: UUID,
    warehouse: str | None = None,
    cutoff: datetime | None = None,
) -> list[SalesOrder]:
    stmt = select(SalesOrder).where(
        SalesOrder.tenant_id == tenant_id,
        SalesOrder.status == "pending_shipment",
    )
    if warehouse is not None:
        stmt = stmt.join(Warehouse, Warehouse.id == SalesOrder.warehouse_id).where(
            Warehouse.tenant_id == tenant_id,
            Warehouse.name == warehouse,
        )
    if cutoff is not None:
        stmt = stmt.where(SalesOrder.created_at < cutoff)
    return list((await session.scalars(stmt.order_by(SalesOrder.created_at))).all())


async def get_order(session: AsyncSession, tenant_id: UUID, order_id: UUID) -> SalesOrder | None:
    return await session.scalar(
        select(SalesOrder).where(SalesOrder.tenant_id == tenant_id, SalesOrder.id == order_id)
    )


async def list_order_lines(
    session: AsyncSession, tenant_id: UUID, order_id: UUID
) -> list[OrderLine]:
    return list(
        (
            await session.scalars(
                select(OrderLine).where(
                    OrderLine.tenant_id == tenant_id, OrderLine.order_id == order_id
                )
            )
        ).all()
    )


async def get_inventory(
    session: AsyncSession, tenant_id: UUID, sku_id: UUID, warehouse_id: UUID
) -> Inventory | None:
    return await session.scalar(
        select(Inventory).where(
            Inventory.tenant_id == tenant_id,
            Inventory.sku_id == sku_id,
            Inventory.warehouse_id == warehouse_id,
        )
    )


async def list_shipments(
    session: AsyncSession, tenant_id: UUID, order_id: UUID
) -> list[Shipment]:
    return list(
        (
            await session.scalars(
                select(Shipment).where(
                    Shipment.tenant_id == tenant_id, Shipment.order_id == order_id
                )
            )
        ).all()
    )
