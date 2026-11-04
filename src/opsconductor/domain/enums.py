"""String enums shared by the API, planner, and persistence layers.

Values are written verbatim into ``String`` columns, so the strings are part of
the persisted contract: changing a value requires a data migration. Persistence
helpers compare using ``.value`` because rows store plain strings, not enum
instances.
"""

from enum import Enum


class Role(str, Enum):  # noqa: UP042
    """Authorization role attached to an API user.

    ``operator`` may request tasks, ``approver`` may decide L2/L3 approvals,
    and ``admin`` has full access including console operations.
    """

    operator = "operator"
    approver = "approver"
    admin = "admin"


class RiskLevel(str, Enum):  # noqa: UP042
    """Risk grade of a planned action.

    ``L0`` covers reads and verification and runs automatically, ``L2`` covers
    ordinary pre-shipment writes and requires approval, and ``L3`` marks
    high-risk or oversized batches that also require approval.
    """

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class TaskStatus(str, Enum):  # noqa: UP042
    """Lifecycle of a task from intake to a terminal outcome.

    A task moves from ``received`` through planning and optional approval into
    ``running``, and ends as ``succeeded``, ``partially_succeeded``, or
    ``failed``. A write failure can instead move it through ``compensating``
    into a compensated terminal state.
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
    """Lifecycle of one plan-node execution attempt.

    ``pending`` steps have not started, ``skipped`` steps were deliberately not
    executed, and ``compensated`` steps were successfully undone by their
    compensation action.
    """

    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"
    compensated = "compensated"


class ApprovalStatus(str, Enum):  # noqa: UP042
    """Decision state of an approval request.

    Only ``pending`` rows can be decided. ``expired`` rows are closed by the
    approval service once ``expires_at`` passes and can no longer be approved.
    """

    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"


class OrderStatus(str, Enum):  # noqa: UP042
    """Lifecycle of a sales order.

    ``pending_shipment`` orders are eligible for split, address change, and
    other pre-shipment writes. ``split`` orders already hold inventory
    reservations through their shipments.

    Note:
        The ``split`` member shadows ``str.split`` on these values. Compare
        against ``OrderStatus.split`` or its ``.value`` instead of calling a
        string ``split`` method on a member.
    """

    pending_shipment = "pending_shipment"
    split = "split"  # type: ignore[assignment]  # collides with str.split
