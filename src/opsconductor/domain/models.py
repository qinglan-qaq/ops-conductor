"""ERP 核心与 agent 运行时表的 SQLAlchemy ORM 模型。

Schema 约定：

- 主键是应用生成的 UUID，因此行在 flush 之前即可被引用，且其 ID 在写入路径
  中保持稳定。
- 每张业务表都带有 ``tenant_id``；省略它的查询可能读取或修改其他租户的数据。
- ``Inventory.version`` 与 ``SalesOrder.version`` 是由
  :mod:`opsconductor.domain.write_service` 管理的乐观并发计数器，每次成功
  写入时递增。
- JSON 列只接受可 JSON 序列化的值。赋值前请用 ``model_dump(mode="json")``
  序列化 Pydantic 模型。
- 模型声明普通列而非 ORM 关系；join 通过显式查询完成。
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
    """所有业务数据的顶层隔离边界。

    租户 UUID 是所有其他表用于隔离的值。``name`` 在整个数据库中唯一，是控制台
    中展示的易读标识；``status`` 默认为 ``active``。
    """

    __tablename__ = "tenant"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")


class Shop(Base, TimestampMixin):
    """拥有订单的销售渠道。

    店铺按租户隔离且名称不唯一，因此查找时必须带上 ``tenant_id`` 以保持无歧义。
    """

    __tablename__ = "shop"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenant.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)


class User(Base, TimestampMixin):
    """带角色与哈希凭据的 API 调用方。

    ``api_key_hash`` 存储由 :func:`opsconductor.domain.security.hash_api_key`
    生成的小写十六进制 SHA-256 摘要；原始 key 从不持久化。该列全局唯一，因此
    认证时以该摘要作为查找键。
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
    """归租户所有的商品记录，用于对 SKU 分组。

    ``category`` 是默认为 ``general`` 的自由文本；它不提供唯一性或引用完整性
    保证。
    """

    __tablename__ = "product"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenant.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False, default="general")


class Sku(Base, TimestampMixin):
    """属于某个商品的可售库存单元。

    数据库强制 ``(tenant_id, code)`` 唯一。schema 不会对 ``product_id`` 施加
    租户约束，因此写入方必须确认所引用的商品属于同一租户。
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
    """存放库存并履行发运的物理位置。

    仓储层按精确的、租户范围内的 ``name`` 解析仓库，而不是按 UUID，这与任务
    指令引用仓库的方式一致。
    """

    __tablename__ = "warehouse"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenant.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)


class Inventory(Base, TimestampMixin):
    """租户内某个仓库中某个 SKU 的库存头寸。

    ``available`` 与 ``reserved`` 是单位数量：拆分把数量从 available 移到
    reserved，补偿则移回。每个 ``(tenant_id, sku_id, warehouse_id)`` 最多存在
    一行。

    Note:
        ``version`` 是乐观并发计数器，写入方在每次库存变更时递增。写入服务还会
        用 ``SELECT ... FOR UPDATE`` 锁定该行，因此绝不能在未持有该锁的情况下
        调整计数器。
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
    """每次库存变更的追加式记录。

    每次预留或释放都会插入若干行，携带带符号的 ``delta_available`` 与
    ``delta_reserved`` 值，以及诸如 ``order_split`` 或 ``split_compensation``
    的 ``reason`` 代码。行从不更新或删除；它们是用于撤销发运单预留的证据。

    ``task_id`` 有意是不带外键的裸 UUID，以便台账历史在任务被清理后仍能保留。
    尽管这些行同时也以订单和发运单为键，它们仍按租户隔离。
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
    """等待履行或已拆分为发运单的客户订单。

    ``order_no`` 在租户内唯一，是展示给用户的业务键。地址字段被反规范化到订单
    上，因此修改地址只是一次普通的行更新。``warehouse_id`` 在订单被分配前保持
    可选，而发运单始终带有仓库。

    Note:
        ``version`` 是乐观并发计数器，由写入服务在每次变更时递增。``status``
        以普通字符串存储 :class:`~opsconductor.domain.enums.OrderStatus` 值。
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
    """销售订单上某个 SKU 的请求数量。

    明细行创建后即视为不可变，且没有时间戳。``qty`` 预期为正数，但只有应用层
    校验会保证这一点；schema 只是把该列标记为非空。
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
    """订单拆分时创建的履行分组。

    ``status`` 初始为 ``created``，当发运单被补偿时变为 ``cancelled``；只有
    ``created`` 状态的发运单仍持有库存预留。一个发运单恰好属于一个订单和一个
    仓库。
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
    """分配给某个发运单的某个 SKU 数量。

    跨发运单汇总时，发运明细必须与订单明细完全一致，否则整个拆分都会被拒绝。
    此处不保留时间戳，因为父发运单行已携带它们。
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
    """在计划与执行过程中被跟踪的一条操作员指令。

    ``status`` 以字符串存储 :class:`~opsconductor.domain.enums.TaskStatus` 值。
    ``plan`` 与 ``result`` 是必须可 JSON 序列化的 JSON 快照，通常由
    ``model_dump(mode="json")`` 生成；``error`` 保存最终失败的原因。

    Note:
        ``task_type`` 与 ``instruction`` 是原始任务输入，不会被 orchestrator
        改写。
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
    """计划节点的一次执行尝试。

    ``node_id`` 是 planner 为该节点分配的字符串标识符。``(task_id, node_id,
    attempt)`` 上的唯一约束使重试的节点可以保留每次尝试，``attempt`` 从 1
    开始。``input`` 与 ``output`` 是 JSON 载荷且必须可 JSON 序列化；实际时间
    信息存放在 ``started_at`` 与 ``finished_at`` 中。
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
    """某个高风险计划动作所需的人工裁决。

    行创建时为 ``pending``，并在 ``expires_at`` 中带有截止时间；审批服务随后会
    将其标记为 ``approved``、``rejected`` 或 ``expired``。只有 ``pending`` 行
    可以被裁决，``risk_level`` 记录触发门禁的风险等级。已持久化的审批行是权威
    依据：执行器在运行受门禁约束的节点前会重新检查它们。

    Note:
        ``approver_id`` 在记录裁决前为 null，``comment`` 是可选的自由文本。
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
    """与安全相关操作的追加式审计轨迹。

    ``before``、``after`` 与 ``evidence`` 是 JSON 快照，其值必须可 JSON 序列
    化。这些行由审计辅助函数写入，它们只在调用方事务上 flush 而不提交，因此审
    计记录与外围业务变更会同时可见。
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
    """存储的响应，使重复写入成为安全的空操作。

    ``(tenant_id, scope, key)`` 唯一，因此并发的重复请求会在提交时失败，并重放
    已存储的响应。``request_hash`` 是规范化请求的 SHA-256 摘要；以不同哈希复用
    同一 key 属于冲突。``response`` 是重放时返回的 JSON 结果，必须可 JSON
    序列化。

    Note:
        该行在写事务中最后暂存；其唯一约束是并发调用方的串行化点。
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
    """记录一个任务工作单元的可观测性 span。

    ``trace_id`` 对 span 分组，``parent_span_id`` 在同一租户内把 span 链接到其
    调用方。``attributes`` 是 JSON 载荷且必须可 JSON 序列化。span 打开期间
    ``ended_at`` 保持为 null。

    Note:
        span 由 tracer 仅以 flush 的方式写入，因此它们随外围事务一起提交，而不
        是独立提交。
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
