"""跨境调度领域错误。

错误类型保持无状态，由应用层或适配层映射为 HTTP 状态码（审批冲突 → 409，
未知审批/异常 → 404，非法目标 → 422）。
"""


class DispatchError(Exception):
    """调度领域错误的基类。"""


class InvalidGoal(DispatchError):
    """目标指令为空或无法解析时抛出。"""


class InvalidTransition(DispatchError):
    """状态机收到非法状态迁移时抛出。"""


class ApprovalNotFound(DispatchError):
    """审批 ID 不存在时抛出。"""


class ApprovalAlreadyDecided(DispatchError):
    """审批案已裁决却再次收到裁决时抛出。"""


class ExceptionNotFound(DispatchError):
    """异常用例 ID 不存在时抛出。"""


class StageNotFound(DispatchError):
    """请求的阶段 ID 不在阶段目录中。"""


class AdapterNotFound(DispatchError):
    """指定平台/店铺没有注册 Adapter。"""


class CapabilityNotSupported(DispatchError):
    """Adapter 未声明请求的 data/control 能力。"""


class ApprovalRequired(DispatchError):
    """L2/L3 控制写缺少已批准的 approval_id。"""


class IdempotencyConflict(DispatchError):
    """同一幂等键被用于不同的控制命令。"""
