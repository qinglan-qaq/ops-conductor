"""Declarative base and shared timestamp columns for the ORM models."""

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for every OpsConductor ORM model.

    Models declare plain typed columns rather than ORM relationships, so
    traversing a foreign key means an explicit query. The metadata here must
    stay in sync with the Alembic migrations in ``migrations/``.
    """


class TimestampMixin:
    """Add database-managed ``created_at`` and ``updated_at`` timestamps.

    Attributes:
        created_at: Insert timestamp, populated by the database ``now()``
            default.
        updated_at: Last-update timestamp, refreshed by the database whenever
            the ORM emits an ``UPDATE`` for the row.

    Note:
        Values come from the database clock, not the application, so freshly
        staged objects hold ``None`` until they are flushed or expired. Tests
        should not assume these timestamps match a locally captured ``now()``.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
