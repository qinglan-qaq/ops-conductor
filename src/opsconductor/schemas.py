"""Pydantic request, plan, and response schemas at the orchestration boundary.

These models validate external input before it reaches the domain layer. Plans
use string IDs because they are produced and persisted as JSON; nested ``params``
and ``evidence`` payloads must stay JSON-serializable, and callers persist them
with ``model_dump(mode="json")``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from opsconductor.domain.enums import RiskLevel


class TaskCreate(BaseModel):
    """Request body that starts a new orchestration task.

    ``instruction`` is the operator's natural-language request, ``warehouse``
    optionally scopes the task to a named warehouse, and ``cutoff`` is an
    optional ISO 8601 timestamp bounding how old affected orders may be.

    Note:
        ``cutoff`` is validated here but kept as the original string; the
        planner parses it when it builds read-tool arguments.
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
    """One action in a plan, with its dependencies and risk metadata.

    ``node_id`` is stable within the plan. ``action`` selects the tool family;
    ``order_id`` is absent for task-level actions such as ``report``. ``params``
    and ``evidence`` are JSON payloads. ``depends_on`` lists node IDs that must
    succeed before this node runs, while ``compensation`` may record the
    planner's compensation hint.

    Note:
        Clients may propose nodes, but the risk policy rewrites ``risk`` and
        ``requires_approval`` before execution; execution derives the actual
        compensation tool from ``action``.
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
    """Dependency graph of nodes that implements a task.

    ``task_id`` is a string rather than a UUID because plans are exchanged and
    stored as JSON; it must equal the owning task's string UUID. ``nodes``
    order is only a hint, since execution follows ``depends_on``.
    ``requires_l3`` is set when at least one node is graded L3.

    Note:
        A plan is not executable until :func:`validate_plan` accepts it.
    """

    task_id: str
    summary: str = ""
    requires_l3: bool = False
    nodes: list[PlanNode] = Field(default_factory=list)


class ApprovalDecision(BaseModel):
    """Decision submitted by an approver for a pending approval.

    ``approved`` is the verdict and ``comment`` is optional free-text context
    stored alongside it.
    """

    approved: bool
    comment: str | None = None


class TaskReport(BaseModel):
    """Outcome summary returned after executing a task.

    Node IDs are grouped by outcome: ``succeeded``, ``skipped``, ``failed``,
    and still ``pending``. ``message`` explains the terminal status, including
    why a run stopped before executing writes.
    """

    task_id: str
    status: str
    succeeded: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)
    pending: list[str] = Field(default_factory=list)
    message: str = ""


class TaskRead(BaseModel):
    """Read model exposing a task's stored state.

    ``plan`` and ``result`` are the raw JSON snapshots stored on the task and
    are ``None`` until the corresponding phase has produced them.
    """

    id: UUID
    status: str
    instruction: str
    plan: dict[str, Any] | None = None
    result: dict[str, Any] | None = None


def validate_plan(plan: Plan) -> None:
    """Validate the plan DAG before it is stored or executed.

    Checks run in a fixed order: duplicate node IDs, dependencies on unknown
    nodes, then cycles. The plan is inspected in place and left unchanged.

    Args:
        plan: Plan whose node graph is checked.

    Returns:
        ``None`` when the graph is well-formed.

    Raises:
        ValueError: If a ``node_id`` repeats, a ``depends_on`` entry names a
            node that does not exist, or the dependency graph contains a cycle.
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
