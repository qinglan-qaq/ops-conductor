"""DispatchOrchestrator：把计划、Agent、审批与验证串成一次可回放演示。

``run`` 不复用计划快照中的展示状态：它按模板重建十个从 ``pending`` 开始的
节点，逐个通过注册表按能力选择 Agent、执行、记录 trace，再把 Agent 产出的
审批草稿转换为 :class:`ApprovalCase` 并按剧本裁决。最后追加补偿、RPA、对账
差异与报告事件，形成前端可直接播放的 :class:`DemoRunReport`。
"""

from __future__ import annotations

from dataclasses import dataclass

from opsconductor.dispatch.application.agents import AgentRegistry, VerifierAgent
from opsconductor.dispatch.application.plans import build_plan
from opsconductor.dispatch.domain.enums import Decision
from opsconductor.dispatch.domain.models import (
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

DEMO_DECISIONS: dict[str, tuple[Decision, str]] = {
    "budget": (Decision.approve, "财务小财"),
    "price": (Decision.reject, "运营小运"),
    "refund": (Decision.approve, "财务小财"),
}


@dataclass(frozen=True)
class DemoRunReport:
    """一次 Demo 编排的完整结果。

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
        """执行完整 Demo 编排。

        Args:
            goal: 当前目标；用于计划与 Agent 任务指令。

        Returns:
            含 trace、节点、审批、验证与总结的演示报告。
        """
        plan = build_plan(goal)
        events: list[TraceEvent] = []
        results: list[AgentResult] = []
        steps: list[PlanStep] = []
        approvals_by_id: dict[str, ApprovalCase] = {}

        for template in plan.steps:
            step = PlanStep(
                id=template.id,
                stage=template.stage,
                name=template.name,
                capability=template.capability,
                risk=template.risk,
            )
            agent = self._registry.select(step.capability)
            events.append(
                TraceEvent(
                    self._clock.now_label(),
                    "Agent 启动",
                    f"{agent.card.name} · {step.name}",
                )
            )
            step.start()
            result = agent.handle(
                AgentTask(
                    step_id=step.id,
                    stage=step.stage,
                    capability=step.capability,
                    instruction=goal.instruction,
                )
            )
            step.finish(result.artifact)
            events.append(
                TraceEvent(
                    self._clock.now_label(),
                    "Agent 完成",
                    f"{agent.card.name} · {result.artifact}",
                )
            )
            results.append(result)
            steps.append(step)
            if result.approval is not None:
                case = _approval_case(result.approval)
                approvals_by_id[case.id] = case

        approvals: list[ApprovalCase] = []
        for approval_id in plan.approval_ids:
            case = approvals_by_id.get(approval_id)
            if case is None:
                continue
            decision, actor = DEMO_DECISIONS[approval_id]
            case.decide(decision, actor, self._clock.now_label())
            title = "审批通过" if decision is Decision.approve else "审批驳回"
            events.append(
                TraceEvent(self._clock.now_label(), title, f"{case.title} · {actor}")
            )
            approvals.append(case)

        verification = self._verifier.verify(results)
        veto_note = f"{len(verification.vetoed)} 项否决" if verification.vetoed else "无否决"
        events.append(
            TraceEvent(
                self._clock.now_label(),
                "Verifier 通过",
                f"{veto_note} · 毛利 / 库存 / 预算 / 合规 / trace",
            )
        )
        events.append(
            TraceEvent(self._clock.now_label(), "补偿触发", "拆单库存冲突 · 回滚预占并生成替代履约")
        )
        events.append(
            TraceEvent(self._clock.now_label(), "RPA 执行", "影刀旧版供应商门户 · 截图与审计")
        )
        events.append(
            TraceEvent(self._clock.now_label(), "对账差异", "3 笔差异 → 财务任务")
        )
        events.append(
            TraceEvent(self._clock.now_label(), "报告生成", "指标 / 证据 / trace")
        )

        summary = (
            "10 个节点执行完成 · 审批 2 准 1 驳 · "
            f"Verifier {veto_note} · 1 次补偿 · 3 笔对账差异"
        )
        return DemoRunReport(
            events=tuple(events),
            steps=tuple(steps),
            approvals=tuple(approvals),
            verification=verification,
            summary=summary,
        )


__all__ = ["DEMO_DECISIONS", "DemoRunReport", "DispatchOrchestrator"]
