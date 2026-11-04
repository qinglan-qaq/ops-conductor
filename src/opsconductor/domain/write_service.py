"""Transactional order write operations with idempotency and compensation.

The service owns each transaction boundary: ``split_order`` and the
compensation entry points commit their own changes. ``write_audit`` only stages
rows on the caller's session, so audit records become visible exactly when the
business change commits.
"""

import hashlib
import json
import uuid
from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from opsconductor.domain.models import (
    IdempotencyKey,
    Inventory,
    InventoryLedger,
    OrderLine,
    SalesOrder,
    Shipment,
    ShipmentLine,
)
from opsconductor.observability.audit import write_audit

__all__ = [
    "IdempotencyConflict",
    "InsufficientStock",
    "InvalidState",
    "NotFound",
    "ValidationError",
    "WriteError",
    "cancel_shipment",
    "cancel_split",
    "release_inventory",
    "split_order",
]

SPLIT_RESERVATION_REASON = "order_split"
SPLIT_COMPENSATION_REASON = "split_compensation"
_RESERVATION_REASONS = (SPLIT_RESERVATION_REASON, SPLIT_COMPENSATION_REASON)


class WriteError(Exception):
    """Base class for write-path failures with a stable tool error code."""

    code = "WRITE_ERROR"


class ValidationError(WriteError):
    code = "VALIDATION_ERROR"


class NotFound(WriteError):
    code = "NOT_FOUND"


class InvalidState(WriteError):
    code = "INVALID_STATE"


class InsufficientStock(WriteError):
    code = "INSUFFICIENT_STOCK"


class IdempotencyConflict(WriteError):
    code = "CONFLICT"


def _split_scope(order_id: UUID) -> str:
    return f"order.split:{order_id}"


def _cancel_split_scope(order_id: UUID) -> str:
    return f"order.split.cancel:{order_id}"


def _shipment_cancel_scope(shipment_id: UUID) -> str:
    return f"shipment.cancel:{shipment_id}"


def _inventory_release_scope(order_id: UUID) -> str:
    return f"inventory.release:{order_id}"


def _request_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validate_idempotency_key(idempotency_key: Any) -> str:
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise ValidationError("idempotency_key must be a non-empty string")
    if len(idempotency_key) > 200:
        raise ValidationError("idempotency_key must be at most 200 characters")
    return idempotency_key


