"""Tests for split-order writes, inventory reservation, and compensation."""

import uuid

import pytest
from sqlalchemy import func, select

from opsconductor.db import SessionLocal
from opsconductor.domain.models import (
    AuditLog,
    IdempotencyKey,
    Inventory,
    InventoryLedger,
    OrderLine,
    SalesOrder,
    Shipment,
    ShipmentLine,
)
from opsconductor.domain.seed import (
    SHOP_A,
    SKU_IDS,
    TENANT_A,
    TENANT_B,
    WAREHOUSE_EAST,
)
from opsconductor.domain.write_service import (
    IdempotencyConflict,
    InsufficientStock,
    InvalidState,
    NotFound,
    ValidationError,
    cancel_shipment,
    cancel_split,
    release_inventory,
    split_order,
)
from opsconductor.tools.client import ErpToolClient

ORDER_O1001 = uuid.uuid5(uuid.NAMESPACE_DNS, "opsconductor.order-O1001")
ORDER_O1003 = uuid.uuid5(uuid.NAMESPACE_DNS, "opsconductor.order-O1003")
ORDER_O1005 = uuid.uuid5(uuid.NAMESPACE_DNS, "opsconductor.order-O1005")
OPERATOR_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "opsconductor.user-operator-a")


def _shipments_o1001() -> list[dict]:
    return [
        {
            "warehouse_id": str(WAREHOUSE_EAST),
            "lines": [{"sku_id": str(SKU_IDS["SKU-001"]), "qty": 2}],
        },
        {
            "warehouse_id": str(WAREHOUSE_EAST),
            "lines": [{"sku_id": str(SKU_IDS["SKU-002"]), "qty": 1}],
        },
    ]


async def _order(session, order_id: uuid.UUID) -> SalesOrder:
    order = await session.scalar(
        select(SalesOrder).where(
            SalesOrder.tenant_id == TENANT_A, SalesOrder.id == order_id
        )
    )
    assert order is not None
    return order


async def _inventory(session, sku_code: str) -> Inventory:
    inventory = await session.scalar(
        select(Inventory).where(
            Inventory.tenant_id == TENANT_A,
            Inventory.sku_id == SKU_IDS[sku_code],
            Inventory.warehouse_id == WAREHOUSE_EAST,
        )
    )
    assert inventory is not None
    return inventory


async def _shipments(session, order_id: uuid.UUID) -> list[Shipment]:
    return list(
        (
            await session.scalars(
                select(Shipment)
                .where(Shipment.tenant_id == TENANT_A, Shipment.order_id == order_id)
                .order_by(Shipment.created_at, Shipment.id)
            )
        ).all()
    )


async def _count(session, model, *conditions) -> int:
    statement = select(func.count()).select_from(model)
    if conditions:
        statement = statement.where(*conditions)
    return int(await session.scalar(statement) or 0)


async def _create_order(order_no: str, sku_code: str, qty: int) -> uuid.UUID:
    """Create a committed tenant A order with a single line for edge-case tests."""

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
            OrderLine(
                tenant_id=TENANT_A,
                order_id=order_id,
                sku_id=SKU_IDS[sku_code],
                qty=qty,
            )
        )
        await session.commit()
    return order_id


