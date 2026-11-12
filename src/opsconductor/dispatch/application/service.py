"""DispatchService：适配层使用的应用门面。

门面把仓储快照整理为 :class:`DispatchSnapshot`，并暴露目标创建、审批裁决、
审批重置、整体重置、Demo 编排与异常查询。所有写操作通过
:class:`~opsconductor.dispatch.domain.ports.DispatchRepository` 的 ``mutate``
完成，trace 事件统一使用 ``ClockPort`` 的展示时刻。
"""

from __future__ import annotations

from dataclasses import dataclass

from opsconductor.dispatch.application.orchestrator import DemoRunReport, DispatchOrchestrator
from opsconductor.dispatch.application.seed import (
    build_approvals,
    build_seed_state,
    build_trace,
)
from opsconductor.dispatch.domain.enums import ApprovalStatus, Decision
from opsconductor.dispatch.domain.errors import ApprovalNotFound, ExceptionNotFound
from opsconductor.dispatch.domain.models import (
    AgentCard,
    ApprovalCase,
    ChainStage,
    DispatchState,
    ExceptionCase,
    Goal,
    Plan,
    TraceEvent,
)
from opsconductor.dispatch.domain.ports import ClockPort, DispatchRepository


@dataclass(frozen=True)
class KpiSnapshot:
    """调度台四个关键指标的只读快照。"""

    gmv_target: int
    exceptions: int
    approvals_pending: int
    compensations: int


@dataclass(frozen=True)
class DispatchSnapshot:
    """前端一次性渲染所需的完整状态快照。"""

    goal: Goal
    plan: Plan
    approvals: dict[str, ApprovalCase]
    exceptions: tuple[ExceptionCase, ...]
    agents: dict[str, AgentCard]
    chain: tuple[ChainStage, ...]
    trace: list[TraceEvent]
    kpis: KpiSnapshot
    flow_note: str


class DispatchService:
    """跨境调度 Demo 的应用服务门面。"""

    def __init__(
        self,
        repo: DispatchRepository,
        orchestrator: DispatchOrchestrator,
        clock: ClockPort,
    ) -> None:
        self._repo = repo
        self._orchestrator = orchestrator
        self._clock = clock

    def snapshot(self) -> DispatchSnapshot:
        """返回当前状态的深拷贝快照及派生 KPI。"""
        state = self._repo.snapshot()
        pending = self._pending_count(state)
        return DispatchSnapshot(
            goal=state.goal,
            plan=state.plan,
            approvals=state.approvals,
            exceptions=state.exceptions,
            agents=state.agents,
            chain=state.chain,
            trace=state.trace,
            kpis=KpiSnapshot(
                gmv_target=state.goal.target_gmv,
                exceptions=len(state.exceptions),
                approvals_pending=pending,
                compensations=1,
            ),
            flow_note=(
                f"审批进行中 · {pending} 件待批" if pending else "审批已清 · 进入执行"
            ),
        )

    def create_goal(self, instruction: str) -> DispatchSnapshot:
        """用新指令重建目标与计划，并把审批、链路、Agent 与 trace 复位。

        Args:
            instruction: 自然语言运营目标；空白指令由领域模型抛出
                :class:`~opsconductor.dispatch.domain.errors.InvalidGoal`。

        Returns:
            重建后的完整快照。
        """
        goal = Goal(id="goal-demo", instruction=instruction)
        plan = self._orchestrator.plan(goal)

        def mutate(state: DispatchState) -> None:
            seeded = build_seed_state(state.agents)
            state.goal = goal
            state.plan = plan
            state.approvals = {approval.id: approval for approval in build_approvals()}
            state.exceptions = seeded.exceptions
            state.agents = seeded.agents
            state.chain = seeded.chain
            state.trace = build_trace()
            state.trace.append(
                TraceEvent(
                    self._clock.now_label(),
                    "计划生成",
                    "目标已结构化 · DAG / 风险 / 预算",
                )
            )

        self._repo.mutate(mutate)
        return self.snapshot()

    def decide_approval(self, approval_id: str, decision: str, actor: str) -> DispatchSnapshot:
        """裁决一件审批案并追加 trace。

        Args:
            approval_id: 审批案 ID。
            decision: ``approve`` 或 ``reject`` 字符串，转换为领域
                :class:`~opsconductor.dispatch.domain.enums.Decision`。
            actor: 做出裁决的人类操作者。

        Returns:
            裁决后的完整快照。

        Raises:
            ApprovalNotFound: 审批 ID 不存在。
            ApprovalAlreadyDecided: 审批案已经裁决。
        """
        chosen = Decision(decision)

        def mutate(state: DispatchState) -> None:
            approval = state.approvals.get(approval_id)
            if approval is None:
                raise ApprovalNotFound(f"unknown approval: {approval_id}")
            approval.decide(chosen, actor, self._clock.now_label())
            state.trace.append(
                TraceEvent(
                    self._clock.now_label(),
                    "审批通过" if chosen is Decision.approve else "审批驳回",
                    f"{approval.title} · {actor}",
                )
            )

        self._repo.mutate(mutate)
        return self.snapshot()

    def reset_approvals(self) -> DispatchSnapshot:
        """把所有审批案恢复为待批并追加一条重置 trace。"""

        def mutate(state: DispatchState) -> None:
            for approval in state.approvals.values():
                approval.reset()
            state.trace.append(
                TraceEvent(
                    self._clock.now_label(),
                    "审批案重置",
                    f"{len(state.approvals)} 件审批回到待批",
                )
            )

        self._repo.mutate(mutate)
        return self.snapshot()

    def reset(self) -> DispatchSnapshot:
        """恢复仓储种子状态并返回快照。"""
        self._repo.reset()
        return self.snapshot()

    def run_demo(self) -> DemoRunReport:
        """对当前目标执行一次完整的 Agent 编排演示。"""
        goal = self._repo.snapshot().goal
        return self._orchestrator.run(goal)

    def get_exception(self, exception_id: str) -> ExceptionCase:
        """按 ID 返回异常用例。

        Raises:
            ExceptionNotFound: 异常 ID 不存在。
        """
        state = self._repo.snapshot()
        for exception in state.exceptions:
            if exception.id == exception_id:
                return exception
        raise ExceptionNotFound(f"unknown exception: {exception_id}")

    @staticmethod
    def _pending_count(state: DispatchState) -> int:
        return sum(
            1
            for approval in state.approvals.values()
            if approval.status is ApprovalStatus.pending
        )


__all__ = ["DispatchService", "DispatchSnapshot", "KpiSnapshot"]
