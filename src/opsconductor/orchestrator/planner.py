"""Plan generation: deterministic template planner and validated LLM planner."""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from opsconductor.domain import repositories
from opsconductor.domain.address import address_is_valid, normalized_address
from opsconductor.domain.models import OrderLine, SalesOrder, Shipment
from opsconductor.llm.gateway import ChatModel
from opsconductor.schemas import Plan, PlanNode, validate_plan


class PlanGenerationError(RuntimeError):
    """Raised when a model cannot produce a valid plan after one repair."""


@dataclass
class _OrderContext:
    order: SalesOrder
    lines: list[OrderLine]
    shipments: list[Shipment]
    available: dict[UUID, int]


_READ_TOOLS = [
    "order_list_overdue(tenant_id, warehouse?, cutoff?)",
    "order_get(tenant_id, order_id)",
    "inventory_get(tenant_id, sku_id, warehouse_id)",
    "shipment_list(tenant_id, order_id)",
    "order_get_state(tenant_id, order_id)",
    "address_validate(tenant_id, order_id)",
]


def _task_cutoff(task: Any) -> datetime | None:
    cutoff = getattr(task, "cutoff", None)
    if isinstance(cutoff, str):
        if not cutoff.strip():
            return None
        return datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
    return cutoff


async def _load_order_contexts(session: AsyncSession, task: Any) -> list[_OrderContext]:
    tenant_id = task.tenant_id
    orders = await repositories.list_overdue_orders(
        session,
        tenant_id,
        getattr(task, "warehouse", None),
        _task_cutoff(task),
    )
    contexts: list[_OrderContext] = []
    for order in orders:
        lines = await repositories.list_order_lines(session, tenant_id, order.id)
        shipments = await repositories.list_shipments(session, tenant_id, order.id)
        available: dict[UUID, int] = {}
        if order.warehouse_id is not None:
            for line in lines:
                inventory = await repositories.get_inventory(
                    session, tenant_id, line.sku_id, order.warehouse_id
                )
                available[line.sku_id] = inventory.available if inventory is not None else 0
        contexts.append(
            _OrderContext(
                order=order,
                lines=lines,
                shipments=shipments,
                available=available,
            )
        )
    return contexts


def _base_evidence(order: SalesOrder) -> dict[str, Any]:
    return {"order_no": order.order_no, "status": order.status}


def _block_node(order: SalesOrder, reason: str, evidence: dict[str, Any]) -> PlanNode:
    return PlanNode(
        node_id=f"{order.order_no}-block_order",
        order_id=order.id,
        action="block_order",
        reason=reason,
        evidence={**_base_evidence(order), **evidence},
    )


def _node_for_context(context: _OrderContext) -> PlanNode:
    order = context.order
    if context.shipments:
        return _block_node(
            order,
            "already_split",
            {"shipment_ids": [str(shipment.id) for shipment in context.shipments]},
        )
    if order.warehouse_id is None:
        return _block_node(order, "missing_warehouse", {})
    if not context.lines:
        return _block_node(order, "no_lines", {})

    shortages = [
        {
            "sku_id": str(line.sku_id),
            "required": line.qty,
            "available": context.available.get(line.sku_id, 0),
        }
        for line in context.lines
        if line.qty > context.available.get(line.sku_id, 0)
    ]
    if shortages:
        return _block_node(order, "insufficient_stock", {"shortages": shortages})

    if not address_is_valid(order):
        return PlanNode(
            node_id=f"{order.order_no}-change_address",
            order_id=order.id,
            action="change_address",
            reason="invalid_address",
            params={"address": normalized_address(order)},
            evidence={**_base_evidence(order), "address_detail": order.address_detail},
        )

    shipments = [
        {
            "warehouse_id": str(order.warehouse_id),
            "lines": [{"sku_id": str(line.sku_id), "qty": line.qty}],
        }
        for line in context.lines
    ]
    return PlanNode(
        node_id=f"{order.order_no}-split_order",
        order_id=order.id,
        action="split_order",
        params={"shipments": shipments},
        evidence={
            **_base_evidence(order),
            "lines": len(context.lines),
            "shipments": len(shipments),
        },
    )


def _summary(nodes: list[PlanNode]) -> str:
    if not nodes:
        return "没有符合条件的待处理订单。"
    counts = {"split_order": 0, "change_address": 0, "block_order": 0}
    for node in nodes:
        counts[node.action] = counts.get(node.action, 0) + 1
    return (
        f"共处理 {len(nodes)} 个订单：拆分 {counts['split_order']} 个，"
        f"改址 {counts['change_address']} 个，拦截 {counts['block_order']} 个。"
    )


def _order_summary(contexts: list[_OrderContext]) -> list[dict[str, Any]]:
    return [
        {
            "order_id": str(context.order.id),
            "order_no": context.order.order_no,
            "status": context.order.status,
            "warehouse_id": (
                str(context.order.warehouse_id)
                if context.order.warehouse_id is not None
                else None
            ),
            "address_valid": address_is_valid(context.order),
            "address_detail": context.order.address_detail,
            "lines": [
                {
                    "sku_id": str(line.sku_id),
                    "qty": line.qty,
                    "available": context.available.get(line.sku_id, 0),
                }
                for line in context.lines
            ],
            "shipments": [str(shipment.id) for shipment in context.shipments],
        }
        for context in contexts
    ]