@pytest.mark.asyncio
async def test_split_order_success_writes_shipments_inventory_and_audit(seeded_db):
    task_id = uuid.uuid4()
    async with SessionLocal() as session:
        response = await split_order(
            session,
            TENANT_A,
            ORDER_O1001,
            _shipments_o1001(),
            "split-ok",
            dry_run=False,
            actor_id=OPERATOR_ID,
            task_id=task_id,
        )

    assert response["status"] == "split"
    assert response["shipments"] == 2
    assert len(response["shipment_ids"]) == 2

    async with SessionLocal() as session:
        order = await _order(session, ORDER_O1001)
        assert (order.status, order.version) == ("split", 1)

        shipments = await _shipments(session, ORDER_O1001)
        assert len(shipments) == 2
        assert {shipment.status for shipment in shipments} == {"created"}

        lines = list(
            (
                await session.scalars(
                    select(ShipmentLine).where(
                        ShipmentLine.tenant_id == TENANT_A,
                        ShipmentLine.shipment_id.in_(
                            [shipment.id for shipment in shipments]
                        ),
                    )
                )
            ).all()
        )
        assert sorted((line.sku_id, line.qty) for line in lines) == sorted(
            [(SKU_IDS["SKU-001"], 2), (SKU_IDS["SKU-002"], 1)]
        )

        sku_001 = await _inventory(session, "SKU-001")
        sku_002 = await _inventory(session, "SKU-002")
        assert (sku_001.available, sku_001.reserved, sku_001.version) == (98, 2, 1)
        assert (sku_002.available, sku_002.reserved, sku_002.version) == (99, 1, 1)

        ledger = list(
            (
                await session.scalars(
                    select(InventoryLedger).where(
                        InventoryLedger.tenant_id == TENANT_A
                    )
                )
            ).all()
        )
        assert len(ledger) == 2
        assert {
            (row.sku_id, row.delta_available, row.delta_reserved, row.reason, row.task_id)
            for row in ledger
        } == {
            (SKU_IDS["SKU-001"], -2, 2, "order_split", task_id),
            (SKU_IDS["SKU-002"], -1, 1, "order_split", task_id),
        }
        assert {row.order_id for row in ledger} == {ORDER_O1001}
        assert {row.shipment_id for row in ledger} == {
            uuid.UUID(value) for value in response["shipment_ids"]
        }

        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.tenant_id == TENANT_A,
                AuditLog.entity_id == str(ORDER_O1001),
            )
        )
        assert audit is not None
        assert audit.action == "order.split"
        assert audit.before == {"status": "pending_shipment"}
        assert audit.after == {"status": "split"}
        assert audit.actor_id == OPERATOR_ID
        assert audit.task_id == task_id
        assert audit.evidence["shipment_ids"] == response["shipment_ids"]

        record = await session.scalar(
            select(IdempotencyKey).where(
                IdempotencyKey.tenant_id == TENANT_A,
                IdempotencyKey.scope == f"order.split:{ORDER_O1001}",
                IdempotencyKey.key == "split-ok",
            )
        )
        assert record is not None
        assert record.response == response


@pytest.mark.asyncio
async def test_split_order_dry_run_returns_impact_without_writes(seeded_db):
    async with SessionLocal() as session:
        response = await split_order(
            session,
            TENANT_A,
            ORDER_O1001,
            _shipments_o1001(),
            "split-dry",
            dry_run=True,
            actor_id=OPERATOR_ID,
            task_id=None,
        )

    assert response["dry_run"] is True
    assert response["order_id"] == str(ORDER_O1001)
    assert {
        (entry["sku_id"], entry["qty"], entry["available"])
        for entry in response["impact"]
    } == {
        (str(SKU_IDS["SKU-001"]), 2, 100),
        (str(SKU_IDS["SKU-002"]), 1, 100),
    }

    async with SessionLocal() as session:
        order = await _order(session, ORDER_O1001)
        assert (order.status, order.version) == ("pending_shipment", 0)
        assert await _shipments(session, ORDER_O1001) == []
        assert (await _inventory(session, "SKU-001")).available == 100
        assert (await _inventory(session, "SKU-001")).reserved == 0
        assert await _count(session, InventoryLedger, InventoryLedger.tenant_id == TENANT_A) == 0
        assert await _count(session, AuditLog, AuditLog.tenant_id == TENANT_A) == 0
        assert await _count(session, IdempotencyKey, IdempotencyKey.tenant_id == TENANT_A) == 0


