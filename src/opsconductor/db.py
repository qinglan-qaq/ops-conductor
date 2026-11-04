"""Process-wide async database engine and session factory.

The module switches Windows to the selector event loop policy before creating
the ``psycopg`` async engine, which that driver requires. Importing the module
therefore changes process state, including in MCP stdio subprocesses that
import OpsConductor.

Transactions belong to callers: :func:`get_session` only scopes the session's
lifetime and rolls back uncommitted work when it closes. Services in
:mod:`opsconductor.domain.write_service` decide when to commit.
"""

import asyncio
import sys
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from opsconductor.config import get_settings

# psycopg async connections require a selector event loop on Windows. This also
# applies to subprocesses (for example the MCP stdio server) that import this module.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

settings = get_settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield one session per request and close it on exit.

    Intended for FastAPI dependency injection. The session is not committed
    automatically; code that mutates state must commit explicitly. On exit the
    context manager rolls back any uncommitted work and returns the connection
    to the pool.

    Yields:
        An ``AsyncSession`` bound to the shared engine.

    Note:
        ``SessionLocal`` sets ``expire_on_commit=False``, so loaded attributes
        remain readable after a commit without an extra refresh.
    """
    async with SessionLocal() as session:
        yield session
