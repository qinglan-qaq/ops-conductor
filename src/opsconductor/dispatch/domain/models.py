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
from typing import Generic, TypeVar

from opsconductor.dispatch.domain.enums import (
    AgentStatus,
    ApprovalStatus,
    ArtifactKind,
    ControlStatus,
    Decision,
    Freshness,
    IntegrationCapability,
    IntegrationMode,
    IntegrationStatus,
    Priority,
    RiskLevel,
    StageStatus,
    StepStatus,
    SyncStatus,
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
    stage_id: str = ""

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
    stage_id: str = ""

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
    results: dict[str, StageResult]


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
        stage_id: 审批所属阶段，用于侧栏计数与阶段工作台过滤。
    """

    id: str
    title: str
    action: str
    risk: RiskLevel
    owner: str
    impact: str
    recommended: Decision
    stage_id: str = ""


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


@dataclass(frozen=True)
class Artifact:
    """阶段产物引用。

    Attributes:
        name: 文件名，例如 ``order-exceptions.csv``。
        kind: 展示类型，用于前端书签标签。
        uri: Mock 或对象存储 URI；Demo 使用 ``mock://`` 前缀。
        description: 可选的一句话说明。
    """

    name: str
    kind: ArtifactKind
    uri: str
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.uri.strip():
            raise ValueError("artifact name and uri must not be blank")


@dataclass(frozen=True)
class Metric:
    """阶段指标键值对。

    小数指标（例如 ROAS）使用字符串保存，避免演示数据引入浮点账务误差。
    """

    key: str
    value: str | int

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("metric key must not be blank")


@dataclass(frozen=True)
class DataProvenance:
    """阶段结果的数据来源与新鲜度。

    Attributes:
        platform: 平台标识，Demo 为 ``mock``。
        shop_id: 店铺/账号标识。
        adapter: 生成该结果的 Adapter。
        synced_at: 数据同步时刻，``HH:MM``。
        schema_version: canonical schema 版本。
    """

    platform: str
    shop_id: str
    adapter: str
    synced_at: str
    schema_version: str

    def __post_init__(self) -> None:
        if not self.platform or not self.shop_id or not self.adapter:
            raise ValueError("provenance platform, shop_id and adapter are required")


@dataclass(frozen=True)
class StageResult:
    """子 Agent 在某个阶段的确定性产出。

    Attributes:
        stage_id: 阶段 ID，例如 ``order``。
        agent_id: 产出的 Agent ID，例如 ``order``。
        status: 展示状态。
        summary: 一句话结果摘要。
        artifacts: 产物元组。
        metrics: 指标元组；序列化时转为对象。
        evidence: 证据/引用描述元组。
        provenance: 平台/店铺/Adapter/同步时间/schema 版本。
        at: 展示时刻，``HH:MM``。
    """

    stage_id: str
    agent_id: str
    status: StageStatus
    summary: str
    artifacts: tuple[Artifact, ...]
    metrics: tuple[Metric, ...]
    evidence: tuple[str, ...]
    provenance: DataProvenance
    at: str

    def __post_init__(self) -> None:
        if not self.stage_id.strip() or not self.agent_id.strip():
            raise ValueError("stage_id and agent_id must not be blank")
        if not self.summary.strip():
            raise ValueError("summary must not be blank")
        keys = [metric.key for metric in self.metrics]
        if len(keys) != len(set(keys)):
            raise ValueError("metric keys must be unique")


@dataclass(frozen=True)
class StageStep:
    """阶段内的一个子流程步骤。"""

    id: str
    name: str


@dataclass(frozen=True)
class StageDefinition:
    """阶段目录中的静态定义。

    Attributes:
        id: 阶段 ID。
        order_label: 中文序号，例如 ``陆``。
        name: 阶段名称。
        owner: 主责角色。
        risk: 默认风险等级。
        actions: 核心动作。
        failures: 典型失败。
        ai: AI 可增强点。
        metrics: 关键指标名称。
        steps: 子流程步骤。
    """

    id: str
    order_label: str
    name: str
    owner: str
    risk: RiskLevel
    actions: tuple[str, ...]
    failures: tuple[str, ...]
    ai: tuple[str, ...]
    metrics: tuple[str, ...]
    steps: tuple[StageStep, ...]


@dataclass(frozen=True)
class PlatformRef:
    """选择 Adapter 的租户/平台/店铺边界。"""

    tenant_id: str
    platform: str
    shop_id: str
    market: str = ""


@dataclass(frozen=True)
class OrderLine:
    """canonical 订单行；金额为整数美元。"""

    sku: str
    quantity: int
    amount_usd: int

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("order line quantity must be positive")


@dataclass(frozen=True)
class CanonicalOrder:
    """与平台无关的订单模型。"""

    external_id: str
    status: str
    currency: str
    total_usd: int
    lines: tuple[OrderLine, ...]
    shipping_address: str
    updated_at: str
    raw_ref: str


@dataclass(frozen=True)
class CanonicalInventory:
    """与平台无关的库存模型。"""

    sku: str
    warehouse: str
    available: int
    reserved: int
    in_transit: int
    version: int
    raw_ref: str


@dataclass(frozen=True)
class CanonicalListing:
    """与平台无关的 Listing/价格模型。"""

    external_id: str
    sku: str
    title: str
    price_usd: int
    currency: str
    status: str
    version: int
    raw_ref: str


@dataclass(frozen=True)
class CanonicalShipment:
    """与平台无关的发货与轨迹模型。"""

    external_id: str
    order_external_id: str
    carrier: str
    tracking_no: str
    status: str
    events: tuple[str, ...]
    raw_ref: str


@dataclass(frozen=True)
class CanonicalSettlement:
    """与平台无关的结算单；金额为整数美元。"""

    external_id: str
    period: str
    gross_usd: int
    fees_usd: int
    refunds_usd: int
    net_usd: int
    currency: str
    raw_ref: str


@dataclass(frozen=True)
class CanonicalAdMetric:
    """与平台无关的广告指标。"""

    campaign_id: str
    spend_usd: int
    impressions: int
    clicks: int
    conversions: int
    roas: float
    source: str


@dataclass(frozen=True)
class CanonicalTrendSignal:
    """低置信度趋势信号；不得当作订单/库存事实源。"""

    keyword: str
    geo: str
    window: str
    interest: int
    confidence: float
    source: str


@dataclass(frozen=True)
class CanonicalPolicy:
    """平台政策/合规引用，带版本与生效时间。"""

    platform: str
    policy_id: str
    version: str
    effective_at: str
    source_url: str
    raw_ref: str


@dataclass(frozen=True)
class IntegrationError:
    """跨平台可归因错误。"""

    code: str
    message: str
    retryable: bool
    external_ref: str | None = None


@dataclass(frozen=True)
class ControlCommand:
    """跨平台控制写命令。

    Attributes:
        params: 适配器参数；调用方必须先在 Adapter 契约内校验。
        expected_version: 乐观锁版本，``None`` 表示由 Adapter 决定。
        dry_run: 为真时只允许预检，不得写平台。
        idempotency_key: 必填幂等键；同一键不得对应不同命令体。
        approval_id: L2/L3 动作必须提供已批准的审批 ID。
    """

    command_id: str
    tenant_id: str
    platform: str
    shop_id: str
    capability: IntegrationCapability
    operation: str
    entity_type: str
    entity_id: str | None
    params: Mapping[str, object]
    expected_version: int | None
    risk: RiskLevel
    dry_run: bool
    idempotency_key: str
    approval_id: str | None
    requested_by: str
    requested_at: str

    def __post_init__(self) -> None:
        if not self.command_id.strip() or not self.operation.strip():
            raise ValueError("command_id and operation must not be blank")
        if not self.idempotency_key.strip():
            raise ValueError("idempotency_key must not be blank")


@dataclass(frozen=True)
class ControlResult:
    """控制命令结果；失败必须可归因、可重试判断、可补偿。"""

    command_id: str
    status: ControlStatus
    external_id: str | None
    evidence: tuple[str, ...]
    error: IntegrationError | None
    adapter_meta: Mapping[str, object]
    completed_at: str


@dataclass(frozen=True)
class DataQuery:
    """分页/增量数据查询。"""

    query_id: str
    tenant_id: str
    platform: str
    shop_id: str
    resource: str
    filters: Mapping[str, object]
    cursor: str | None
    page_size: int
    since: str | None
    until: str | None

    def __post_init__(self) -> None:
        if self.page_size <= 0:
            raise ValueError("page_size must be positive")


@dataclass(frozen=True)
class DataQuality:
    """数据质量与新鲜度告警。"""

    warnings: tuple[str, ...]
    missing_fields: tuple[str, ...]
    stale_after: str | None


T = TypeVar("T")


@dataclass(frozen=True)
class DataPage(Generic[T]):
    """一页 canonical 数据及同步元信息。"""

    items: tuple[T, ...]
    next_cursor: str | None
    fetched_at: str
    source: DataProvenance
    quality: DataQuality


@dataclass(frozen=True)
class SyncRun:
    """一次数据同步的可审计记录。"""

    id: str
    resource: str
    platform: str
    status: SyncStatus
    cursor_start: str | None
    cursor_end: str | None
    fetched: int
    upserted: int
    failed: int
    started_at: str
    finished_at: str | None
    errors: tuple[IntegrationError, ...]


@dataclass(frozen=True)
class AdapterManifest:
    """适配器能力与限制声明。

    Attributes:
        display_name: 平台/店铺展示名；仅用于 UI，不参与能力判断。
    """

    adapter_id: str
    platform: str
    version: str
    capabilities: tuple[IntegrationCapability, ...]
    default_risk: RiskLevel
    rate_limit_per_minute: int
    supports_dry_run: bool
    supports_idempotency: bool
    display_name: str = ""


@dataclass(frozen=True)
class IntegrationHealth:
    """集成健康与数据新鲜度。"""

    platform: str
    shop_id: str
    status: IntegrationStatus
    mode: IntegrationMode
    capabilities: tuple[IntegrationCapability, ...]
    last_sync_at: str | None
    freshness: Freshness
    warnings: tuple[str, ...]
