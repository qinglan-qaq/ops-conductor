# 订单异常 MVP 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 3 周内交付订单异常的可写闭环：自然语言任务 → 计划 → L2/L3 审批 → 拆单/改址 → 幂等执行 → 验证 → 补偿 → 审计/trace → 报告。

**Architecture:** FastAPI 接入层 + LangGraph 执行图 + MCP 工具网关；PostgreSQL 作为业务事实源；审批、幂等、补偿、审计和 trace 都是一等公民。计划生成与执行分离，审批是执行前的门禁。

**Tech Stack:** Python 3.11、FastAPI 0.162、Pydantic 2.14、SQLAlchemy 2.1 async + psycopg 3、PostgreSQL 16、LangGraph 1.2、MCP Python SDK 2.3（`mcp.server.mcpserver.MCPServer`）、Jinja2、pytest、ruff、mypy。

**Spec:** [MVP 设计规格](../specs/2026-11-04-mvp-order-exception-design.md) ｜ [系统设计](../design.md)

## Global Constraints

- 所有业务查询和写入必须带 `tenant_id`；跨租户访问返回 403 并写审计。
- 所有写操作必须先通过审批记录检查，携带幂等键，写后写审计和 trace。
- 拆单是「同一订单下多个发货单」，不创建子订单；整单全有或全无。
- 改址只允许在订单 `pending_shipment` 且没有发货单时执行。
- L2 动作用户二次确认；同一任务批量拆单 ≥ 10 单升级 L3，阈值来自配置。
- 测试默认使用 stub 模型和测试数据库，不调用真实 LLM；真实模型只做冒烟。
- MCP 工具名使用下划线，例如 `order_list_overdue`、`order_split`；文档中的点号是能力名。
- 所有代码从仓库根目录执行，Python 环境为 conda `opsconductor`。
- 测试数据库使用独立库：先执行 `createdb -U ops opsconductor_test`，并设置 `OPSCONDUCTOR_DATABASE_URL=postgresql+psycopg://ops:ops@localhost:5432/opsconductor_test`。
- 每个任务结束前必须跑对应测试并通过 ruff；提交信息使用 `feat:`、`test:`、`chore:` 前缀。

---

## Phase 1：基础与数据模型（第 1 周前半）

### Task 1: 工程基础、配置与数据库会话

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/opsconductor/config.py`
- Create: `src/opsconductor/db.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Consumes: 现有 `Settings`、`get_settings()`。
- Produces: `Settings.l3_batch_threshold: int`、`Settings.approval_timeout_minutes: int`、`Settings.stub_llm: bool`、`Settings.llm_base_url: str | None`、`Settings.llm_api_key: str | None`、`Settings.llm_model_planner: str`、`Settings.llm_model_router: str`、`Settings.llm_model_verifier: str`；`engine`、`SessionLocal`、`get_session()`。

- [ ] **Step 1: 写失败测试**

`tests/test_config.py`：

```python
import os

from opsconductor.config import Settings


def test_settings_defaults_and_env_override(monkeypatch):
    monkeypatch.setenv("OPSCONDUCTOR_L3_BATCH_THRESHOLD", "2")
    settings = Settings(_env_file=None)
    assert settings.l3_batch_threshold == 2
    assert settings.approval_timeout_minutes == 30
    assert settings.stub_llm is True
    assert settings.database_url.startswith("postgresql+psycopg://")
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_config.py -q
```

预期：`AttributeError` 或 `ValidationError`，因为字段不存在。

- [ ] **Step 3: 修改配置与数据库会话**

`config.py` 的 `Settings` 增加：

```python
    l3_batch_threshold: int = 10
    approval_timeout_minutes: int = 30
    stub_llm: bool = True
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model_planner: str = "gpt-4o-mini"
    llm_model_router: str = "gpt-4o-mini"
    llm_model_verifier: str = "gpt-4o-mini"
    mcp_server_command: str = "python"
    mcp_server_args: list[str] = ["-m", "opsconductor.tools.server"]
```

`pyproject.toml` 增加运行时依赖 `jinja2>=3.1`、开发依赖 `alembic>=1.14`，并补充：

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

`db.py`：

```python
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from opsconductor.config import get_settings

settings = get_settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/test_config.py -q
ruff check src/opsconductor/config.py src/opsconductor/db.py
```

预期：PASS。

- [ ] **Step 5: 提交**

```bash
git add pyproject.toml src/opsconductor/config.py src/opsconductor/db.py tests/test_config.py
git commit -m "feat: add settings and async database session"
```

### Task 2: 领域模型与 Alembic 初始迁移

**Files:**
- Create: `src/opsconductor/domain/base.py`
- Create: `src/opsconductor/domain/enums.py`
- Create: `src/opsconductor/domain/models.py`
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/script.py.mako`
- Create: `migrations/versions/0001_initial.py`
- Create: `tests/test_models.py`
- Create: `tests/conftest.py`
- Modify: `src/opsconductor/domain/__init__.py`

**Interfaces:**
- Consumes: `Base.metadata`、`SessionLocal`。
- Produces: 所有 ORM 模型，供 repositories、tools、orchestrator 使用。

- [ ] **Step 1: 写模型测试**

`tests/test_models.py`：

```python
import uuid

import pytest
from sqlalchemy import select

from opsconductor.db import SessionLocal
from opsconductor.domain.models import Base, Tenant, User
from opsconductor.domain.security import hash_api_key


@pytest.mark.asyncio
async def test_create_tenant_and_user(test_engine):
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as session:
        tenant = Tenant(id=uuid.uuid4(), name="tenant-a")
        session.add(tenant)
        await session.flush()
        user = User(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            name="operator-a",
            role="operator",
            api_key_hash=hash_api_key("dev-operator-a"),
        )
        session.add(user)
        await session.commit()
        loaded = await session.scalar(select(User).where(User.name == "operator-a"))
        assert loaded is not None
        assert loaded.tenant_id == tenant.id
```

`tests/conftest.py`：

```python
import os

import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from opsconductor.config import get_settings
from opsconductor.domain import Base

os.environ.setdefault(
    "OPSCONDUCTOR_DATABASE_URL",
    "postgresql+psycopg://ops:ops@localhost:5432/opsconductor_test",
)


@pytest_asyncio.fixture
async def test_engine():
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_models.py -q
```

预期：导入失败，模型不存在。

- [ ] **Step 3: 创建枚举与模型**

`domain/enums.py`：

```python
from enum import Enum


class Role(str, Enum):
    operator = "operator"
    approver = "approver"
    admin = "admin"


