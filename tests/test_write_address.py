"""Tests for address-change writes, validation, idempotency, and compensation."""

import uuid

import pytest
from sqlalchemy import func, select

from opsconductor.db import SessionLocal
from opsconductor.domain.models import (
    AuditLog,
    IdempotencyKey,
    SalesOrder,
    Shipment,
)
from opsconductor.domain.seed import (
    SHOP_A,
    TENANT_A,
    TENANT_B,
    WAREHOUSE_EAST,
)
from opsconductor.domain.write_service import (
    IdempotencyConflict,
    InvalidState,
    NotFound,
    ValidationError,
    change_address,
    revert_address,
)
from opsconductor.tools.client import ErpToolClient

ORDER_O1002 = uuid.uuid5(uuid.NAMESPACE_DNS, "opsconductor.order-O1002")
ORDER_O1005 = uuid.uuid5(uuid.NAMESPACE_DNS, "opsconductor.order-O1005")
OPERATOR_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "opsconductor.user-operator-a")

ORIGINAL_O1002 = {
    "receiver_name": "张三",
    "phone": "13800138000",
    "province": "上海市",
    "city": "上海市",
    "district": "浦东新区",
    "address_detail": "",
}
NEW_ADDRESS = {
    "receiver_name": "李四",
    "phone": "13900139000",
    "province": "浙江省",
    "city": "杭州市",
    "district": "西湖区",
    "address_detail": "文三路 1 号",
}


def _change_scope(order_id: uuid.UUID) -> str:
    return f"order.change_address:{order_id}"


def _revert_scope(order_id: uuid.UUID) -> str:
    return f"order.change_address.revert:{order_id}"


async def _order(
    session, order_id: uuid.UUID, tenant_id: uuid.UUID = TENANT_A
) -> SalesOrder:
    order = await session.scalar(
        select(SalesOrder).where(
            SalesOrder.tenant_id == tenant_id, SalesOrder.id == order_id
        )
    )
    assert order is not None
    return order


def _address(order: SalesOrder) -> dict[str, str]:
    return {
        "receiver_name": order.receiver_name,
        "phone": order.phone,
        "province": order.province,
        "city": order.city,
        "district": order.district,
        "address_detail": order.address_detail,
    }


async def _count(session, model, *conditions) -> int:
    statement = select(func.count()).select_from(model)
    if conditions:
        statement = statement.where(*conditions)
    return int(await session.scalar(statement) or 0)


async def _pending_order_with_shipment(order_no: str) -> uuid.UUID:
    """Create a pending_shipment order that already has a shipment row."""

    order_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"opsconductor.order-{order_no}")
    async with SessionLocal() as session:
        session.add(
            SalesOrder(
                id=order_id,
                tenant_id=TENANT_A,
                shop_id=SHOP_A,
                warehouse_id=WAREHOUSE_EAST,
                order_no=order_no,
                status="pending_shipment",
                receiver_name="张三",
                phone="13800138000",
                province="上海市",
                city="上海市",
                district="浦东新区",
                address_detail="世纪大道 100 号",
            )
        )
        await session.flush()
        session.add(
            Shipment(
                tenant_id=TENANT_A,
                order_id=order_id,
                warehouse_id=WAREHOUSE_EAST,
                status="created",
            )
        )
        await session.commit()
    return order_id


@pytest.mark.asyncio
async def test_change_address_updates_fields_and_records_audit_and_idempotency(seeded_db):
    task_id = uuid.uuid4()
    async with SessionLocal() as session:
        response = await change_address(
            session,
            TENANT_A,
            ORDER_O1002,
            NEW_ADDRESS,
            "change-ok",
            dry_run=False,
            actor_id=OPERATOR_ID,
            task_id=task_id,
        )

    assert response["order_id"] == str(ORDER_O1002)
    assert response["status"] == "updated"
    assert response["before"] == ORIGINAL_O1002
    assert response["after"] == NEW_ADDRESS

    async with SessionLocal() as session:
        order = await _order(session, ORDER_O1002)
        assert order.status == "pending_shipment"
        assert order.version == 1
        assert _address(order) == NEW_ADDRESS

        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.tenant_id == TENANT_A,
                AuditLog.entity_id == str(ORDER_O1002),
            )
        )
        assert audit is not None
        assert audit.action == "order.change_address"
        assert audit.entity_type == "sales_order"
        assert audit.before == ORIGINAL_O1002
        assert audit.after == NEW_ADDRESS
        assert audit.actor_id == OPERATOR_ID
        assert audit.task_id == task_id

        record = await session.scalar(
            select(IdempotencyKey).where(
                IdempotencyKey.tenant_id == TENANT_A,
                IdempotencyKey.scope == _change_scope(ORDER_O1002),
                IdempotencyKey.key == "change-ok",
            )
        )
        assert record is not None
        assert record.status == "completed"
        assert record.response == response


