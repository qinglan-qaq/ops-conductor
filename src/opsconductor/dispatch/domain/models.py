"""跨境调度领域模型。

模型分为两类：

- 不可变值对象使用 ``frozen=True`` 的 dataclass，例如 :class:`Goal`、
  :class:`AgentCard`、:class:`TraceEvent`；需要变更时通过 ``replace`` 或
  ``with_status`` 生成新实例。
- 有状态实体使用可变 dataclass 并自带状态机方法，例如 :class:`PlanStep`
  与 :class:`ApprovalCase`。非法迁移会抛出
  :class:`~opsconductor.dispatch.domain.errors.InvalidTransition` 或
  :class:`~opsconductor.dispatch.domain.errors.ApprovalAlreadyDecided`。

所有金额均为整数美元；Demo 的目标 GMV 为 100000、广告预算为 10000。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from opsconductor.dispatch.domain.enums import (
    AgentStatus,
    ApprovalStatus,
    Decision,
    Priority,
    RiskLevel,
    StageStatus,
    StepStatus,
)
from opsconductor.dispatch.domain.errors import (
    ApprovalAlreadyDecided,
    InvalidGoal,
    InvalidTransition,
)

_RISK_ORDER = {
    RiskLevel.L0: 0,
    RiskLevel.L1: 1,
    RiskLevel.L2: 2,
    RiskLevel.L3: 3,
}


@dataclass(frozen=True)
class Goal:
    """一条自然语言运营目标及其结构化约束。

    Attributes:
        id: 目标 ID，Demo 固定为 ``goal-demo``。
        instruction: 自然语言指令；空白字符串视为非法目标。
        store: 店铺名称，默认 Demo 店铺。
        market: 市场与品类标签。
        target_gmv: 本周 GMV 目标（整数美元）。
        budget: 广告预算（整数美元）。
        roas_target: 目标 ROAS。
    """

    id: str
    instruction: str
    store: str = "NestWell Home US"
    market: str = "美区 · 家居"
    target_gmv: int = 100_000
    budget: int = 10_000
    roas_target: float = 2.5

    def __post_init__(self) -> None:
        if not self.instruction.strip():
            raise InvalidGoal("goal instruction must not be blank")


@dataclass
class PlanStep:
    """计划 DAG 中的一个可执行节点。

    生命周期为 ``pending → running → succeeded`` 或 ``pending → running →
    failed``；跳过直接使用 ``skipped`` 终态。状态机方法只接受合法来源状态，
    重复完成或未启动即完成都会抛出 ``InvalidTransition``。
    """

    id: str
    stage: str
    name: str
    capability: str
    risk: RiskLevel
    status: StepStatus = StepStatus.pending
    artifact: str | None = None
    error: str | None = None

    def start(self) -> None:
        """把待执行节点置为运行中。

        Raises:
            InvalidTransition: 节点不是 ``pending`` 状态。
        """
        self._require(StepStatus.pending, "start")
        self.status = StepStatus.running

    def finish(self, artifact: str) -> None:
        """记录节点成功并保存产物。

        Args:
            artifact: 节点产物的可读引用，例如 ``orders.json``。

        Raises:
            InvalidTransition: 节点不是 ``running`` 状态。
        """
        self._require(StepStatus.running, "finish")
        self.artifact = artifact
        self.status = StepStatus.succeeded

    def fail(self, reason: str = "") -> None:
        """记录节点失败及原因。

        Args:
            reason: 失败的可读原因；默认空字符串。

        Raises:
            InvalidTransition: 节点不是 ``running`` 状态。
        """
        self._require(StepStatus.running, "fail")
        self.error = reason
        self.status = StepStatus.failed

    def _require(self, expected: StepStatus, action: str) -> None:
        if self.status is not expected:
            raise InvalidTransition(
                f"cannot {action} step {self.id} from {self.status.value}"
            )


@dataclass
class Plan:
    """由目标生成的有序计划。

    Attributes:
        id: 计划 ID。
        goal_id: 所属目标 ID。
        steps: 十段链路对应的执行节点。
        approval_ids: 需要人工审批的审批案 ID，按剧本顺序排列。
        created_at: 计划生成时刻的展示标签。
    """

    id: str
    goal_id: str
    steps: list[PlanStep]
    approval_ids: list[str] = field(default_factory=list)
    created_at: str = ""

    @property
    def risk(self) -> RiskLevel:
        """返回计划中最高风险等级；无节点时为 ``L0``。"""
        return max(
            (step.risk for step in self.steps),
            default=RiskLevel.L0,
            key=_RISK_ORDER.__getitem__,
        )


@dataclass
class ApprovalCase:
    """等待人工裁决的审批案。

    审批案从 ``pending`` 开始，只能被裁决一次；重复裁决抛出
    ``ApprovalAlreadyDecided``。:meth:`reset` 供 Demo 的「重置审批案」流程
    恢复初始状态。
    """

    id: str
    title: str
    action: str
    risk: RiskLevel
    owner: str
    impact: str
    recommended: Decision | None = None
    status: ApprovalStatus = ApprovalStatus.pending
    actor: str | None = None
    decided_at: str | None = None

    def decide(self, decision: Decision, actor: str, at: str) -> None:
        """应用一次裁决。

        Args:
            decision: ``approve`` 或 ``reject``。
            actor: 做出裁决的人类操作者。
            at: 裁决时刻的展示标签。

        Raises:
            ApprovalAlreadyDecided: 审批案已不在 ``pending`` 状态。
        """
        if self.status is not ApprovalStatus.pending:
            raise ApprovalAlreadyDecided(
                f"approval {self.id} is already {self.status.value}"
            )
        self.status = (
            ApprovalStatus.approved
            if decision is Decision.approve
            else ApprovalStatus.rejected
        )
        self.actor = actor
        self.decided_at = at

    def reset(self) -> None:
        """恢复为待批状态并清除裁决人、时刻与结果。"""
        self.status = ApprovalStatus.pending
        self.actor = None
        self.decided_at = None


@dataclass(frozen=True)
class ChainStage:
    """十段价值链上的一个节点。

    Attributes:
        id: 节点 ID，例如 ``selection``、``order``。
        name: 展示名称。
        status: 节点状态。
        meta: 节点右侧的摘要文本。
    """

    id: str
    name: str
    status: StageStatus
    meta: str


@dataclass(frozen=True)
class AgentCard:
    """领域 Agent 的注册卡片。

    Attributes:
        id: Agent ID。
        name: 展示名称。
        role: 职责摘要。
        capabilities: 可处理的能力名，供 Orchestrator 按能力选择。
        risk: Agent 动作的默认风险等级。
        status: 调度台展示状态。
        current_task: 当前任务的可读描述。
    """

    id: str
    name: str
    role: str
    capabilities: tuple[str, ...]
    risk: RiskLevel
    status: AgentStatus = AgentStatus.idle
    current_task: str = ""

    def with_status(
        self, status: AgentStatus, current_task: str | None = None
    ) -> AgentCard:
        """返回更新状态后的卡片副本。

        Args:
            status: 新的 Agent 状态。
            current_task: 新的当前任务；``None`` 表示保留原任务描述。

        Returns:
            使用 ``dataclasses.replace`` 生成的冻结副本。
        """
        task = self.current_task if current_task is None else current_task
        return replace(self, status=status, current_task=task)


@dataclass(frozen=True)
class PlaybookPhase:
    """异常 Playbook 的一个处置阶段。"""

    label: str
    steps: tuple[str, ...]


@dataclass(frozen=True)
class Playbook:
    """异常的触发条件、分阶段处置与 Agent 自动化描述。"""

    trigger: str
    phases: tuple[PlaybookPhase, ...]
    automation: str


@dataclass(frozen=True)
class ExceptionCase:
    """一条可定级、可处置的运营异常。

    Attributes:
        id: 异常 ID，例如 ``ORD-01``。
        title: 异常标题。
        priority: 按 5×5 矩阵定级后的优先级。
        likelihood: 可能性维度 L（1–5）。
        impact: 影响维度 I（1–5）。
        sla: 响应与止损 SLA 文案。
        owner: 负责处置的 Agent 或角色。
        count: 影响范围摘要，例如 ``2 单``。
        playbook: 分阶段处置手册。
    """

    id: str
    title: str
    priority: Priority
    likelihood: int
    impact: int
    sla: str
    owner: str
    count: str
    playbook: Playbook

    @property
    def li(self) -> str:
        """返回 ``Lx / Iy`` 形式的矩阵坐标。"""
        return f"L{self.likelihood} / I{self.impact}"


@dataclass(frozen=True)
class TraceEvent:
    """一条可回放的 trace 记录。"""

    at: str
    title: str
    detail: str


@dataclass
class DispatchState:
    """调度台的整体演示状态。

    ``approvals`` 与 ``agents`` 以 ID 为键，便于按审批案或 Agent 定位；
    ``trace`` 是可变列表，服务层在每次动作后追加事件。仓储负责对该状态做
    快照与深拷贝。
    """

    goal: Goal
    plan: Plan
    approvals: dict[str, ApprovalCase]
    exceptions: tuple[ExceptionCase, ...]
    agents: dict[str, AgentCard]
    chain: tuple[ChainStage, ...]
    trace: list[TraceEvent]


@dataclass(frozen=True)
class AgentTask:
    """Orchestrator 分派给领域 Agent 的结构化任务。"""

    step_id: str
    stage: str
    capability: str
    instruction: str = ""


@dataclass(frozen=True)
class ApprovalDraft:
    """Agent 产出的审批草稿，稍后转换为 :class:`ApprovalCase`。

    Attributes:
        recommended: Demo 剧本推荐的裁决结果，仅供展示，不自动执行。
    """

    id: str
    title: str
    action: str
    risk: RiskLevel
    owner: str
    impact: str
    recommended: Decision


@dataclass(frozen=True)
class AgentResult:
    """一次 Agent 处理的确定性结果。"""

    agent_id: str
    stage: str
    summary: str
    artifact: str
    risk: RiskLevel
    approval: ApprovalDraft | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class VerificationResult:
    """独立 Verifier 的检查结果。

    Attributes:
        passed: 确定性检查是否通过。
        checks: 实际执行的检查项名称。
        vetoed: 被否决的条目描述；为空表示没有否决项。
    """

    passed: bool
    checks: tuple[str, ...]
    vetoed: tuple[str, ...] = ()
