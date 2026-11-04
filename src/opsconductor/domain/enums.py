from enum import Enum


class Role(str, Enum):  # noqa: UP042
    operator = "operator"
    approver = "approver"
    admin = "admin"


class RiskLevel(str, Enum):  # noqa: UP042
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class TaskStatus(str, Enum):  # noqa: UP042
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
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"
    compensated = "compensated"


class ApprovalStatus(str, Enum):  # noqa: UP042
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"


class OrderStatus(str, Enum):  # noqa: UP042
    pending_shipment = "pending_shipment"
    split = "split"  # type: ignore[assignment]  # collides with str.split