@pytest.mark.asyncio
async def test_change_address_dry_run_returns_before_and_after_without_writes(seeded_db):
    async with SessionLocal() as session:
        response = await change_address(
            session,
            TENANT_A,
            ORDER_O1002,
            NEW_ADDRESS,
            "change-dry",
            dry_run=True,
            actor_id=OPERATOR_ID,
            task_id=None,
        )

    assert response == {
        "dry_run": True,
        "order_id": str(ORDER_O1002),
        "order_no": "O1002",
        "before": ORIGINAL_O1002,
        "after": NEW_ADDRESS,
    }

    async with SessionLocal() as session:
        order = await _order(session, ORDER_O1002)
        assert _address(order) == ORIGINAL_O1002
        assert (order.status, order.version) == ("pending_shipment", 0)
        assert await _count(session, AuditLog, AuditLog.tenant_id == TENANT_A) == 0
        assert await _count(session, IdempotencyKey, IdempotencyKey.tenant_id == TENANT_A) == 0


@pytest.mark.asyncio
async def test_change_address_accepts_detail_string_and_preserves_other_fields(seeded_db):
    async with SessionLocal() as session:
        response = await change_address(
            session,
            TENANT_A,
            ORDER_O1002,
            "  新地址 88 号  ",
            "change-string",
            dry_run=False,
            actor_id=OPERATOR_ID,
            task_id=None,
        )

    expected = {**ORIGINAL_O1002, "address_detail": "新地址 88 号"}
    assert response["before"] == ORIGINAL_O1002
    assert response["after"] == expected

    async with SessionLocal() as session:
        order = await _order(session, ORDER_O1002)
        assert _address(order) == expected
        assert order.status == "pending_shipment"


@pytest.mark.asyncio
async def test_change_address_rejects_split_order_without_writes(seeded_db):
    async with SessionLocal() as session:
        with pytest.raises(InvalidState, match="pending_shipment"):
            await change_address(
                session,
                TENANT_A,
                ORDER_O1005,
                NEW_ADDRESS,
                "change-split",
                dry_run=False,
                actor_id=OPERATOR_ID,
                task_id=None,
            )

    async with SessionLocal() as session:
        order = await _order(session, ORDER_O1005)
        assert order.status == "split"
        assert order.version == 0
        assert _address(order) == {
            "receiver_name": "张三",
            "phone": "13800138000",
            "province": "上海市",
            "city": "上海市",
            "district": "浦东新区",
            "address_detail": "世纪大道 100 号",
        }
        assert await _count(session, AuditLog, AuditLog.tenant_id == TENANT_A) == 0
        assert await _count(session, IdempotencyKey, IdempotencyKey.tenant_id == TENANT_A) == 0


@pytest.mark.asyncio
async def test_change_address_rejects_order_with_existing_shipment(seeded_db):
    order_id = await _pending_order_with_shipment("O1096")
    async with SessionLocal() as session:
        with pytest.raises(InvalidState, match="already has shipments"):
            await change_address(
                session,
                TENANT_A,
                order_id,
                NEW_ADDRESS,
                "change-shipped",
                dry_run=False,
                actor_id=OPERATOR_ID,
                task_id=None,
            )

    async with SessionLocal() as session:
        order = await _order(session, order_id)
        assert order.status == "pending_shipment"
        assert order.version == 0
        assert _address(order)["address_detail"] == "世纪大道 100 号"
        assert await _count(session, AuditLog, AuditLog.tenant_id == TENANT_A) == 0
        assert await _count(session, IdempotencyKey, IdempotencyKey.tenant_id == TENANT_A) == 0


