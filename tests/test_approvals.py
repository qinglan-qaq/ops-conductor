"""Tests for risk grading and approval decisions."""

from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_DNS, UUID, uuid4, uuid5

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from opsconductor.api.main import app
from opsconductor.config import get_settings
from opsconductor.db import SessionLocal
from opsconductor.domain.models import Approval, AuditLog, TaskRun

TASK_URL = "/api/v1/tasks"
BODY = {
    "instruction": "处理今天华东仓超时未发货的订单",
    "warehouse": "east",
    "cutoff": "2026-11-04T00:00:00Z",
}
OPERATOR_A = uuid5(NAMESPACE_DNS, "opsconductor.user-operator-a")
APPROVER_A = uuid5(NAMESPACE_DNS, "opsconductor.user-approver-a")


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _auth(api_key: str = "dev-operator-a") -> dict[str, str]:
    return {"X-API-Key": api_key}


async def _create_task(client: AsyncClient, key: str) -> UUID:
    response = await client.post(
        TASK_URL,
        json=BODY,
        headers={**_auth(), "Idempotency-Key": key},
    )
    assert response.status_code == 200
    return UUID(response.json()["id"])


async def _approvals(task_id: UUID) -> list[Approval]:
    async with SessionLocal() as session:
        return list(
            (
                await session.scalars(
                    select(Approval)
                    .where(Approval.task_id == task_id)
                    .order_by(Approval.action, Approval.id)
                )
            ).all()
        )


async def _task(task_id: UUID) -> TaskRun:
    async with SessionLocal() as session:
        task = await session.scalar(select(TaskRun).where(TaskRun.id == task_id))
    assert task is not None
    return task


async def _audit_count(task_id: UUID, action: str | None = None) -> int:
    statement = (
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.task_id == task_id)
    )
    if action is not None:
        statement = statement.where(AuditLog.action == action)
    async with SessionLocal() as session:
        return int(await session.scalar(statement) or 0)


async def _expire(
    task_id: UUID, *, only_order_id: UUID | None = None
) -> None:
    async with SessionLocal() as session:
        statement = select(Approval).where(Approval.task_id == task_id)
        if only_order_id is not None:
            statement = statement.where(Approval.order_id == only_order_id)
        approvals = (await session.scalars(statement)).all()
        assert approvals
        for approval in approvals:
            approval.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()


