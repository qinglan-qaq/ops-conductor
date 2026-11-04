from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from opsconductor.domain.enums import RiskLevel


class TaskCreate(BaseModel):
    instruction: str = Field(min_length=2, max_length=1000)
    warehouse: str | None = None
    cutoff: str | None = None


class PlanNode(BaseModel):
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
    task_id: str
    summary: str = ""
    requires_l3: bool = False
    nodes: list[PlanNode] = Field(default_factory=list)


class ApprovalDecision(BaseModel):
    approved: bool
    comment: str | None = None


class TaskReport(BaseModel):
    task_id: str
    status: str
    succeeded: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)
    pending: list[str] = Field(default_factory=list)
    message: str = ""


class TaskRead(BaseModel):
    id: UUID
    status: str
    instruction: str
    plan: dict[str, Any] | None = None
    result: dict[str, Any] | None = None


def validate_plan(plan: Plan) -> None:
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
