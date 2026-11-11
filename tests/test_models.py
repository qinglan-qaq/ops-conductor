import uuid

import pytest
from sqlalchemy import select

from opsconductor.db import SessionLocal
from opsconductor.domain.models import Base, Tenant, User
from opsconductor.domain.security import hash_api_key


@pytest.mark.asyncio
async def test_create_tenant_and_user(test_engine):
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as session:
        tenant = Tenant(id=uuid.uuid4(), name="tenant-a")
        session.add(tenant)
        await session.flush()
        user = User(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            name="operator-a",
            role="operator",
            api_key_hash=hash_api_key("dev-operator-a"),
        )
        session.add(user)
        await session.commit()
        loaded = await session.scalar(select(User).where(User.name == "operator-a"))
        assert loaded is not None
        assert loaded.tenant_id == tenant.id
