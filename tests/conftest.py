import asyncio
import os
import sys

# psycopg async connections require a selector event loop on Windows.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# The test database must be configured before opsconductor.config / opsconductor.db
# are imported, because the module-level engine binds the URL at import time.
# Tests use the Dockerized PostgreSQL instance from docker-compose.yml, which maps
# container port 5432 to host port 15432.
os.environ["OPSCONDUCTOR_DATABASE_URL"] = (
    "postgresql+psycopg://ops:ops@localhost:15432/opsconductor_test"
)

import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from opsconductor.config import get_settings  # noqa: E402
from opsconductor.domain import Base  # noqa: E402


@pytest_asyncio.fixture
async def test_engine():
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_db(test_engine):
    from opsconductor.db import SessionLocal
    from opsconductor.domain.seed import seed

    async with SessionLocal() as session:
        await seed(session)
    yield


@pytest_asyncio.fixture
async def approved_task(seeded_db):
    """Create a running task with one approved write approval for MCP tests."""

    from datetime import UTC, datetime, timedelta
    from uuid import NAMESPACE_DNS, uuid4, uuid5

    from opsconductor.db import SessionLocal
    from opsconductor.domain.models import Approval, TaskRun
    from opsconductor.domain.seed import TENANT_A

    operator_id = uuid5(NAMESPACE_DNS, "opsconductor.user-operator-a")

    async def create(order_id, action: str):
        task_id = uuid4()
        now = datetime.now(UTC)
        async with SessionLocal() as session:
            session.add(
                TaskRun(
                    id=task_id,
                    tenant_id=TENANT_A,
                    user_id=operator_id,
                    task_type="order_exception",
                    instruction="MCP approval fixture",
                    status="running",
                )
            )
            await session.flush()
            session.add(
                Approval(
                    tenant_id=TENANT_A,
                    task_id=task_id,
                    order_id=order_id,
                    action=action,
                    risk_level="L2",
                    status="approved",
                    approver_id=operator_id,
                    expires_at=now + timedelta(minutes=30),
                    decided_at=now,
                )
            )
            await session.commit()
        return task_id

    return create
