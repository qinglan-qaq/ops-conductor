"""跨境调度领域枚举。

枚举值会直接序列化为 API 契约与前端展示标签，因此修改值属于破坏性变更。
"""

from enum import Enum


class RiskLevel(str, Enum):  # noqa: UP042
    """动作风险等级。

    ``L0`` 自动执行，``L1`` 事后通知，``L2`` 需要二次确认，``L3`` 必须人工
    审批。Demo 中 ``L2``/``L3`` 动作在计划中标为待审批。
    """

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class Priority(str, Enum):  # noqa: UP042
    """异常按 5×5 风险矩阵定级后的处置优先级。

    ``P0`` 响应最快（15 分钟），``P3`` 最慢（1440 分钟），SLA 由
    :class:`~opsconductor.dispatch.domain.policies.PriorityPolicy` 提供。
    """

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class ApprovalStatus(str, Enum):  # noqa: UP042
    """审批案的生命周期。

    只有 ``pending`` 状态可以被裁决；已裁决的审批案再次裁决会抛出
    :class:`~opsconductor.dispatch.domain.errors.ApprovalAlreadyDecided`。
    """

    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class StepStatus(str, Enum):  # noqa: UP042
    """计划节点从待执行到终态的状态。"""

    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"


class AgentStatus(str, Enum):  # noqa: UP042
    """领域 Agent 在调度台中的状态。"""

    idle = "idle"
    running = "running"
    waiting = "waiting"
    done = "done"
    error = "error"


class StageStatus(str, Enum):  # noqa: UP042
    """十段价值链节点的状态。"""

    done = "done"
    running = "running"
    alert = "alert"
    waiting = "waiting"


class Decision(str, Enum):  # noqa: UP042
    """审批裁决结果。"""

    approve = "approve"
    reject = "reject"


class ArtifactKind(str, Enum):  # noqa: UP042
    """阶段产物的展示类型。

    前端用该枚举选择书签标签；枚举值直接进入 API 契约，新增类型必须同步
    更新前端 ``ArtifactChip`` 映射。
    """

    json = "json"
    csv = "csv"
    markdown = "markdown"
    image = "image"
    video = "video"
    pdf = "pdf"
    other = "other"


class ControlStatus(str, Enum):  # noqa: UP042
    """平台控制命令的生命周期。"""

    accepted = "accepted"
    rejected = "rejected"
    succeeded = "succeeded"
    failed = "failed"
    compensated = "compensated"


class SyncStatus(str, Enum):  # noqa: UP042
    """一次数据同步的生命周期。"""

    running = "running"
    succeeded = "succeeded"
    partial = "partial"
    failed = "failed"


class IntegrationStatus(str, Enum):  # noqa: UP042
    """平台集成连接状态。"""

    connected = "connected"
    mock = "mock"
    degraded = "degraded"
    disconnected = "disconnected"


class IntegrationMode(str, Enum):  # noqa: UP042
    """平台运行模式；``mock`` 不得产生真实外部副作用。"""

    mock = "mock"
    live = "live"


class Freshness(str, Enum):  # noqa: UP042
    """数据新鲜度；``unknown`` 表示缺乏同步证据。"""

    fresh = "fresh"
    stale = "stale"
    unknown = "unknown"


class IntegrationCapability(str, Enum):  # noqa: UP042
    """跨平台数据与控制能力名。

    页面和 Agent 只依据能力名做门禁，不依据平台名写分支。值必须与 spec
    §6.7.2 及 Adapter manifest 保持逐字一致。
    """

    data_orders = "data.orders"
    data_inventory = "data.inventory"
    data_listings = "data.listings"
    data_settlements = "data.settlements"
    data_ads = "data.ads"
    data_logistics = "data.logistics"
    data_trends = "data.trends"
    control_purchase = "control.purchase"
    control_listing = "control.listing"
    control_price = "control.price"
    control_inventory = "control.inventory"
    control_shipment = "control.shipment"
    control_refund = "control.refund"
    control_ads = "control.ads"
