"""风险门控的审批决策与任务审批状态机。

审批以 ``pending`` 开始，以 ``approved``、``rejected`` 或 ``expired`` 结束。
:class:`ApprovalService` 对任务的待处理行应用决策，执行角色门控，并在没有未解决
审批时把任务从 ``awaiting_approval`` 推进到 ``running``。

Invariants:

- 所有查询都按租户限定。属于其他租户的任务会以 :class:`ApprovalForbidden` 拒绝，
  并留下一条访问拒绝审计行。
- ``operator``、``approver``、``admin`` 可以裁决普通审批；L3 审批额外要求
  ``approver`` 或 ``admin``。
- 决策幂等：重复相同决策返回当前任务且不再写审计行；相互冲突的决策抛出
  :class:`ApprovalConflict`。
- 到期时间 ``expires_at`` 已到或已过的待处理审批会被标记为 ``expired``，之后
  不能再被批准或拒绝。
- 服务拥有事务：成功的决策在返回前提交。
"""

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
    """有权裁决审批的已认证调用方。

    只读属性让冻结的身份对象（``Identity``）无需可变属性即可满足该协议。

    Attributes:
        tenant_id: 决策所属的租户。
        user_id: 记录为审批人的用户。
        role: 参与决策门控的角色。
    """

    @property
    def tenant_id(self) -> UUID: ...

    @property
    def user_id(self) -> UUID: ...

    @property
    def role(self) -> str: ...


class ApprovalError(Exception):
    """审批失败的基类，映射到 HTTP 状态码。"""

    status_code = 409


class ApprovalNotFound(ApprovalError):
    """任务或其审批无法找到时抛出（HTTP 404）。"""

    status_code = 404


class ApprovalForbidden(ApprovalError):
    """租户或角色无权裁决该审批时抛出（HTTP 403）。"""

    status_code = 403


class ApprovalConflict(ApprovalError):
    """审批已过期或已按不同结果裁决时抛出。"""

    status_code = 409


DECIDER_ROLES = {"operator", "approver", "admin"}
L3_ROLES = {"approver", "admin"}


def _is_expired(approval: Approval, now: datetime) -> bool:
    """返回审批的到期时间是否早于或等于 ``now``。"""

    return approval.expires_at <= now


class ApprovalService:
    """幂等且按租户限定地为单个任务裁决待处理审批。

    服务拥有事务：成功的决策在返回前提交。重复相同决策返回当前任务且不再写审计
    行；对已解决审批给出不同决策会抛出 ``ApprovalConflict``。

    Attributes:
        session: 用于锁定并更新任务与审批的会话。
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
        """批准或拒绝待处理审批，并推进任务状态。

        带 ``order_id`` 时只有该订单的审批在作用域内；否则任务的全部待处理审批
        都会被裁决。已过期的待处理行会先被标记为 ``expired``，随后请求以
        :class:`ApprovalConflict` 失败。已处于请求状态的行视为幂等重复，原样
        返回。

        Args:
            task_id: 需要裁决审批的任务。
            identity: 已认证调用方；其租户限定查询，其角色门控 L3 决策。
            approved: ``True`` 表示批准，``False`` 表示拒绝。
            comment: 可选备注，存入每条已裁决审批与审计 ``after`` 载荷。
            order_id: 只裁决单个订单的审批。

        Returns:
            已锁定的任务；当不再有 pending 或 expired 审批时推进为
            ``running``。

        Raises:
            ApprovalNotFound: 任务或目标订单的审批不存在。
            ApprovalForbidden: 任务属于其他租户，或调用方角色无权裁决该审批。
            ApprovalConflict: 审批已过期，或已记录不同决策。

        Note:
            过期审批会在抛出 :class:`ApprovalConflict` 之前提交，因此该过期状态
            能在失败请求的回滚中保留。
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
        """在决策提交后持久化 ``source="production"`` 的审批 span。"""

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
        """当不再存在 pending 或 expired 行时，把待审批任务推进为 running。"""

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
