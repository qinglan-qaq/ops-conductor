"""API、planner 与持久化层共用的字符串枚举。

枚举值会原样写入 ``String`` 列，因此这些字符串属于持久化契约的一部分：修改
某个值需要数据迁移。持久化辅助代码使用 ``.value`` 进行比较，因为数据库中
存储的是普通字符串，而非枚举实例。
"""

from enum import Enum


class Role(str, Enum):  # noqa: UP042
    """附加到 API 用户的授权角色。

    ``operator`` 可以请求任务，``approver`` 可以裁决 L2/L3 审批，``admin``
    拥有完整权限（包括控制台操作）。
    """

    operator = "operator"
    approver = "approver"
    admin = "admin"


class RiskLevel(str, Enum):  # noqa: UP042
    """计划动作的风险等级。

    ``L0`` 涵盖读取与校验，自动执行；``L2`` 涵盖一般的发货前写入，需要审批；
    ``L3`` 标记高风险或超大批次，同样需要审批。
    """

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class TaskStatus(str, Enum):  # noqa: UP042
    """任务从受理到最终结果的生命周期。

    任务从 ``received`` 开始，经计划与可选审批进入 ``running``，最终以
    ``succeeded``、``partially_succeeded`` 或 ``failed`` 结束。若写入失败，
    任务也可能经 ``compensating`` 进入已补偿的终止状态。
    """

    received = "received"
    planned = "planned"
    awaiting_approval = "awaiting_approval"
    running = "running"
    succeeded = "succeeded"
    partially_succeeded = "partially_succeeded"
    failed = "failed"
    compensating = "compensating"
    compensated = "compensated"
    partially_compensated = "partially_compensated"


class StepStatus(str, Enum):  # noqa: UP042
    """单次计划节点执行尝试的生命周期。

    ``pending`` 步骤尚未开始，``skipped`` 步骤是有意未执行，``compensated``
    步骤已由其补偿动作成功撤销。
    """

    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"
    compensated = "compensated"


class ApprovalStatus(str, Enum):  # noqa: UP042
    """审批请求的裁决状态。

    只有 ``pending`` 行可以被裁决。``expires_at`` 过期后，审批服务会把行关闭为
    ``expired``，此后不能再被批准。
    """

    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"


class OrderStatus(str, Enum):  # noqa: UP042
    """销售订单的生命周期。

    ``pending_shipment`` 状态的订单可以拆分、修改地址以及执行其他发货前写入。
    ``split`` 状态的订单已通过其发运单持有库存预留。

    Note:
        ``split`` 成员会遮蔽这些值上的 ``str.split``。请与
        ``OrderStatus.split`` 或其 ``.value`` 比较，而不要在成员上调用字符串
        的 ``split`` 方法。
    """

    pending_shipment = "pending_shipment"
    split = "split"  # type: ignore[assignment]  # collides with str.split
