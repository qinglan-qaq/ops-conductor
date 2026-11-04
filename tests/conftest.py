import asyncio
import os
import sys

# psycopg async connections require a selector event loop on Windows.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# The test database must be configured before opsconductor.config / opsconductor.db
# are imported, because the module-level engine binds the URL at import time.
# Tests use the Dockerized PostgreSQL instance from docker-compose.yml.
os.environ["OPSCONDUCTOR_DATABASE_URL"] = (
    "postgresql+psycopg://ops:ops@localhost:5432/opsconductor_test"
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
