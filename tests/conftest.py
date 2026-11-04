import os
import pathlib
import tempfile

# The test database must be configured before opsconductor.config / opsconductor.db
# are imported, because the module-level engine binds the URL at import time.
# Docker/PostgreSQL is unavailable in this environment, so tests use file-based SQLite.
db_file = pathlib.Path(tempfile.gettempdir()) / "opsconductor_test.db"
os.environ["OPSCONDUCTOR_DATABASE_URL"] = f"sqlite+aiosqlite:///{db_file.as_posix()}"

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
