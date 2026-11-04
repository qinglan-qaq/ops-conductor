"""ORM 模型使用的声明式基类与共享时间戳列。"""

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有 OpsConductor ORM 模型的声明式基类。

    模型声明的是普通类型化列而非 ORM 关系，因此遍历外键意味着显式查询。此处的
    元数据必须与 ``migrations/`` 中的 Alembic 迁移保持同步。
    """


class TimestampMixin:
    """添加由数据库管理的 ``created_at`` 与 ``updated_at`` 时间戳。

    Attributes:
        created_at: 插入时间戳，由数据库的 ``now()`` 默认值填充。
        updated_at: 最后更新时间戳，每当 ORM 为该行发出 ``UPDATE`` 时由数据库
            刷新。

    Note:
        这些值来自数据库时钟而非应用，因此刚暂存的对象在 flush 或过期前保持
        ``None``。测试不应假定这些时间戳与本地捕获的 ``now()`` 一致。
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
