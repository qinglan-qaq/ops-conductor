"""Golden task table for the MVP order-exception flow.

Each case mirrors one row of section 9.1 in
``docs/specs/2026-11-04-mvp-order-exception-design.md``. Plans are fixed stubs
(the spec requires golden tests to use fixed plan output, not a live model),
while every write is executed by the real write services through the
fault-aware tool gateway in ``tests/eval/harness.py``.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid5

from opsconductor.domain.seed import SKU_IDS, WAREHOUSE_EAST
from opsconductor.schemas import Plan, PlanNode

BASE_INSTRUCTION = "处理今天华东仓超时未发货的订单"
DEFAULT_CUTOFF = "2026-11-04T00:00:00Z"
OPERATOR_API_KEY = "dev-operator-a"
APPROVER_API_KEY = "dev-approver-a"
TENANT_B_OPERATOR_API_KEY = "dev-operator-b"

CATEGORY_MAIN = "main"
CATEGORY_VALIDATION = "validation/state"
CATEGORY_INVENTORY = "inventory"
CATEGORY_APPROVAL = "approval"
CATEGORY_IDEMPOTENCY = "idempotency"
CATEGORY_COMPENSATION = "failure/compensation"
CATEGORY_SECURITY = "tenant/security"

ORDER_LINES: dict[str, tuple[tuple[str, int], ...]] = {
    "O1001": (("SKU-001", 2), ("SKU-002", 1)),
    "O1002": (("SKU-006", 1),),
    "O1003": (("SKU-003", 5),),
    "O1004": (("SKU-004", 1),),
    "O1005": (("SKU-005", 1),),
    "O1006": (("SKU-006", 2),),
}


def order_id(order_no: str) -> UUID:
    return uuid5(NAMESPACE_DNS, f"opsconductor.order-{order_no}")


def _split_node(order_no: str) -> PlanNode:
    shipments = [
        {
            "warehouse_id": str(WAREHOUSE_EAST),
            "lines": [{"sku_id": str(SKU_IDS[sku_code]), "qty": qty}],
        }
        for sku_code, qty in ORDER_LINES[order_no]
    ]
    return PlanNode(
        node_id=f"{order_no}-split_order",
        order_id=order_id(order_no),
        action="split_order",
        params={"shipments": shipments},
        evidence={"order_no": order_no},
    )


def _address_node(order_no: str, address: str) -> PlanNode:
    return PlanNode(
        node_id=f"{order_no}-change_address",
        order_id=order_id(order_no),
        action="change_address",
        params={"address": address},
        evidence={"order_no": order_no, "reason": "invalid_address"},
    )


def _plan(task_id: str, *nodes: PlanNode) -> Plan:
    return Plan(task_id=task_id, summary="golden stub plan", nodes=list(nodes))


def _plan_split_o1001(task_id: str) -> Plan:
    return _plan(task_id, _split_node("O1001"))


def _plan_split_o1003(task_id: str) -> Plan:
    return _plan(task_id, _split_node("O1003"))


def _plan_split_o1004(task_id: str) -> Plan:
    return _plan(task_id, _split_node("O1004"))


def _plan_address_o1002(task_id: str) -> Plan:
    return _plan(
        task_id, _address_node("O1002", "上海市浦东新区世纪大道100号")
    )


def _plan_address_o1005(task_id: str) -> Plan:
    return _plan(task_id, _address_node("O1005", "新地址 1 号"))


def _plan_mixed(task_id: str) -> Plan:
    return _plan(
        task_id,
        _split_node("O1001"),
        _address_node("O1002", "上海市浦东新区世纪大道100号"),
    )


def _plan_split_two(task_id: str) -> Plan:
    return _plan(task_id, _split_node("O1001"), _split_node("O1004"))


def _plan_split_three(task_id: str) -> Plan:
    return _plan(
        task_id,
        _split_node("O1001"),
        _split_node("O1004"),
        _split_node("O1006"),
    )


def _plan_invalid(task_id: str) -> Plan:
    duplicate = _split_node("O1001")
    duplicate.node_id = "duplicate-node"
    other = _split_node("O1004")
    other.node_id = "duplicate-node"
    return _plan(task_id, duplicate, other)


PLANS = {
    "split_o1001": _plan_split_o1001,
    "split_o1003": _plan_split_o1003,
    "split_o1004": _plan_split_o1004,
    "address_o1002": _plan_address_o1002,
    "address_o1005": _plan_address_o1005,
    "mixed_o1001_o1002": _plan_mixed,
    "split_two_o1001_o1004": _plan_split_two,
    "split_three": _plan_split_three,
    "invalid_plan": _plan_invalid,
}


def build_plan(name: str, task_id: str) -> Plan:
    """Build a fixed stub plan for a golden case."""

    return PLANS[name](task_id)


@dataclass(frozen=True)
class ApprovalDirective:
    """One golden-case approval decision, scoped to an order and action."""

    order_no: str
    action: str | None
    approved: bool


@dataclass(frozen=True)
class ToolFault:
    """Order- and phase-scoped fault handled by the eval tool gateway."""

    tool: str
    mode: str
    order_no: str | None = None
    phase: str | None = None
    times: int = 1


@dataclass(frozen=True)
class GoldenCase:
    """One row of the 28-case MVP golden table."""

    id: str
    category: str
    scenario: str
    instruction: str
    api_key: str
    approvals: tuple[ApprovalDirective, ...]
    expected_status: str
    expected_orders: Mapping[str, str] = field(default_factory=dict)
    forbidden_writes: frozenset[str] = frozenset()
    faults: Mapping[str, str] = field(default_factory=dict)
    fault_plan: tuple[ToolFault, ...] = ()
    plan: str | None = None
    pre_setup: tuple[str, ...] = ()
    post_create_setup: tuple[str, ...] = ()
    driver: str = "execute"
    decider: str = "operator"
    l3_threshold: int | None = None
    verifier: str = "real"
    expected_first_status: str | None = None
    expected_writes: tuple[str, ...] = ()
    expected_compensations: tuple[str, ...] = ()
    expected_error_codes: tuple[str, ...] = ()
    expected_error_text: str | None = None
    expected_shipments: Mapping[str, int] = field(default_factory=dict)
    expected_shipment_statuses: Mapping[str, str] = field(default_factory=dict)
    expected_shipment_lines: Mapping[
        str, tuple[tuple[str, int], ...]
    ] = field(default_factory=dict)
    expected_inventory: Mapping[str, tuple[int, int]] = field(
        default_factory=dict
    )
    expected_order_tenants: Mapping[str, str] = field(default_factory=dict)
    expected_approval_status: str | None = None
    expected_denial_status: int | None = None
    slow: bool = False
    notes: str = ""


def _approve(order_no: str, action: str | None = None) -> ApprovalDirective:
    return ApprovalDirective(order_no=order_no, action=action, approved=True)


def _reject(order_no: str, action: str | None = None) -> ApprovalDirective:
    return ApprovalDirective(order_no=order_no, action=action, approved=False)


INV_O1001_SPLIT = {"SKU-001": (98, 2), "SKU-002": (99, 1)}
INV_THREE_SPLIT = {
    **INV_O1001_SPLIT,
    "SKU-004": (99, 1),
    "SKU-006": (98, 2),
}
INV_RESTORED_O1001 = {"SKU-001": (100, 0), "SKU-002": (100, 0)}


GOLDEN_CASES: tuple[GoldenCase, ...] = (
    GoldenCase(
        id="GT-01",
        category=CATEGORY_MAIN,
        scenario="单笔拆单，库存充足",
        instruction=BASE_INSTRUCTION,
        api_key=OPERATOR_API_KEY,
        plan="split_o1001",
        approvals=(_approve("O1001", "split_order"),),
        expected_status="succeeded",
        expected_orders={"O1001": "split"},
        expected_writes=("order_split:O1001",),
        expected_shipments={"O1001": 2},
        expected_shipment_statuses={"O1001": "created"},
        expected_shipment_lines={"O1001": (("SKU-001", 2), ("SKU-002", 1))},
        expected_inventory=INV_O1001_SPLIT,
        expected_approval_status="approved",
        notes="O1001 has two lines and splits into two shipments.",
    ),
    GoldenCase(
        id="GT-02",
        category=CATEGORY_MAIN,
        scenario="多行订单拆单",
        instruction=BASE_INSTRUCTION,
        api_key=OPERATOR_API_KEY,
        plan="split_o1001",
        approvals=(_approve("O1001", "split_order"),),
        expected_status="succeeded",
        expected_orders={"O1001": "split"},
        expected_writes=("order_split:O1001",),
        expected_shipments={"O1001": 2},
        expected_shipment_statuses={"O1001": "created"},
        expected_shipment_lines={"O1001": (("SKU-001", 2), ("SKU-002", 1))},
        expected_inventory=INV_O1001_SPLIT,
        expected_approval_status="approved",
        notes="Shipment-line per-SKU totals must equal order-line totals.",
    ),
    GoldenCase(
        id="GT-03",
        category=CATEGORY_MAIN,
        scenario="发货前改址",
        instruction=BASE_INSTRUCTION,
        api_key=OPERATOR_API_KEY,
        plan="address_o1002",
        approvals=(_approve("O1002", "change_address"),),
        expected_status="succeeded",
        expected_orders={"O1002": "pending_shipment"},
        expected_writes=("order_change_address:O1002",),
        expected_shipments={"O1002": 0},
        expected_approval_status="approved",
        notes="Address changes while the order stays pending_shipment.",
    ),
    GoldenCase(
        id="GT-04",
        category=CATEGORY_MAIN,
        scenario="拆单 + 改址混合任务",
        instruction=BASE_INSTRUCTION,
        api_key=OPERATOR_API_KEY,
        plan="mixed_o1001_o1002",
        approvals=(
            _approve("O1001", "split_order"),
            _approve("O1002", "change_address"),
        ),
        expected_status="succeeded",
        expected_orders={"O1001": "split", "O1002": "pending_shipment"},
        expected_writes=(
            "order_split:O1001",
            "order_change_address:O1002",
        ),
        expected_shipments={"O1001": 2, "O1002": 0},
        expected_shipment_statuses={"O1001": "created"},
        expected_inventory=INV_O1001_SPLIT,
        expected_approval_status="approved",
    ),
    GoldenCase(
        id="GT-05",
        category=CATEGORY_MAIN,
        scenario="多订单正常处理",
        instruction=BASE_INSTRUCTION,
        api_key=OPERATOR_API_KEY,
        driver="execute_twice",
        approvals=(
            _approve("O1001", "split_order"),
            _approve("O1002", "change_address"),
            _approve("O1004", "split_order"),
            _approve("O1006", "split_order"),
        ),
        expected_status="succeeded",
        expected_orders={
            "O1001": "split",
            "O1002": "pending_shipment",
            "O1003": "pending_shipment",
            "O1004": "split",
            "O1006": "split",
        },
        expected_writes=(
            "order_split:O1001",
            "order_change_address:O1002",
            "order_split:O1004",
            "order_split:O1006",
        ),
        expected_shipments={"O1001": 2, "O1002": 0, "O1004": 1, "O1006": 1},
        expected_shipment_statuses={
            "O1001": "created",
            "O1004": "created",
            "O1006": "created",
        },
        expected_inventory=INV_THREE_SPLIT,
        expected_approval_status="approved",
        notes="Template plan exercises O1003 blocking and a second no-op run.",
    ),
    GoldenCase(
        id="GT-06",
        category=CATEGORY_VALIDATION,
        scenario="非法地址",
        instruction=BASE_INSTRUCTION,
        api_key=OPERATOR_API_KEY,
        plan="address_o1002",
        pre_setup=("invalidate_o1002_phone",),
        approvals=(_approve("O1002", "change_address"),),
        expected_status="failed",
        expected_orders={"O1002": "pending_shipment"},
        forbidden_writes=frozenset({"order_change_address"}),
        expected_error_codes=("VALIDATION_ERROR",),
        expected_error_text="invalid address",
        expected_shipments={"O1002": 0},
        expected_approval_status="approved",
    ),
    GoldenCase(
        id="GT-07",
        category=CATEGORY_VALIDATION,
        scenario="已拆单后改址",
        instruction=BASE_INSTRUCTION,
        api_key=OPERATOR_API_KEY,
        plan="address_o1005",
        approvals=(_approve("O1005", "change_address"),),
        expected_status="failed",
        expected_orders={"O1005": "split"},
        forbidden_writes=frozenset({"order_change_address"}),
        expected_error_codes=("INVALID_STATE",),
        expected_error_text="expected 'pending_shipment'",
        expected_shipments={"O1005": 1},
        expected_shipment_statuses={"O1005": "created"},
        expected_approval_status="approved",
    ),
    GoldenCase(
        id="GT-08",
        category=CATEGORY_VALIDATION,
        scenario="Planner 输出非法计划",
        instruction=BASE_INSTRUCTION,
        api_key=OPERATOR_API_KEY,
        plan="invalid_plan",
        driver="creation_failure",
        approvals=(),
        expected_status="creation_failed",
        forbidden_writes=frozenset(
            {"order_split", "order_change_address"}
        ),
        notes="Duplicate node_id fails plan validation; no task is committed.",
    ),
    GoldenCase(
        id="GT-09",
        category=CATEGORY_VALIDATION,
        scenario="订单不存在",
        instruction=BASE_INSTRUCTION,
        api_key=OPERATOR_API_KEY,
        plan="split_o1004",
        post_create_setup=("move_o1004_to_tenant_b",),
        approvals=(_approve("O1004", "split_order"),),
        expected_status="failed",
        expected_orders={"O1004": "pending_shipment"},
        expected_order_tenants={"O1004": "tenant-b"},
        forbidden_writes=frozenset({"order_split"}),
        expected_error_codes=("NOT_FOUND",),
        expected_error_text="not found",
        expected_shipments={"O1004": 0},
        expected_approval_status="approved",
        notes="O1004 is moved out of tenant A after planning; writes fail closed.",
    ),
    GoldenCase(
        id="GT-10",
        category=CATEGORY_INVENTORY,
        scenario="库存不足",
        instruction=BASE_INSTRUCTION,
        api_key=OPERATOR_API_KEY,
        plan="split_o1003",
        approvals=(_approve("O1003", "split_order"),),
        expected_status="failed",
        expected_orders={"O1003": "pending_shipment"},
        forbidden_writes=frozenset({"order_split"}),
        expected_error_codes=("INSUFFICIENT_STOCK",),
        expected_error_text="insufficient stock",
        expected_shipments={"O1003": 0},
        expected_inventory={"SKU-003": (0, 0)},
        expected_approval_status="approved",
    ),
    GoldenCase(
        id="GT-11",
        category=CATEGORY_INVENTORY,
        scenario="部分行库存不足",
        instruction=BASE_INSTRUCTION,
        api_key=OPERATOR_API_KEY,
        plan="split_o1001",
        pre_setup=("zero_sku_002",),
        approvals=(_approve("O1001", "split_order"),),
        expected_status="failed",
        expected_orders={"O1001": "pending_shipment"},
        forbidden_writes=frozenset({"order_split"}),
        expected_error_codes=("INSUFFICIENT_STOCK",),
        expected_error_text="insufficient stock",
        expected_shipments={"O1001": 0},
        expected_inventory={"SKU-001": (100, 0), "SKU-002": (0, 0)},
        expected_approval_status="approved",
        notes="One short line rejects the whole order; no partial shipment.",
    ),
    GoldenCase(
        id="GT-12",
        category=CATEGORY_INVENTORY,
        scenario="并发预占冲突",
        instruction=BASE_INSTRUCTION,
        api_key=OPERATOR_API_KEY,
        plan="split_o1001",
        driver="concurrent",
        approvals=(_approve("O1001", "split_order"),),
        expected_status="concurrent_split",
        expected_orders={"O1001": "split"},
        expected_shipments={"O1001": 2},
        expected_shipment_statuses={"O1001": "created"},
        expected_inventory=INV_O1001_SPLIT,
        slow=True,
        notes="Two tasks race on one order; exactly one wins, the other fails safely.",
    ),
    GoldenCase(
        id="GT-13",
        category=CATEGORY_INVENTORY,
        scenario="后置库存不一致",
        instruction=BASE_INSTRUCTION,
        api_key=OPERATOR_API_KEY,
        plan="split_o1001",
        verifier="corrupt_inventory",
        approvals=(_approve("O1001", "split_order"),),
        expected_status="partially_succeeded",
        expected_orders={"O1001": "pending_shipment"},
        expected_writes=("order_split:O1001",),
        expected_compensations=("order_revert_split:O1001",),
        expected_shipments={"O1001": 2},
        expected_shipment_statuses={"O1001": "cancelled"},
        expected_inventory={"SKU-001": (1, 0), "SKU-002": (100, 0)},
        expected_approval_status="approved",
        notes="Verifier sees injected negative available stock and compensates.",
    ),
    GoldenCase(
        id="GT-14",
        category=CATEGORY_APPROVAL,
        scenario="L2 通过",
        instruction=BASE_INSTRUCTION,
        api_key=OPERATOR_API_KEY,
        plan="split_o1001",
        approvals=(_approve("O1001", "split_order"),),
        expected_status="succeeded",
        expected_orders={"O1001": "split"},
        expected_writes=("order_split:O1001",),
        expected_shipments={"O1001": 2},
        expected_shipment_statuses={"O1001": "created"},
        expected_inventory=INV_O1001_SPLIT,
        expected_approval_status="approved",
    ),
    GoldenCase(
        id="GT-15",
        category=CATEGORY_APPROVAL,
        scenario="L2 拒绝",
        instruction=BASE_INSTRUCTION,
        api_key=OPERATOR_API_KEY,
        plan="split_o1001",
        approvals=(_reject("O1001", "split_order"),),
        expected_status="partially_succeeded",
        expected_orders={"O1001": "pending_shipment"},
        expected_shipments={"O1001": 0},
        expected_inventory=INV_RESTORED_O1001,
        expected_approval_status="rejected",
    ),
    GoldenCase(
        id="GT-16",
        category=CATEGORY_APPROVAL,
        scenario="L3 通过（测试阈值下调）",
        instruction=BASE_INSTRUCTION,
        api_key=APPROVER_API_KEY,
        plan="split_three",
        l3_threshold=3,
        decider="approver",
        approvals=(
            _approve("O1001", "split_order"),
            _approve("O1004", "split_order"),
            _approve("O1006", "split_order"),
        ),
        expected_status="succeeded",
        expected_orders={
            "O1001": "split",
            "O1004": "split",
            "O1006": "split",
        },
        expected_writes=(
            "order_split:O1001",
            "order_split:O1004",
            "order_split:O1006",
        ),
        expected_shipments={"O1001": 2, "O1004": 1, "O1006": 1},
        expected_shipment_statuses={
            "O1001": "created",
            "O1004": "created",
            "O1006": "created",
        },
        expected_inventory=INV_THREE_SPLIT,
        expected_approval_status="approved",
    ),
    GoldenCase(
        id="GT-17",
        category=CATEGORY_APPROVAL,
        scenario="L3 拒绝",
        instruction=BASE_INSTRUCTION,
        api_key=APPROVER_API_KEY,
        plan="split_three",
        l3_threshold=3,
        decider="approver",
        approvals=(
            _reject("O1001", "split_order"),
            _reject("O1004", "split_order"),
            _reject("O1006", "split_order"),
        ),
        expected_status="partially_succeeded",
        expected_orders={
            "O1001": "pending_shipment",
            "O1004": "pending_shipment",
            "O1006": "pending_shipment",
        },
        expected_shipments={"O1001": 0, "O1004": 0, "O1006": 0},
        expected_inventory={
            "SKU-001": (100, 0),
            "SKU-002": (100, 0),
            "SKU-004": (100, 0),
            "SKU-006": (100, 0),
        },
        expected_approval_status="rejected",
    ),
    GoldenCase(
        id="GT-18",
        category=CATEGORY_APPROVAL,
        scenario="审批超时后恢复",
        instruction=BASE_INSTRUCTION,
        api_key=OPERATOR_API_KEY,
        plan="split_o1001",
        driver="await_then_resume",
        approvals=(_approve("O1001", "split_order"),),
        expected_status="succeeded",
        expected_first_status="awaiting_approval",
        expected_orders={"O1001": "split"},
        expected_writes=("order_split:O1001",),
        expected_shipments={"O1001": 2},
        expected_shipment_statuses={"O1001": "created"},
        expected_inventory=INV_O1001_SPLIT,
        expected_approval_status="approved",
    ),
    GoldenCase(
        id="GT-19",
        category=CATEGORY_IDEMPOTENCY,
        scenario="重复提交同一任务",
        instruction=BASE_INSTRUCTION,
        api_key=OPERATOR_API_KEY,
        plan="split_o1001",
        driver="duplicate_create",
        approvals=(_approve("O1001", "split_order"),),
        expected_status="succeeded",
        expected_orders={"O1001": "split"},
        expected_writes=("order_split:O1001",),
        expected_shipments={"O1001": 2},
        expected_shipment_statuses={"O1001": "created"},
        expected_inventory=INV_O1001_SPLIT,
        expected_approval_status="approved",
    ),
    GoldenCase(
        id="GT-20",
        category=CATEGORY_IDEMPOTENCY,
        scenario="重复审批",
        instruction=BASE_INSTRUCTION,
        api_key=OPERATOR_API_KEY,
        plan="split_o1001",
        driver="duplicate_approve",
        approvals=(_approve("O1001", "split_order"),),
        expected_status="succeeded",
        expected_orders={"O1001": "split"},
        expected_writes=("order_split:O1001",),
        expected_shipments={"O1001": 2},
        expected_shipment_statuses={"O1001": "created"},
        expected_inventory=INV_O1001_SPLIT,
        expected_approval_status="approved",
    ),
    GoldenCase(
        id="GT-21",
        category=CATEGORY_IDEMPOTENCY,
        scenario="超时重试",
        instruction=BASE_INSTRUCTION,
        api_key=OPERATOR_API_KEY,
        plan="split_o1001",
        driver="retry",
        fault_plan=(
            ToolFault(
                tool="order_split",
                mode="timeout_after_commit",
                order_no="O1001",
                phase="execute",
            ),
        ),
        approvals=(_approve("O1001", "split_order"),),
        expected_status="succeeded",
        expected_first_status="failed",
        expected_orders={"O1001": "split"},
        expected_writes=("order_split:O1001",),
        expected_shipments={"O1001": 2},
        expected_shipment_statuses={"O1001": "created"},
        expected_inventory=INV_O1001_SPLIT,
        expected_approval_status="approved",
        notes="Committed write loses its response; same-key replay must not duplicate.",
    ),
    GoldenCase(
        id="GT-22",
        category=CATEGORY_COMPENSATION,
        scenario="拆单工具超时",
        instruction=BASE_INSTRUCTION,
        api_key=OPERATOR_API_KEY,
        plan="split_o1001",
        driver="retry",
        fault_plan=(
            ToolFault(
                tool="order_split",
                mode="timeout",
                order_no="O1001",
                phase="execute",
            ),
        ),
        approvals=(_approve("O1001", "split_order"),),
        expected_status="succeeded",
        expected_first_status="failed",
        expected_orders={"O1001": "split"},
        expected_writes=("order_split:O1001",),
        expected_shipments={"O1001": 2},
        expected_shipment_statuses={"O1001": "created"},
        expected_inventory=INV_O1001_SPLIT,
        expected_approval_status="approved",
        notes="Timeout before commit: fail safely, confirm no key, retry once.",
    ),
    GoldenCase(
        id="GT-23",
        category=CATEGORY_COMPENSATION,
        scenario="改址上游错误",
        instruction=BASE_INSTRUCTION,
        api_key=OPERATOR_API_KEY,
        plan="address_o1002",
        fault_plan=(
            ToolFault(
                tool="order_change_address",
                mode="upstream",
                order_no="O1002",
                phase="execute",
            ),
        ),
        approvals=(_approve("O1002", "change_address"),),
        expected_status="failed",
        expected_orders={"O1002": "pending_shipment"},
        forbidden_writes=frozenset({"order_change_address"}),
        expected_error_text="upstream error",
        expected_shipments={"O1002": 0},
        expected_approval_status="approved",
        notes="Failed write retains its idempotency key in the failed TaskStep.",
    ),
    GoldenCase(
        id="GT-24",
        category=CATEGORY_COMPENSATION,
        scenario="多订单中一单工具失败",
        instruction=BASE_INSTRUCTION,
        api_key=OPERATOR_API_KEY,
        plan="split_two_o1001_o1004",
        fault_plan=(
            ToolFault(
                tool="order_split",
                mode="timeout",
                order_no="O1004",
                phase="execute",
            ),
        ),
        approvals=(
            _approve("O1001", "split_order"),
            _approve("O1004", "split_order"),
        ),
        expected_status="partially_succeeded",
        expected_orders={
            "O1001": "split",
            "O1004": "pending_shipment",
        },
        expected_writes=("order_split:O1001",),
        expected_compensations=(),
        expected_shipments={"O1001": 2, "O1004": 0},
        expected_shipment_statuses={"O1001": "created"},
        expected_inventory=INV_O1001_SPLIT,
        expected_approval_status="approved",
        notes=(
            "The failed order is isolated; successful orders keep their "
            "writes and are never compensated."
        ),
    ),
    GoldenCase(
        id="GT-25",
        category=CATEGORY_COMPENSATION,
        scenario="已执行拆单后验证失败",
        instruction=BASE_INSTRUCTION,
        api_key=OPERATOR_API_KEY,
        plan="split_two_o1001_o1004",
        verifier="failing",
        approvals=(
            _approve("O1001", "split_order"),
            _approve("O1004", "split_order"),
        ),
        expected_status="partially_succeeded",
        expected_orders={
            "O1001": "pending_shipment",
            "O1004": "pending_shipment",
        },
        expected_writes=("order_split:O1001", "order_split:O1004"),
        expected_compensations=(
            "order_revert_split:O1001",
            "order_revert_split:O1004",
        ),
        expected_shipments={"O1001": 2, "O1004": 1},
        expected_shipment_statuses={
            "O1001": "cancelled",
            "O1004": "cancelled",
        },
        expected_inventory={
            "SKU-001": (100, 0),
            "SKU-002": (100, 0),
            "SKU-004": (100, 0),
        },
        expected_approval_status="approved",
    ),
    GoldenCase(
        id="GT-26",
        category=CATEGORY_COMPENSATION,
        scenario="补偿工具失败",
        instruction=BASE_INSTRUCTION,
        api_key=OPERATOR_API_KEY,
        plan="split_two_o1001_o1004",
        verifier="failing",
        faults={"order_revert_split": "timeout"},
        approvals=(
            _approve("O1001", "split_order"),
            _approve("O1004", "split_order"),
        ),
        expected_status="partially_compensated",
        expected_orders={"O1001": "split", "O1004": "split"},
        expected_writes=("order_split:O1001", "order_split:O1004"),
        expected_shipments={"O1001": 2, "O1004": 1},
        expected_shipment_statuses={
            "O1001": "created",
            "O1004": "created",
        },
        expected_inventory={
            "SKU-001": (98, 2),
            "SKU-002": (99, 1),
            "SKU-004": (99, 1),
        },
        expected_approval_status="approved",
        notes="Uses order_revert_split, the real executor compensation tool.",
    ),
    GoldenCase(
        id="GT-27",
        category=CATEGORY_SECURITY,
        scenario="跨租户访问订单",
        instruction=BASE_INSTRUCTION,
        api_key=OPERATOR_API_KEY,
        plan="split_o1001",
        driver="security_cross_tenant",
        approvals=(),
        expected_status="awaiting_approval",
        expected_orders={"O1001": "pending_shipment"},
        forbidden_writes=frozenset({"order_split"}),
        expected_shipments={"O1001": 0},
        expected_denial_status=403,
    ),
    GoldenCase(
        id="GT-28",
        category=CATEGORY_SECURITY,
        scenario="未授权工具调用",
        instruction=BASE_INSTRUCTION,
        api_key=OPERATOR_API_KEY,
        plan="split_o1001",
        driver="security_unauthorized_tool",
        approvals=(),
        expected_status="awaiting_approval",
        expected_orders={"O1001": "pending_shipment"},
        forbidden_writes=frozenset({"order_split"}),
        expected_shipments={"O1001": 0},
        expected_denial_status=403,
    ),
)


CASE_BY_ID = {case.id: case for case in GOLDEN_CASES}
ALL_CASE_IDS = tuple(case.id for case in GOLDEN_CASES)

CATEGORY_COUNTS = {
    CATEGORY_MAIN: 5,
    CATEGORY_VALIDATION: 4,
    CATEGORY_INVENTORY: 4,
    CATEGORY_APPROVAL: 5,
    CATEGORY_IDEMPOTENCY: 3,
    CATEGORY_COMPENSATION: 5,
    CATEGORY_SECURITY: 2,
}

# Cases that exercise a spec outcome the product does not implement yet. The
# golden table must list them, so they are marked xfailed with these reasons
# instead of being weakened into a false pass. See docs/KNOWN_GAPS.md.
KNOWN_GAP_REASONS: dict[str, str] = {
    "GT-08": (
        "Invalid planner output is rejected at task creation with HTTP 500 and "
        "a full rollback; there is no failed TaskRun or human-handoff record "
        "to satisfy '任务失败，转人工'."
    ),
    "GT-09": (
        "The case plan contains only the missing order, so the task ends "
        "'failed', not the spec's literal 'partially_succeeded'."
    ),
    "GT-12": (
        "Write conflicts use SELECT ... FOR UPDATE waiting, not the spec's "
        "limited optimistic-lock retry; the loser fails safely without a "
        "retry attempt."
    ),
    "GT-17": (
        "There is no task-level 'rejected' status; a rejected batch ends "
        "'partially_succeeded' with rejected Approval rows and skipped steps."
    ),
    "GT-26": (
        "Failed compensations are reported in task.result, but there is no "
        "human-escalation or work-queue artifact for '转人工'."
    ),
}


def cases_by_category(category: str) -> tuple[GoldenCase, ...]:
    return tuple(case for case in GOLDEN_CASES if case.category == category)


def describe(case: GoldenCase) -> dict[str, Any]:
    """Return a JSON-friendly description used by the live smoke script."""

    return {
        "id": case.id,
        "category": case.category,
        "scenario": case.scenario,
        "instruction": case.instruction,
        "api_key": case.api_key,
        "expected_status": case.expected_status,
        "expected_orders": dict(case.expected_orders),
        "forbidden_writes": sorted(case.forbidden_writes),
    }