@pytest.mark.asyncio
async def test_l2_approval_passes_and_task_becomes_running(seeded_db):
    async with _client() as client:
        task_id = await _create_task(client, "approve-l2")
        response = await client.post(
            f"{TASK_URL}/{task_id}/approve",
            headers=_auth(),
            json={"comment": "looks good"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    approvals = await _approvals(task_id)
    assert len(approvals) == 4
    assert {approval.status for approval in approvals} == {"approved"}
    assert {approval.approver_id for approval in approvals} == {OPERATOR_A}
    assert {approval.comment for approval in approvals} == {"looks good"}
    assert all(approval.decided_at is not None for approval in approvals)
    assert await _audit_count(task_id, "approval.approve") == 4
    assert (await _task(task_id)).status == "running"


@pytest.mark.asyncio
async def test_l2_rejection_is_recorded_and_task_becomes_running(seeded_db):
    async with _client() as client:
        task_id = await _create_task(client, "reject-l2")
        response = await client.post(
            f"{TASK_URL}/{task_id}/reject",
            headers=_auth(),
            json={"comment": "do not ship"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    approvals = await _approvals(task_id)
    assert {approval.status for approval in approvals} == {"rejected"}
    assert {approval.approver_id for approval in approvals} == {OPERATOR_A}
    assert {approval.comment for approval in approvals} == {"do not ship"}
    assert await _audit_count(task_id, "approval.reject") == 4
    task = await _task(task_id)
    assert task.status == "running"


@pytest.mark.asyncio
async def test_batch_split_threshold_upgrades_split_approvals_to_l3(
    seeded_db, monkeypatch
):
    monkeypatch.setattr(get_settings(), "l3_batch_threshold", 3)

    async with _client() as client:
        task_id = await _create_task(client, "threshold-l3")

    approvals = await _approvals(task_id)
    split = [approval for approval in approvals if approval.action == "split_order"]
    change = [approval for approval in approvals if approval.action == "change_address"]
    assert len(split) == 3
    assert {approval.risk_level for approval in split} == {"L3"}
    assert len(change) == 1
    assert change[0].risk_level == "L2"

    task = await _task(task_id)
    assert task.plan is not None
    assert task.plan["requires_l3"] is True
    split_nodes = [
        node for node in task.plan["nodes"] if node["action"] == "split_order"
    ]
    assert {node["risk"] for node in split_nodes} == {"L3"}


@pytest.mark.asyncio
async def test_l3_requires_approver_role_while_l2_accepts_operator(
    seeded_db, monkeypatch
):
    monkeypatch.setattr(get_settings(), "l3_batch_threshold", 3)

    async with _client() as client:
        task_id = await _create_task(client, "roles-l3")
        approvals = await _approvals(task_id)
        change = next(
            approval for approval in approvals if approval.action == "change_address"
        )

        forbidden = await client.post(
            f"{TASK_URL}/{task_id}/approve", headers=_auth()
        )
        assert forbidden.status_code == 403

        l2 = await client.post(
            f"{TASK_URL}/{task_id}/approve",
            headers=_auth(),
            json={"order_id": str(change.order_id)},
        )
        assert l2.status_code == 200
        assert l2.json()["status"] == "awaiting_approval"

        still_forbidden = await client.post(
            f"{TASK_URL}/{task_id}/approve", headers=_auth()
        )
        assert still_forbidden.status_code == 403
        assert await _audit_count(task_id) == 1

        approved = await client.post(
            f"{TASK_URL}/{task_id}/approve", headers=_auth("dev-approver-a")
        )

    assert approved.status_code == 200
    assert approved.json()["status"] == "running"

    approvals = await _approvals(task_id)
    assert {approval.status for approval in approvals} == {"approved"}
    change_row = next(a for a in approvals if a.action == "change_address")
    assert change_row.approver_id == OPERATOR_A
    split_rows = [a for a in approvals if a.action == "split_order"]
    assert {row.approver_id for row in split_rows} == {APPROVER_A}
    assert await _audit_count(task_id, "approval.approve") == 4
    assert await _audit_count(task_id) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint", "expected_status", "audit_action"),
    [
        ("approve", "approved", "approval.approve"),
        ("reject", "rejected", "approval.reject"),
    ],
)
async def test_repeated_decision_is_idempotent_without_duplicate_audit(
    seeded_db, endpoint, expected_status, audit_action
):
    async with _client() as client:
        task_id = await _create_task(client, f"repeat-{endpoint}")
        first = await client.post(
            f"{TASK_URL}/{task_id}/{endpoint}", headers=_auth()
        )
        second = await client.post(
            f"{TASK_URL}/{task_id}/{endpoint}", headers=_auth()
        )
        opposite = "reject" if endpoint == "approve" else "approve"
        conflict = await client.post(
            f"{TASK_URL}/{task_id}/{opposite}", headers=_auth()
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "running"
    assert second.json()["status"] == "running"
    assert conflict.status_code == 409
    approvals = await _approvals(task_id)
    assert {approval.status for approval in approvals} == {expected_status}
    assert await _audit_count(task_id, audit_action) == 4
    assert await _audit_count(task_id) == 4


@pytest.mark.asyncio
async def test_conflicting_decision_on_decided_approval_returns_409(seeded_db):
    async with _client() as client:
        task_id = await _create_task(client, "conflict-order")
        approval = (await _approvals(task_id))[0]
        assert approval.order_id is not None

        approved = await client.post(
            f"{TASK_URL}/{task_id}/approve",
            headers=_auth(),
            json={"order_id": str(approval.order_id)},
        )
        rejected = await client.post(
            f"{TASK_URL}/{task_id}/reject",
            headers=_auth(),
            json={"order_id": str(approval.order_id)},
        )
        repeated = await client.post(
            f"{TASK_URL}/{task_id}/approve",
            headers=_auth(),
            json={"order_id": str(approval.order_id)},
        )

    assert approved.status_code == 200
    assert approved.json()["status"] == "awaiting_approval"
    assert rejected.status_code == 409
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "awaiting_approval"

    approvals = await _approvals(task_id)
    target = next(row for row in approvals if row.id == approval.id)
    assert target.status == "approved"
    assert target.approver_id == OPERATOR_A
    assert sum(row.status == "pending" for row in approvals) == 3
    assert await _audit_count(task_id) == 1


@pytest.mark.asyncio
async def test_expired_approvals_become_expired_and_task_waits(seeded_db):
    async with _client() as client:
        task_id = await _create_task(client, "expired-bulk")
        await _expire(task_id)
        response = await client.post(
            f"{TASK_URL}/{task_id}/approve", headers=_auth()
        )

    assert response.status_code == 200
    assert response.json()["status"] == "awaiting_approval"
    approvals = await _approvals(task_id)
    assert {approval.status for approval in approvals} == {"expired"}
    assert await _audit_count(task_id) == 0
    assert (await _task(task_id)).status == "awaiting_approval"


@pytest.mark.asyncio
async def test_expired_approval_targeted_by_order_returns_409(seeded_db):
    async with _client() as client:
        task_id = await _create_task(client, "expired-order")
        approval = (await _approvals(task_id))[0]
        assert approval.order_id is not None
        await _expire(task_id, only_order_id=approval.order_id)
        response = await client.post(
            f"{TASK_URL}/{task_id}/approve",
            headers=_auth(),
            json={"order_id": str(approval.order_id)},
        )

    assert response.status_code == 409
    assert "expired" in response.json()["detail"]
    approvals = await _approvals(task_id)
    target = next(row for row in approvals if row.id == approval.id)
    assert target.status == "expired"
    assert sum(row.status == "pending" for row in approvals) == 3
    assert (await _task(task_id)).status == "awaiting_approval"
    assert await _audit_count(task_id) == 0


@pytest.mark.asyncio
async def test_cannot_decide_another_tenants_approval(seeded_db):
    async with _client() as client:
        task_id = await _create_task(client, "tenant-isolation")
        approval = (await _approvals(task_id))[0]
        assert approval.order_id is not None
        bulk = await client.post(
            f"{TASK_URL}/{task_id}/approve", headers=_auth("dev-approver-b")
        )
        targeted = await client.post(
            f"{TASK_URL}/{task_id}/approve",
            headers=_auth("dev-approver-b"),
            json={"order_id": str(approval.order_id)},
        )

    assert bulk.status_code == 403
    assert targeted.status_code == 403
    approvals = await _approvals(task_id)
    assert {row.status for row in approvals} == {"pending"}
    assert (await _task(task_id)).status == "awaiting_approval"
    assert await _audit_count(task_id, "security.access_denied") == 2
    assert await _audit_count(task_id) == 2


@pytest.mark.asyncio
async def test_unknown_task_and_order_return_not_found(seeded_db):
    async with _client() as client:
        task_id = await _create_task(client, "not-found")
        unknown_task = await client.post(
            f"{TASK_URL}/{uuid4()}/approve", headers=_auth()
        )
        unknown_order = await client.post(
            f"{TASK_URL}/{task_id}/approve",
            headers=_auth(),
            json={"order_id": str(uuid4())},
        )

    assert unknown_task.status_code == 404
    assert unknown_order.status_code == 404
    assert await _audit_count(task_id) == 0