@pytest.mark.parametrize(
    "invalid",
    [
        {**NEW_ADDRESS, "phone": "12345"},
        {**NEW_ADDRESS, "phone": "23800138000"},
        {**NEW_ADDRESS, "receiver_name": ""},
        {**NEW_ADDRESS, "district": "   "},
        {**NEW_ADDRESS, "address_detail": "   "},
    ],
)
@pytest.mark.asyncio
async def test_change_address_rejects_invalid_address_without_writes(seeded_db, invalid):
    async with SessionLocal() as session:
        with pytest.raises(ValidationError, match="invalid address"):
            await change_address(
                session,
                TENANT_A,
                ORDER_O1002,
                invalid,
                "change-invalid",
                dry_run=False,
                actor_id=OPERATOR_ID,
                task_id=None,
            )

    async with SessionLocal() as session:
        order = await _order(session, ORDER_O1002)
        assert _address(order) == ORIGINAL_O1002
        assert (order.status, order.version) == ("pending_shipment", 0)
        assert await _count(session, AuditLog, AuditLog.tenant_id == TENANT_A) == 0
        assert await _count(session, IdempotencyKey, IdempotencyKey.tenant_id == TENANT_A) == 0


@pytest.mark.asyncio
async def test_change_address_rejects_malformed_address_object(seeded_db):
    async with SessionLocal() as session:
        with pytest.raises(ValidationError, match="missing fields"):
            await change_address(
                session,
                TENANT_A,
                ORDER_O1002,
                {"receiver_name": "李四"},
                "change-malformed",
                dry_run=False,
                actor_id=OPERATOR_ID,
                task_id=None,
            )
        with pytest.raises(ValidationError, match="must be an address object"):
            await change_address(
                session,
                TENANT_A,
                ORDER_O1002,
                123,
                "change-malformed-type",
                dry_run=False,
                actor_id=OPERATOR_ID,
                task_id=None,
            )

    async with SessionLocal() as session:
        order = await _order(session, ORDER_O1002)
        assert _address(order) == ORIGINAL_O1002
        assert await _count(session, AuditLog, AuditLog.tenant_id == TENANT_A) == 0
        assert await _count(session, IdempotencyKey, IdempotencyKey.tenant_id == TENANT_A) == 0


@pytest.mark.asyncio
async def test_change_address_is_idempotent_and_rejects_changed_body(seeded_db):
    async with SessionLocal() as session:
        first = await change_address(
            session,
            TENANT_A,
            ORDER_O1002,
            NEW_ADDRESS,
            "change-dupe",
            dry_run=False,
            actor_id=OPERATOR_ID,
            task_id=None,
        )
        second = await change_address(
            session,
            TENANT_A,
            ORDER_O1002,
            NEW_ADDRESS,
            "change-dupe",
            dry_run=False,
            actor_id=OPERATOR_ID,
            task_id=None,
        )
        assert second == first

        with pytest.raises(IdempotencyConflict):
            await change_address(
                session,
                TENANT_A,
                ORDER_O1002,
                {**NEW_ADDRESS, "phone": "13700137000"},
                "change-dupe",
                dry_run=False,
                actor_id=OPERATOR_ID,
                task_id=None,
            )

    async with SessionLocal() as session:
        order = await _order(session, ORDER_O1002)
        assert order.version == 1
        assert _address(order) == NEW_ADDRESS
        assert await _count(session, AuditLog, AuditLog.tenant_id == TENANT_A) == 1
        assert await _count(session, IdempotencyKey, IdempotencyKey.tenant_id == TENANT_A) == 1


