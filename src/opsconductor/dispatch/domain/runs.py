"""Agent Run 领域模型。

``AgentRun`` 是一次真实编排的不可变记录：10 个步骤、8 个 Agent、事件流、
工具调用、审批门、交接、产物与 Verifier 结论。所有值对象在构造时校验，
非法数据在领域边界 fail-fast，不进入 API 或 UI。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from opsconductor.dispatch.domain.enums import (
    ApprovalStatus,
    ArtifactKind,
    Decision,
    RiskLevel,
)
from opsconductor.dispatch.domain.models import (
    Goal,
    ToolCallRecord,
    VerificationResult,
)

RunToolCall = ToolCallRecord


class RunStatus(str, Enum):  # noqa: UP042
    """Run 的生命周期。"""

    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class RunMode(str, Enum):  # noqa: UP042
    """Run 的运行模式；本期固定为 mock 工具驱动的演示。"""

    demo = "demo"
    live = "live"


class RunStepStatus(str, Enum):  # noqa: UP042
    """步骤在 Run 记录中的状态。"""

    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"


class RunEventKind(str, Enum):  # noqa: UP042
    """可回放事件类型；值直接进入 API 契约。"""

    run_started = "run_started"
    agent_started = "agent_started"
    tool_called = "tool_called"
    step_completed = "step_completed"
    handoff = "handoff"
    approval_requested = "approval_requested"
    approval_decided = "approval_decided"
    verification_passed = "verification_passed"
    compensation_triggered = "compensation_triggered"
    rpa_executed = "rpa_executed"
    reconciliation_found = "reconciliation_found"
    report_generated = "report_generated"
    run_completed = "run_completed"


def _text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")


def _optional_text(value: str | None, field: str) -> None:
    if value is not None:
        _text(value, field)


def _non_negative(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")


def _positive(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")


def _unique(values: tuple[str, ...], field: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{field} must be unique")


def _string_tuple(values: tuple[str, ...], field: str, *, non_empty: bool) -> None:
    if not isinstance(values, tuple):
        raise ValueError(f"{field} must be a tuple")
    for value in values:
        _text(value, field)
    if non_empty and not values:
        raise ValueError(f"{field} must not be empty")
    _unique(values, field)


@dataclass(frozen=True)
class RunStep:
    """Run 中的一个执行步骤。"""

    index: int
    id: str
    stage: str
    name: str
    agent_id: str
    capability: str
    risk: RiskLevel
    status: RunStepStatus
    summary: str
    artifact: str | None
    tool_calls: tuple[RunToolCall, ...]
    approval_id: str | None
    duration_ms: int
    error: str | None = None

    def __post_init__(self) -> None:
        _positive(self.index, "index")
        for field in ("id", "stage", "name", "agent_id", "capability", "summary"):
            _text(getattr(self, field), field)
        if not isinstance(self.risk, RiskLevel):
            raise ValueError("risk must be a RiskLevel")
        if not isinstance(self.status, RunStepStatus):
            raise ValueError("status must be a RunStepStatus")
        _optional_text(self.artifact, "artifact")
        _optional_text(self.approval_id, "approval_id")
        _optional_text(self.error, "error")
        _non_negative(self.duration_ms, "duration_ms")
        if not isinstance(self.tool_calls, tuple):
            raise ValueError("tool_calls must be a tuple")
        for call in self.tool_calls:
            if not isinstance(call, RunToolCall):
                raise ValueError("tool_calls must contain RunToolCall records")


@dataclass(frozen=True)
class RunAgent:
    """参与 Run 的 Agent 及其步骤归属。"""

    id: str
    name: str
    role: str
    risk: RiskLevel
    capabilities: tuple[str, ...]
    step_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for field in ("id", "name", "role"):
            _text(getattr(self, field), field)
        if not isinstance(self.risk, RiskLevel):
            raise ValueError("risk must be a RiskLevel")
        _string_tuple(self.capabilities, "capabilities", non_empty=True)
        _string_tuple(self.step_ids, "step_ids", non_empty=True)


@dataclass(frozen=True)
class RunEvent:
    """按 ``seq`` 回放的事件。"""

    seq: int
    kind: RunEventKind
    at: str
    step_id: str | None
    agent_id: str | None
    gate_id: str | None
    title: str
    detail: str

    def __post_init__(self) -> None:
        _positive(self.seq, "seq")
        if not isinstance(self.kind, RunEventKind):
            raise ValueError("kind must be a RunEventKind")
        for field in ("at", "title", "detail"):
            _text(getattr(self, field), field)
        _optional_text(self.step_id, "step_id")
        _optional_text(self.agent_id, "agent_id")
        _optional_text(self.gate_id, "gate_id")
        if self.kind in {
            RunEventKind.agent_started,
            RunEventKind.tool_called,
            RunEventKind.step_completed,
            RunEventKind.handoff,
        }:
            if self.step_id is None:
                raise ValueError(f"step_id is required for {self.kind.value}")
            if self.agent_id is None:
                raise ValueError(f"agent_id is required for {self.kind.value}")
            if self.gate_id is not None:
                raise ValueError(f"gate_id must be empty for {self.kind.value}")
        elif self.kind in {
            RunEventKind.approval_requested,
            RunEventKind.approval_decided,
        }:
            if self.gate_id is None:
                raise ValueError(f"gate_id is required for {self.kind.value}")
            if self.step_id is None:
                raise ValueError(f"step_id is required for {self.kind.value}")
            if self.agent_id is not None:
                raise ValueError(f"agent_id must be empty for {self.kind.value}")
        elif self.step_id is not None or self.agent_id is not None or self.gate_id is not None:
            raise ValueError(f"{self.kind.value} must not reference step/agent/gate")


@dataclass(frozen=True)
class RunGate:
    """Run 中的审批门禁。"""

    id: str
    step_id: str
    stage: str
    title: str
    action: str
    risk: RiskLevel
    owner: str
    impact: str
    recommended: Decision | None
    status: ApprovalStatus
    decision: Decision | None
    actor: str | None
    decided_at: str | None

    def __post_init__(self) -> None:
        for field in ("id", "step_id", "stage", "title", "action", "owner", "impact"):
            _text(getattr(self, field), field)
        if not isinstance(self.risk, RiskLevel):
            raise ValueError("risk must be a RiskLevel")
        if not isinstance(self.status, ApprovalStatus):
            raise ValueError("status must be an ApprovalStatus")
        if self.recommended is not None and not isinstance(self.recommended, Decision):
            raise ValueError("recommended must be a Decision or None")
        if self.decision is not None and not isinstance(self.decision, Decision):
            raise ValueError("decision must be a Decision or None")
        if self.status is ApprovalStatus.approved:
            if self.decision is not Decision.approve:
                raise ValueError("decision must be approve when approved")
        elif self.status is ApprovalStatus.rejected:
            if self.decision is not Decision.reject:
                raise ValueError("decision must be reject when rejected")
        else:
            if self.decision is not None:
                raise ValueError("decision must be None when pending")
        if self.status is ApprovalStatus.pending:
            if self.actor is not None or self.decided_at is not None:
                raise ValueError("actor and decided_at must be None when pending")
        else:
            _text(self.actor or "", "actor")
            _text(self.decided_at or "", "decided_at")


@dataclass(frozen=True)
class RunHandoff:
    """一次结构化的 Agent 交接。"""

    event_seq: int
    from_agent_id: str
    to_agent_id: str
    from_step_id: str
    to_step_id: str
    artifact: str
    note: str

    def __post_init__(self) -> None:
        _positive(self.event_seq, "event_seq")
        for field in (
            "from_agent_id",
            "to_agent_id",
            "from_step_id",
            "to_step_id",
            "artifact",
            "note",
        ):
            _text(getattr(self, field), field)
        if self.from_agent_id == self.to_agent_id:
            raise ValueError("from_agent_id and to_agent_id must differ")
        if self.from_step_id == self.to_step_id:
            raise ValueError("from_step_id and to_step_id must differ")


@dataclass(frozen=True)
class RunArtifact:
    """Run 中的产物引用。"""

    name: str
    kind: ArtifactKind
    uri: str
    step_id: str
    agent_id: str
    description: str

    def __post_init__(self) -> None:
        for field in ("name", "uri", "step_id", "agent_id", "description"):
            _text(getattr(self, field), field)
        if not isinstance(self.kind, ArtifactKind):
            raise ValueError("kind must be an ArtifactKind")
        if not self.uri.startswith("mock://"):
            raise ValueError("uri must start with mock:// in the demo run")


@dataclass(frozen=True)
class RunMetrics:
    """由实体计算的 Run 指标。"""

    step_count: int
    succeeded_steps: int
    failed_steps: int
    agent_count: int
    handoff_count: int
    gate_count: int
    approved_gates: int
    rejected_gates: int
    artifact_count: int
    compensation_count: int
    reconciliation_count: int
    duration_ms: int

    def __post_init__(self) -> None:
        for field in (
            "step_count",
            "succeeded_steps",
            "failed_steps",
            "agent_count",
            "handoff_count",
            "gate_count",
            "approved_gates",
            "rejected_gates",
            "artifact_count",
            "compensation_count",
            "reconciliation_count",
            "duration_ms",
        ):
            _non_negative(getattr(self, field), field)
        if self.succeeded_steps + self.failed_steps > self.step_count:
            raise ValueError("succeeded_steps + failed_steps must not exceed step_count")
        if self.approved_gates + self.rejected_gates > self.gate_count:
            raise ValueError("approved_gates + rejected_gates must not exceed gate_count")


@dataclass(frozen=True)
class AgentRun:
    """一次完整、不可回的 Agent 编排记录。"""

    id: str
    goal: Goal
    plan_id: str
    status: RunStatus
    mode: RunMode
    started_at: str
    finished_at: str
    summary: str
    steps: tuple[RunStep, ...]
    agents: tuple[RunAgent, ...]
    events: tuple[RunEvent, ...]
    gates: tuple[RunGate, ...]
    handoffs: tuple[RunHandoff, ...]
    artifacts: tuple[RunArtifact, ...]
    verification: VerificationResult
    metrics: RunMetrics

    def __post_init__(self) -> None:
        for field in ("id", "plan_id", "started_at", "finished_at", "summary"):
            _text(getattr(self, field), field)
        if not isinstance(self.goal, Goal):
            raise ValueError("goal must be a Goal")
        if not isinstance(self.status, RunStatus):
            raise ValueError("status must be a RunStatus")
        if not isinstance(self.mode, RunMode):
            raise ValueError("mode must be a RunMode")
        if not isinstance(self.verification, VerificationResult):
            raise ValueError("verification must be a VerificationResult")
        if not isinstance(self.metrics, RunMetrics):
            raise ValueError("metrics must be a RunMetrics")
        for field, value in (
            ("steps", self.steps),
            ("agents", self.agents),
            ("events", self.events),
            ("gates", self.gates),
            ("handoffs", self.handoffs),
            ("artifacts", self.artifacts),
        ):
            if not isinstance(value, tuple):
                raise ValueError(f"{field} must be a tuple")

        self._validate_steps_and_agents()
        self._validate_events()
        self._validate_handoffs()
        self._validate_gates()
        self._validate_artifacts()
        self._validate_metrics()
        self._validate_status()

    def _validate_steps_and_agents(self) -> None:
        if tuple(step.index for step in self.steps) != tuple(range(1, len(self.steps) + 1)):
            raise ValueError("steps index must be contiguous from 1")
        agent_ids = {agent.id for agent in self.agents}
        if len(agent_ids) != len(self.agents):
            raise ValueError("agents must have unique ids")
        for step in self.steps:
            if step.agent_id not in agent_ids:
                raise ValueError(f"step {step.id} references unknown agent {step.agent_id}")
        for agent in self.agents:
            expected = tuple(step.id for step in self.steps if step.agent_id == agent.id)
            if agent.step_ids != expected:
                raise ValueError(f"agent {agent.id} step_ids do not match steps")

    def _validate_events(self) -> None:
        if tuple(event.seq for event in self.events) != tuple(range(1, len(self.events) + 1)):
            raise ValueError("events seq must be contiguous from 1")

    def _validate_handoffs(self) -> None:
        step_by_id = {step.id: step for step in self.steps}
        events_by_seq = {event.seq: event for event in self.events}
        for handoff in self.handoffs:
            from_step = step_by_id.get(handoff.from_step_id)
            to_step = step_by_id.get(handoff.to_step_id)
            if from_step is None or to_step is None:
                raise ValueError(
                    f"handoff {handoff.from_step_id}->{handoff.to_step_id} "
                    "references unknown step"
                )
            if to_step.index != from_step.index + 1:
                raise ValueError("handoff steps must be adjacent")
            if (
                from_step.agent_id != handoff.from_agent_id
                or to_step.agent_id != handoff.to_agent_id
            ):
                raise ValueError("handoff agents do not match step agents")
            event = events_by_seq.get(handoff.event_seq)
            if event is None or event.kind is not RunEventKind.handoff:
                raise ValueError("handoff event_seq must reference a handoff event")
            if event.step_id != handoff.to_step_id or event.agent_id != handoff.to_agent_id:
                raise ValueError("handoff event does not match receiving step/agent")

    def _validate_gates(self) -> None:
        step_by_id = {step.id: step for step in self.steps}
        for gate in self.gates:
            step = step_by_id.get(gate.step_id)
            if step is None:
                raise ValueError(f"gate {gate.id} references unknown step {gate.step_id}")
            if gate.stage != step.stage:
                raise ValueError(f"gate {gate.id} stage does not match step stage")
            if step.approval_id is not None and step.approval_id != gate.id:
                raise ValueError(f"gate {gate.id} does not match step approval_id")

    def _validate_artifacts(self) -> None:
        step_by_id = {step.id: step for step in self.steps}
        for artifact in self.artifacts:
            step = step_by_id.get(artifact.step_id)
            if step is None:
                raise ValueError(f"artifact {artifact.name} references unknown step")
            if step.agent_id != artifact.agent_id:
                raise ValueError(f"artifact {artifact.name} agent does not match step")
        for step in self.steps:
            if step.artifact is None:
                continue
            matching = [
                artifact
                for artifact in self.artifacts
                if artifact.step_id == step.id and artifact.name == step.artifact
            ]
            if len(matching) != 1:
                raise ValueError(f"artifact for step {step.id} must be unique")

    def _validate_metrics(self) -> None:
        expected = {
            "step_count": len(self.steps),
            "succeeded_steps": sum(
                1 for step in self.steps if step.status is RunStepStatus.succeeded
            ),
            "failed_steps": sum(
                1 for step in self.steps if step.status is RunStepStatus.failed
            ),
            "agent_count": len(self.agents),
            "handoff_count": len(self.handoffs),
            "gate_count": len(self.gates),
            "approved_gates": sum(
                1 for gate in self.gates if gate.status is ApprovalStatus.approved
            ),
            "rejected_gates": sum(
                1 for gate in self.gates if gate.status is ApprovalStatus.rejected
            ),
            "artifact_count": len(self.artifacts),
            "compensation_count": sum(
                1 for event in self.events if event.kind is RunEventKind.compensation_triggered
            ),
        }
        differences = {
            field: (getattr(self.metrics, field), value)
            for field, value in expected.items()
            if getattr(self.metrics, field) != value
        }
        if differences:
            raise ValueError(f"metrics do not match entities: {differences}")

    def _validate_status(self) -> None:
        failed = any(step.status is RunStepStatus.failed for step in self.steps)
        if self.status is RunStatus.succeeded and failed:
            raise ValueError("succeeded run must not contain failed steps")
        if self.status is RunStatus.failed and not failed:
            raise ValueError("failed run must contain at least one failed step")


__all__ = [
    "AgentRun",
    "RunAgent",
    "RunArtifact",
    "RunEvent",
    "RunEventKind",
    "RunGate",
    "RunHandoff",
    "RunMetrics",
    "RunMode",
    "RunStatus",
    "RunStep",
    "RunStepStatus",
    "RunToolCall",
]
