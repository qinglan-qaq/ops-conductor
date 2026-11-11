"""基于 ``trace_span`` 表的 trace span 记录。

:class:`TraceRecorder` 在调用方事务上写出 span 行，从不提交。调用方必须在
span 退出后提交，最终的 ``ended_at`` 更新才会持久化。

Invariants:

- span 在进入时 flush 一次；正常退出时更新结束时间并再次 flush。
- 被追踪代码抛出异常时不 flush，span 的结束时间与属性仅在内存中更新，原始
  异常原样传播。
- 父 span 继承按租户限定：只有同租户的父 span 会被采用，否则新起一条 trace。
"""

import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opsconductor.domain.models import TraceSpan


class TraceRecorder:
    """在调用方事务上记录 trace span。

    ``start`` 返回一个异步上下文管理器并产出所创建的 span，调用方可以把
    ``span.span_id`` 传给子 span。span 在进入与正常退出时 flush，但从不提交；
    调用方必须在 span 退出后提交，最终的 ``ended_at`` 更新才会持久化。被追踪
    代码抛出异常时，span 的结束时间与属性只在内存中设置，不尝试 flush，原始
    异常原样传播。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @asynccontextmanager
    async def start(
        self,
        name: str,
        task_id: uuid.UUID | None,
        tenant_id: uuid.UUID,
        parent_span_id: str | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[TraceSpan]:
        """创建并产出一次 trace span。

        Args:
            name: span 名称，例如 ``executor.execute`` 或 ``tool.order_split``。
            task_id: 关联任务；与任务无关的 span 可为 ``None``。
            tenant_id: span 归属租户；父 span 查找也限定在该租户内。
            parent_span_id: 父 span 的 ``span_id``；同租户时子 span 继承其
                ``trace_id``，找不到时新起一条 trace。
            attributes: 初始属性，会与上下文内写入的属性合并。

        Yields:
            已加入会话并 flush 的 :class:`TraceSpan`。

        Note:
            正常退出时更新 ``ended_at`` 并 flush；异常退出时只更新内存中的
            span，不 flush，让原始异常继续传播。本方法不提交事务。
        """
        parent = await self._find_parent(tenant_id, parent_span_id)
        initial_attributes = dict(attributes or {})
        span = TraceSpan(
            trace_id=parent.trace_id if parent is not None else uuid.uuid4().hex,
            span_id=uuid.uuid4().hex,
            parent_span_id=parent_span_id if parent is not None else None,
            tenant_id=tenant_id,
            task_id=task_id,
            name=name,
            started_at=datetime.now(UTC),
            attributes=initial_attributes or None,
        )
        self.session.add(span)
        await self.session.flush()
        try:
            yield span
        except BaseException:
            self._finish(span, initial_attributes)
            raise
        else:
            self._finish(span, initial_attributes)
            await self.session.flush()

    @staticmethod
    def _finish(span: TraceSpan, initial_attributes: dict[str, Any]) -> None:
        """设置结束时间，并合并初始属性与上下文内新增属性。"""

        span.ended_at = datetime.now(UTC)
        merged = {**initial_attributes, **(span.attributes or {})}
        span.attributes = merged or None

    async def _find_parent(
        self, tenant_id: uuid.UUID, parent_span_id: str | None
    ) -> TraceSpan | None:
        """仅在父 span 属于同一租户时返回它。"""

        if parent_span_id is None:
            return None
        return await self.session.scalar(
            select(TraceSpan).where(
                TraceSpan.tenant_id == tenant_id,
                TraceSpan.span_id == parent_span_id,
            )
        )