def _system_prompt(contexts: list[_OrderContext]) -> str:
    schema = json.dumps(Plan.model_json_schema(), ensure_ascii=False)
    tools = "\n".join(f"- {tool}" for tool in _READ_TOOLS)
    orders = json.dumps(_order_summary(contexts), ensure_ascii=False)
    return (
        "你是电商 ERP 运营计划生成器，只输出单个 JSON 对象，不执行写操作。\n"
        f"可用只读工具：\n{tools}\n"
        f"输出必须符合以下 JSON Schema：\n{schema}\n"
        "约束：不要编造订单；task_id 由系统填写；每个 node_id 必须唯一，"
        "depends_on 只能引用已知 node_id。\n"
        f"当前订单摘要：\n{orders}"
    )


def _user_prompt(task: Any) -> str:
    return (
        f"任务指令：{getattr(task, 'instruction', '')}\n"
        f"tenant_id：{task.tenant_id}\n"
        f"warehouse：{getattr(task, 'warehouse', None)}\n"
        f"cutoff：{_task_cutoff(task)}\n"
        "请生成计划 JSON。"
    )


def _repair_prompt(task: Any, previous: Any, error: Exception) -> str:
    if previous is None:
        previous_text = "(no parsable JSON output)"
    else:
        try:
            previous_text = json.dumps(previous, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            previous_text = repr(previous)
    if len(previous_text) > 4000:
        previous_text = f"{previous_text[:4000]}...(truncated)"
    return (
        f"任务指令：{getattr(task, 'instruction', '')}\n"
        f"上一次输出未通过校验：{error}\n"
        f"上一次输出：{previous_text}\n"
        "请修正后只输出一个符合 schema 的 JSON 对象。"
    )


def _validate_plan_against_contexts(plan: Plan, contexts: list[_OrderContext]) -> None:
    """Reject plans that reference orders or params outside the loaded context."""

    contexts_by_order = {context.order.id: context for context in contexts}
    for node in plan.nodes:
        if node.order_id is not None and node.order_id not in contexts_by_order:
            raise ValueError(f"plan references unknown order: {node.order_id}")
        if node.action == "split_order":
            _validate_split_node(node, contexts_by_order)
        elif node.action == "change_address":
            address = node.params.get("address")
            if not isinstance(address, str) or not address.strip():
                raise ValueError(
                    f"change_address node {node.node_id} requires a non-empty address"
                )


def _validate_split_node(
    node: PlanNode, contexts_by_order: dict[UUID, _OrderContext]
) -> None:
    if node.order_id is None:
        raise ValueError(f"split_order node {node.node_id} requires an order_id")
    context = contexts_by_order[node.order_id]
    order = context.order
    if order.warehouse_id is None:
        raise ValueError(
            f"split_order node {node.node_id} references an order without a warehouse"
        )
    shipments = node.params.get("shipments")
    if not isinstance(shipments, list) or not shipments:
        raise ValueError(
            f"split_order node {node.node_id} requires a non-empty shipments list"
        )
    order_skus = {str(line.sku_id) for line in context.lines}
    for shipment in shipments:
        if not isinstance(shipment, dict):
            raise ValueError(f"split_order node {node.node_id} has an invalid shipment")
        if str(shipment.get("warehouse_id")) != str(order.warehouse_id):
            raise ValueError(
                f"split_order node {node.node_id} shipment warehouse does not match "
                f"order {order.order_no}"
            )
        lines = shipment.get("lines")
        if not isinstance(lines, list) or not lines:
            raise ValueError(
                f"split_order node {node.node_id} requires non-empty shipment lines"
            )
        for line in lines:
            if not isinstance(line, dict):
                raise ValueError(f"split_order node {node.node_id} has an invalid line")
            sku_id = line.get("sku_id")
            qty = line.get("qty")
            if not isinstance(sku_id, str) or sku_id not in order_skus:
                raise ValueError(
                    f"split_order node {node.node_id} references SKU {sku_id!r} "
                    f"outside order {order.order_no}"
                )
            if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
                raise ValueError(
                    f"split_order node {node.node_id} requires positive line quantities"
                )


def _parse_plan(raw: Any, task_id: str, contexts: list[_OrderContext]) -> Plan:
    if not isinstance(raw, dict):
        raise ValueError("model output must be a JSON object")
    payload = dict(raw)
    payload["task_id"] = task_id
    plan = Plan.model_validate(payload)
    validate_plan(plan)
    _validate_plan_against_contexts(plan, contexts)
    return plan


class TemplatePlanner:
    """Deterministic fallback planner for order-exception tasks."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def plan(self, task: Any) -> Plan:
        contexts = await _load_order_contexts(self.session, task)
        nodes = [_node_for_context(context) for context in contexts]
        plan = Plan(task_id=str(task.id), summary=_summary(nodes), nodes=nodes)
        validate_plan(plan)
        return plan


class LLMPlanner:
    """LLM planner that validates output and retries once with a repair prompt."""

    def __init__(self, model: ChatModel, session: AsyncSession):
        self.model = model
        self.session = session

    async def plan(self, task: Any) -> Plan:
        contexts = await _load_order_contexts(self.session, task)
        system = _system_prompt(contexts)
        raw: Any = None
        try:
            raw = await self.model.complete_json(system=system, user=_user_prompt(task))
            return _parse_plan(raw, str(task.id), contexts)
        except ValueError as first_error:
            try:
                repaired = await self.model.complete_json(
                    system=system,
                    user=_repair_prompt(task, raw, first_error),
                )
                return _parse_plan(repaired, str(task.id), contexts)
            except ValueError as second_error:
                raise PlanGenerationError(
                    "LLM planner produced an invalid plan after one repair attempt: "
                    f"{second_error}"
                ) from second_error
