"""SQLAlchemy ORM models for the ERP core and agent runtime tables.

Schema conventions:

- Primary keys are application-generated UUIDs, so a row can be referenced
  before it is flushed and its ID stays stable through the write path.
- Every business table carries ``tenant_id``; a query that omits it can read
  or mutate another tenant's data.
- ``Inventory.version`` and ``SalesOrder.version`` are optimistic-concurrency
  counters owned by :mod:`opsconductor.domain.write_service`, which increments
  them on every successful write.
- JSON columns accept only JSON-serializable values. Serialize Pydantic models
  with ``model_dump(mode="json")`` before assigning them.
- Models declare plain columns rather than ORM relationships; joins are
  explicit queries.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from opsconductor.domain.base import Base, TimestampMixin


class Tenant(Base, TimestampMixin):
    """Top-level isolation boundary for all business data.

    The tenant UUID is the value every other table scopes on. ``name`` is unique
    across the database and is the human-readable identifier shown in the
    console; ``status`` defaults to ``active``.
    """

    __tablename__ = "tenant"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")


class Shop(Base, TimestampMixin):
    """Sales channel that owns orders.

    Shops are tenant-scoped and their names are not unique, so a lookup must
    include ``tenant_id`` to stay unambiguous.
    """

    __tablename__ = "shop"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenant.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)


class User(Base, TimestampMixin):
    """API caller with a role and a hashed credential.

    ``api_key_hash`` stores the lowercase hexadecimal SHA-256 digest produced
    by :func:`opsconductor.domain.security.hash_api_key`; the raw key is never
    persisted. The column is globally unique, making the digest the lookup key
    during authentication.
    """

    __tablename__ = "app_user"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenant.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)


class Product(Base, TimestampMixin):
    """Tenant-owned product record that groups SKUs.

    ``category`` is free-form text defaulting to ``general``; it carries no
    uniqueness or referential guarantees.
    """

    __tablename__ = "product"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenant.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False, default="general")


class Sku(Base, TimestampMixin):
    """Sellable stock-keeping unit belonging to a product.

    The database enforces uniqueness of ``(tenant_id, code)``. ``product_id``
    is not tenant-constrained by the schema, so writers must verify that the
    referenced product belongs to the same tenant.
    """

    __tablename__ = "sku"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenant.id"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("product.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    barcode: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_sku_tenant_code"),)


class Warehouse(Base, TimestampMixin):
    """Physical location that holds inventory and fulfils shipments.

    Repositories resolve warehouses by exact, tenant-scoped ``name`` rather than
    by UUID, matching how task instructions refer to them.
    """

    __tablename__ = "warehouse"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenant.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)


class Inventory(Base, TimestampMixin):
    """Stock position for one SKU in one warehouse of a tenant.

    ``available`` and ``reserved`` are unit counts: a split moves quantity from
    available to reserved, and a compensation moves it back. At most one row
    exists per ``(tenant_id, sku_id, warehouse_id)``.

    Note:
        ``version`` is an optimistic-concurrency counter that writers increment
        on every stock change. The write service also locks the row with
        ``SELECT ... FOR UPDATE``, so counters must never be adjusted without
        holding that lock.
    """

    __tablename__ = "inventory"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenant.id"), nullable=False, index=True
    )
    sku_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("sku.id"), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("warehouse.id"), nullable=False
    )
    available: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    __table_args__ = (
        UniqueConstraint("tenant_id", "sku_id", "warehouse_id", name="uq_inventory_sku_warehouse"),
    )


class InventoryLedger(Base):
    """Append-only record of every stock change.

    Each reservation or release inserts rows carrying signed
    ``delta_available`` and ``delta_reserved`` values plus a ``reason`` code
    such as ``order_split`` or ``split_compensation``. Rows are never updated
    or deleted; they are the evidence used to reverse a shipment's reservation.

    ``task_id`` is intentionally a bare UUID without a foreign key so ledger
    history survives task retention. Rows remain tenant-scoped even though they
    are also keyed by order and shipment.
    """

    __tablename__ = "inventory_ledger"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenant.id"), nullable=False, index=True
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sales_order.id"), nullable=True
    )
    shipment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("shipment.id"), nullable=True
    )
    sku_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("sku.id"), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("warehouse.id"), nullable=False
    )
    delta_available: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delta_reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason: Mapped[str] = mapped_column(String(100), nullable=False)
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SalesOrder(Base, TimestampMixin):
    """Customer order awaiting fulfilment or already split into shipments.

    ``order_no`` is unique per tenant and is the business key shown to users.
    Address fields are denormalized onto the order so an address change is a
    plain row update. ``warehouse_id`` stays optional until an order is
    assigned, while shipments always carry a warehouse.

    Note:
        ``version`` is an optimistic-concurrency counter incremented by the
        write service on every mutation. ``status`` stores an
        :class:`~opsconductor.domain.enums.OrderStatus` value as a plain string.
    """

    __tablename__ = "sales_order"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenant.id"), nullable=False, index=True
    )
    shop_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("shop.id"), nullable=False)
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("warehouse.id"), nullable=True
    )
    order_no: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending_shipment")
    receiver_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    province: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    city: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    district: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    address_detail: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    __table_args__ = (UniqueConstraint("tenant_id", "order_no", name="uq_order_tenant_no"),)


class OrderLine(Base):
    """Requested quantity of one SKU on a sales order.

    Lines are treated as immutable after creation and have no timestamps.
    ``qty`` is expected to be positive, but only application validation
    enforces that; the schema merely marks the column non-nullable.
    """

    __tablename__ = "order_line"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenant.id"), nullable=False, index=True
    )
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("sales_order.id"), nullable=False)
    sku_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("sku.id"), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)


class Shipment(Base, TimestampMixin):
    """Fulfilment group created when an order is split.

    ``status`` starts as ``created`` and becomes ``cancelled`` when the shipment
    is compensated; only ``created`` shipments still own an inventory
    reservation. A shipment belongs to exactly one order and one warehouse.
    """

    __tablename__ = "shipment"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenant.id"), nullable=False, index=True
    )
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("sales_order.id"), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("warehouse.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="created")


class ShipmentLine(Base):
    """Quantity of one SKU allocated to a shipment.

    Shipment lines must cover the order's lines exactly when totalled across
    shipments, or the whole split is rejected. No timestamps are kept because
    the parent shipment row carries them.
    """

    __tablename__ = "shipment_line"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenant.id"), nullable=False, index=True
    )
    shipment_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("shipment.id"), nullable=False)
    sku_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("sku.id"), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)


class TaskRun(Base, TimestampMixin):
    """One operator instruction tracked through planning and execution.

    ``status`` stores a :class:`~opsconductor.domain.enums.TaskStatus` value as
    a string. ``plan`` and ``result`` are JSON snapshots that must be
    JSON-serializable, typically produced with ``model_dump(mode="json")``;
    ``error`` keeps the failure reason for terminal failures.

    Note:
        ``task_type`` and ``instruction`` are the raw task input and are not
        rewritten by the orchestrator.
    """

    __tablename__ = "task_run"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenant.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("app_user.id"), nullable=False)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    instruction: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="received", index=True)
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)


class TaskStep(Base, TimestampMixin):
    """One execution attempt of a plan node.

    ``node_id`` is the planner's string identifier for the node. The unique
    constraint on ``(task_id, node_id, attempt)`` lets a retried node retain
    every attempt, with ``attempt`` starting at 1. ``input`` and ``output`` are
    JSON payloads and must be JSON-serializable; the actual timing lives in
    ``started_at`` and ``finished_at``.
    """

    __tablename__ = "task_step"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenant.id"), nullable=False, index=True
    )
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("task_run.id"), nullable=False)
    node_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    input: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint("task_id", "node_id", "attempt", name="uq_step_task_node_attempt"),
    )


class Approval(Base, TimestampMixin):
    """Human decision required for one high-risk planned action.

    A row is created as ``pending`` with a deadline in ``expires_at``; the
    approval service later marks it ``approved``, ``rejected``, or ``expired``.
    Only ``pending`` rows can be decided, and ``risk_level`` records the grade
    that triggered the gate. Persisted approval rows are authoritative:
    execution re-checks them before running gated nodes.

    Note:
        ``approver_id`` is null until a decision is recorded, and ``comment`` is
        optional free text.
    """

    __tablename__ = "approval"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenant.id"), nullable=False, index=True
    )
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("task_run.id"), nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sales_order.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    approver_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("app_user.id"), nullable=True
    )
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    """Append-only audit trail for security-relevant actions.

    ``before``, ``after``, and ``evidence`` are JSON snapshots whose values must
    be JSON-serializable. Rows are written by the audit helpers, which flush on
    the caller's transaction instead of committing, so an audit entry becomes
    visible exactly when the surrounding business change does.
    """

    __tablename__ = "audit_log"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenant.id"), nullable=False, index=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(100), nullable=False)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IdempotencyKey(Base):
    """Stored response that makes a repeated write a safe no-op.

    ``(tenant_id, scope, key)`` is unique, so a concurrent duplicate fails at
    commit and its stored response is replayed. ``request_hash`` is the SHA-256
    digest of the canonical request; reusing a key with a different hash is a
    conflict. ``response`` is the JSON result returned on replay and must be
    JSON-serializable.

    Note:
        The row is staged last inside a write transaction; its unique
        constraint is the serialization point for concurrent callers.
    """

    __tablename__ = "idempotency_key"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenant.id"), nullable=False, index=True
    )
    scope: Mapped[str] = mapped_column(String(100), nullable=False)
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("tenant_id", "scope", "key", name="uq_idempotency_tenant_scope_key"),
    )


class TraceSpan(Base):
    """Observability span recording one unit of task work.

    ``trace_id`` groups spans, and ``parent_span_id`` links a span to its caller
    within the same tenant. ``attributes`` is a JSON payload and must be
    JSON-serializable. ``ended_at`` stays null while the span is open.

    Note:
        Spans are written by the tracer with a flush only, so they commit with
        the surrounding transaction rather than on their own.
    """

    __tablename__ = "trace_span"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    span_id: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_span_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenant.id"), nullable=False, index=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attributes: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
