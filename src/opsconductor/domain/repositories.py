"""Tenant-scoped read-only queries for ERP entities.

Every function requires a ``tenant_id`` and filters on it, so a UUID belonging
to another tenant is indistinguishable from a missing row. Queries only read:
they never commit, roll back, or flush. Callers own the session and its
transaction, and returned ORM objects stay bound to that session until it is
closed.
"""

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
    """List pending shipments, optionally narrowed by warehouse and age.

    Args:
        session: Caller-owned session used for the read.
        tenant_id: Tenant whose orders are returned; never omitted.
        warehouse: Exact warehouse name within the tenant. ``None`` keeps
            orders from every warehouse.
        cutoff: Return only orders created strictly before this timestamp.
            ``None`` keeps orders of any age.

    Returns:
        Matching ``SalesOrder`` rows ordered oldest first by ``created_at``;
        an empty list when nothing matches.

    Note:
        Pass a timezone-aware ``cutoff`` so the comparison against the
        timezone-aware ``created_at`` column is unambiguous.
    """

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
    """Fetch one order by ID within a tenant.

    Args:
        session: Caller-owned session used for the read.
        tenant_id: Tenant that must own the order.
        order_id: Order UUID; an ID from another tenant yields ``None``.

    Returns:
        The matching order, or ``None`` when it does not exist in the tenant.
    """

    return await session.scalar(
        select(SalesOrder).where(SalesOrder.tenant_id == tenant_id, SalesOrder.id == order_id)
    )


async def list_order_lines(
    session: AsyncSession, tenant_id: UUID, order_id: UUID
) -> list[OrderLine]:
    """List an order's lines within a tenant.

    Args:
        session: Caller-owned session used for the read.
        tenant_id: Tenant that must own both the order and its lines.
        order_id: Order whose lines are returned.

    Returns:
        The order's ``OrderLine`` rows in no guaranteed order; empty when the
        order has no lines or is not in the tenant.
    """

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
    """Fetch the stock row for one SKU and warehouse in a tenant.

    Args:
        session: Caller-owned session used for the read.
        tenant_id: Tenant that must own the inventory row.
        sku_id: SKU whose position is read.
        warehouse_id: Warehouse whose position is read.

    Returns:
        The unique matching row, or ``None`` when that pair has no inventory
        record in this tenant.
    """

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
    """List the shipments created for an order within a tenant.

    Args:
        session: Caller-owned session used for the read.
        tenant_id: Tenant that must own the shipments.
        order_id: Order whose shipments are returned.

    Returns:
        All matching ``Shipment`` rows in no guaranteed order, including
        cancelled ones; empty when the order has not been split.
    """

    return list(
        (
            await session.scalars(
                select(Shipment).where(
                    Shipment.tenant_id == tenant_id, Shipment.order_id == order_id
                )
            )
        ).all()
    )
