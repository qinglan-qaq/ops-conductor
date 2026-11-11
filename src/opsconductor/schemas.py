"""编排边界上的 Pydantic 请求、计划与响应 schema。

这些模型在外部输入到达领域层之前对其进行校验。计划使用字符串 ID，因为它们
以 JSON 形式产生和持久化；嵌套的 ``params`` 与 ``evidence`` 载荷必须保持可
JSON 序列化，调用方用 ``model_dump(mode="json")`` 持久化它们。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from opsconductor.domain.enums import RiskLevel


class TaskCreate(BaseModel):
    """启动新编排任务的请求体。

    ``instruction`` 是操作员的自然语言请求，``warehouse`` 可选地把任务限定到
    指定名称的仓库，``cutoff`` 是可选的 ISO 8601 时间戳，用于限制受影响订单
    的最早时间。

    Note:
        ``cutoff`` 在此处校验但保留原始字符串；planner 在构建读取工具参数时
        才会解析它。
    """

    instruction: str = Field(min_length=2, max_length=1000)
    warehouse: str | None = None
    cutoff: str | None = None

    @field_validator("cutoff")
    @classmethod
    def _validate_cutoff(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return value
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("cutoff must be an ISO 8601 timestamp") from exc
        return value


class PlanNode(BaseModel):
    """计划中的一个动作，包含其依赖与风险元数据。

    ``node_id`` 在计划内保持稳定。``action`` 选择工具族；对于 ``report`` 这类
    任务级动作，``order_id`` 不存在。``params`` 与 ``evidence`` 是 JSON 载荷。
    ``depends_on`` 列出本节点运行前必须成功的节点 ID，``compensation`` 可记录
    planner 的补偿提示。

    Note:
        客户端可以提议节点，但风险策略会在执行前重写 ``risk`` 与
        ``requires_approval``；执行器会根据 ``action`` 推导实际使用的补偿
        工具。
    """

    node_id: str
    order_id: UUID | None = None
    action: Literal["split_order", "change_address", "block_order", "verify", "report"]
    risk: RiskLevel = RiskLevel.L0
    requires_approval: bool = False
    params: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    compensation: str | None = None
    reason: str = ""


class Plan(BaseModel):
    """实现某个任务的节点依赖图。

    ``task_id`` 使用字符串而非 UUID，因为计划以 JSON 形式交换和存储；它必须
    等于所属任务的字符串 UUID。``nodes`` 的顺序只是提示，执行时以
    ``depends_on`` 为准。当至少一个节点被评为 L3 时，``requires_l3`` 会被
    置位。

    Note:
        在 :func:`validate_plan` 接受计划之前，计划不可执行。
    """

    task_id: str
    summary: str = ""
    requires_l3: bool = False
    nodes: list[PlanNode] = Field(default_factory=list)


class ApprovalDecision(BaseModel):
    """审批人为待审批项提交的裁决。

    ``approved`` 是裁决结果，``comment`` 是随之一同存储的可选自由文本上下文。
    """

    approved: bool
    comment: str | None = None


class TaskReport(BaseModel):
    """任务执行后返回的结果摘要。

    节点 ID 按结果分组：``succeeded``、``skipped``、``failed`` 以及仍为
    ``pending`` 的节点。``message`` 说明最终状态，包括运行在写入前中止的原因。
    """

    task_id: str
    status: str
    succeeded: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)
    pending: list[str] = Field(default_factory=list)
    message: str = ""


class TaskRead(BaseModel):
    """暴露任务已存储状态的读取模型。

    ``plan`` 与 ``result`` 是存储在任务上的原始 JSON 快照，在对应阶段产出之前
    为 ``None``。
    """

    id: UUID
    status: str
    instruction: str
    plan: dict[str, Any] | None = None
    result: dict[str, Any] | None = None


def validate_plan(plan: Plan) -> None:
    """在存储或执行之前校验计划 DAG。

    检查按固定顺序进行：重复的节点 ID、依赖未知节点，最后是环。计划仅被原地
    检查，不会被修改。

    Args:
        plan: 校验其节点图的计划。

    Returns:
        图结构良好时返回 ``None``。

    Raises:
        ValueError: 当 ``node_id`` 重复、``depends_on`` 中的条目指向不存在的
            节点，或依赖图包含环时抛出。
    """

    ids = [node.node_id for node in plan.nodes]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate node_id")
    known = set(ids)
    for node in plan.nodes:
        missing = set(node.depends_on) - known
        if missing:
            raise ValueError(f"unknown dependency: {sorted(missing)}")
    visiting: set[str] = set()
    visited: set[str] = set()
    graph = {node.node_id: node.depends_on for node in plan.nodes}

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise ValueError("cycle detected")
        if node_id in visited:
            return
        visiting.add(node_id)
        for dep in graph[node_id]:
            visit(dep)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in ids:
        visit(node_id)