def _as_uuid(value: Any, field: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValidationError(f"{field} must be a UUID") from exc


def _normalize_shipments(shipments: Any) -> list[dict[str, Any]]:
    """Validate the request shape and normalize IDs to ``UUID`` objects."""

    if not isinstance(shipments, list) or not shipments:
        raise ValidationError("shipments must be a non-empty list")

    normalized: list[dict[str, Any]] = []
    for index, entry in enumerate(shipments):
        if not isinstance(entry, dict):
            raise ValidationError(f"shipments[{index}] must be an object")
        warehouse_id = _as_uuid(
            entry.get("warehouse_id"), f"shipments[{index}].warehouse_id"
        )
        lines = entry.get("lines")
        if not isinstance(lines, list) or not lines:
            raise ValidationError(f"shipments[{index}].lines must be a non-empty list")

        normalized_lines: list[dict[str, Any]] = []
        for line_index, line in enumerate(lines):
            label = f"shipments[{index}].lines[{line_index}]"
            if not isinstance(line, dict):
                raise ValidationError(f"{label} must be an object")
            sku_id = _as_uuid(line.get("sku_id"), f"{label}.sku_id")
            qty = line.get("qty")
            if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
                raise ValidationError(f"{label}.qty must be a positive integer")
            normalized_lines.append({"sku_id": sku_id, "qty": qty})
        normalized.append({"warehouse_id": warehouse_id, "lines": normalized_lines})
    return normalized


def _canonical_shipments(shipments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a JSON-stable representation used for idempotency hashing."""

    return [
        {
            "warehouse_id": str(entry["warehouse_id"]),
            "lines": [
                {"sku_id": str(line["sku_id"]), "qty": line["qty"]}
                for line in entry["lines"]
            ],
        }
        for entry in shipments
    ]


async def _find_idempotency(
    session: AsyncSession, tenant_id: UUID, scope: str, key: str
) -> IdempotencyKey | None:
    return await session.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.tenant_id == tenant_id,
            IdempotencyKey.scope == scope,
            IdempotencyKey.key == key,
        )
    )


async def _replay(
    session: AsyncSession,
    tenant_id: UUID,
    scope: str,
    key: str,
    fingerprint: str,
) -> dict[str, Any] | None:
    """Return a stored response, or ``None`` when the key is unused."""

    record = await _find_idempotency(session, tenant_id, scope, key)
    if record is None:
        return None
    if record.request_hash != fingerprint:
        raise IdempotencyConflict(
            f"idempotency key {key!r} was used with a different request"
        )
    if record.response is None:
        raise IdempotencyConflict(f"idempotency key {key!r} is still in progress")
    return record.response


async def _commit_or_replay(
    session: AsyncSession,
    tenant_id: UUID,
    scope: str,
    key: str,
    fingerprint: str,
) -> dict[str, Any] | None:
    """Commit, or return a concurrently committed response on key collision."""

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        replay = await _replay(session, tenant_id, scope, key, fingerprint)
        if replay is None:
            raise
        return replay
    return None


async def _lock_order(
    session: AsyncSession, tenant_id: UUID, order_id: UUID
) -> SalesOrder | None:
    return await session.scalar(
        select(SalesOrder)
        .where(SalesOrder.tenant_id == tenant_id, SalesOrder.id == order_id)
        .with_for_update()
    )


async def _lock_inventory(
    session: AsyncSession, tenant_id: UUID, sku_id: UUID, warehouse_id: UUID
) -> Inventory | None:
    return await session.scalar(
        select(Inventory)
        .where(
            Inventory.tenant_id == tenant_id,
            Inventory.sku_id == sku_id,
            Inventory.warehouse_id == warehouse_id,
        )
        .with_for_update()
    )


async def _validate_shipment_coverage(
    session: AsyncSession,
    tenant_id: UUID,
    order_id: UUID,
    shipments: list[dict[str, Any]],
) -> None:
    """Require shipment lines to match the order lines exactly as a multiset.

    Every order SKU must be shipped in full, and no SKU outside the order may
    appear. This runs before inventory is locked or any row is staged, so an
    under-shipment or foreign SKU can never move an order into ``split``.
    """

    order_lines = list(
        (
            await session.scalars(
                select(OrderLine).where(
                    OrderLine.tenant_id == tenant_id,
                    OrderLine.order_id == order_id,
                )
            )
        ).all()
    )
    expected: dict[UUID, int] = defaultdict(int)
    for line in order_lines:
        expected[line.sku_id] += line.qty

    shipped: dict[UUID, int] = defaultdict(int)
    for entry in shipments:
        for line in entry["lines"]:
            shipped[line["sku_id"]] += line["qty"]

    if dict(shipped) == dict(expected):
        return

    missing = {
        sku_id: expected[sku_id] - shipped.get(sku_id, 0)
        for sku_id in expected
        if shipped.get(sku_id, 0) < expected[sku_id]
    }
    extra = {
        sku_id: shipped[sku_id] - expected.get(sku_id, 0)
        for sku_id in shipped
        if shipped[sku_id] > expected.get(sku_id, 0)
    }
    details: list[str] = []
    if missing:
        details.append(
            "missing "
            + ", ".join(
                f"SKU {sku_id} qty {qty}"
                for sku_id, qty in sorted(missing.items(), key=lambda item: str(item[0]))
            )
        )
    if extra:
        details.append(
            "unexpected "
            + ", ".join(
                f"SKU {sku_id} qty {qty}"
                for sku_id, qty in sorted(extra.items(), key=lambda item: str(item[0]))
            )
        )
    raise ValidationError(
        f"shipments do not match order {order_id} lines: " + "; ".join(details)
    )


async def _plan_inventory(
    session: AsyncSession,
    tenant_id: UUID,
    shipments: list[dict[str, Any]],
) -> tuple[dict[tuple[UUID, UUID], Inventory], list[dict[str, Any]]]:
    """Lock every affected inventory row and prove the whole demand is covered.

    Demand is aggregated per SKU/warehouse before the stock check, so repeated
    lines across shipments cannot each pass a check that the total would fail.
    """

    demand: dict[tuple[UUID, UUID], int] = defaultdict(int)
    for entry in shipments:
        for line in entry["lines"]:
            demand[(entry["warehouse_id"], line["sku_id"])] += line["qty"]

    inventory_rows: dict[tuple[UUID, UUID], Inventory] = {}
    impact: list[dict[str, Any]] = []
    for warehouse_id, sku_id in sorted(demand, key=lambda item: (str(item[0]), str(item[1]))):
        qty = demand[(warehouse_id, sku_id)]
        inventory = await _lock_inventory(session, tenant_id, sku_id, warehouse_id)
        if inventory is None:
            raise InsufficientStock(
                f"insufficient stock for SKU {sku_id} in warehouse {warehouse_id}: "
                f"no inventory row (required {qty})"
            )
        if inventory.available < qty:
            raise InsufficientStock(
                f"insufficient stock for SKU {sku_id} in warehouse {warehouse_id}: "
                f"required {qty}, available {inventory.available}"
            )
        inventory_rows[(warehouse_id, sku_id)] = inventory
        impact.append(
            {
                "sku_id": str(sku_id),
                "warehouse_id": str(warehouse_id),
                "qty": qty,
                "available": inventory.available,
                "reserved": inventory.reserved,
                "version": inventory.version,
            }
        )
    return inventory_rows, impact


async def _shipment_lines(
    session: AsyncSession, tenant_id: UUID, shipment_id: UUID
) -> list[ShipmentLine]:
    return list(
        (
            await session.scalars(
                select(ShipmentLine).where(
                    ShipmentLine.tenant_id == tenant_id,
                    ShipmentLine.shipment_id == shipment_id,
                )
            )
        ).all()
    )


async def _release_shipment_stock(
    session: AsyncSession,
    tenant_id: UUID,
    shipment: Shipment,
    task_id: UUID | None,
) -> list[dict[str, Any]]:
    """Release one shipment's reservation back into available stock.

    Only ledger rows attributed to this exact order and shipment are released.
    The net attributed reservation must still equal the shipment lines;
    otherwise the release fails closed instead of consuming aggregate
    ``inventory.reserved`` that may belong to another order.
    """

    lines = await _shipment_lines(session, tenant_id, shipment.id)
    if not lines:
        raise InvalidState(f"shipment {shipment.id} has no lines")

    demand: dict[UUID, int] = defaultdict(int)
    for line in lines:
        demand[line.sku_id] += line.qty

    ledger_rows = list(
        (
            await session.scalars(
                select(InventoryLedger).where(
                    InventoryLedger.tenant_id == tenant_id,
                    InventoryLedger.order_id == shipment.order_id,
                    InventoryLedger.shipment_id == shipment.id,
                    InventoryLedger.reason.in_(_RESERVATION_REASONS),
                )
            )
        ).all()
    )
    if not ledger_rows:
        raise InvalidState(
            f"no reservation ledger for shipment {shipment.id}; refusing to "
            "release aggregate inventory"
        )

    balance: dict[UUID, int] = defaultdict(int)
    for row in ledger_rows:
        if row.warehouse_id != shipment.warehouse_id:
            raise InvalidState(
                f"reservation ledger for shipment {shipment.id} references "
                f"warehouse {row.warehouse_id}, expected {shipment.warehouse_id}"
            )
        balance[row.sku_id] += row.delta_reserved

    if set(balance) != set(demand) or any(
        balance[sku_id] != qty for sku_id, qty in demand.items()
    ):
        raise InvalidState(
            f"reservation ledger for shipment {shipment.id} does not match "
            "shipment lines"
        )

    inventory_rows: dict[UUID, Inventory] = {}
    for sku_id in sorted(demand, key=str):
        inventory = await _lock_inventory(
            session, tenant_id, sku_id, shipment.warehouse_id
        )
        if inventory is None:
            raise InvalidState(
                f"inventory row missing for SKU {sku_id} in warehouse "
                f"{shipment.warehouse_id}"
            )
        if inventory.reserved < demand[sku_id]:
            raise InvalidState(
                f"reserved inventory for SKU {sku_id} in warehouse "
                f"{shipment.warehouse_id} is {inventory.reserved}, below shipment "
                f"reservation {demand[sku_id]}"
            )
        inventory_rows[sku_id] = inventory

    released: list[dict[str, Any]] = []
    for line in lines:
        inventory = inventory_rows[line.sku_id]
        inventory.available += line.qty
        inventory.reserved -= line.qty
        inventory.version += 1
        session.add(
            InventoryLedger(
                tenant_id=tenant_id,
                order_id=shipment.order_id,
                shipment_id=shipment.id,
                sku_id=line.sku_id,
                warehouse_id=shipment.warehouse_id,
                delta_available=line.qty,
                delta_reserved=-line.qty,
                reason=SPLIT_COMPENSATION_REASON,
                task_id=task_id,
            )
        )
        released.append(
            {
                "sku_id": str(line.sku_id),
                "warehouse_id": str(shipment.warehouse_id),
                "qty": line.qty,
            }
        )
    return released


async def _lock_order_shipments(
    session: AsyncSession, tenant_id: UUID, order_id: UUID
) -> list[Shipment]:
    return list(
        (
            await session.scalars(
                select(Shipment)
                .where(
                    Shipment.tenant_id == tenant_id,
                    Shipment.order_id == order_id,
                )
                .order_by(Shipment.created_at, Shipment.id)
                .with_for_update()
            )
        ).all()
    )


async def split_order(
    session: AsyncSession,
    tenant_id: UUID,
    order_id: UUID,
    shipments: list[dict[str, Any]],
    idempotency_key: str,
    dry_run: bool = False,
    actor_id: UUID | None = None,
    task_id: UUID | None = None,
) -> dict[str, Any]:
    """Split a pending order into shipments, reserving all inventory atomically.

    Every shortage rejects the entire order; no partial split is written.
    ``dry_run`` locks and validates the same rows but returns the impact without
    staging any write. A successful call commits before returning.
    """

    idempotency_key = _validate_idempotency_key(idempotency_key)
    normalized = _normalize_shipments(shipments)
    scope = _split_scope(order_id)
    fingerprint = _request_hash(
        {"order_id": str(order_id), "shipments": _canonical_shipments(normalized)}
    )

    replay = await _replay(session, tenant_id, scope, idempotency_key, fingerprint)
    if replay is not None:
        return replay

    try:
        order = await _lock_order(session, tenant_id, order_id)
        if order is None:
            raise NotFound(f"order {order_id} not found for this tenant")
        if order.status != "pending_shipment":
            replay = await _replay(
                session, tenant_id, scope, idempotency_key, fingerprint
            )
            if replay is not None:
                await session.rollback()
                return replay
            raise InvalidState(
                f"order {order_id} is {order.status!r}, expected 'pending_shipment'"
            )
        existing_shipment = await session.scalar(
            select(Shipment.id)
            .where(Shipment.tenant_id == tenant_id, Shipment.order_id == order_id)
            .limit(1)
        )
        if existing_shipment is not None:
            raise InvalidState(f"order {order_id} already has shipments")

        await _validate_shipment_coverage(
            session, tenant_id, order_id, normalized
        )
        inventory_rows, impact = await _plan_inventory(
            session, tenant_id, normalized
        )

        if dry_run:
            result = {
                "dry_run": True,
                "order_id": str(order_id),
                "order_no": order.order_no,
                "shipments": len(normalized),
                "impact": impact,
            }
            await session.rollback()
            return result

        shipment_ids: list[uuid.UUID] = []
        for entry in normalized:
            shipment_id = uuid.uuid4()
            shipment_ids.append(shipment_id)
            session.add(
                Shipment(
                    id=shipment_id,
                    tenant_id=tenant_id,
                    order_id=order_id,
                    warehouse_id=entry["warehouse_id"],
                    status="created",
                )
            )
            for line in entry["lines"]:
                session.add(
                    ShipmentLine(
                        tenant_id=tenant_id,
                        shipment_id=shipment_id,
                        sku_id=line["sku_id"],
                        qty=line["qty"],
                    )
                )
        # Ledger rows reference shipments by FK; flush the parents first because
        # the models declare plain columns rather than ORM relationships.
        await session.flush()

        for entry, shipment_id in zip(normalized, shipment_ids, strict=True):
            for line in entry["lines"]:
                inventory = inventory_rows[
                    (entry["warehouse_id"], line["sku_id"])
                ]
                inventory.available -= line["qty"]
                inventory.reserved += line["qty"]
                inventory.version += 1
                session.add(
                    InventoryLedger(
                        tenant_id=tenant_id,
                        order_id=order_id,
                        shipment_id=shipment_id,
                        sku_id=line["sku_id"],
                        warehouse_id=entry["warehouse_id"],
                        delta_available=-line["qty"],
                        delta_reserved=line["qty"],
                        reason=SPLIT_RESERVATION_REASON,
                        task_id=task_id,
                    )
                )

        order.status = "split"
        order.version += 1
        response = {
            "order_id": str(order_id),
            "order_no": order.order_no,
            "status": "split",
            "shipments": len(normalized),
            "shipment_ids": [str(shipment_id) for shipment_id in shipment_ids],
        }
        session.add(
            IdempotencyKey(
                tenant_id=tenant_id,
                scope=scope,
                key=idempotency_key,
                request_hash=fingerprint,
                response=response,
                status="completed",
            )
        )
        await write_audit(
            session,
            tenant_id=tenant_id,
            task_id=task_id,
            actor_id=actor_id,
            action="order.split",
            entity_type="sales_order",
            entity_id=str(order_id),
            before={"status": "pending_shipment"},
            after={"status": "split"},
            evidence={
                "impact": impact,
                "shipment_ids": response["shipment_ids"],
            },
        )
        replayed = await _commit_or_replay(
            session, tenant_id, scope, idempotency_key, fingerprint
        )
        return replayed if replayed is not None else response
    except BaseException:
        await session.rollback()
        raise


async def cancel_split(
    session: AsyncSession,
    tenant_id: UUID,
    order_id: UUID,
    idempotency_key: str,
    task_id: UUID | None = None,
) -> dict[str, Any]:
    """Compensate a split: cancel shipments, release stock, restore the order."""

    idempotency_key = _validate_idempotency_key(idempotency_key)
    scope = _cancel_split_scope(order_id)
    fingerprint = _request_hash({"order_id": str(order_id)})

    replay = await _replay(session, tenant_id, scope, idempotency_key, fingerprint)
    if replay is not None:
        return replay

    try:
        order = await _lock_order(session, tenant_id, order_id)
        if order is None:
            raise NotFound(f"order {order_id} not found for this tenant")
        if order.status != "split":
            replay = await _replay(
                session, tenant_id, scope, idempotency_key, fingerprint
            )
            if replay is not None:
                await session.rollback()
                return replay
            raise InvalidState(
                f"order {order_id} is {order.status!r}, expected 'split'"
            )

        shipments = await _lock_order_shipments(session, tenant_id, order_id)
        cancelled = 0
        released: list[dict[str, Any]] = []
        for shipment in shipments:
            if shipment.status != "created":
                continue
            released.extend(
                await _release_shipment_stock(session, tenant_id, shipment, task_id)
            )
            shipment.status = "cancelled"
            cancelled += 1

        order.status = "pending_shipment"
        order.version += 1
        response = {
            "order_id": str(order_id),
            "order_no": order.order_no,
            "status": "compensated",
            "shipments_cancelled": cancelled,
        }
        session.add(
            IdempotencyKey(
                tenant_id=tenant_id,
                scope=scope,
                key=idempotency_key,
                request_hash=fingerprint,
                response=response,
                status="completed",
            )
        )
        await write_audit(
            session,
            tenant_id=tenant_id,
            task_id=task_id,
            actor_id=None,
            action="order.split.cancel",
            entity_type="sales_order",
            entity_id=str(order_id),
            before={"status": "split"},
            after={"status": "pending_shipment"},
            evidence={"shipments": cancelled, "released": released},
        )
        replayed = await _commit_or_replay(
            session, tenant_id, scope, idempotency_key, fingerprint
        )
        return replayed if replayed is not None else response
    except BaseException:
        await session.rollback()
        raise


async def cancel_shipment(
    session: AsyncSession,
    tenant_id: UUID,
    shipment_id: UUID,
    idempotency_key: str,
    task_id: UUID | None = None,
    actor_id: UUID | None = None,
) -> dict[str, Any]:
    """Cancel one shipment and release its reservation back to available stock."""

    idempotency_key = _validate_idempotency_key(idempotency_key)
    scope = _shipment_cancel_scope(shipment_id)
    fingerprint = _request_hash({"shipment_id": str(shipment_id)})

    replay = await _replay(session, tenant_id, scope, idempotency_key, fingerprint)
    if replay is not None:
        return replay

    try:
        shipment = await session.scalar(
            select(Shipment)
            .where(
                Shipment.tenant_id == tenant_id,
                Shipment.id == shipment_id,
            )
            .with_for_update()
        )
        if shipment is None:
            raise NotFound(f"shipment {shipment_id} not found for this tenant")

        if shipment.status == "cancelled":
            result = {
                "shipment_id": str(shipment.id),
                "order_id": str(shipment.order_id),
                "status": "cancelled",
                "already_cancelled": True,
            }
            await session.rollback()
            return result
        if shipment.status != "created":
            raise InvalidState(
                f"shipment {shipment_id} is {shipment.status!r}, expected 'created'"
            )

        released = await _release_shipment_stock(
            session, tenant_id, shipment, task_id
        )
        shipment.status = "cancelled"
        response = {
            "shipment_id": str(shipment.id),
            "order_id": str(shipment.order_id),
            "status": "cancelled",
            "already_cancelled": False,
            "released": released,
        }
        session.add(
            IdempotencyKey(
                tenant_id=tenant_id,
                scope=scope,
                key=idempotency_key,
                request_hash=fingerprint,
                response=response,
                status="completed",
            )
        )
        await write_audit(
            session,
            tenant_id=tenant_id,
            task_id=task_id,
            actor_id=actor_id,
            action="shipment.cancel",
            entity_type="shipment",
            entity_id=str(shipment.id),
            before={"status": "created"},
            after={"status": "cancelled"},
            evidence={"released": released},
        )
        replayed = await _commit_or_replay(
            session, tenant_id, scope, idempotency_key, fingerprint
        )
        return replayed if replayed is not None else response
    except BaseException:
        await session.rollback()
        raise


async def release_inventory(
    session: AsyncSession,
    tenant_id: UUID,
    order_id: UUID,
    idempotency_key: str,
    task_id: UUID | None = None,
    actor_id: UUID | None = None,
) -> dict[str, Any]:
    """Release every active shipment's reservation, leaving the order split.

    This is the inventory half of split compensation; ``cancel_split`` performs
    it together with the order status rollback. Already-cancelled shipments are
    skipped so a reservation is never released twice.
    """

    idempotency_key = _validate_idempotency_key(idempotency_key)
    scope = _inventory_release_scope(order_id)
    fingerprint = _request_hash({"order_id": str(order_id)})

    replay = await _replay(session, tenant_id, scope, idempotency_key, fingerprint)
    if replay is not None:
        return replay

    try:
        order = await _lock_order(session, tenant_id, order_id)
        if order is None:
            raise NotFound(f"order {order_id} not found for this tenant")
        if order.status != "split":
            replay = await _replay(
                session, tenant_id, scope, idempotency_key, fingerprint
            )
            if replay is not None:
                await session.rollback()
                return replay
            raise InvalidState(
                f"order {order_id} is {order.status!r}, expected 'split'"
            )

        shipments = await _lock_order_shipments(session, tenant_id, order_id)
        cancelled = 0
        released: list[dict[str, Any]] = []
        for shipment in shipments:
            if shipment.status != "created":
                continue
            released.extend(
                await _release_shipment_stock(session, tenant_id, shipment, task_id)
            )
            shipment.status = "cancelled"
            cancelled += 1

        response = {
            "order_id": str(order_id),
            "order_no": order.order_no,
            "status": "released",
            "shipments_cancelled": cancelled,
            "released": released,
        }
        session.add(
            IdempotencyKey(
                tenant_id=tenant_id,
                scope=scope,
                key=idempotency_key,
                request_hash=fingerprint,
                response=response,
                status="completed",
            )
        )
        await write_audit(
            session,
            tenant_id=tenant_id,
            task_id=task_id,
            actor_id=actor_id,
            action="inventory.release",
            entity_type="sales_order",
            entity_id=str(order_id),
            before={"status": "split"},
            after={"status": "split"},
            evidence={"shipments": cancelled, "released": released},
        )
        replayed = await _commit_or_replay(
            session, tenant_id, scope, idempotency_key, fingerprint
        )
        return replayed if replayed is not None else response
    except BaseException:
        await session.rollback()
        raise
