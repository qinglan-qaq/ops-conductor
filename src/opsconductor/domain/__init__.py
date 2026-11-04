"""领域层：ORM 基类、模型、枚举、地址规则与仓储。

本包重新导出声明式基类、所有 ORM 模型以及演示数据填充器，调用方可以直接从
``opsconductor.domain`` 导入。

Note:
    所有业务表都按租户隔离。查询必须按 ``tenant_id`` 过滤；仅有 ID 绝不能证明
    调用方有权访问某行。
"""

from opsconductor.domain.base import Base
from opsconductor.domain.models import (
    Approval,
    AuditLog,
    IdempotencyKey,
    Inventory,
    InventoryLedger,
    OrderLine,
    Product,
    SalesOrder,
    Shipment,
    ShipmentLine,
    Shop,
    Sku,
    TaskRun,
    TaskStep,
    Tenant,
    TraceSpan,
    User,
    Warehouse,
)
from opsconductor.domain.seed import seed

__all__ = [
    "Base",
    "Tenant",
    "Shop",
    "User",
    "Product",
    "Sku",
    "Warehouse",
    "Inventory",
    "InventoryLedger",
    "SalesOrder",
    "OrderLine",
    "Shipment",
    "ShipmentLine",
    "TaskRun",
    "TaskStep",
    "Approval",
    "AuditLog",
    "IdempotencyKey",
    "TraceSpan",
    "seed",
]
