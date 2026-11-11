"""HTTP API 的认证依赖。

认证只使用 API key：调用方在 ``X-API-Key`` 请求头中传入原始 key，服务端用
:func:`opsconductor.domain.security.hash_api_key` 计算摘要，并在唯一的
``api_key_hash`` 列上做等值查找。原始 key 从不写入数据库或日志。

Invariants:

- 缺失 key 与未知 key 都返回 401，且响应相同，避免向调用方泄露 key 是否存在。
- 认证成功后返回的 :class:`Identity` 是后续查询的唯一租户边界。
"""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opsconductor.db import get_session
from opsconductor.domain.models import User
from opsconductor.domain.security import hash_api_key


@dataclass(frozen=True)
class Identity:
    """从 API key 解析出的已认证调用方。

    Attributes:
        tenant_id: 调用方所属租户；所有业务查询都应以此为范围。
        user_id: 调用方用户 ID，用于审计与审批人记录。
        role: 调用方角色，例如 ``operator``、``approver`` 或 ``admin``。
    """

    tenant_id: UUID
    user_id: UUID
    role: str


async def get_identity(
    session: Annotated[AsyncSession, Depends(get_session)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> Identity:
    """解析调用方身份，拒绝缺失或未知的 API key。

    Args:
        session: 用于查找 ``User`` 行的会话。
        x_api_key: 调用方提供的原始 key；请求头缺失时为 ``None``。

    Returns:
        与该 key 关联的不可变 :class:`Identity`。

    Raises:
        HTTPException: key 缺失或无法匹配任何用户时返回 401
            ``invalid api key``。

    Note:
        这里只做认证，不做角色校验；角色相关的门禁由审批服务等下游组件负责。
    """

    if not x_api_key:
        raise HTTPException(status_code=401, detail="invalid api key")
    user = await session.scalar(
        select(User).where(User.api_key_hash == hash_api_key(x_api_key))
    )
    if user is None:
        raise HTTPException(status_code=401, detail="invalid api key")
    return Identity(tenant_id=user.tenant_id, user_id=user.id, role=user.role)