@pytest.mark.asyncio
async def test_split_order_is_idempotent_and_rejects_changed_body(seeded_db):
    async with SessionLocal() as session:
        first = await split_order(
            session,
            TENANT_A,
            ORDER_O1001,
            _shipments_o1001(),
            "split-dupe",
            dry_run=False,
            actor_id=OPERATOR_ID,
            task_id=None,
        )
        second = await split_order(
            session,
            TENANT_A,
            ORDER_O1001,
            _shipments_o1001(),
            "split-dupe",
            dry_run=False,
            actor_id=OPERATOR_ID,
            task_id=None,
        )

        assert second == first

        changed = [
            {
                "warehouse_id": str(WAREHOUSE_EAST),
                "lines": [{"sku_id": str(SKU_IDS["SKU-001"]), "qty": 1}],
            }
        ]
        with pytest.raises(IdempotencyConflict):
            await split_order(
                session,
                TENANT_A,
                ORDER_O1001,
                changed,
                "split-dupe",
                dry_run=False,
                actor_id=OPERATOR_ID,
                task_id=None,
            )

    async with SessionLocal() as session:
        shipments = await _shipments(session, ORDER_O1001)
        assert len(shipments) == 2
        assert (
            await _count(
                session,
                ShipmentLine,
                ShipmentLine.tenant_id == TENANT_A,
                ShipmentLine.shipment_id.in_(
                    [shipment.id for shipment in shipments]
                ),
            )
            == 2
        )
        assert await _count(session, InventoryLedger, InventoryLedger.tenant_id == TENANT_A) == 2
        assert await _count(session, AuditLog, AuditLog.tenant_id == TENANT_A) == 1
        assert await _count(session, IdempotencyKey, IdempotencyKey.tenant_id == TENANT_A) == 1
        assert (await _inventory(session, "SKU-001")).available == 98
        assert (await _inventory(session, "SKU-001")).reserved == 2


@pytest.mark.asyncio
async def test_split_order_rejects_under_shipment_without_writes(seeded_db):
    shipments = [
        {
            "warehouse_id": str(WAREHOUSE_EAST),
            "lines": [{"sku_id": str(SKU_IDS["SKU-001"]), "qty": 2}],
        }
    ]
    async with SessionLocal() as session:
        with pytest.raises(ValidationError, match="do not match order") as error:
            await split_order(
                session,
                TENANT_A,
                ORDER_O1001,
                shipments,
                "split-under",
                dry_run=False,
                actor_id=OPERATOR_ID,
                task_id=None,
            )
        assert "missing" in str(error.value)
        assert str(SKU_IDS["SKU-002"]) in str(error.value)

    async with SessionLocal() as session:
        order = await _order(session, ORDER_O1001)
        assert (order.status, order.version) == ("pending_shipment", 0)
        assert await _shipments(session, ORDER_O1001) == []
        for sku_code in ("SKU-001", "SKU-002"):
            inventory = await _inventory(session, sku_code)
            assert (inventory.available, inventory.reserved, inventory.version) == (
                100,
                0,
                0,
            )
        assert await _count(session, InventoryLedger, InventoryLedger.tenant_id == TENANT_A) == 0
        assert await _count(session, AuditLog, AuditLog.tenant_id == TENANT_A) == 0
        assert await _count(session, IdempotencyKey, IdempotencyKey.tenant_id == TENANT_A) == 0


@pytest.mark.asyncio
async def test_split_order_rejects_sku_not_on_order_without_writes(seeded_db):
    shipments = [
        *_shipments_o1001(),
        {
            "warehouse_id": str(WAREHOUSE_EAST),
            "lines": [{"sku_id": str(SKU_IDS["SKU-004"]), "qty": 1}],
        },
    ]
    async with SessionLocal() as session:
        with pytest.raises(ValidationError, match="do not match order") as error:
            await split_order(
                session,
                TENANT_A,
                ORDER_O1001,
                shipments,
                "split-foreign-sku",
                dry_run=False,
                actor_id=OPERATOR_ID,
                task_id=None,
            )
        assert "unexpected" in str(error.value)
        assert str(SKU_IDS["SKU-004"]) in str(error.value)

    async with SessionLocal() as session:
        order = await _order(session, ORDER_O1001)
        assert (order.status, order.version) == ("pending_shipment", 0)
        assert await _shipments(session, ORDER_O1001) == []
        foreign_inventory = await _inventory(session, "SKU-004")
        assert (
            foreign_inventory.available,
            foreign_inventory.reserved,
            foreign_inventory.version,
        ) == (100, 0, 0)
        assert (await _inventory(session, "SKU-001")).available == 100
        assert await _count(session, InventoryLedger, InventoryLedger.tenant_id == TENANT_A) == 0
        assert await _count(session, AuditLog, AuditLog.tenant_id == TENANT_A) == 0
        assert await _count(session, IdempotencyKey, IdempotencyKey.tenant_id == TENANT_A) == 0


