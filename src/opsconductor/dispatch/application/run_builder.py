"""把一次真实编排累积为可回放的 :class:`AgentRun`。

构建器只负责记录事实：事件序号、步骤、Agent、门禁、交接、产物和指标。
播放节奏、遮罩和交互全部在前端，构建器不引入演示延时。
"""

from __future__ import annotations

from uuid import uuid4

from opsconductor.dispatch.domain.enums import ApprovalStatus, Decision
from opsconductor.dispatch.domain.models import (
    AgentCard,
    ApprovalCase,
    Goal,
    Plan,
    PlanStep,
    VerificationResult,
)
from opsconductor.dispatch.domain.ports import ClockPort
from opsconductor.dispatch.domain.runs import (
    AgentRun,
    RunAgent,
    RunArtifact,
    RunEvent,
    RunEventKind,
    RunGate,
    RunHandoff,
    RunMetrics,
    RunMode,
    RunStatus,
    RunStep,
    RunStepStatus,
)


class RunBuilder:
    """按执行顺序累积 Run 实体。"""

    def __init__(
        self,
        goal: Goal,
        plan: Plan,
        clock: ClockPort,
        run_id: str | None = None,
    ) -> None:
        self.goal = goal
        self.plan = plan
        self.clock = clock
        self.run_id = run_id or f"run-{uuid4().hex[:12]}"
        self.started_at = clock.now_label()
        self.events: list[RunEvent] = []
        self.steps: list[RunStep] = []
        self.gates: list[RunGate] = []
        self.handoffs: list[RunHandoff] = []
        self.artifacts: list[RunArtifact] = []
        self._cards: dict[str, AgentCard] = {}
        self._agent_steps: dict[str, list[str]] = {}
        self._verification: VerificationResult | None = None

    def _emit(
        self,
        kind: RunEventKind,
        *,
        title: str,
        detail: str,
        step_id: str | None = None,
        agent_id: str | None = None,
        gate_id: str | None = None,
    ) -> int:
        seq = len(self.events) + 1
        self.events.append(
            RunEvent(
                seq=seq,
                kind=kind,
                at=self.clock.now_label(),
                step_id=step_id,
                agent_id=agent_id,
                gate_id=gate_id,
                title=title,
                detail=detail,
            )
        )
        return seq

    def run_started(self) -> None:
        self._emit(
            RunEventKind.run_started,
            title="运行开始",
            detail=f"{self.goal.instruction} · {len(self.plan.steps)} 步计划",
        )

    def ensure_agent(self, card: AgentCard) -> None:
        if card.id not in self._cards:
            self._cards[card.id] = card
            self._agent_steps[card.id] = []

    def agent_started(self, step: PlanStep, card: AgentCard) -> int:
        return self._emit(
            RunEventKind.agent_started,
            step_id=step.id,
            agent_id=card.id,
            title="Agent 启动",
            detail=f"{card.name} · {step.name}",
        )

    def tool_called(self, step: PlanStep, card: AgentCard, tool: str, duration_ms: int) -> int:
        return self._emit(
            RunEventKind.tool_called,
            step_id=step.id,
            agent_id=card.id,
            title="工具调用",
            detail=f"{tool} · {duration_ms}ms",
        )

    def step_completed(self, step: PlanStep, card: AgentCard, artifact: str) -> int:
        return self._emit(
            RunEventKind.step_completed,
            step_id=step.id,
            agent_id=card.id,
            title="Agent 完成",
            detail=f"{card.name} · {artifact}",
        )

    def add_step(self, step: RunStep) -> None:
        self.steps.append(step)
        self._agent_steps.setdefault(step.agent_id, []).append(step.id)

    def add_artifact(self, artifact: RunArtifact) -> None:
        self.artifacts.append(artifact)

    def add_handoff(
        self,
        *,
        from_step: PlanStep,
        to_step: PlanStep,
        from_card: AgentCard,
        to_card: AgentCard,
        artifact: str,
    ) -> RunHandoff:
        seq = self._emit(
            RunEventKind.handoff,
            step_id=to_step.id,
            agent_id=to_card.id,
            title="Agent 交接",
            detail=f"{from_card.name} → {to_card.name} · {artifact}",
        )
        handoff = RunHandoff(
            event_seq=seq,
            from_agent_id=from_card.id,
            to_agent_id=to_card.id,
            from_step_id=from_step.id,
            to_step_id=to_step.id,
            artifact=artifact,
            note=f"{from_card.name} → {to_card.name}",
        )
        self.handoffs.append(handoff)
        return handoff

    def approval_requested(self, case: ApprovalCase, step_id: str) -> int:
        return self._emit(
            RunEventKind.approval_requested,
            step_id=step_id,
            gate_id=case.id,
            title="审批待决",
            detail=f"{case.title} · {case.risk.value} · {case.owner}",
        )

    def approval_decided(self, case: ApprovalCase, step_id: str) -> int:
        title = "审批通过" if case.status is ApprovalStatus.approved else "审批驳回"
        return self._emit(
            RunEventKind.approval_decided,
            step_id=step_id,
            gate_id=case.id,
            title=title,
            detail=f"{case.title} · {case.actor}",
        )

    def add_gate(self, case: ApprovalCase, step_id: str, stage: str) -> None:
        decision: Decision | None
        if case.status is ApprovalStatus.approved:
            decision = Decision.approve
        elif case.status is ApprovalStatus.rejected:
            decision = Decision.reject
        else:
            decision = None
        self.gates.append(
            RunGate(
                id=case.id,
                step_id=step_id,
                stage=stage,
                title=case.title,
                action=case.action,
                risk=case.risk,
                owner=case.owner,
                impact=case.impact,
                recommended=case.recommended,
                status=case.status,
                decision=decision,
                actor=case.actor,
                decided_at=case.decided_at,
            )
        )

    def verification_passed(self, verification: VerificationResult) -> int:
        self._verification = verification
        veto_note = (
            f"{len(verification.vetoed)} 项否决" if verification.vetoed else "无否决"
        )
        return self._emit(
            RunEventKind.verification_passed,
            title="Verifier 通过",
            detail=f"{veto_note} · 毛利 / 库存 / 预算 / 合规 / trace",
        )

    def tail(self, kind: RunEventKind, title: str, detail: str) -> int:
        return self._emit(kind, title=title, detail=detail)

    def finish(
        self,
        *,
        summary: str,
        duration_ms: int,
        reconciliation_count: int = 3,
    ) -> AgentRun:
        if self._verification is None:
            raise ValueError("verification must be recorded before finish")
        agents = tuple(
            RunAgent(
                id=card.id,
                name=card.name,
                role=card.role,
                risk=card.risk,
                capabilities=card.capabilities,
                step_ids=tuple(self._agent_steps.get(card.id, ())),
            )
            for card in self._cards.values()
        )
        metrics = RunMetrics(
            step_count=len(self.steps),
            succeeded_steps=sum(
                1 for step in self.steps if step.status is RunStepStatus.succeeded
            ),
            failed_steps=sum(
                1 for step in self.steps if step.status is RunStepStatus.failed
            ),
            agent_count=len(agents),
            handoff_count=len(self.handoffs),
            gate_count=len(self.gates),
            approved_gates=sum(
                1 for gate in self.gates if gate.status is ApprovalStatus.approved
            ),
            rejected_gates=sum(
                1 for gate in self.gates if gate.status is ApprovalStatus.rejected
            ),
            artifact_count=len(self.artifacts),
            compensation_count=sum(
                1
                for event in self.events
                if event.kind is RunEventKind.compensation_triggered
            ),
            reconciliation_count=reconciliation_count,
            duration_ms=duration_ms,
        )
        return AgentRun(
            id=self.run_id,
            goal=self.goal,
            plan_id=self.plan.id,
            status=RunStatus.succeeded,
            mode=RunMode.demo,
            started_at=self.started_at,
            finished_at=self.clock.now_label(),
            summary=summary,
            steps=tuple(self.steps),
            agents=agents,
            events=tuple(self.events),
            gates=tuple(self.gates),
            handoffs=tuple(self.handoffs),
            artifacts=tuple(self.artifacts),
            verification=self._verification,
            metrics=metrics,
        )


__all__ = ["RunBuilder"]