@pytest.mark.asyncio
async def test_revert_address_restores_original_and_is_idempotent(seeded_db):
    task_id = uuid.uuid4()
    async with SessionLocal() as session:
        changed = await change_address(
            session,
            TENANT_A,
            ORDER_O1002,
            NEW_ADDRESS,
            "change-for-revert",
            dry_run=False,
            actor_id=OPERATOR_ID,
            task_id=task_id,
        )
        reverted = await revert_address(
            session,
            TENANT_A,
            ORDER_O1002,
            changed["before"],
            "revert-ok",
            task_id=task_id,
        )
        replay = await revert_address(
            session,
            TENANT_A,
            ORDER_O1002,
            changed["before"],
            "revert-ok",
            task_id=task_id,
        )
        assert replay == reverted

    assert reverted["status"] == "reverted"
    assert reverted["before"] == NEW_ADDRESS
    assert reverted["after"] == ORIGINAL_O1002

    async with SessionLocal() as session:
        order = await _order(session, ORDER_O1002)
        assert (order.status, order.version) == ("pending_shipment", 2)
        assert _address(order) == ORIGINAL_O1002

        audits = list(
            (
                await session.scalars(
                    select(AuditLog).where(
                        AuditLog.tenant_id == TENANT_A,
                        AuditLog.entity_id == str(ORDER_O1002),
                    )
                )
            ).all()
        )
        assert sorted(audit.action for audit in audits) == [
            "order.change_address",
            "order.change_address.revert",
        ]
        revert_audit = next(
            audit for audit in audits if audit.action == "order.change_address.revert"
        )
        assert revert_audit.before == NEW_ADDRESS
        assert revert_audit.after == ORIGINAL_O1002
        assert revert_audit.task_id == task_id

        records = list(
            (
                await session.scalars(
                    select(IdempotencyKey).where(
                        IdempotencyKey.tenant_id == TENANT_A
                    )
                )
            ).all()
        )
        assert {record.scope for record in records} == {
            _change_scope(ORDER_O1002),
            _revert_scope(ORDER_O1002),
        }


@pytest.mark.asyncio
async def test_address_writes_are_tenant_scoped(seeded_db):
    async with SessionLocal() as session:
        with pytest.raises(NotFound):
            await change_address(
                session,
                TENANT_B,
                ORDER_O1002,
                NEW_ADDRESS,
                "change-foreign",
                dry_run=False,
                actor_id=None,
                task_id=None,
            )
        with pytest.raises(NotFound):
            await revert_address(
                session,
                TENANT_B,
                ORDER_O1002,
                NEW_ADDRESS,
                "revert-foreign",
                task_id=None,
            )

    async with SessionLocal() as session:
        tenant_a_order = await _order(session, ORDER_O1002)
        assert _address(tenant_a_order) == ORIGINAL_O1002
        assert (tenant_a_order.status, tenant_a_order.version) == ("pending_shipment", 0)

        tenant_b_order = await session.scalar(
            select(SalesOrder).where(
                SalesOrder.tenant_id == TENANT_B, SalesOrder.order_no == "O2001"
            )
        )
        assert tenant_b_order is not None
        assert tenant_b_order.receiver_name == "李四"
        assert tenant_b_order.address_detail == "文三路 1 号"

        assert await _count(session, AuditLog, AuditLog.tenant_id == TENANT_B) == 0
        assert await _count(session, IdempotencyKey, IdempotencyKey.tenant_id == TENANT_B) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mcp_address_tools_are_registered_and_execute(seeded_db):
    async with ErpToolClient() as client:
        listed = await client._session.list_tools()
        names = {tool.name for tool in listed.tools}
        assert {"order_change_address", "order_revert_address"} <= names

        changed = await client.call(
            "order_change_address",
            {
                "tenant_id": str(TENANT_A),
                "order_id": str(ORDER_O1002),
                "address": NEW_ADDRESS,
                "idempotency_key": "mcp-change",
            },
        )
        assert changed["status"] == "updated"
        assert changed["before"] == ORIGINAL_O1002
        assert changed["after"] == NEW_ADDRESS

        reverted = await client.call(
            "order_revert_address",
            {
                "tenant_id": str(TENANT_A),
                "order_id": str(ORDER_O1002),
                "before_address": changed["before"],
                "idempotency_key": "mcp-revert",
            },
        )
        assert reverted["status"] == "reverted"
        assert reverted["after"] == ORIGINAL_O1002

    async with SessionLocal() as session:
        order = await _order(session, ORDER_O1002)
        assert order.status == "pending_shipment"
        assert _address(order) == ORIGINAL_O1002
