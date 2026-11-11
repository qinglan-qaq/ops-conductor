"""任务创建的幂等记录。

任务创建由唯一的 ``(tenant_id, scope, key)`` 记录保护。记录保存归一化请求的指纹
与已返回的响应，因此使用相同键与载荷的重试会重放原始响应，而不是再创建一个任务。

Invariants:

- 作用域按操作命名空间划分；任务创建使用 :data:`TASK_CREATE_SCOPE`，因此同一个
  键可以被其他作用域独立使用。
- 指纹是用排序键转储请求后的 SHA-256，因此字段顺序永远不会改变请求身份。
- 以不同指纹复用键，或遇到尚未持久化响应的记录，都会抛出
  :class:`IdempotencyConflict`。
- 记录按租户限定：另一个租户使用相同的键互不相关。
"""

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opsconductor.domain.models import IdempotencyKey

TASK_CREATE_SCOPE = "task.create"


class IdempotencyConflict(Exception):
    """幂等键被复用于不同请求时抛出。"""


def request_hash(payload: Any) -> str:
    """为 Pydantic 模型或类 JSON 映射返回稳定的 SHA-256 哈希。

    Args:
        payload: Pydantic 模型（先转储为字典）或类 JSON 数据。键会排序，非
            JSON 值回退为 ``str``。

    Returns:
        规范化 JSON 编码的小写 SHA-256 十六进制摘要。
    """

    if hasattr(payload, "model_dump"):
        payload = payload.model_dump()
    encoded = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def get_existing_record(
    session: AsyncSession,
    tenant_id: UUID,
    scope: str,
    key: str,
    fingerprint: str,
) -> IdempotencyKey | None:
    """查找已存储的响应；请求哈希不同则抛出。

    Args:
        session: 调用方会话；查询不会提交。
        tenant_id: 拥有该记录的租户。
        scope: 操作作用域，例如 :data:`TASK_CREATE_SCOPE`。
        key: 调用方提供的幂等键。
        fingerprint: 当前请求负载的哈希。

    Returns:
        当键用于相同请求时返回已存储的记录；键未被使用时返回 ``None``。

    Raises:
        IdempotencyConflict: 键属于不同请求，或记录存在但没有已存储的响应。
    """

    record = await session.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.tenant_id == tenant_id,
            IdempotencyKey.scope == scope,
            IdempotencyKey.key == key,
        )
    )
    if record is None:
        return None
    if record.request_hash != fingerprint:
        raise IdempotencyConflict(f"idempotency key {key!r} was used with another request")
    if record.response is None:
        raise IdempotencyConflict(f"idempotency key {key!r} is still in progress")
    return record


def build_record(
    *,
    tenant_id: UUID,
    scope: str,
    key: str,
    fingerprint: str,
    response: dict[str, Any],
) -> IdempotencyKey:
    """为首次成功响应创建已完成的幂等记录。

    调用方把该记录与业务变更暂存在同一事务上，因此响应恰好在业务变更提交时变得
    可重放。

    Args:
        tenant_id: 拥有该记录的租户。
        scope: 操作作用域，例如 :data:`TASK_CREATE_SCOPE`。
        key: 调用方提供的幂等键。
        fingerprint: 请求负载的哈希。
        response: 重试时重放的 JSON 可序列化响应。

    Returns:
        一条尚未持久化、状态为 ``completed`` 的 ``IdempotencyKey`` 行。
    """

    return IdempotencyKey(
        tenant_id=tenant_id,
        scope=scope,
        key=key,
        request_hash=fingerprint,
        response=response,
        status="completed",
    )
