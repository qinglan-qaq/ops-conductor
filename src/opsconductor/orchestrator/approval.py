"""Risk-gated approval decisions and the task approval state machine."""

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from opsconductor.domain.enums import ApprovalStatus, RiskLevel, TaskStatus
from opsconductor.domain.models import Approval, TaskRun
from opsconductor.observability.audit import write_access_denied, write_audit
from opsconductor.observability.trace import TraceRecorder


class ApprovalActor(Protocol):
    """Authenticated caller allowed to decide approvals."""

    tenant_id: UUID
    user_id: UUID
    role: str


class ApprovalError(Exception):
    """Base class for approval failures that map to an HTTP status."""

    status_code = 409


class ApprovalNotFound(ApprovalError):
    status_code = 404


class ApprovalForbidden(ApprovalError):
    status_code = 403


class ApprovalConflict(ApprovalError):
    status_code = 409


DECIDER_ROLES = {"operator", "approver", "admin"}
L3_ROLES = {"approver", "admin"}


def _is_expired(approval: Approval, now: datetime) -> bool:
    return approval.expires_at <= now


class ApprovalService:
    """Decide pending approvals for one task, idempotently and tenant-scoped.

    The service owns the transaction: a successful decision commits before it
    returns. Repeated identical decisions return the current task without
    writing another audit row; a different decision on an approval that is
    already resolved raises ``ApprovalConflict``.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def decide(
        self,
        task_id: UUID,
        identity: ApprovalActor,
        approved: bool,
        comment: str | None = None,
        order_id: UUID | None = None,
    ) -> TaskRun:
        """Approve or reject pending approvals and advance the task status.

        With ``order_id`` only that order's approvals are in scope; otherwise
        every pending approval for the task is decided.
        """

        now = datetime.now(UTC)
        desired = (
            ApprovalStatus.approved.value
            if approved
            else ApprovalStatus.rejected.value
        )
        audit_action = "approval.approve" if approved else "approval.reject"

        try:
            task = await self._load_task(task_id, identity.tenant_id)
            if task is None:
                foreign = await self.session.scalar(
                    select(TaskRun).where(TaskRun.id == task_id)
                )
                if foreign is not None:
                    await write_access_denied(
                        self.session,
                        tenant_id=foreign.tenant_id,
                        actor_id=identity.user_id,
                        task_id=foreign.id,
                        entity_type="task",
                        entity_id=str(foreign.id),
                        reason="cross-tenant approval access",
                        evidence={
                            "caller_tenant_id": str(identity.tenant_id),
                            "endpoint": "approval.decide",
                        },
                    )
                    raise ApprovalForbidden(
                        f"task {task_id} belongs to another tenant"
                    )
                raise ApprovalNotFound(f"task {task_id} not found")

            approvals = await self._load_approvals(
                task_id, identity.tenant_id, order_id
            )
            if not approvals:
                if order_id is not None:
                    raise ApprovalNotFound(
                        f"no approval for order {order_id} on task {task_id}"
                    )
                raise ApprovalNotFound(f"task {task_id} has no approvals")

            if order_id is not None:
                result = await self._decide_targeted(
                    task,
                    approvals,
                    identity,
                    desired,
                    audit_action,
                    comment,
                    now,
                )
            else:
                result = await self._decide_pending(
                    task,
                    approvals,
                    identity,
                    desired,
                    audit_action,
                    comment,
                    now,
                )
            await self._record_decision_span(task, identity, approved, order_id)
            return result
        except BaseException:
            await self.session.rollback()
            raise

    async def _record_decision_span(
        self,
        task: TaskRun,
        identity: ApprovalActor,
        approved: bool,
        order_id: UUID | None,
    ) -> None:
        """Persist a production approval span after the decision commits."""

        async with TraceRecorder(self.session).start(
            "approval",
            task_id=task.id,
            tenant_id=identity.tenant_id,
            attributes={
                "source": "production",
                "approved": approved,
                "order_id": str(order_id) if order_id is not None else None,
                "role": identity.role,
            },
        ):
            pass
        await self.session.commit()

    async def _load_task(self, task_id: UUID, tenant_id: UUID) -> TaskRun | None:
        return await self.session.scalar(
            select(TaskRun)
            .where(TaskRun.id == task_id, TaskRun.tenant_id == tenant_id)
            .with_for_update()
        )

    async def _load_approvals(
        self, task_id: UUID, tenant_id: UUID, order_id: UUID | None
    ) -> list[Approval]:
        statement = (
            select(Approval)
            .where(
                Approval.task_id == task_id,
                Approval.tenant_id == tenant_id,
            )
            .order_by(Approval.id)
            .with_for_update()
        )
        if order_id is not None:
            statement = statement.where(Approval.order_id == order_id)
        return list((await self.session.scalars(statement)).all())

    async def _decide_targeted(
        self,
        task: TaskRun,
        approvals: list[Approval],
        identity: ApprovalActor,
        desired: str,
        audit_action: str,
        comment: str | None,
        now: datetime,
    ) -> TaskRun:
        pending = [
            approval
            for approval in approvals
            if approval.status == ApprovalStatus.pending.value
        ]
        expired = [approval for approval in pending if _is_expired(approval, now)]
        active = [approval for approval in pending if not _is_expired(approval, now)]

        if expired:
            self._mark_expired(expired, now)
            await self.session.commit()
            raise ApprovalConflict(
                f"approval for order {expired[0].order_id} has expired"
            )

        conflicting = [
            approval
            for approval in approvals
            if approval.status != ApprovalStatus.pending.value
            and approval.status != desired
        ]
        if conflicting:
            raise ApprovalConflict(
                f"approval for order {conflicting[0].order_id} was already "
                f"{conflicting[0].status}"
            )

        if not active:
            return task

        self._check_roles(active, identity)
        for approval in active:
            await self._record(
                approval, identity, desired, audit_action, comment, now
            )
        await self._finish(task)
        await self.session.commit()
        return task

    async def _decide_pending(
        self,
        task: TaskRun,
        approvals: list[Approval],
        identity: ApprovalActor,
        desired: str,
        audit_action: str,
        comment: str | None,
        now: datetime,
    ) -> TaskRun:
        pending = [
            approval
            for approval in approvals
            if approval.status == ApprovalStatus.pending.value
        ]
        expired = [approval for approval in pending if _is_expired(approval, now)]
        active = [approval for approval in pending if not _is_expired(approval, now)]

        conflicting = [
            approval
            for approval in approvals
            if approval.status in {
                ApprovalStatus.approved.value,
                ApprovalStatus.rejected.value,
            }
            and approval.status != desired
        ]
        if conflicting:
            raise ApprovalConflict(
                f"task {task.id} already has a different approval decision"
            )

        self._check_roles(active, identity)
        if not active and not expired:
            return task

        self._mark_expired(expired, now)
        for approval in active:
            await self._record(
                approval, identity, desired, audit_action, comment, now
            )
        await self._finish(task)
        await self.session.commit()
        return task

    def _check_roles(
        self, approvals: list[Approval], identity: ApprovalActor
    ) -> None:
        if identity.role not in DECIDER_ROLES:
            raise ApprovalForbidden(
                "only operators, approvers, or admins may decide approvals"
            )
        if identity.role not in L3_ROLES and any(
            approval.risk_level == RiskLevel.L3.value for approval in approvals
        ):
            raise ApprovalForbidden("L3 approvals require the approver or admin role")

    def _mark_expired(self, approvals: list[Approval], now: datetime) -> None:
        for approval in approvals:
            approval.status = ApprovalStatus.expired.value
            approval.decided_at = now

    async def _record(
        self,
        approval: Approval,
        identity: ApprovalActor,
        desired: str,
        audit_action: str,
        comment: str | None,
        now: datetime,
    ) -> None:
        before = {"status": approval.status}
        approval.status = desired
        approval.approver_id = identity.user_id
        approval.decided_at = now
        approval.comment = comment
        await write_audit(
            self.session,
            tenant_id=approval.tenant_id,
            task_id=approval.task_id,
            actor_id=identity.user_id,
            action=audit_action,
            entity_type="approval",
            entity_id=str(approval.id),
            before=before,
            after={
                "status": desired,
                "approver_id": str(identity.user_id),
                "comment": comment,
                "order_id": (
                    str(approval.order_id) if approval.order_id is not None else None
                ),
                "risk_level": approval.risk_level,
            },
            evidence={"task_id": str(approval.task_id)},
        )

    async def _finish(self, task: TaskRun) -> None:
        """Move an awaiting task to running once no pending or expired rows remain."""

        if task.status != TaskStatus.awaiting_approval.value:
            return
        unresolved = await self.session.scalar(
            select(func.count())
            .select_from(Approval)
            .where(
                Approval.task_id == task.id,
                Approval.tenant_id == task.tenant_id,
                Approval.status.in_(
                    [
                        ApprovalStatus.pending.value,
                        ApprovalStatus.expired.value,
                    ]
                ),
            )
        )
        if not unresolved:
            task.status = TaskStatus.running.value