@pytest.mark.asyncio
async def test_split_order_insufficient_stock_rejects_whole_order(seeded_db):
    shipments = [
        {
            "warehouse_id": str(WAREHOUSE_EAST),
            "lines": [{"sku_id": str(SKU_IDS["SKU-003"]), "qty": 5}],
        }
    ]
    async with SessionLocal() as session:
        with pytest.raises(InsufficientStock, match="insufficient stock") as error:
            await split_order(
                session,
                TENANT_A,
                ORDER_O1003,
                shipments,
                "split-short",
                dry_run=False,
                actor_id=OPERATOR_ID,
                task_id=None,
            )
        assert str(SKU_IDS["SKU-003"]) in str(error.value)

    async with SessionLocal() as session:
        order = await _order(session, ORDER_O1003)
        assert (order.status, order.version) == ("pending_shipment", 0)
        assert await _shipments(session, ORDER_O1003) == []
        inventory = await _inventory(session, "SKU-003")
        assert (inventory.available, inventory.reserved, inventory.version) == (0, 0, 0)
        assert await _count(session, InventoryLedger, InventoryLedger.tenant_id == TENANT_A) == 0
        assert await _count(session, AuditLog, AuditLog.tenant_id == TENANT_A) == 0
        assert await _count(session, IdempotencyKey, IdempotencyKey.tenant_id == TENANT_A) == 0


@pytest.mark.asyncio
async def test_split_order_treats_repeated_sku_demand_cumulatively(seeded_db):
    order_id = await _create_order("O1098", "SKU-005", 120)
    shipments = [
        {
            "warehouse_id": str(WAREHOUSE_EAST),
            "lines": [{"sku_id": str(SKU_IDS["SKU-005"]), "qty": 60}],
        },
        {
            "warehouse_id": str(WAREHOUSE_EAST),
            "lines": [{"sku_id": str(SKU_IDS["SKU-005"]), "qty": 60}],
        },
    ]
    async with SessionLocal() as session:
        with pytest.raises(InsufficientStock, match="120"):
            await split_order(
                session,
                TENANT_A,
                order_id,
                shipments,
                "split-cumulative",
                dry_run=False,
                actor_id=OPERATOR_ID,
                task_id=None,
            )

    async with SessionLocal() as session:
        order = await _order(session, order_id)
        assert order.status == "pending_shipment"
        assert await _shipments(session, order_id) == []
        inventory = await _inventory(session, "SKU-005")
        assert (inventory.available, inventory.reserved) == (100, 0)
        assert await _count(session, InventoryLedger, InventoryLedger.tenant_id == TENANT_A) == 0


