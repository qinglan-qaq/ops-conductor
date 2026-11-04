"""Domain layer: ORM base, models, enums, address rules, and repositories.

The package re-exports the declarative base, every ORM model, and the demo
seeder so callers can import from ``opsconductor.domain`` directly.

Note:
    Every business table is tenant-scoped. Queries must filter on
    ``tenant_id``; an ID alone is never proof that the caller may access a row.
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
