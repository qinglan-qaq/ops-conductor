"""Authentication dependencies for the HTTP API."""

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
    """Authenticated caller resolved from an API key."""

    tenant_id: UUID
    user_id: UUID
    role: str


async def get_identity(
    session: Annotated[AsyncSession, Depends(get_session)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> Identity:
    """Resolve the caller's identity, rejecting missing or unknown API keys."""

    if not x_api_key:
        raise HTTPException(status_code=401, detail="invalid api key")
    user = await session.scalar(
        select(User).where(User.api_key_hash == hash_api_key(x_api_key))
    )
    if user is None:
        raise HTTPException(status_code=401, detail="invalid api key")
    return Identity(tenant_id=user.tenant_id, user_id=user.id, role=user.role)