@pytest.mark.asyncio
async def test_split_order_rejects_order_that_is_already_split(seeded_db):
    shipments = [
        {
            "warehouse_id": str(WAREHOUSE_EAST),
            "lines": [{"sku_id": str(SKU_IDS["SKU-005"]), "qty": 1}],
        }
    ]
    async with SessionLocal() as session:
        with pytest.raises(InvalidState, match="split"):
            await split_order(
                session,
                TENANT_A,
                ORDER_O1005,
                shipments,
                "split-invalid",
                dry_run=False,
                actor_id=OPERATOR_ID,
                task_id=None,
            )

    async with SessionLocal() as session:
        order = await _order(session, ORDER_O1005)
        assert order.status == "split"
        shipments = await _shipments(session, ORDER_O1005)
        assert len(shipments) == 1
        assert shipments[0].status == "created"
        inventory = await _inventory(session, "SKU-005")
        assert (inventory.available, inventory.reserved, inventory.version) == (100, 0, 0)
        assert await _count(session, InventoryLedger, InventoryLedger.tenant_id == TENANT_A) == 0
        assert await _count(session, AuditLog, AuditLog.tenant_id == TENANT_A) == 0
        assert await _count(session, IdempotencyKey, IdempotencyKey.tenant_id == TENANT_A) == 0


@pytest.mark.asyncio
async def test_cancel_split_compensates_and_is_idempotent(seeded_db):
    task_id = uuid.uuid4()
    async with SessionLocal() as session:
        await split_order(
            session,
            TENANT_A,
            ORDER_O1001,
            _shipments_o1001(),
            "split-comp",
            dry_run=False,
            actor_id=OPERATOR_ID,
            task_id=task_id,
        )
        response = await cancel_split(
            session, TENANT_A, ORDER_O1001, "cancel-comp", task_id=task_id
        )
        replay = await cancel_split(
            session, TENANT_A, ORDER_O1001, "cancel-comp", task_id=task_id
        )
        assert replay == response

        with pytest.raises(InvalidState, match="pending_shipment"):
            await cancel_split(
                session, TENANT_A, ORDER_O1001, "cancel-comp-again", task_id=task_id
            )

    assert response["status"] == "compensated"
    assert response["shipments_cancelled"] == 2

    async with SessionLocal() as session:
        order = await _order(session, ORDER_O1001)
        assert (order.status, order.version) == ("pending_shipment", 2)

        shipments = await _shipments(session, ORDER_O1001)
        assert len(shipments) == 2
        assert {shipment.status for shipment in shipments} == {"cancelled"}

        sku_001 = await _inventory(session, "SKU-001")
        sku_002 = await _inventory(session, "SKU-002")
        assert (sku_001.available, sku_001.reserved, sku_001.version) == (100, 0, 2)
        assert (sku_002.available, sku_002.reserved, sku_002.version) == (100, 0, 2)

        ledger = list(
            (
                await session.scalars(
                    select(InventoryLedger).where(
                        InventoryLedger.tenant_id == TENANT_A
                    )
                )
            ).all()
        )
        assert len(ledger) == 4
        assert [row.reason for row in ledger].count("order_split") == 2
        assert [row.reason for row in ledger].count("split_compensation") == 2
        assert {row.task_id for row in ledger} == {task_id}
        assert {row.order_id for row in ledger} == {ORDER_O1001}
        assert {row.shipment_id for row in ledger} == {
            shipment.id for shipment in shipments
        }

        audits = list(
            (
                await session.scalars(
                    select(AuditLog).where(
                        AuditLog.tenant_id == TENANT_A,
                        AuditLog.entity_id == str(ORDER_O1001),
                    )
                )
            ).all()
        )
        assert sorted(audit.action for audit in audits) == [
            "order.split",
            "order.split.cancel",
        ]
        cancel_audit = next(
            audit for audit in audits if audit.action == "order.split.cancel"
        )
        assert cancel_audit.before == {"status": "split"}
        assert cancel_audit.after == {"status": "pending_shipment"}
        assert cancel_audit.evidence["shipments"] == 2

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
            f"order.split:{ORDER_O1001}",
            f"order.split.cancel:{ORDER_O1001}",
        }


