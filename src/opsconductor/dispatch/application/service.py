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
from opsconductor.dispatch.application.stages import CONTROL_STAGE, STAGE_CATALOG
from opsconductor.dispatch.domain.enums import (
    AgentStatus,
    ApprovalStatus,
    Decision,
    Priority,
    RiskLevel,
    StageStatus,
)
from opsconductor.dispatch.domain.errors import (
    ApprovalNotFound,
    ExceptionNotFound,
    StageNotFound,
)
from opsconductor.dispatch.domain.models import (
    AgentCard,
    ApprovalCase,
    ChainStage,
    DispatchState,
    ExceptionCase,
    Goal,
    Plan,
    StageDefinition,
    StageResult,
    StageStep,
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
class StageNavigation:
    """侧边栏的一组场景目录。

    Attributes:
        id: 阶段 ID；控制塔固定为 ``control``。
        order_label: 中文序号；控制塔使用 ``—``。
        status: 阶段展示状态。
        meta: 阶段摘要文本。
        approval_count: 该阶段待批审批数；控制塔为全局待批数。
        exception_count: 该阶段异常数；控制塔为全局异常数。
        steps: 子流程步骤。
    """

    id: str
    order_label: str
    name: str
    status: StageStatus
    meta: str
    approval_count: int
    exception_count: int
    steps: tuple[StageStep, ...]


@dataclass(frozen=True)
class StageDetail:
    """阶段工作台的组合视图。

    Attributes:
        result: 子 Agent 产出；尚未执行时为 ``None``。
        approvals: 属于该阶段的全部审批案。
        exceptions: 属于该阶段的全部异常。
    """

    definition: StageDefinition
    status: StageStatus
    meta: str
    result: StageResult | None
    approvals: tuple[ApprovalCase, ...]
    exceptions: tuple[ExceptionCase, ...]


@dataclass(frozen=True)
class ApprovalProgress:
    """首页审批进度。"""

    total: int
    pending: int
    approved: int
    rejected: int
    decided_percent: int
    l2_total: int
    l3_total: int


@dataclass(frozen=True)
class StatusSummary:
    """首页全部状态的聚合视图。"""

    chain: dict[str, int]
    agents: dict[str, int]
    approvals: ApprovalProgress
    exceptions: dict[str, int]


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
    navigation: tuple[StageNavigation, ...]
    status_summary: StatusSummary
    approval_progress: ApprovalProgress


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
        """返回当前状态的深拷贝快照及派生 KPI、导航与态势聚合。"""
        state = self._repo.snapshot()
        progress = self._approval_progress(state)
        pending = progress.pending
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
            navigation=self._navigation(state, progress),
            status_summary=self._status_summary(state, progress),
            approval_progress=progress,
        )

    def get_stage_detail(self, stage_id: str) -> StageDetail:
        """返回阶段工作台所需的定义、结果与上下文。

        Args:
            stage_id: 阶段 ID，必须存在于 :data:`STAGE_CATALOG`。

        Returns:
            阶段定义、链路状态、Agent 产出、相关审批与异常。

        Raises:
            StageNotFound: 阶段 ID 未知，或请求的是不提供详情的控制塔。
        """
        definition = next(
            (stage for stage in STAGE_CATALOG if stage.id == stage_id),
            None,
        )
        if definition is None:
            raise StageNotFound(f"unknown stage: {stage_id}")

        state = self._repo.snapshot()
        chain_stage = next(
            (stage for stage in state.chain if stage.id == stage_id),
            None,
        )
        return StageDetail(
            definition=definition,
            status=chain_stage.status if chain_stage is not None else StageStatus.waiting,
            meta=chain_stage.meta if chain_stage is not None else "待开始",
            result=state.results.get(stage_id),
            approvals=tuple(
                approval
                for approval in state.approvals.values()
                if approval.stage_id == stage_id
            ),
            exceptions=tuple(
                exception
                for exception in state.exceptions
                if exception.stage_id == stage_id
            ),
        )

    def approval_progress(self) -> ApprovalProgress:
        """返回当前审批进度聚合。"""
        return self._approval_progress(self._repo.snapshot())

    @staticmethod
    def _approval_progress(state: DispatchState) -> ApprovalProgress:
        """按状态与风险统计审批案，供首页进度条使用。"""
        approvals = tuple(state.approvals.values())
        total = len(approvals)
        pending = sum(
            1 for approval in approvals if approval.status is ApprovalStatus.pending
        )
        approved = sum(
            1 for approval in approvals if approval.status is ApprovalStatus.approved
        )
        rejected = sum(
            1 for approval in approvals if approval.status is ApprovalStatus.rejected
        )
        decided = approved + rejected
        return ApprovalProgress(
            total=total,
            pending=pending,
            approved=approved,
            rejected=rejected,
            decided_percent=round(decided / total * 100) if total else 0,
            l2_total=sum(
                1 for approval in approvals if approval.risk is RiskLevel.L2
            ),
            l3_total=sum(
                1 for approval in approvals if approval.risk is RiskLevel.L3
            ),
        )

    def _navigation(
        self,
        state: DispatchState,
        progress: ApprovalProgress,
    ) -> tuple[StageNavigation, ...]:
        """按运营顺序组装 10 个阶段与控制塔的侧栏目录。"""
        chain_by_id = {stage.id: stage for stage in state.chain}
        items: list[StageNavigation] = []
        for definition in STAGE_CATALOG:
            chain_stage = chain_by_id.get(definition.id)
            items.append(
                StageNavigation(
                    id=definition.id,
                    order_label=definition.order_label,
                    name=definition.name,
                    status=(
                        chain_stage.status
                        if chain_stage is not None
                        else StageStatus.waiting
                    ),
                    meta=chain_stage.meta if chain_stage is not None else "待开始",
                    approval_count=self._stage_approval_count(state, definition.id),
                    exception_count=sum(
                        1
                        for exception in state.exceptions
                        if exception.stage_id == definition.id
                    ),
                    steps=definition.steps,
                )
            )
        items.append(
            StageNavigation(
                id=CONTROL_STAGE.id,
                order_label=CONTROL_STAGE.order_label,
                name=CONTROL_STAGE.name,
                status=StageStatus.running,
                meta=f"{progress.pending} 件待批",
                approval_count=progress.pending,
                exception_count=len(state.exceptions),
                steps=CONTROL_STAGE.steps,
            )
        )
        return tuple(items)

    @staticmethod
    def _stage_approval_count(state: DispatchState, stage_id: str) -> int:
        """统计阶段内待批审批；控制塔由调用方直接使用全局进度。"""
        return sum(
            1
            for approval in state.approvals.values()
            if approval.stage_id == stage_id
            and approval.status is ApprovalStatus.pending
        )

    @staticmethod
    def _status_summary(
        state: DispatchState,
        progress: ApprovalProgress,
    ) -> StatusSummary:
        """固定枚举键输出链路、Agent 与异常分布，前端无需自行补齐零值。"""
        chain = {status.value: 0 for status in StageStatus}
        for stage in state.chain:
            chain[stage.status.value] += 1

        agents = {status.value: 0 for status in AgentStatus}
        for agent in state.agents.values():
            agents[agent.status.value] += 1

        exceptions = {priority.value: 0 for priority in Priority}
        for exception in state.exceptions:
            exceptions[exception.priority.value] += 1

        return StatusSummary(
            chain=chain,
            agents=agents,
            approvals=progress,
            exceptions=exceptions,
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
            state.results = seeded.results
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

__all__ = [
    "ApprovalProgress",
    "DispatchService",
    "DispatchSnapshot",
    "KpiSnapshot",
    "StageDetail",
    "StageNavigation",
    "StatusSummary",
]
