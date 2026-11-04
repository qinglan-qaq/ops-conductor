"""用于本地开发与测试的确定性演示数据。

种子脚本插入两个租户（A 与 B）、各自的用户与店铺、十个带库存的 SKU、租户 A 的
六个订单以及租户 B 的一个订单。所有固定 ID 都由稳定名称经 ``uuid5`` 推导，因此
重复运行会命中相同的行，测试也可以按 ID 引用夹具。

Invariants:

- 播种幂等：仅当行不存在时才插入，因此第二次运行不会复制或覆盖夹具数据。
- 租户 B 的订单 ``O2001`` 是刻意保留的，用于支撑租户隔离测试；它绝不能被租户 A
  看到。
- ``SKU-003`` 初始可用库存为零且 ``O1003`` 请求该 SKU，因此夹具覆盖缺货处理。
- ``O1005`` 预先拆分并带一个发货单，用于覆盖状态校验。
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from opsconductor.domain.security import hash_api_key

TENANT_A = uuid.uuid5(uuid.NAMESPACE_DNS, "opsconductor.tenant-a")
TENANT_B = uuid.uuid5(uuid.NAMESPACE_DNS, "opsconductor.tenant-b")
SHOP_A = uuid.uuid5(uuid.NAMESPACE_DNS, "opsconductor.shop-a")
SHOP_B = uuid.uuid5(uuid.NAMESPACE_DNS, "opsconductor.shop-b")
WAREHOUSE_EAST = uuid.uuid5(uuid.NAMESPACE_DNS, "opsconductor.warehouse-east")
SKU_IDS = {
    f"SKU-{i:03d}": uuid.uuid5(uuid.NAMESPACE_DNS, f"opsconductor.sku-{i:03d}")
    for i in range(1, 11)
}


async def seed(session: AsyncSession) -> None:
    """插入演示用的租户、用户、商品目录、库存与订单。

    缺失的行会被创建，已存在的行保持原样，因此可以安全地在已有数据的库上重复
    运行。函数在返回前提交自己的事务；没有可回滚的外层事务。

    Args:
        session: 用于查找、插入与最终提交的异步会话。

    Returns:
        ``None``。所有行都已提交到数据库。
    """

    for tenant_id, name in [(TENANT_A, "tenant-a"), (TENANT_B, "tenant-b")]:
        if not await session.scalar(select(Tenant).where(Tenant.id == tenant_id)):
            session.add(Tenant(id=tenant_id, name=name))

    users = [
        (TENANT_A, "operator-a", "operator", "dev-operator-a"),
        (TENANT_A, "approver-a", "approver", "dev-approver-a"),
        (TENANT_B, "operator-b", "operator", "dev-operator-b"),
        (TENANT_B, "approver-b", "approver", "dev-approver-b"),
    ]
    for tenant_id, name, role, api_key in users:
        if not await session.scalar(select(User).where(User.name == name)):
            session.add(
                User(
                    id=uuid.uuid5(uuid.NAMESPACE_DNS, f"opsconductor.user-{name}"),
                    tenant_id=tenant_id,
                    name=name,
                    role=role,
                    api_key_hash=hash_api_key(api_key),
                )
            )

    if not await session.scalar(select(Shop).where(Shop.id == SHOP_A)):
        session.add(Shop(id=SHOP_A, tenant_id=TENANT_A, name="shop-a"))
    if not await session.scalar(select(Shop).where(Shop.id == SHOP_B)):
        session.add(Shop(id=SHOP_B, tenant_id=TENANT_B, name="shop-b"))
    if not await session.scalar(select(Warehouse).where(Warehouse.id == WAREHOUSE_EAST)):
        session.add(Warehouse(id=WAREHOUSE_EAST, tenant_id=TENANT_A, name="east"))

    for code, sku_id in SKU_IDS.items():
        if await session.scalar(select(Sku).where(Sku.id == sku_id)):
            continue
        product_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"opsconductor.product-{code}")
        session.add(Product(id=product_id, tenant_id=TENANT_A, name=f"Product {code}"))
        await session.flush()
        session.add(Sku(id=sku_id, tenant_id=TENANT_A, product_id=product_id, code=code))
        await session.flush()
        available = 0 if code == "SKU-003" else 100
        session.add(
            Inventory(
                id=uuid.uuid5(uuid.NAMESPACE_DNS, f"opsconductor.inventory-{code}"),
                tenant_id=TENANT_A,
                sku_id=sku_id,
                warehouse_id=WAREHOUSE_EAST,
                available=available,
                reserved=0,
            )
        )

    orders = [
        ("O1001", [("SKU-001", 2), ("SKU-002", 1)], "世纪大道 100 号"),
        ("O1002", [("SKU-006", 1)], ""),
        ("O1003", [("SKU-003", 5)], "世纪大道 100 号"),
        ("O1004", [("SKU-004", 1)], "世纪大道 100 号"),
        ("O1005", [("SKU-005", 1)], "世纪大道 100 号"),
        ("O1006", [("SKU-006", 2)], "世纪大道 100 号"),
    ]
    for order_no, lines, address_detail in orders:
        existing = await session.scalar(
            select(SalesOrder).where(
                SalesOrder.tenant_id == TENANT_A,
                SalesOrder.order_no == order_no,
            )
        )
        if existing:
            continue
        order_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"opsconductor.order-{order_no}")
        session.add(
            SalesOrder(
                id=order_id,
                tenant_id=TENANT_A,
                shop_id=SHOP_A,
                warehouse_id=WAREHOUSE_EAST,
                order_no=order_no,
                status="pending_shipment",
                receiver_name="张三",
                phone="13800138000",
                province="上海市",
                city="上海市",
                district="浦东新区",
                address_detail=address_detail,
                created_at=datetime(2026, 11, 1, tzinfo=UTC),
            )
        )
        await session.flush()
        for sku_code, qty in lines:
            session.add(
                OrderLine(
                    id=uuid.uuid5(uuid.NAMESPACE_DNS, f"opsconductor.line-{order_no}-{sku_code}"),
                    tenant_id=TENANT_A,
                    order_id=order_id,
                    sku_id=SKU_IDS[sku_code],
                    qty=qty,
                )
            )

    # O1005 已拆单，用于状态校验
    order_1005 = await session.scalar(
        select(SalesOrder).where(
            SalesOrder.tenant_id == TENANT_A,
            SalesOrder.order_no == "O1005",
        )
    )
    if order_1005 and not await session.scalar(
        select(Shipment).where(Shipment.order_id == order_1005.id)
    ):
        shipment_id = uuid.uuid5(uuid.NAMESPACE_DNS, "opsconductor.shipment-O1005")
        session.add(
            Shipment(
                id=shipment_id,
                tenant_id=TENANT_A,
                order_id=order_1005.id,
                warehouse_id=WAREHOUSE_EAST,
            )
        )
        await session.flush()
        session.add(
            ShipmentLine(
                id=uuid.uuid5(uuid.NAMESPACE_DNS, "opsconductor.shipment-line-O1005"),
                tenant_id=TENANT_A,
                shipment_id=shipment_id,
                sku_id=SKU_IDS["SKU-005"],
                qty=1,
            )
        )
        order_1005.status = "split"

    # 租户 B 的越权测试订单
    if not await session.scalar(
        select(SalesOrder).where(
            SalesOrder.tenant_id == TENANT_B,
            SalesOrder.order_no == "O2001",
        )
    ):
        order_id = uuid.uuid5(uuid.NAMESPACE_DNS, "opsconductor.order-O2001")
        session.add(
            SalesOrder(
                id=order_id,
                tenant_id=TENANT_B,
                shop_id=SHOP_B,
                order_no="O2001",
                status="pending_shipment",
                receiver_name="李四",
                phone="13900139000",
                province="浙江省",
                city="杭州市",
                district="西湖区",
                address_detail="文三路 1 号",
                created_at=datetime(2026, 11, 1, tzinfo=UTC),
            )
        )

    await session.commit()


if __name__ == "__main__":
    import asyncio

    from opsconductor.db import SessionLocal

    async def main() -> None:
        async with SessionLocal() as session:
            await seed(session)

    asyncio.run(main())