@pytest.mark.asyncio
async def test_compensation_primitives_release_each_shipment_once(seeded_db):
    async with SessionLocal() as session:
        split = await split_order(
            session,
            TENANT_A,
            ORDER_O1001,
            _shipments_o1001(),
            "split-primitives",
            dry_run=False,
            actor_id=OPERATOR_ID,
            task_id=None,
        )
        shipment_ids = [uuid.UUID(value) for value in split["shipment_ids"]]

        cancelled = await cancel_shipment(
            session, TENANT_A, shipment_ids[0], "cancel-one", task_id=None
        )
        assert cancelled["status"] == "cancelled"
        assert cancelled["released"] == [
            {
                "sku_id": str(SKU_IDS["SKU-001"]),
                "warehouse_id": str(WAREHOUSE_EAST),
                "qty": 2,
            }
        ]

        released = await release_inventory(
            session, TENANT_A, ORDER_O1001, "release-rest", task_id=None
        )
        assert released["status"] == "released"
        assert released["shipments_cancelled"] == 1

        compensated = await cancel_split(
            session, TENANT_A, ORDER_O1001, "cancel-after-release", task_id=None
        )
        assert compensated["status"] == "compensated"
        assert compensated["shipments_cancelled"] == 0

    async with SessionLocal() as session:
        order = await _order(session, ORDER_O1001)
        assert (order.status, order.version) == ("pending_shipment", 2)
        assert {shipment.status for shipment in await _shipments(session, ORDER_O1001)} == {
            "cancelled"
        }
        assert (await _inventory(session, "SKU-001")).available == 100
        assert (await _inventory(session, "SKU-001")).reserved == 0
        assert (await _inventory(session, "SKU-002")).available == 100
        assert (await _inventory(session, "SKU-002")).reserved == 0
        ledger = list(
            (
                await session.scalars(
                    select(InventoryLedger).where(
                        InventoryLedger.tenant_id == TENANT_A
                    )
                )
            ).all()
        )
        assert len(ledger) == 4
        assert {row.order_id for row in ledger} == {ORDER_O1001}
        assert {row.shipment_id for row in ledger} == set(shipment_ids)


@pytest.mark.asyncio
async def test_cancel_split_cannot_release_another_orders_reservation(seeded_db):
    other_order_id = await _create_order("O1099", "SKU-005", 1)
    async with SessionLocal() as session:
        split = await split_order(
            session,
            TENANT_A,
            other_order_id,
            [
                {
                    "warehouse_id": str(WAREHOUSE_EAST),
                    "lines": [{"sku_id": str(SKU_IDS["SKU-005"]), "qty": 1}],
                }
            ],
            "split-other-o1099",
            dry_run=False,
            actor_id=OPERATOR_ID,
            task_id=None,
        )
        assert split["status"] == "split"

        with pytest.raises(InvalidState, match="reservation ledger"):
            await cancel_split(
                session,
                TENANT_A,
                ORDER_O1005,
                "cancel-seeded-o1005",
                task_id=None,
            )

    async with SessionLocal() as session:
        sku_005 = await _inventory(session, "SKU-005")
        assert (sku_005.available, sku_005.reserved, sku_005.version) == (99, 1, 1)

        seeded_order = await _order(session, ORDER_O1005)
        assert seeded_order.status == "split"
        seeded_shipments = await _shipments(session, ORDER_O1005)
        assert len(seeded_shipments) == 1
        assert seeded_shipments[0].status == "created"

        other_order = await _order(session, other_order_id)
        assert other_order.status == "split"
        other_shipments = await _shipments(session, other_order_id)
        assert len(other_shipments) == 1
        assert other_shipments[0].status == "created"

        ledger = list(
            (
                await session.scalars(
                    select(InventoryLedger).where(
                        InventoryLedger.tenant_id == TENANT_A
                    )
                )
            ).all()
        )
        assert len(ledger) == 1
        assert ledger[0].order_id == other_order_id
        assert ledger[0].shipment_id == other_shipments[0].id
        assert ledger[0].reason == "order_split"
        assert (
            await _count(
                session,
                AuditLog,
                AuditLog.tenant_id == TENANT_A,
                AuditLog.entity_id == str(ORDER_O1005),
            )
            == 0
        )
        assert (
            await _count(
                session,
                IdempotencyKey,
                IdempotencyKey.tenant_id == TENANT_A,
                IdempotencyKey.scope == f"order.split.cancel:{ORDER_O1005}",
            )
            == 0
        )


