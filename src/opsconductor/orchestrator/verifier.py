"""对已执行计划节点做确定性后置校验。

校验器只读：所有检查都通过仓储读取数据库，不写入业务数据、不提交事务，最终
任务状态由执行器决定。

Invariants:

- 只校验 ``results`` 中出现的节点；被审批拒绝或跳过的节点不在其中。
- 拆分校验要求订单状态为 ``split``，且各 SKU 的订单数量总和与发运数量总和
  完全一致（按 SKU 聚合，不要求逐行对应）。
- 校验后每个 SKU 在该仓库的库存 ``available`` 与 ``reserved`` 必须非负。
- 拆分与改址都必须留下对应动作的审计行；改址还必须与计划地址一致。
"""

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
    """一次确定性后置校验的结果。

    Attributes:
        passed: 所有检查是否通过。
        reason: 失败时可读的原因；通过时为空。
    """

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
    """检查已执行拆分/改址节点的确定性后置条件。

    只校验 ``results`` 中出现的节点：被拒绝或未审批而跳过的节点会有意缺席，
    最终任务状态仍由执行器拥有。检查失败返回可读原因，使补偿可解释。

    发运覆盖度按每个 SKU 的数量总和比较，与写入服务强制的约束一致：数量为 3
    的订单行可由数量 2 与 1 的发运行满足，无论这些数量被拆成多少行。

    Note:
        校验器是只读的：它不写业务数据，也不提交事务。
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def verify(
        self, task: Any, plan: Any, results: dict[str, Any]
    ) -> VerificationResult:
        """依次校验计划中出现在 ``results`` 里的写入节点。

        Args:
            task: 任务对象，提供 ``tenant_id`` 与 ``id``。
            plan: 计划对象或字典，含 ``nodes`` 列表。
            results: 节点 ID 到工具输出的映射；不在其中的节点会被跳过。

        Returns:
            首个失败检查的 :class:`VerificationResult`，或全部通过的结果。

        Note:
            只读检查；未知动作的节点会被跳过而不报错。
        """

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
        """校验一次拆分：订单状态、发运数量、库存与审计行。

        Args:
            task: 任务对象，限定租户与审计归属。
            node: 被校验的拆分节点。

        Returns:
            首个失败原因；全部通过时返回 ``None``。

        Note:
            发运覆盖度按每个 SKU 的数量总和比较，这是预期的校验不变量；逐行
            一一对应不是要求。
        """
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
        """校验改址：订单地址与计划地址一致，且存在审计行。

        Args:
            task: 任务对象，限定租户与审计归属。
            node: 被校验的改址节点。

        Returns:
            首个失败原因；全部通过时返回 ``None``。

        Note:
            计划地址可以是完整地址字符串，也可以是逐字段字典；字典只比较出现
            其中的 ``ADDRESS_FIELDS`` 字段。
        """
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
        """按 SKU 聚合订单行的数量总和。"""
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
        """按 SKU 聚合给定发运单下所有发运行的数量总和。"""
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
        """确认任务在租户内留下了指定动作与实体的审计行。"""
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
