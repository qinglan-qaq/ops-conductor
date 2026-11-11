"""进程级异步数据库引擎与会话工厂。

由于 ``psycopg`` 异步驱动要求 selector 事件循环，本模块会在创建
``psycopg`` 异步引擎之前将 Windows 切换为该策略。因此，导入本模块会改变
进程状态，导入 OpsConductor 的 MCP stdio 子进程同样如此。

事务由调用方负责：:func:`get_session` 仅限定会话的生命周期，并在关闭时回滚
未提交的工作。何时提交由 :mod:`opsconductor.domain.write_service` 中的服务
决定。
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
    """每次请求产出一个会话，并在退出时关闭。

    用于 FastAPI 依赖注入。会话不会自动提交；修改状态的代码必须显式提交。退出
    时上下文管理器会回滚所有未提交的工作，并将连接归还连接池。

    Yields:
        绑定到共享引擎的 ``AsyncSession``。

    Note:
        ``SessionLocal`` 设置了 ``expire_on_commit=False``，因此提交后已加载的
        属性无需额外刷新即可继续读取。
    """
    async with SessionLocal() as session:
        yield session
