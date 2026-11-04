"""Deterministic post-condition verification for executed plan nodes."""

from collections import Counter
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opsconductor.domain import repositories
from opsconductor.domain.address import ADDRESS_FIELDS
from opsconductor.domain.models import AuditLog, OrderLine, Shipment, ShipmentLine

SPLIT_ACTION = "split_order"
ADDRESS_ACTION = "change_address"


class VerificationResult(BaseModel):
    """Outcome of a deterministic post-condition check."""

    passed: bool
    reason: str = ""


def _node_dict(node: Any) -> dict[str, Any]:
    if hasattr(node, "model_dump"):
        return node.model_dump()
    return dict(node)


def _plan_nodes(plan: Any) -> list[dict[str, Any]]:
    if hasattr(plan, "model_dump"):
        plan = plan.model_dump()
    if isinstance(plan, dict):
        return [_node_dict(node) for node in plan.get("nodes", [])]
    return [_node_dict(node) for node in getattr(plan, "nodes", [])]


def _as_uuid(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (AttributeError, TypeError, ValueError):
        return None


class Verifier:
    """Check the deterministic post-conditions of executed split/address nodes.

    Only nodes present in ``results`` are verified: nodes skipped by rejection
    or approval are intentionally absent, and the executor owns the final task
    status. A failed check returns a readable reason so compensation is
    explainable.

    Shipment coverage is compared as per-SKU quantity totals, the same invariant
    the write service enforces: an order line of qty 3 is satisfied by shipment
    lines of qty 2 and 1, regardless of how those quantities are grouped into
    individual shipment-line rows.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def verify(
        self, task: Any, plan: Any, results: dict[str, Any]
    ) -> VerificationResult:
        for node in _plan_nodes(plan):
            node_id = node.get("node_id")
            if node_id not in results:
                continue
            action = node.get("action")
            if action == SPLIT_ACTION:
                failure = await self._verify_split(task, node)
            elif action == ADDRESS_ACTION:
                failure = await self._verify_address(task, node)
            else:
                failure = None
            if failure is not None:
                return VerificationResult(passed=False, reason=failure)
        return VerificationResult(passed=True)

    async def _verify_split(
        self, task: Any, node: dict[str, Any]
    ) -> str | None:
        tenant_id = task.tenant_id
        order_id = _as_uuid(node.get("order_id"))
        if order_id is None:
            return "split node has no valid order_id"

        order = await repositories.get_order(self.session, tenant_id, order_id)
        if order is None:
            return f"order {order_id} not found for this tenant"
        if order.status != "split":
            return (
                f"order {order_id} is {order.status!r}, expected 'split'"
            )

        shipments = await repositories.list_shipments(
            self.session, tenant_id, order_id
        )
        if not shipments:
            return f"order {order_id} has no shipments"

        expected = await self._order_line_multiset(tenant_id, order_id)
        shipped = await self._shipment_line_multiset(tenant_id, shipments)
        if shipped != expected:
            return (
                f"shipment lines do not match order {order_id} lines: "
                f"expected {self._format_multiset(expected)}, "
                f"found {self._format_multiset(shipped)}"
            )

        if order.warehouse_id is None:
            return f"order {order_id} has no warehouse"
        for sku_id in expected:
            inventory = await repositories.get_inventory(
                self.session, tenant_id, sku_id, order.warehouse_id
            )
            if inventory is None:
                return f"inventory row missing for SKU {sku_id}"
            if inventory.available < 0 or inventory.reserved < 0:
                return (
                    f"inventory negative for SKU {sku_id}: "
                    f"available={inventory.available}, "
                    f"reserved={inventory.reserved}"
                )

        audit = await self._audit_exists(task, "order.split", str(order_id))
        if not audit:
            return f"missing audit row for order.split on order {order_id}"
        return None

    async def _verify_address(
        self, task: Any, node: dict[str, Any]
    ) -> str | None:
        tenant_id = task.tenant_id
        order_id = _as_uuid(node.get("order_id"))
        if order_id is None:
            return "change_address node has no valid order_id"

        order = await repositories.get_order(self.session, tenant_id, order_id)
        if order is None:
            return f"order {order_id} not found for this tenant"

        expected = (node.get("params") or {}).get("address")
        if expected is None:
            return f"change_address node for order {order_id} has no planned address"
        if isinstance(expected, str):
            if (order.address_detail or "") != expected.strip():
                return (
                    f"address mismatch for order {order_id}: expected "
                    f"{expected.strip()!r}, found {order.address_detail!r}"
                )
        elif isinstance(expected, dict):
            for field in ADDRESS_FIELDS:
                if field not in expected:
                    continue
                found = getattr(order, field, "") or ""
                if found != str(expected[field]).strip():
                    return (
                        f"address mismatch for order {order_id} field "
                        f"{field!r}: expected {str(expected[field]).strip()!r}, "
                        f"found {found!r}"
                    )
        else:
            return "change_address node has an unsupported address shape"

        audit = await self._audit_exists(
            task, "order.change_address", str(order_id)
        )
        if not audit:
            return (
                "missing audit row for order.change_address on order "
                f"{order_id}"
            )
        return None

    async def _order_line_multiset(
        self, tenant_id: UUID, order_id: UUID
    ) -> Counter[UUID]:
        lines = list(
            (
                await self.session.scalars(
                    select(OrderLine).where(
                        OrderLine.tenant_id == tenant_id,
                        OrderLine.order_id == order_id,
                    )
                )
            ).all()
        )
        totals: Counter[UUID] = Counter()
        for line in lines:
            totals[line.sku_id] += line.qty
        return totals

    async def _shipment_line_multiset(
        self, tenant_id: UUID, shipments: list[Shipment]
    ) -> Counter[UUID]:
        lines = list(
            (
                await self.session.scalars(
                    select(ShipmentLine).where(
                        ShipmentLine.tenant_id == tenant_id,
                        ShipmentLine.shipment_id.in_(
                            [shipment.id for shipment in shipments]
                        ),
                    )
                )
            ).all()
        )
        totals: Counter[UUID] = Counter()
        for line in lines:
            totals[line.sku_id] += line.qty
        return totals

    @staticmethod
    def _format_multiset(totals: Counter[UUID]) -> str:
        if not totals:
            return "{}"
        return "{" + ", ".join(
            f"{sku_id}: {qty}" for sku_id, qty in sorted(totals.items(), key=str)
        ) + "}"

    async def _audit_exists(
        self, task: Any, action: str, entity_id: str
    ) -> bool:
        found = await self.session.scalar(
            select(AuditLog.id)
            .where(
                AuditLog.tenant_id == task.tenant_id,
                AuditLog.task_id == task.id,
                AuditLog.action == action,
                AuditLog.entity_id == entity_id,
            )
            .limit(1)
        )
        return found is not None