@pytest.mark.asyncio
async def test_write_operations_never_touch_foreign_tenant_data(seeded_db):
    async with SessionLocal() as session:
        with pytest.raises(NotFound):
            await split_order(
                session,
                TENANT_B,
                ORDER_O1001,
                _shipments_o1001(),
                "split-foreign",
                dry_run=False,
                actor_id=None,
                task_id=None,
            )
        with pytest.raises(NotFound):
            await cancel_split(
                session, TENANT_B, ORDER_O1001, "cancel-foreign", task_id=None
            )

        tenant_b_order = await session.scalar(
            select(SalesOrder).where(
                SalesOrder.tenant_id == TENANT_B, SalesOrder.order_no == "O2001"
            )
        )
        assert tenant_b_order is not None
        assert tenant_b_order.status == "pending_shipment"

    async with SessionLocal() as session:
        order = await _order(session, ORDER_O1001)
        assert (order.status, order.version) == ("pending_shipment", 0)
        assert await _shipments(session, ORDER_O1001) == []
        assert (await _inventory(session, "SKU-001")).available == 100
        assert await _count(session, AuditLog, AuditLog.tenant_id == TENANT_B) == 0
        assert await _count(session, IdempotencyKey, IdempotencyKey.tenant_id == TENANT_B) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mcp_write_tools_are_registered_and_complete_compensation_cycle(seeded_db):
    async with ErpToolClient() as client:
        listed = await client._session.list_tools()
        names = {tool.name for tool in listed.tools}
        assert {
            "order_split",
            "shipment_cancel",
            "inventory_release",
            "order_revert_split",
        } <= names

        dry = await client.call(
            "order_split",
            {
                "tenant_id": str(TENANT_A),
                "order_id": str(ORDER_O1001),
                "shipments": _shipments_o1001(),
                "idempotency_key": "mcp-dry",
                "dry_run": True,
            },
        )
        assert dry["dry_run"] is True
        assert len(dry["impact"]) == 2

        split = await client.call(
            "order_split",
            {
                "tenant_id": str(TENANT_A),
                "order_id": str(ORDER_O1001),
                "shipments": _shipments_o1001(),
                "idempotency_key": "mcp-split",
                "dry_run": False,
            },
        )
        assert split["status"] == "split"
        assert len(split["shipment_ids"]) == 2

        cancelled = await client.call(
            "shipment_cancel",
            {
                "tenant_id": str(TENANT_A),
                "shipment_id": split["shipment_ids"][0],
                "idempotency_key": "mcp-cancel-one",
            },
        )
        assert cancelled["status"] == "cancelled"

        released = await client.call(
            "inventory_release",
            {
                "tenant_id": str(TENANT_A),
                "order_id": str(ORDER_O1001),
                "idempotency_key": "mcp-release",
            },
        )
        assert released["status"] == "released"
        assert released["shipments_cancelled"] == 1

        reverted = await client.call(
            "order_revert_split",
            {
                "tenant_id": str(TENANT_A),
                "order_id": str(ORDER_O1001),
                "idempotency_key": "mcp-revert",
            },
        )
        assert reverted["status"] == "compensated"
        assert reverted["shipments_cancelled"] == 0

        state = await client.call(
            "order_get_state",
            {"tenant_id": str(TENANT_A), "order_id": str(ORDER_O1001)},
        )
        assert state["status"] == "pending_shipment"

    async with SessionLocal() as session:
        assert {shipment.status for shipment in await _shipments(session, ORDER_O1001)} == {
            "cancelled"
        }
        assert (await _inventory(session, "SKU-001")).available == 100
        assert (await _inventory(session, "SKU-001")).reserved == 0
        assert (await _inventory(session, "SKU-002")).available == 100
        assert (await _inventory(session, "SKU-002")).reserved == 0
        assert await _count(session, InventoryLedger, InventoryLedger.tenant_id == TENANT_A) == 4
