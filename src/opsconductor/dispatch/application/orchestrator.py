"""DispatchOrchestrator：把计划、Agent、审批与验证串成一次可回放 Run。

``run_agent`` 是唯一执行入口：按模板重建十个从 ``pending`` 开始的节点，逐个
通过注册表按能力选择 Agent、执行、记录事件与工具调用，再把 Agent 产出的审批
草稿转换为门禁并应用剧本裁决。``run`` 只把 ``AgentRun`` 转换为旧版
``DemoRunReport``，保证 ``/demo/run`` 的 28 个事件与标题不变。
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from opsconductor.dispatch.application.agents import AgentRegistry, VerifierAgent
from opsconductor.dispatch.application.plans import build_plan
from opsconductor.dispatch.application.run_builder import RunBuilder
from opsconductor.dispatch.domain.enums import ArtifactKind, Decision, StepStatus
from opsconductor.dispatch.domain.models import (
    AgentCard,
    AgentResult,
    AgentTask,
    ApprovalCase,
    ApprovalDraft,
    Goal,
    Plan,
    PlanStep,
    TraceEvent,
    VerificationResult,
)
from opsconductor.dispatch.domain.ports import ClockPort
from opsconductor.dispatch.domain.runs import (
    AgentRun,
    RunArtifact,
    RunEventKind,
    RunStep,
    RunStepStatus,
)

DEMO_DECISIONS: dict[str, tuple[Decision, str]] = {
    "budget": (Decision.approve, "财务小财"),
    "price": (Decision.reject, "运营小运"),
    "refund": (Decision.approve, "财务小财"),
}

_REPORT_KINDS = {
    RunEventKind.agent_started,
    RunEventKind.step_completed,
    RunEventKind.approval_decided,
    RunEventKind.verification_passed,
    RunEventKind.compensation_triggered,
    RunEventKind.rpa_executed,
    RunEventKind.reconciliation_found,
    RunEventKind.report_generated,
}

_STEP_STATUS = {
    RunStepStatus.pending: StepStatus.pending,
    RunStepStatus.running: StepStatus.running,
    RunStepStatus.succeeded: StepStatus.succeeded,
    RunStepStatus.failed: StepStatus.failed,
    RunStepStatus.skipped: StepStatus.skipped,
}


@dataclass(frozen=True)
class DemoRunReport:
    """一次 Demo 编排的完整结果（旧版报告契约）。

    Attributes:
        events: 按时间顺序排列的 trace 事件。
        steps: 执行完成后的十个计划节点。
        approvals: 本次执行生成并已按剧本裁决的三个审批案。
        verification: 独立 Verifier 的检查结论。
        summary: 供 toast / 报告展示的一句话总结。
    """

    events: tuple[TraceEvent, ...]
    steps: tuple[PlanStep, ...]
    approvals: tuple[ApprovalCase, ...]
    verification: VerificationResult
    summary: str


def _approval_case(draft: ApprovalDraft) -> ApprovalCase:
    """把 Agent 的审批草稿转换为可变审批实体。"""
    return ApprovalCase(
        id=draft.id,
        title=draft.title,
        action=draft.action,
        risk=draft.risk,
        owner=draft.owner,
        impact=draft.impact,
        recommended=draft.recommended,
        stage_id=draft.stage_id,
    )


def _report_from_run(run: AgentRun) -> DemoRunReport:
    """把 AgentRun 过滤/映射为旧版 DemoRunReport。"""
    events = tuple(
        TraceEvent(event.at, event.title, event.detail)
        for event in run.events
        if event.kind in _REPORT_KINDS
    )
    steps = tuple(
        PlanStep(
            id=step.id,
            stage=step.stage,
            name=step.name,
            capability=step.capability,
            risk=step.risk,
            status=_STEP_STATUS[step.status],
            artifact=step.artifact,
            error=step.error,
        )
        for step in run.steps
    )
    approvals = tuple(
        ApprovalCase(
            id=gate.id,
            title=gate.title,
            action=gate.action,
            risk=gate.risk,
            owner=gate.owner,
            impact=gate.impact,
            recommended=gate.recommended,
            status=gate.status,
            actor=gate.actor,
            decided_at=gate.decided_at,
            stage_id=gate.stage,
        )
        for gate in run.gates
    )
    return DemoRunReport(
        events=events,
        steps=steps,
        approvals=approvals,
        verification=run.verification,
        summary=run.summary,
    )


class DispatchOrchestrator:
    """按固定剧本执行十段计划的编排器。"""

    def __init__(
        self,
        registry: AgentRegistry,
        verifier: VerifierAgent,
        clock: ClockPort,
    ) -> None:
        self._registry = registry
        self._verifier = verifier
        self._clock = clock

    def plan(self, goal: Goal) -> Plan:
        """生成目标对应的十段计划。"""
        return build_plan(goal)

    def run(self, goal: Goal) -> DemoRunReport:
        """执行完整 Demo 编排并返回旧版报告。"""
        return _report_from_run(self.run_agent(goal))

    def run_agent(self, goal: Goal, run_id: str | None = None) -> AgentRun:
        """执行完整 Demo 编排并返回真实 Run 记录。

        Args:
            goal: 当前目标；用于计划与 Agent 任务指令。
            run_id: 可选的固定 Run ID，测试/fixture 使用。

        Returns:
            含步骤、事件、门禁、交接、产物与 Verifier 结论的 Run。
        """
        started = perf_counter()
        plan = build_plan(goal)
        builder = RunBuilder(goal, plan, self._clock, run_id=run_id)
        builder.run_started()

        step_cards: list[AgentCard] = [
            self._registry.select(template.capability).card for template in plan.steps
        ]
        results: list[AgentResult] = []
        approvals_by_id: dict[str, ApprovalCase] = {}
        approval_steps: dict[str, str] = {}
        steps: list[PlanStep] = []

        for index, template in enumerate(plan.steps):
            step = PlanStep(
                id=template.id,
                stage=template.stage,
                name=template.name,
                capability=template.capability,
                risk=template.risk,
            )
            card = step_cards[index]
            agent = self._registry.get(card.id)
            builder.ensure_agent(card)
            builder.agent_started(step, card)
            step.start()

            step_started = perf_counter()
            result = agent.handle(
                AgentTask(
                    step_id=step.id,
                    stage=step.stage,
                    capability=step.capability,
                    instruction=goal.instruction,
                )
            )
            step_duration = int((perf_counter() - step_started) * 1000)
            step.finish(result.artifact)
            for tool_call in result.tool_calls:
                builder.tool_called(
                    step, card, tool_call.tool, tool_call.duration_ms
                )
            builder.step_completed(step, card, result.artifact)

            results.append(result)
            steps.append(step)
            builder.add_step(
                RunStep(
                    index=index + 1,
                    id=step.id,
                    stage=step.stage,
                    name=step.name,
                    agent_id=card.id,
                    capability=step.capability,
                    risk=step.risk,
                    status=RunStepStatus.succeeded,
                    summary=result.summary,
                    artifact=result.artifact,
                    tool_calls=result.tool_calls,
                    approval_id=(
                        result.approval.id if result.approval is not None else None
                    ),
                    duration_ms=step_duration,
                )
            )
            builder.add_artifact(
                RunArtifact(
                    name=result.artifact,
                    kind=ArtifactKind.json,
                    uri=f"mock://{result.artifact}",
                    step_id=step.id,
                    agent_id=card.id,
                    description=f"{card.name} · {step.name}",
                )
            )
            if result.approval is not None:
                case = _approval_case(result.approval)
                approvals_by_id[case.id] = case
                approval_steps[case.id] = step.id

            if index + 1 < len(plan.steps):
                next_card = step_cards[index + 1]
                if next_card.id != card.id:
                    builder.add_handoff(
                        from_step=step,
                        to_step=plan.steps[index + 1],
                        from_card=card,
                        to_card=next_card,
                        artifact=result.artifact,
                    )

        step_by_id = {step.id: step for step in plan.steps}
        for approval_id in plan.approval_ids:
            pending_case = approvals_by_id.get(approval_id)
            if pending_case is None:
                continue
            step_id = approval_steps[approval_id]
            decision, actor = DEMO_DECISIONS[approval_id]
            builder.approval_requested(pending_case, step_id)
            pending_case.decide(decision, actor, self._clock.now_label())
            builder.approval_decided(pending_case, step_id)
            builder.add_gate(pending_case, step_id, step_by_id[step_id].stage)

        verification = self._verifier.verify(results)
        builder.verification_passed(verification)
        builder.tail(
            RunEventKind.compensation_triggered,
            "补偿触发",
            "拆单库存冲突 · 回滚预占并生成替代履约",
        )
        builder.tail(
            RunEventKind.rpa_executed,
            "RPA 执行",
            "影刀旧版供应商门户 · 截图与审计",
        )
        builder.tail(
            RunEventKind.reconciliation_found,
            "对账差异",
            "3 笔差异 → 财务任务",
        )
        builder.tail(
            RunEventKind.report_generated,
            "报告生成",
            "指标 / 证据 / trace",
        )
        agent_count = len({card.id for card in step_cards})
        builder.tail(
            RunEventKind.run_completed,
            "运行完成",
            f"{len(plan.steps)} 步 · {agent_count} Agent · "
            f"{len(builder.handoffs)} 交接 · 2 准 1 驳",
        )

        veto_note = (
            f"{len(verification.vetoed)} 项否决"
            if verification.vetoed
            else "无否决"
        )
        summary = (
            "10 个节点执行完成 · 审批 2 准 1 驳 · "
            f"Verifier {veto_note} · 1 次补偿 · 3 笔对账差异"
        )
        return builder.finish(
            summary=summary,
            duration_ms=int((perf_counter() - started) * 1000),
        )


__all__ = ["DEMO_DECISIONS", "DemoRunReport", "DispatchOrchestrator"]