class RiskLevel(str, Enum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class TaskStatus(str, Enum):
    received = "received"
    planned = "planned"
    awaiting_approval = "awaiting_approval"
    running = "running"
    succeeded = "succeeded"
    partially_succeeded = "partially_succeeded"
    failed = "failed"
    compensating = "compensating"
    compensated = "compensated"
    partially_compensated = "partially_compensated"


class StepStatus(str, Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"
    compensated = "compensated"


class ApprovalStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"


class OrderStatus(str, Enum):
    pending_shipment = "pending_shipment"
    split = "split"
```

`domain/base.py`：

```python
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

`domain/models.py` 使用以下表（全部带 `tenant_id`，除 `tenant` 自身）：

```python
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
    __tablename__ = "tenant"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")


class Shop(Base, TimestampMixin):
    __tablename__ = "shop"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenant.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)


class User(Base, TimestampMixin):
    __tablename__ = "app_user"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenant.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)


class Product(Base, TimestampMixin):
    __tablename__ = "product"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenant.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False, default="general")


class Sku(Base, TimestampMixin):
    __tablename__ = "sku"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenant.id"), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("product.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    barcode: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_sku_tenant_code"),)


class Warehouse(Base, TimestampMixin):
    __tablename__ = "warehouse"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenant.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)


class Inventory(Base, TimestampMixin):
    __tablename__ = "inventory"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenant.id"), nullable=False, index=True)
    sku_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("sku.id"), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("warehouse.id"), nullable=False)
    available: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    __table_args__ = (
        UniqueConstraint("tenant_id", "sku_id", "warehouse_id", name="uq_inventory_sku_warehouse"),
    )


class InventoryLedger(Base):
    __tablename__ = "inventory_ledger"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenant.id"), nullable=False, index=True)
    sku_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("sku.id"), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("warehouse.id"), nullable=False)
    delta_available: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delta_reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason: Mapped[str] = mapped_column(String(100), nullable=False)
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SalesOrder(Base, TimestampMixin):
    __tablename__ = "sales_order"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenant.id"), nullable=False, index=True)
    shop_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("shop.id"), nullable=False)
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("warehouse.id"), nullable=True)
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
    __tablename__ = "order_line"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenant.id"), nullable=False, index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("sales_order.id"), nullable=False)
    sku_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("sku.id"), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)


class Shipment(Base, TimestampMixin):
    __tablename__ = "shipment"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenant.id"), nullable=False, index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("sales_order.id"), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("warehouse.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="created")


class ShipmentLine(Base):
    __tablename__ = "shipment_line"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenant.id"), nullable=False, index=True)
    shipment_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("shipment.id"), nullable=False)
    sku_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("sku.id"), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)


class TaskRun(Base, TimestampMixin):
    __tablename__ = "task_run"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenant.id"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("app_user.id"), nullable=False)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    instruction: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="received", index=True)
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)


class TaskStep(Base, TimestampMixin):
    __tablename__ = "task_step"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenant.id"), nullable=False, index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("task_run.id"), nullable=False)
    node_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    input: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("task_id", "node_id", "attempt", name="uq_step_task_node_attempt"),)


class Approval(Base, TimestampMixin):
    __tablename__ = "approval"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenant.id"), nullable=False, index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("task_run.id"), nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("sales_order.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    approver_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("app_user.id"), nullable=True)
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenant.id"), nullable=False, index=True)
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
    __tablename__ = "idempotency_key"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenant.id"), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(100), nullable=False)
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("tenant_id", "scope", "key", name="uq_idempotency_tenant_scope_key"),)


class TraceSpan(Base):
    __tablename__ = "trace_span"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    span_id: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_span_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenant.id"), nullable=False, index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attributes: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
```

`domain/security.py`：

```python
import hashlib


def hash_api_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
```

`domain/__init__.py` 导入 `Base` 和所有模型，确保 Alembic 能发现它们：

```python
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

__all__ = [
    "Base", "Tenant", "Shop", "User", "Product", "Sku", "Warehouse", "Inventory",
    "InventoryLedger", "SalesOrder", "OrderLine", "Shipment", "ShipmentLine",
    "TaskRun", "TaskStep", "Approval", "AuditLog", "IdempotencyKey", "TraceSpan",
]
```

- [ ] **Step 4: 初始化 Alembic 并生成迁移**

```bash
alembic init migrations
```

编辑 `alembic.ini`，设置 `script_location = migrations`；编辑 `migrations/env.py`：

```python
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from opsconductor.config import get_settings
from opsconductor.domain import Base

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

```bash
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

- [ ] **Step 5: 运行测试与迁移测试**

```bash
pytest tests/test_models.py -q
alembic upgrade head
```

预期：PASS；迁移成功。

- [ ] **Step 6: 提交**

```bash
git add src/opsconductor/domain migrations alembic.ini tests/test_models.py
git commit -m "feat: add domain models and initial migration"
```

### Task 3: 种子数据与测试租户

**Files:**
- Create: `src/opsconductor/domain/seed.py`
- Create: `tests/test_seed.py`
- Modify: `src/opsconductor/domain/__init__.py`

**Interfaces:**
- Consumes: `SessionLocal`、模型、`hash_api_key`。
- Produces: `async def seed(session) -> None`；固定租户、用户、SKU、订单，供 API、MCP、评测使用。

- [ ] **Step 1: 写种子测试**

```python
import pytest
from sqlalchemy import func, select

from opsconductor.db import SessionLocal
from opsconductor.domain.models import SalesOrder, Tenant
from opsconductor.domain.seed import seed


@pytest.mark.asyncio
async def test_seed_is_idempotent(seeded_db):
    async with SessionLocal() as session:
        await seed(session)
        count = await session.scalar(select(func.count()).select_from(Tenant))
        assert count == 2
        orders = (await session.scalars(select(SalesOrder))).all()
        assert any(o.order_no == "O1001" for o in orders)
```

- [ ] **Step 2: 实现种子**

`seed.py` 使用固定业务键，先查再建，保证可重复：

```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opsconductor.domain.models import (
    Inventory, OrderLine, Product, SalesOrder, Shipment, ShipmentLine,
    Shop, Sku, Tenant, User, Warehouse,
)
from opsconductor.domain.security import hash_api_key

TENANT_A = uuid.uuid5(uuid.NAMESPACE_DNS, "opsconductor.tenant-a")
TENANT_B = uuid.uuid5(uuid.NAMESPACE_DNS, "opsconductor.tenant-b")
SHOP_A = uuid.uuid5(uuid.NAMESPACE_DNS, "opsconductor.shop-a")
SHOP_B = uuid.uuid5(uuid.NAMESPACE_DNS, "opsconductor.shop-b")
WAREHOUSE_EAST = uuid.uuid5(uuid.NAMESPACE_DNS, "opsconductor.warehouse-east")
SKU_IDS = {f"SKU-{i:03d}": uuid.uuid5(uuid.NAMESPACE_DNS, f"opsconductor.sku-{i:03d}") for i in range(1, 11)}


async def seed(session: AsyncSession) -> None:
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
            session.add(User(
                id=uuid.uuid5(uuid.NAMESPACE_DNS, f"opsconductor.user-{name}"),
                tenant_id=tenant_id, name=name, role=role, api_key_hash=hash_api_key(api_key),
            ))

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
        session.add(Sku(id=sku_id, tenant_id=TENANT_A, product_id=product_id, code=code))
        available = 0 if code == "SKU-003" else 100
        session.add(Inventory(
            id=uuid.uuid5(uuid.NAMESPACE_DNS, f"opsconductor.inventory-{code}"),
            tenant_id=TENANT_A, sku_id=sku_id, warehouse_id=WAREHOUSE_EAST,
            available=available, reserved=0,
        ))

    orders = [
        ("O1001", [("SKU-001", 2), ("SKU-002", 1)], "世纪大道 100 号"),
        ("O1002", [("SKU-006", 1)], ""),
        ("O1003", [("SKU-003", 5)], "世纪大道 100 号"),
        ("O1004", [("SKU-004", 1)], "世纪大道 100 号"),
        ("O1005", [("SKU-005", 1)], "世纪大道 100 号"),
        ("O1006", [("SKU-006", 2)], "世纪大道 100 号"),
    ]
    for order_no, lines, address_detail in orders:
        if await session.scalar(select(SalesOrder).where(SalesOrder.tenant_id == TENANT_A, SalesOrder.order_no == order_no)):
            continue
        order_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"opsconductor.order-{order_no}")
        session.add(SalesOrder(
            id=order_id, tenant_id=TENANT_A, shop_id=SHOP_A, warehouse_id=WAREHOUSE_EAST,
            order_no=order_no, status="pending_shipment", receiver_name="张三", phone="13800138000",
            province="上海市", city="上海市", district="浦东新区", address_detail=address_detail,
            created_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        ))
        for sku_code, qty in lines:
            session.add(OrderLine(
                id=uuid.uuid5(uuid.NAMESPACE_DNS, f"opsconductor.line-{order_no}-{sku_code}"),
                tenant_id=TENANT_A, order_id=order_id, sku_id=SKU_IDS[sku_code], qty=qty,
            ))

    # O1005 已拆单，用于状态校验
    order_1005 = await session.scalar(select(SalesOrder).where(SalesOrder.order_no == "O1005"))
    if order_1005 and not await session.scalar(select(Shipment).where(Shipment.order_id == order_1005.id)):
        shipment_id = uuid.uuid5(uuid.NAMESPACE_DNS, "opsconductor.shipment-O1005")
        session.add(Shipment(id=shipment_id, tenant_id=TENANT_A, order_id=order_1005.id, warehouse_id=WAREHOUSE_EAST))
        session.add(ShipmentLine(
            id=uuid.uuid5(uuid.NAMESPACE_DNS, "opsconductor.shipment-line-O1005"),
            tenant_id=TENANT_A, shipment_id=shipment_id, sku_id=SKU_IDS["SKU-005"], qty=1,
        ))
        order_1005.status = "split"

    # 租户 B 的越权测试订单
    if not await session.scalar(select(SalesOrder).where(SalesOrder.order_no == "O2001")):
        order_id = uuid.uuid5(uuid.NAMESPACE_DNS, "opsconductor.order-O2001")
        session.add(SalesOrder(
            id=order_id, tenant_id=TENANT_B, shop_id=SHOP_B, order_no="O2001",
            status="pending_shipment", receiver_name="李四", phone="13900139000",
            province="浙江省", city="杭州市", district="西湖区", address_detail="文三路 1 号",
            created_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        ))

    await session.commit()


if __name__ == "__main__":
    import asyncio

    from opsconductor.db import SessionLocal

    async def main() -> None:
        async with SessionLocal() as session:
            await seed(session)

    asyncio.run(main())
```

- [ ] **Step 3: 添加 `seeded_db` fixture**

`tests/conftest.py` 追加：

```python
@pytest_asyncio.fixture
async def seeded_db(test_engine):
    from opsconductor.db import SessionLocal
    from opsconductor.domain.seed import seed

    async with SessionLocal() as session:
        await seed(session)
    yield
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/test_seed.py -q
```

预期：PASS；重复执行不重复建租户/订单。

- [ ] **Step 5: 提交**

```bash
git add src/opsconductor/domain/seed.py tests/test_seed.py tests/conftest.py
git commit -m "feat: add deterministic seed data"
```

### Task 4: Pydantic Schema 与计划校验

**Files:**
- Create: `src/opsconductor/schemas.py`
- Create: `tests/test_schemas.py`

**Interfaces:**
- Produces: `TaskCreate`、`TaskRead`、`Plan`、`PlanNode`、`ApprovalDecision`、`TaskReport`、`validate_plan(plan)`。

- [ ] **Step 1: 写校验测试**

```python
import pytest

from opsconductor.schemas import Plan, PlanNode, validate_plan


def test_plan_rejects_cycle():
    plan = Plan(
        task_id="00000000-0000-0000-0000-000000000001",
        nodes=[
            PlanNode(node_id="a", action="verify", depends_on=["b"]),
            PlanNode(node_id="b", action="verify", depends_on=["a"]),
        ],
    )
    with pytest.raises(ValueError, match="cycle"):
        validate_plan(plan)


def test_plan_accepts_linear_nodes():
    plan = Plan(
        task_id="00000000-0000-0000-0000-000000000001",
        nodes=[
            PlanNode(node_id="a", action="verify"),
            PlanNode(node_id="b", action="verify", depends_on=["a"]),
        ],
    )
    validate_plan(plan)
```

- [ ] **Step 2: 实现 schema**

```python
from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from opsconductor.domain.enums import RiskLevel


class TaskCreate(BaseModel):
    instruction: str = Field(min_length=2, max_length=1000)
    warehouse: str | None = None
    cutoff: str | None = None


class PlanNode(BaseModel):
    node_id: str
    order_id: UUID | None = None
    action: Literal["split_order", "change_address", "block_order", "verify", "report"]
    risk: RiskLevel = RiskLevel.L0
    requires_approval: bool = False
    params: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    compensation: str | None = None
    reason: str = ""


class Plan(BaseModel):
    task_id: str
    summary: str = ""
    requires_l3: bool = False
    nodes: list[PlanNode] = Field(default_factory=list)


class ApprovalDecision(BaseModel):
    approved: bool
    comment: str | None = None


class TaskReport(BaseModel):
    task_id: str
    status: str
    succeeded: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)
    pending: list[str] = Field(default_factory=list)
    message: str = ""


class TaskRead(BaseModel):
    id: UUID
    status: str
    instruction: str
    plan: dict[str, Any] | None = None
    result: dict[str, Any] | None = None


def validate_plan(plan: Plan) -> None:
    ids = [node.node_id for node in plan.nodes]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate node_id")
    known = set(ids)
    for node in plan.nodes:
        missing = set(node.depends_on) - known
        if missing:
            raise ValueError(f"unknown dependency: {sorted(missing)}")
    visiting: set[str] = set()
    visited: set[str] = set()
    graph = {node.node_id: node.depends_on for node in plan.nodes}

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise ValueError("cycle detected")
        if node_id in visited:
            return
        visiting.add(node_id)
        for dep in graph[node_id]:
            visit(dep)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in ids:
        visit(node_id)
```

- [ ] **Step 3: 运行测试**

```bash
pytest tests/test_schemas.py -q
```

- [ ] **Step 4: 提交**

```bash
git add src/opsconductor/schemas.py tests/test_schemas.py
git commit -m "feat: add task and plan schemas"
```

## Phase 2：只读链路与计划（第 1 周后半）

### Task 5: 只读仓储与 MCP 只读工具

**Files:**
- Create: `src/opsconductor/domain/repositories.py`
- Create: `src/opsconductor/tools/service.py`
- Create: `src/opsconductor/tools/server.py`
- Create: `src/opsconductor/tools/client.py`
- Create: `tests/test_repositories.py`
- Create: `tests/test_mcp_tools.py`

**Interfaces:**
- `list_overdue_orders(session, tenant_id, warehouse, cutoff) -> list[SalesOrder]`
- `get_order(session, tenant_id, order_id) -> SalesOrder | None`
- `get_inventory(session, tenant_id, sku_id, warehouse_id) -> Inventory | None`
- `list_shipments(session, tenant_id, order_id) -> list[Shipment]`
- `ErpToolService` 方法：`order_list_overdue`、`order_get`、`inventory_get`、`address_validate`、`shipment_list`、`order_get_state`
- `ErpToolClient.call(name, arguments) -> dict[str, Any]`

- [ ] **Step 1: 写仓储测试**

```python
import pytest

from opsconductor.db import SessionLocal
from opsconductor.domain.repositories import list_overdue_orders
from opsconductor.domain.seed import TENANT_A


@pytest.mark.asyncio
async def test_list_overdue_orders_is_tenant_scoped(seeded_db):
    async with SessionLocal() as session:
        orders = await list_overdue_orders(session, TENANT_A, warehouse="east")
        assert {o.order_no for o in orders} >= {"O1001", "O1002", "O1003", "O1004"}
        assert all(o.tenant_id == TENANT_A for o in orders)
```

- [ ] **Step 2: 实现仓储**

```python
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


async def list_order_lines(session: AsyncSession, tenant_id: UUID, order_id: UUID) -> list[OrderLine]:
    return list((await session.scalars(
        select(OrderLine).where(OrderLine.tenant_id == tenant_id, OrderLine.order_id == order_id)
    )).all())


async def get_inventory(session: AsyncSession, tenant_id: UUID, sku_id: UUID, warehouse_id: UUID) -> Inventory | None:
    return await session.scalar(
        select(Inventory).where(
            Inventory.tenant_id == tenant_id,
            Inventory.sku_id == sku_id,
            Inventory.warehouse_id == warehouse_id,
        )
    )


async def list_shipments(session: AsyncSession, tenant_id: UUID, order_id: UUID) -> list[Shipment]:
    return list((await session.scalars(
        select(Shipment).where(Shipment.tenant_id == tenant_id, Shipment.order_id == order_id)
    )).all())
```

- [ ] **Step 3: 实现 MCP 只读服务与服务器**

`tools/service.py` 封装 `SessionLocal`，所有方法先取订单/库存；`address_validate` 用本地规则：

```python
import re
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from opsconductor.domain import repositories
from opsconductor.domain.models import SalesOrder


def address_is_valid(order: SalesOrder) -> bool:
    if not all([order.receiver_name, order.phone, order.province, order.city, order.district]):
        return False
    if not re.fullmatch(r"1[3-9]\d{9}", order.phone):
        return False
    return bool(order.address_detail.strip())


class ErpToolService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def order_list_overdue(self, tenant_id: UUID, warehouse: str | None = None) -> list[dict[str, Any]]:
        orders = await repositories.list_overdue_orders(self.session, tenant_id, warehouse)
        return [
            {"id": str(order.id), "order_no": order.order_no, "status": order.status}
            for order in orders
        ]

    async def order_get(self, tenant_id: UUID, order_id: UUID) -> dict[str, Any]:
        order = await repositories.get_order(self.session, tenant_id, order_id)
        if order is None:
            raise ValueError("order not found")
        lines = await repositories.list_order_lines(self.session, tenant_id, order_id)
        return {
            "id": str(order.id), "order_no": order.order_no, "status": order.status,
            "warehouse_id": str(order.warehouse_id) if order.warehouse_id else None,
            "receiver_name": order.receiver_name, "phone": order.phone,
            "province": order.province, "city": order.city, "district": order.district,
            "address_detail": order.address_detail, "version": order.version,
            "lines": [{"sku_id": str(line.sku_id), "qty": line.qty} for line in lines],
        }

    async def inventory_get(self, tenant_id: UUID, sku_id: UUID, warehouse_id: UUID) -> dict[str, Any]:
        inv = await repositories.get_inventory(self.session, tenant_id, sku_id, warehouse_id)
        if inv is None:
            raise ValueError("inventory not found")
        return {"sku_id": str(inv.sku_id), "warehouse_id": str(inv.warehouse_id),
                "available": inv.available, "reserved": inv.reserved, "version": inv.version}

    async def shipment_list(self, tenant_id: UUID, order_id: UUID) -> list[dict[str, Any]]:
        shipments = await repositories.list_shipments(self.session, tenant_id, order_id)
        return [{"id": str(shipment.id), "status": shipment.status} for shipment in shipments]

    async def order_get_state(self, tenant_id: UUID, order_id: UUID) -> dict[str, Any]:
        order = await repositories.get_order(self.session, tenant_id, order_id)
        if order is None:
            raise ValueError("order not found")
        return {"order_id": str(order_id), "status": order.status, "version": order.version}

    async def address_validate(self, order_id: UUID, tenant_id: UUID) -> dict[str, Any]:
        order = await repositories.get_order(self.session, tenant_id, order_id)
        if order is None:
            raise ValueError("order not found")
        return {"valid": address_is_valid(order), "order_id": str(order_id)}
```

`tools/server.py`：

```python
from mcp.server.mcpserver import MCPServer

from opsconductor.db import SessionLocal
from opsconductor.tools.service import ErpToolService

server = MCPServer("opsconductor-erp")


@server.tool(name="order_list_overdue")
async def order_list_overdue(tenant_id: str, warehouse: str | None = None) -> dict:
    from uuid import UUID
    async with SessionLocal() as session:
        orders = await ErpToolService(session).order_list_overdue(UUID(tenant_id), warehouse)
        return {"orders": orders}


if __name__ == "__main__":
    server.run(transport="stdio")
```

其余只读工具按同样模式注册；每个工具第一个参数都是 `tenant_id`，由编排器注入：

```python
@server.tool(name="order_get")
async def order_get(tenant_id: str, order_id: str) -> dict:
    from uuid import UUID
    async with SessionLocal() as session:
        return await ErpToolService(session).order_get(UUID(tenant_id), UUID(order_id))


@server.tool(name="inventory_get")
async def inventory_get(tenant_id: str, sku_id: str, warehouse_id: str) -> dict:
    from uuid import UUID
    async with SessionLocal() as session:
        return await ErpToolService(session).inventory_get(
            UUID(tenant_id), UUID(sku_id), UUID(warehouse_id)
        )


@server.tool(name="shipment_list")
async def shipment_list(tenant_id: str, order_id: str) -> dict:
    from uuid import UUID
    async with SessionLocal() as session:
        return {"shipments": await ErpToolService(session).shipment_list(UUID(tenant_id), UUID(order_id))}


@server.tool(name="order_get_state")
async def order_get_state(tenant_id: str, order_id: str) -> dict:
    from uuid import UUID
    async with SessionLocal() as session:
        return await ErpToolService(session).order_get_state(UUID(tenant_id), UUID(order_id))


@server.tool(name="address_validate")
async def address_validate(tenant_id: str, order_id: str) -> dict:
    from uuid import UUID
    async with SessionLocal() as session:
        return await ErpToolService(session).address_validate(UUID(order_id), UUID(tenant_id))
```


`tools/client.py`：

```python
import json
import sys
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


class ErpToolClient:
    def __init__(self) -> None:
        self._stack = AsyncExitStack()
        self._session: ClientSession | None = None

    async def __aenter__(self) -> "ErpToolClient":
        params = StdioServerParameters(command=sys.executable, args=["-m", "opsconductor.tools.server"])
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._stack.aclose()

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        assert self._session is not None
        result = await self._session.call_tool(name, arguments)
        if result.is_error:
            raise RuntimeError(f"MCP tool {name} failed")
        if result.structured_content is not None:
            return result.structured_content
        return json.loads(result.content[0].text)
```

- [ ] **Step 4: 写 MCP 工具测试**

`tests/test_mcp_tools.py` 直接测试 `ErpToolService`，并增加一个标记为 `integration` 的测试启动 stdio 客户端调用 `order_list_overdue`。集成测试使用 `OPSCONDUCTOR_DATABASE_URL` 指向测试库。

- [ ] **Step 5: 运行测试**

```bash
pytest tests/test_repositories.py tests/test_mcp_tools.py -q
```

- [ ] **Step 6: 提交**

```bash
git add src/opsconductor/domain/repositories.py src/opsconductor/tools tests/test_repositories.py tests/test_mcp_tools.py
git commit -m "feat: add read repositories and MCP read tools"
```

### Task 6: 模板 Planner、LLM 网关与计划生成

**Files:**
- Create: `src/opsconductor/llm/gateway.py`
- Create: `src/opsconductor/orchestrator/planner.py`
- Create: `tests/test_planner.py`

**Interfaces:**
- `TemplatePlanner(session).plan(task) -> Plan`
- `ChatModel.complete_json(system, user) -> dict[str, Any]`
- `StubChatModel(responses: list[dict])`
- `HttpChatModel(base_url, api_key, model)`
- `LLMPlanner(model, session).plan(task) -> Plan`

- [ ] **Step 1: 写模板 Planner 测试**

```python
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from opsconductor.db import SessionLocal
from opsconductor.domain.seed import TENANT_A
from opsconductor.orchestrator.planner import TemplatePlanner


@pytest.mark.asyncio
async def test_template_planner_blocks_stockout_and_plans_split(seeded_db):
    async with SessionLocal() as session:
        task = SimpleNamespace(
            id=uuid4(),
            tenant_id=TENANT_A,
            instruction="处理今天华东仓超时未发货的订单",
            warehouse="east",
            cutoff=datetime(2026, 11, 4, tzinfo=timezone.utc),
        )
        plan = await TemplatePlanner(session).plan(task)
    actions = {node.action for node in plan.nodes}
    assert "split_order" in actions
    assert "block_order" in actions
    assert "change_address" in actions
```

测试必须覆盖：O1001 产生 `split_order`；O1003 产生 `block_order`；O1002 产生 `change_address`。

- [ ] **Step 2: 实现模板 Planner**

`TemplatePlanner` 先通过 `ErpToolService` 或仓储读取订单行、库存、发货单；对每个订单：
- 已有发货单 → `block_order`，原因 `already_split`；
- 库存不足 → `block_order`，原因 `insufficient_stock`；
- 地址无效 → `change_address`，`params={"address": normalized_address(order)}`；
- 否则 → `split_order`，例如 `params={"shipments": [{"warehouse_id": str(order.warehouse_id), "lines": [{"sku_id": str(line.sku_id), "qty": line.qty} for line in lines]}]}`；多行订单按每行生成一个发货单。

`normalized_address` 在 `domain/address.py` 实现：当 `address_detail` 为空时返回 `city + district + "世纪大道100号"`；测试覆盖。

- [ ] **Step 3: 实现 LLM 网关与 LLM Planner**

`llm/gateway.py`：

```python
import json
from typing import Any, Protocol

import httpx


class ChatModel(Protocol):
    async def complete_json(self, *, system: str, user: str) -> dict[str, Any]: ...


class StubChatModel:
    def __init__(self, responses: list[dict[str, Any]]):
        self.responses = list(responses)

    async def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        if not self.responses:
            raise RuntimeError("no stub response left")
        return self.responses.pop(0)


class HttpChatModel:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            return json.loads(response.json()["choices"][0]["message"]["content"])
```

`LLMPlanner` 把工具清单、订单摘要和输出 schema 放入 system prompt；解析后用 `Plan.model_validate` 校验；失败时调用一次修复；再失败则抛错，由上层降级到 `TemplatePlanner`。测试使用 `StubChatModel`，不需要真实网络：

```python
@pytest.mark.asyncio
async def test_stub_chat_model_returns_queued_json():
    from opsconductor.llm.gateway import StubChatModel

    model = StubChatModel([{"ok": True}])
    assert await model.complete_json(system="s", user="u") == {"ok": True}
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/test_planner.py -q
```

- [ ] **Step 5: 提交**

```bash
git add src/opsconductor/llm src/opsconductor/orchestrator/planner.py tests/test_planner.py
git commit -m "feat: add template and LLM planners"
```

### Task 7: 身份、任务 API 与幂等

**Files:**
- Create: `src/opsconductor/api/deps.py`
- Create: `src/opsconductor/api/routes/tasks.py`
- Create: `src/opsconductor/orchestrator/idempotency.py`
- Modify: `src/opsconductor/api/main.py`
- Create: `tests/test_tasks_api.py`

**Interfaces:**
- `Identity(tenant_id, user_id, role)`
- `get_identity(x_api_key, session) -> Identity`
- `create_task(session, identity, payload, idempotency_key) -> TaskRead`
- `GET /api/v1/tasks/{id}`

- [ ] **Step 1: 写 API 测试**

```python
import pytest
from httpx import ASGITransport, AsyncClient

from opsconductor.api.main import app


@pytest.mark.asyncio
async def test_create_task_is_idempotent(seeded_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"X-API-Key": "dev-operator-a", "Idempotency-Key": "task-1"}
        body = {"instruction": "处理今天华东仓超时未发货的订单", "warehouse": "east", "cutoff": "2026-11-04T00:00:00Z"}
        first = await client.post("/api/v1/tasks", json=body, headers=headers)
        second = await client.post("/api/v1/tasks", json=body, headers=headers)
        assert first.status_code == 200
        assert first.json()["id"] == second.json()["id"]
```

- [ ] **Step 2: 实现身份依赖**

```python
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opsconductor.db import get_session
from opsconductor.domain.models import User
from opsconductor.domain.security import hash_api_key


@dataclass(frozen=True)
class Identity:
    tenant_id: UUID
    user_id: UUID
    role: str


async def get_identity(
    x_api_key: str = Header(..., alias="X-API-Key"),
    session: AsyncSession = Depends(get_session),
) -> Identity:
    user = await session.scalar(select(User).where(User.api_key_hash == hash_api_key(x_api_key)))
    if user is None:
        raise HTTPException(status_code=401, detail="invalid api key")
    return Identity(user.tenant_id, user.id, user.role)
```

- [ ] **Step 3: 实现任务创建与幂等**

`create_task`：
1. 计算请求哈希 `sha256(json.dumps(payload.model_dump(), sort_keys=True))`。
2. 查 `IdempotencyKey`（scope=`task.create`，key=header）；存在且哈希不同 → 409；相同 → 返回存储的 response。
3. 创建 `TaskRun(status="received")`。
4. 用 `TemplatePlanner` 生成计划（LLM Planner 可用配置切换）；`validate_plan`。
5. 创建 `Approval` 记录（每个 `requires_approval` 节点一条），`expires_at = now + approval_timeout_minutes`。
6. 保存 `TaskRun.plan`，状态 `awaiting_approval`。
7. 返回 `TaskRead`。

- [ ] **Step 4: 注册路由并运行测试**

```bash
pytest tests/test_tasks_api.py -q
```

- [ ] **Step 5: 提交**

```bash
git add src/opsconductor/api src/opsconductor/orchestrator/idempotency.py tests/test_tasks_api.py
git commit -m "feat: add task API with idempotency"
```

## Phase 3：审计、写操作与审批（第 2 周）

### Task 8: 审计与 Trace

**Files:**
- Create: `src/opsconductor/observability/audit.py`
- Create: `src/opsconductor/observability/trace.py`
- Create: `tests/test_audit_trace.py`

**Interfaces:**
- `write_audit(session, *, tenant_id, task_id, actor_id, action, entity_type, entity_id, before, after, evidence)`
- `TraceRecorder.start(name, task_id, tenant_id, parent_span_id=None, attributes=None)` 上下文管理器

- [ ] **Step 1: 写测试**

测试断言：写入一条 `AuditLog`；trace span 有 `trace_id`、`span_id`、父子关系、结束时间。

- [ ] **Step 2: 实现审计与 trace**

提供 `TraceRecorder`，在 `__aenter__` 写 `TraceSpan(started_at=now)`，在 `__aexit__` 更新 `ended_at` 和 attributes；span ID 用 `uuid.uuid4().hex`。

- [ ] **Step 3: 运行测试并提交**

```bash
pytest tests/test_audit_trace.py -q
git add src/opsconductor/observability tests/test_audit_trace.py
git commit -m "feat: add audit log and trace spans"
```

### Task 9: 拆单写操作与补偿

**Files:**
- Create: `src/opsconductor/domain/write_service.py`
- Modify: `src/opsconductor/tools/service.py`
- Modify: `src/opsconductor/tools/server.py`
- Create: `tests/test_write_split.py`

**Interfaces:**
- `split_order(session, tenant_id, order_id, shipments, idempotency_key, dry_run, actor_id, task_id) -> dict`
- `cancel_split(session, tenant_id, order_id, idempotency_key, task_id) -> dict`

- [ ] **Step 1: 写失败测试**

覆盖：
- O1001 拆单成功后订单 `split`，生成两个 `shipment`，库存 `available` 减少、`reserved` 增加；
- `dry_run=True` 不写库；
- 同一幂等键重复调用返回同一结果；
- O1003 库存不足抛 `InsufficientStock`；
- O1005 已有发货单抛 `InvalidState`。

- [ ] **Step 2: 实现拆单事务**

```python
import hashlib
import json
import uuid
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opsconductor.domain.models import (
    IdempotencyKey, Inventory, InventoryLedger, SalesOrder, Shipment, ShipmentLine,
)
from opsconductor.observability.audit import write_audit


async def split_order(session, tenant_id, order_id, shipments, idempotency_key, dry_run, actor_id, task_id):
    scope = f"order.split:{order_id}"
    request_hash = hashlib.sha256(
        json.dumps({"order_id": str(order_id), "shipments": shipments}, sort_keys=True, default=str).encode()
    ).hexdigest()
    existing = await session.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.tenant_id == tenant_id,
            IdempotencyKey.scope == scope,
            IdempotencyKey.key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise ValueError("idempotency conflict")
        return existing.response or {}

    order = await session.scalar(
        select(SalesOrder).where(SalesOrder.tenant_id == tenant_id, SalesOrder.id == order_id).with_for_update()
    )
    if order is None:
        raise ValueError("order not found")
    if order.status != "pending_shipment":
        raise ValueError("invalid state")
    if await session.scalar(select(Shipment).where(Shipment.order_id == order_id)):
        raise ValueError("already split")

    impact = []
    for shipment in shipments:
        for line in shipment["lines"]:
            inv = await session.scalar(
                select(Inventory).where(
                    Inventory.tenant_id == tenant_id,
                    Inventory.sku_id == line["sku_id"],
                    Inventory.warehouse_id == shipment["warehouse_id"],
                ).with_for_update()
            )
            if inv is None or inv.available < line["qty"]:
                raise ValueError("insufficient stock")
            impact.append({"sku_id": str(line["sku_id"]), "qty": line["qty"], "available": inv.available})

    if dry_run:
        return {"dry_run": True, "order_id": str(order_id), "impact": impact}

    for shipment in shipments:
        shipment_id = uuid.uuid4()
        session.add(Shipment(id=shipment_id, tenant_id=tenant_id, order_id=order_id, warehouse_id=shipment["warehouse_id"]))
        for line in shipment["lines"]:
            inv = await session.scalar(
                select(Inventory).where(
                    Inventory.tenant_id == tenant_id,
                    Inventory.sku_id == line["sku_id"],
                    Inventory.warehouse_id == shipment["warehouse_id"],
                ).with_for_update()
            )
            inv.available -= line["qty"]
            inv.reserved += line["qty"]
            inv.version += 1
            session.add(InventoryLedger(
                tenant_id=tenant_id, sku_id=line["sku_id"], warehouse_id=shipment["warehouse_id"],
                delta_available=-line["qty"], delta_reserved=line["qty"], reason="order_split", task_id=task_id,
            ))
            session.add(ShipmentLine(tenant_id=tenant_id, shipment_id=shipment_id, sku_id=line["sku_id"], qty=line["qty"]))

    order.status = "split"
    order.version += 1
    response = {"order_id": str(order_id), "shipments": len(shipments), "status": "split"}
    session.add(IdempotencyKey(
        tenant_id=tenant_id, scope=scope, key=idempotency_key,
        request_hash=request_hash, response=response,
    ))
    await write_audit(
        session, tenant_id=tenant_id, task_id=task_id, actor_id=actor_id,
        action="order.split", entity_type="sales_order", entity_id=str(order_id),
        before={"status": "pending_shipment"}, after={"status": "split"}, evidence={"impact": impact},
    )
    await session.commit()
    return response


async def cancel_split(session, tenant_id, order_id, idempotency_key, task_id):
    scope = f"order.split.cancel:{order_id}"
    existing = await session.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.tenant_id == tenant_id,
            IdempotencyKey.scope == scope,
            IdempotencyKey.key == idempotency_key,
        )
    )
    if existing is not None:
        return existing.response or {}

    order = await session.scalar(
        select(SalesOrder).where(SalesOrder.tenant_id == tenant_id, SalesOrder.id == order_id).with_for_update()
    )
    if order is None:
        return {"order_id": str(order_id), "status": "missing"}
    shipments = list((await session.scalars(
        select(Shipment).where(Shipment.tenant_id == tenant_id, Shipment.order_id == order_id)
    )).all())
    for shipment in shipments:
        lines = list((await session.scalars(
            select(ShipmentLine).where(ShipmentLine.tenant_id == tenant_id, ShipmentLine.shipment_id == shipment.id)
        )).all())
        for line in lines:
            inv = await session.scalar(
                select(Inventory).where(
                    Inventory.tenant_id == tenant_id,
                    Inventory.sku_id == line.sku_id,
                    Inventory.warehouse_id == shipment.warehouse_id,
                ).with_for_update()
            )
            inv.available += line.qty
            inv.reserved -= line.qty
            inv.version += 1
            session.add(InventoryLedger(
                tenant_id=tenant_id, sku_id=line.sku_id, warehouse_id=shipment.warehouse_id,
                delta_available=line.qty, delta_reserved=-line.qty, reason="split_compensation", task_id=task_id,
            ))
        shipment.status = "cancelled"
    order.status = "pending_shipment"
    order.version += 1
    response = {"order_id": str(order_id), "shipments_cancelled": len(shipments), "status": "compensated"}
    session.add(IdempotencyKey(
        tenant_id=tenant_id, scope=scope, key=idempotency_key,
        request_hash="compensation", response=response,
    ))
    await write_audit(
        session, tenant_id=tenant_id, task_id=task_id, actor_id=None,
        action="order.split.cancel", entity_type="sales_order", entity_id=str(order_id),
        before={"status": "split"}, after={"status": "pending_shipment"}, evidence={"shipments": len(shipments)},
    )
    await session.commit()
    return response
```

- [ ] **Step 3: 暴露 MCP 写工具并运行测试**

注册 `order_split`、`shipment_cancel`、`inventory_release`、`order_revert_split`；测试直接调用 `write_service`，MCP 集成测试走客户端。

```bash
pytest tests/test_write_split.py -q
```

- [ ] **Step 4: 提交**

```bash
git add src/opsconductor/domain/write_service.py src/opsconductor/tools tests/test_write_split.py
git commit -m "feat: add split order write path and compensation"
```

### Task 10: 改址写操作与补偿

**Files:**
- Modify: `src/opsconductor/domain/write_service.py`
- Create: `src/opsconductor/domain/address.py`
- Modify: `src/opsconductor/tools/server.py`
- Create: `tests/test_write_address.py`

**Interfaces:**
- `change_address(session, tenant_id, order_id, new_address, idempotency_key, dry_run, actor_id, task_id) -> dict`
- `revert_address(session, tenant_id, order_id, before_address, idempotency_key, task_id) -> dict`

- [ ] **Step 1: 写测试**

覆盖：发货前改址成功、订单状态不变、审计有前后值；已拆单（O1005）拒绝；非法地址拒绝；重复幂等键返回同一结果；补偿恢复原地址。

- [ ] **Step 2: 实现改址**

前置条件：订单 `pending_shipment`，无发货单；地址字段通过 `address_is_valid` 校验。`dry_run=True` 只返回 before/after；否则更新地址、写审计、存幂等响应。补偿用 `revert_address` 恢复 `before` 字段。

- [ ] **Step 3: 运行测试并提交**

```bash
pytest tests/test_write_address.py -q
git add src/opsconductor/domain/write_service.py src/opsconductor/domain/address.py src/opsconductor/tools/server.py tests/test_write_address.py
git commit -m "feat: add address change and compensation"
```

### Task 11: 风险分级、审批 API 与状态机

**Files:**
- Create: `src/opsconductor/orchestrator/policy.py`
- Create: `src/opsconductor/orchestrator/approval.py`
- Create: `src/opsconductor/api/routes/approvals.py`
- Modify: `src/opsconductor/api/main.py`
- Create: `tests/test_approvals.py`

**Interfaces:**
- `RiskPolicy.assign(plan, split_count) -> RiskLevel`
- `ApprovalService.decide(task_id, identity, approved, comment, order_id=None) -> TaskRun`
- `POST /api/v1/tasks/{id}/approve`、`POST /api/v1/tasks/{id}/reject`

- [ ] **Step 1: 写测试**

覆盖：L2 通过执行；L2 拒绝跳过；批量拆分 ≥ 阈值升级 L3；L3 需要 approver 角色；重复审批幂等；审批超时任务保持 `awaiting_approval`。

- [ ] **Step 2: 实现风险策略与审批服务**

`RiskPolicy.assign`：每个 `split_order`/`change_address` 节点 L2；如果同一任务 `split_order` 数量 ≥ `settings.l3_batch_threshold`，全部拆分节点升级 L3。`ApprovalService.decide`：校验审批记录属于租户、状态 pending、角色允许；写入 `approver_id`、`status`、`decided_at`、`comment`；重复调用返回当前状态，不重复写审计。

- [ ] **Step 3: 运行测试并提交**

```bash
pytest tests/test_approvals.py -q
git add src/opsconductor/orchestrator/policy.py src/opsconductor/orchestrator/approval.py src/opsconductor/api/routes/approvals.py src/opsconductor/api/main.py tests/test_approvals.py
git commit -m "feat: add risk policy and approval API"
```

## Phase 4：执行器、验证与控制台（第 2 周后半）

### Task 12: LangGraph 执行图、Verifier 与补偿

**Files:**
- Create: `src/opsconductor/orchestrator/executor.py`
- Create: `src/opsconductor/orchestrator/verifier.py`
- Create: `src/opsconductor/orchestrator/graph.py`
- Create: `tests/test_executor.py`

**Interfaces:**
- `TaskExecutor.start(task_id) -> ExecutionResult`
- `TaskExecutor.resume(task_id, approved: bool) -> ExecutionResult`
- `Verifier.verify(task, plan, results) -> VerificationResult`

- [ ] **Step 1: 写执行测试**

使用 `StubChatModel`、`FakeToolClient`（记录调用）和 seeded DB：
- 审批通过 → 拆单/改址工具被调用，订单最终状态正确；
- 后置条件失败 → 补偿工具被调用，库存释放、订单回退；
- 审批拒绝 → 无写操作，任务 `partially_succeeded`；
- 重复执行 → 已成功的 `TaskStep` 被跳过，不重复写。

- [ ] **Step 2: 实现执行图**

```python
from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt


class ExecutionState(TypedDict, total=False):
    task_id: str
    tenant_id: str
    approved: bool
    plan: dict
    results: dict
    verified: bool
    report: dict


async def approval_node(state: ExecutionState) -> dict:
    if "approved" in state:
        return {"approved": state["approved"]}
    decision = interrupt({"task_id": state["task_id"], "plan": state["plan"], "type": "approval"})
    return {"approved": bool(decision.get("approved"))}


def build_graph(nodes):
    builder = StateGraph(ExecutionState)
    builder.add_node("load", nodes.load)
    builder.add_node("approval", approval_node)
    builder.add_node("dry_run", nodes.dry_run)
    builder.add_node("execute", nodes.execute)
    builder.add_node("verify", nodes.verify)
    builder.add_node("compensate", nodes.compensate)
    builder.add_node("report", nodes.report)
    builder.add_edge(START, "load")
    builder.add_edge("load", "approval")
    builder.add_conditional_edges("approval", lambda s: "dry_run" if s.get("approved") else "report")
    builder.add_edge("dry_run", "execute")
    builder.add_edge("execute", "verify")
    builder.add_conditional_edges("verify", lambda s: "report" if s.get("verified") else "compensate")
    builder.add_edge("compensate", "report")
    builder.add_edge("report", END)
    return builder.compile(checkpointer=InMemorySaver())
```

`TaskExecutor.start` 用 `thread_id=task_id` 调用 `ainvoke`；如果返回 `__interrupt__`，把任务状态设为 `awaiting_approval`。`resume` 在同一个进程用 `Command(resume={"approved": approved})`；如果 checkpointer 没有状态（进程重启），重建 graph 并以 `approved=approved` 作为初始状态，`approval_node` 不再 interrupt。执行节点按 `TaskStep` 跳过已成功节点。

- [ ] **Step 3: 实现 Verifier**

```python
from uuid import UUID

from pydantic import BaseModel

from opsconductor.domain import repositories
from opsconductor.domain.models import OrderLine, ShipmentLine
from sqlalchemy import select


class VerificationResult(BaseModel):
    passed: bool
    reason: str = ""


class Verifier:
    def __init__(self, session):
        self.session = session

    async def verify(self, task, plan, results) -> VerificationResult:
        for action in plan["nodes"]:
            if action["action"] == "split_order":
                order = await repositories.get_order(self.session, task.tenant_id, UUID(action["order_id"]))
                if order is None or order.status != "split":
                    return VerificationResult(passed=False, reason=f"order {action['order_id']} not split")
                shipments = await repositories.list_shipments(self.session, task.tenant_id, order.id)
                if not shipments:
                    return VerificationResult(passed=False, reason="no shipments")
                shipped = 0
                for shipment in shipments:
                    shipped += len((await self.session.scalars(
                        select(ShipmentLine).where(
                            ShipmentLine.tenant_id == task.tenant_id,
                            ShipmentLine.shipment_id == shipment.id,
                        )
                    )).all())
                order_lines = len((await self.session.scalars(
                    select(OrderLine).where(OrderLine.tenant_id == task.tenant_id, OrderLine.order_id == order.id)
                )).all())
                if shipped != order_lines:
                    return VerificationResult(passed=False, reason="shipment lines mismatch")
                for line in (await self.session.scalars(
                    select(OrderLine).where(OrderLine.tenant_id == task.tenant_id, OrderLine.order_id == order.id)
                )).all():
                    inv = await repositories.get_inventory(self.session, task.tenant_id, line.sku_id, order.warehouse_id)
                    if inv is None or inv.available < 0 or inv.reserved < 0:
                        return VerificationResult(passed=False, reason="inventory negative")
            if action["action"] == "change_address":
                order = await repositories.get_order(self.session, task.tenant_id, UUID(action["order_id"]))
                expected = action["params"].get("address")
                if order is not None and expected and order.address_detail != expected:
                    return VerificationResult(passed=False, reason="address mismatch")
        return VerificationResult(passed=True)
```

确定性检查必须覆盖：订单状态、发货单行与订单行一致、库存 `available >= 0`、`reserved >= 0`、地址与计划一致、审计存在。LLM 复核可作为可选步骤，使用独立模型；离线时只跑确定性检查。

- [ ] **Step 4: 运行测试并提交**

```bash
pytest tests/test_executor.py -q
git add src/opsconductor/orchestrator/executor.py src/opsconductor/orchestrator/verifier.py src/opsconductor/orchestrator/graph.py tests/test_executor.py
git commit -m "feat: add execution graph, verifier and compensation"
```

### Task 13: 控制台页面

**Files:**
- Create: `src/opsconductor/api/routes/console.py`
- Create: `src/opsconductor/templates/console/base.html`
- Create: `src/opsconductor/templates/console/tasks.html`
- Create: `src/opsconductor/templates/console/task_detail.html`
- Create: `src/opsconductor/templates/console/trace.html`
- Create: `tests/test_console.py`

**Interfaces:**
- `GET /console/tasks`
- `GET /console/tasks/{id}`
- `POST /console/tasks/{id}/approve`
- `POST /console/tasks/{id}/reject`

- [ ] **Step 1: 写页面测试**

断言任务列表包含 `O1001` 计划摘要；详情页包含审批按钮、trace 区块；拒绝后任务状态变为 `partially_succeeded` 或 `running` 的预期状态。

- [ ] **Step 2: 实现页面**

使用 `Jinja2Templates(directory="src/opsconductor/templates")`；任务详情展示计划节点、风险、依赖、证据、审批状态、trace span。审批表单 POST 到控制台路由，调用 `ApprovalService` 后重定向。

- [ ] **Step 3: 运行测试并提交**

```bash
pytest tests/test_console.py -q
git add src/opsconductor/api/routes/console.py src/opsconductor/templates tests/test_console.py
git commit -m "feat: add approval console and trace views"
```

## Phase 5：评测、演示与收尾（第 3 周）

### Task 14: 失败注入与 28 条 Golden Tasks

**Files:**
- Create: `src/opsconductor/tools/faults.py`
- Create: `tests/eval/cases.py`
- Create: `tests/eval/test_golden_tasks.py`
- Create: `scripts/smoke_live.py`

**Interfaces:**
- `FaultInjector.set(**faults)`、`FaultInjector.check(tool_name)`。
- 28 条 case：主路径 5、校验/状态 4、库存 4、审批 5、幂等 3、失败/补偿 5、租户/安全 2。

- [ ] **Step 1: 实现故障注入**

```python
import contextvars
from contextlib import contextmanager
from typing import Iterator

_current: contextvars.ContextVar[dict[str, str]] = contextvars.ContextVar("faults", default={})


@contextmanager
def inject(**faults: str) -> Iterator[None]:
    token = _current.set({**_current.get(), **faults})
    try:
        yield
    finally:
        _current.reset(token)


def check(tool_name: str) -> None:
    fault = _current.get().get(tool_name)
    if fault == "timeout":
        raise TimeoutError(f"{tool_name} timeout")
    if fault == "upstream":
        raise RuntimeError(f"{tool_name} upstream error")
```

在 `ErpToolClient.call` 或测试用 `FakeToolClient` 中调用 `check(name)`；补偿失败用例通过注入 `shipment_cancel=timeout` 模拟。

- [ ] **Step 2: 写 28 条 case 表与参数化测试**

`tests/eval/cases.py` 定义 `GoldenCase(id, category, instruction, expected_status, expected_orders, forbidden_writes)`；覆盖 MVP 规格第 9.1 节的 GT-01 到 GT-28。测试用 `pytest.mark.parametrize` 驱动：
- 创建任务；
- 按 case 审批/拒绝；
- 调用 executor；
- 断言订单状态、发货单数量、库存、审计、审批、幂等记录、trace 完整。

- [ ] **Step 3: 真实模型冒烟脚本**

`scripts/smoke_live.py` 读取 `OPSCONDUCTOR_LLM_*`，对 5–10 条主路径调用真实模型；没有密钥时打印 `SKIPPED`，退出码 0。结果单独输出，不作为 pytest 硬门槛。

- [ ] **Step 4: 运行评测**

```bash
pytest tests/eval -q
python scripts/smoke_live.py
```

- [ ] **Step 5: 提交**

```bash
git add src/opsconductor/tools/faults.py tests/eval scripts/smoke_live.py
git commit -m "test: add failure injection and golden task suite"
```

### Task 15: 演示、文档与收尾

**Files:**
- Modify: `README.md`
- Create: `docs/demo-script.md`
- Create: `docs/adr/0004-mvp-approval-and-idempotency.md`
- Create: `scripts/demo.sh`

**Interfaces:**
- `scripts/demo.sh` 启动依赖、迁移、种子、API、控制台。
- `docs/demo-script.md` 逐分钟演示脚本。

- [ ] **Step 1: 写演示脚本**

```bash
#!/usr/bin/env bash
set -euo pipefail
docker compose up -d
conda run -n opsconductor alembic upgrade head
conda run -n opsconductor python -m opsconductor.domain.seed
conda run -n opsconductor uvicorn opsconductor.api.main:app --reload
```

- [ ] **Step 2: 更新 README 与演示文档**

README 增加：启动命令、演示账号、控制台地址、审批流程、故障注入命令、测试命令。`docs/demo-script.md` 按「提交任务 → 计划 → 审批 → 执行 → 失败补偿 → trace/report」写 3 分钟脚本。

- [ ] **Step 3: 写 ADR 0004**

记录 MVP 决策：审批采用外部任务状态 + LangGraph interrupt；幂等键作用域；拆单建模为发货单；补偿边界。包含背景、决策、后果、备选方案。

- [ ] **Step 4: 运行完整验证**

```bash
pytest -q
ruff check .
mypy src
```

- [ ] **Step 5: 提交**

```bash
git add README.md docs/demo-script.md docs/adr/0004-mvp-approval-and-idempotency.md scripts/demo.sh
git commit -m "docs: add MVP demo, ADR and runbook"
```

---

## 自检清单

- [ ] 28 条 Golden Tasks 全部有对应 case ID 和断言。
- [ ] 每个写操作测试同时断言审计与幂等。
- [ ] 失败注入测试断言补偿后的最终一致性。
- [ ] 所有查询和写入带 `tenant_id`。
- [ ] 所有 MCP 工具名与客户端调用一致。
- [ ] `TaskStatus`、`RiskLevel`、`ApprovalStatus` 在计划、审批、执行、报告中一致。
- [ ] `pytest -q`、`ruff check .`、`mypy src` 通过。
