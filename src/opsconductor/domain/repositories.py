"""面向 ERP 实体的租户隔离只读查询。

每个函数都要求 ``tenant_id`` 并按其过滤，因此属于其他租户的 UUID 与不存在的
行无法区分。查询只读：从不提交、回滚或 flush。会话及其事务由调用方负责，
返回的 ORM 对象在会话关闭前始终绑定到该会话。
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
    """列出待发货订单，可选按仓库与时间范围收窄。

    Args:
        session: 调用方拥有的会话，用于本次读取。
        tenant_id: 返回其订单的租户；不可省略。
        warehouse: 租户内的精确仓库名称。``None`` 表示保留所有仓库的订单。
        cutoff: 仅返回创建时间严格早于该时间戳的订单。``None`` 表示不限订单
            时间。

    Returns:
        匹配的 ``SalesOrder`` 行，按 ``created_at`` 从旧到新排序；无匹配时返回
        空列表。

    Note:
        请传入带时区的 ``cutoff``，以便与带时区的 ``created_at`` 列比较时不存在
        歧义。
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
    """在租户内按 ID 获取单个订单。

    Args:
        session: 调用方拥有的会话，用于本次读取。
        tenant_id: 必须拥有该订单的租户。
        order_id: 订单 UUID；来自其他租户的 ID 会返回 ``None``。

    Returns:
        匹配的订单；在该租户中不存在时返回 ``None``。
    """

    return await session.scalar(
        select(SalesOrder).where(SalesOrder.tenant_id == tenant_id, SalesOrder.id == order_id)
    )


async def list_order_lines(
    session: AsyncSession, tenant_id: UUID, order_id: UUID
) -> list[OrderLine]:
    """列出租户内某个订单的明细行。

    Args:
        session: 调用方拥有的会话，用于本次读取。
        tenant_id: 必须同时拥有该订单及其明细的租户。
        order_id: 返回其明细的订单。

    Returns:
        该订单的 ``OrderLine`` 行，顺序不作保证；订单没有明细或不属于该租户时
        返回空列表。
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
    """获取租户内某个 SKU 与仓库的库存行。

    Args:
        session: 调用方拥有的会话，用于本次读取。
        tenant_id: 必须拥有该库存行的租户。
        sku_id: 读取其库存的 SKU。
        warehouse_id: 读取其库存的仓库。

    Returns:
        唯一的匹配行；该组合在此租户中没有库存记录时返回 ``None``。
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
    """列出租户内为某个订单创建的发运单。

    Args:
        session: 调用方拥有的会话，用于本次读取。
        tenant_id: 必须拥有这些发运单的租户。
        order_id: 返回其发运单的订单。

    Returns:
        所有匹配的 ``Shipment`` 行，顺序不作保证，包含已取消的发运单；订单尚未
        拆分时返回空列表。
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
