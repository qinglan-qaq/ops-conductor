"""计划生成：确定性模板规划器与经过校验的 LLM 规划器。

两个规划器都把同一条任务指令转换为相同的 :class:`Plan` 契约。
:class:`TemplatePlanner` 是固定兜底方案：它按硬编码规则（拦截、改址或拆分）为
每个逾期订单派生一个节点。:class:`LLMPlanner` 要求聊天模型输出 JSON，然后对答案
施加同样的校验，并额外允许一次修复。

Invariants:

- 每个返回的计划都通过 :func:`opsconductor.schemas.validate_plan`，在计划可执行
  前同时校验 Pydantic schema 与节点 DAG。
- 计划只基于为任务租户加载的订单构建；引用其他订单、仓库或 SKU 的 LLM 计划会被
  拒绝。
- LLM 只有一次修复机会；第二次输出仍无效会抛出 :class:`PlanGenerationError`，
  而不是执行任何操作。
- 规划是只读的：只查询仓储，从不写入。
"""

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
    """模型在一次修复后仍无法产出有效计划时抛出。"""


@dataclass
class _OrderContext:
    """用于决定计划节点的单个逾期订单快照。

    Attributes:
        order: 正在为其规划的订单。
        lines: 带请求数量的订单明细。
        shipments: 已有发货单；任何一项都表示订单已拆分，必须拦截。
        available: 订单所在仓库中每个 SKU 的可用库存；没有库存行的 SKU 不出现，
            按零处理。
    """

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
    """解析任务截止时间，把空白字符串视为未设置。

    Args:
        task: 携带可选 ``cutoff`` 值的规划任务。

    Returns:
        解析后的 datetime；截止时间缺失或为空白时返回 ``None``；已是 datetime
        时原样返回。

    Raises:
        ValueError: 字符串形式的截止时间无法按 ISO-8601 解析。
    """

    cutoff = getattr(task, "cutoff", None)
    if isinstance(cutoff, str):
        if not cutoff.strip():
            return None
        return datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
    return cutoff


async def _load_order_contexts(session: AsyncSession, task: Any) -> list[_OrderContext]:
    """为任务中的每个逾期订单加载租户限定上下文。

    Args:
        session: 用于只读仓储查询的会话。
        task: 暴露 ``tenant_id`` 以及可选 ``warehouse``、``cutoff`` 过滤条件
            的规划任务。

    Returns:
        每个逾期订单一个上下文，包含其明细、发货单以及订单所在仓库中逐 SKU 的
        可用库存。
    """

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
    """为单个订单构建固定模板节点。

    规则按顺序匹配，首个命中即生效：存在发货单的订单以 ``already_split`` 拦截；
    没有仓库、没有明细或库存不足的订单按对应原因拦截；地址无效则生成
    ``change_address`` 节点；其余情况生成 ``split_order`` 节点，每条订单明细对应
    一个发货单。

    Args:
        context: 为任务加载的订单快照。

    Returns:
        该订单的拦截、改址或拆分节点。
    """

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
    """返回带各动作计数的本地化单行摘要。"""

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
    """拒绝引用已加载上下文之外订单或参数的计划。

    仅 schema 与 DAG 有效还不够：模型仍可能编造订单 ID、引用其他租户的订单或传入
    执行器不应接受的参数。该校验有意从严，因此计划只能作用于任务已加载的订单。

    Args:
        plan: 模型返回的 schema 有效计划。
        contexts: 提供给模型的租户限定订单快照。

    Raises:
        ValueError: 节点引用未知订单、拆分节点使用其他仓库/SKU 或非正数量，或
            改址节点缺少非空地址。
    """

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
    """检查拆分节点是否停留在其订单的仓库与 SKU 范围内。

    Args:
        node: 待校验的 ``split_order`` 节点。
        contexts_by_order: 计划可引用的全部订单快照。

    Raises:
        ValueError: 节点缺少订单、订单没有仓库、发货单列表为空、发货单指向其他
            仓库、明细引用订单之外的 SKU，或数量不是正整数。
    """

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
    """将模型原始输出转换为绑定该任务的有效计划。

    Args:
        raw: 解码后的模型输出；必须是 JSON 对象。
        task_id: 写入计划的 task ID，覆盖模型输出。
        contexts: 计划可引用的订单快照。

    Returns:
        通过 schema、DAG 与订单上下文校验的计划。

    Raises:
        ValueError: 输出不是对象、未通过 ``Plan`` 校验、未通过 DAG 校验，或
            引用了未提供的上下文。
    """

    if not isinstance(raw, dict):
        raise ValueError("model output must be a JSON object")
    payload = dict(raw)
    payload["task_id"] = task_id
    plan = Plan.model_validate(payload)
    validate_plan(plan)
    _validate_plan_against_contexts(plan, contexts)
    return plan


class TemplatePlanner:
    """面向订单异常任务的确定性兜底规划器。

    对每个逾期订单应用 :func:`_node_for_context` 中的固定规则，因此相同的数据库
    状态总是产出相同的计划。不调用模型，也不写入任何内容。
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def plan(self, task: Any) -> Plan:
        """为任务构建并校验模板计划。

        Args:
            task: 带 ``id``、``tenant_id`` 以及可选仓库与截止时间过滤的规划
                任务。

        Returns:
            每个逾期订单一个节点的有效计划。

        Raises:
            ValueError: 生成的计划未通过 schema 或 DAG 校验。
        """

        contexts = await _load_order_contexts(self.session, task)
        nodes = [_node_for_context(context) for context in contexts]
        plan = Plan(task_id=str(task.id), summary=_summary(nodes), nodes=nodes)
        validate_plan(plan)
        return plan


class LLMPlanner:
    """校验模型输出并在失败时用修复提示重试一次的 LLM 规划器。

    模型在系统提示中收到只读订单上下文，并且必须回复单个 JSON 对象。首次回答会
    按 ``Plan`` schema、DAG 规则与已加载订单上下文校验；失败时携带校验错误发起
    一次修复请求，再次失败则抛出 :class:`PlanGenerationError`。
    """

    def __init__(self, model: ChatModel, session: AsyncSession):
        self.model = model
        self.session = session

    async def plan(self, task: Any) -> Plan:
        """生成有效计划，最多允许一次修复尝试。

        Args:
            task: 带 ``id``、``tenant_id``、指令以及可选仓库与截止时间过滤的
                规划任务。

        Returns:
            通过 schema、DAG 与订单上下文校验的计划。

        Raises:
            PlanGenerationError: 修复尝试后模型输出仍然无效。
        """

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
