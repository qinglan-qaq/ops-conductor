"""Tests for task submission, lookup, and idempotency."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from opsconductor.api.main import app
from opsconductor.config import get_settings
from opsconductor.db import SessionLocal
from opsconductor.domain.models import Approval, AuditLog, IdempotencyKey, TaskRun
from opsconductor.domain.seed import TENANT_A

TASK_URL = "/api/v1/tasks"
BODY = {
    "instruction": "处理今天华东仓超时未发货的订单",
    "warehouse": "east",
    "cutoff": "2026-11-04T00:00:00Z",
}
WRITE_ACTIONS = {"split_order", "change_address"}


def _headers(
    *, key: str = "task-1", api_key: str = "dev-operator-a"
) -> dict[str, str]:
    return {"X-API-Key": api_key, "Idempotency-Key": key}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_create_task_is_idempotent(seeded_db):
    async with _client() as client:
        headers = {"X-API-Key": "dev-operator-a", "Idempotency-Key": "task-1"}
        body = {
            "instruction": "处理今天华东仓超时未发货的订单",
            "warehouse": "east",
            "cutoff": "2026-11-04T00:00:00Z",
        }
        first = await client.post(TASK_URL, json=body, headers=headers)
        second = await client.post(TASK_URL, json=body, headers=headers)

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]
        assert first.json()["status"] == "awaiting_approval"
        assert first.json()["plan"] == second.json()["plan"]


@pytest.mark.asyncio
async def test_same_key_with_different_body_returns_conflict(seeded_db):
    async with _client() as client:
        first = await client.post(TASK_URL, json=BODY, headers=_headers(key="conflict-1"))
        changed = {**BODY, "warehouse": "south"}
        second = await client.post(
            TASK_URL, json=changed, headers=_headers(key="conflict-1")
        )

        assert first.status_code == 200
        assert second.status_code == 409
        async with SessionLocal() as session:
            tasks = (await session.scalars(select(TaskRun))).all()
            assert len(tasks) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        {"Idempotency-Key": "missing-key"},
        {"X-API-Key": "not-a-real-key", "Idempotency-Key": "invalid-key"},
    ],
)
async def test_create_task_requires_valid_api_key(seeded_db, headers):
    async with _client() as client:
        response = await client.post(TASK_URL, json=BODY, headers=headers)

        assert response.status_code == 401
        async with SessionLocal() as session:
            assert (await session.scalars(select(TaskRun))).all() == []


@pytest.mark.asyncio
async def test_get_task_is_tenant_scoped(seeded_db):
    async with _client() as client:
        created = await client.post(TASK_URL, json=BODY, headers=_headers(key="get-1"))
        assert created.status_code == 200
        task_id = created.json()["id"]

        same_tenant = await client.get(
            f"{TASK_URL}/{task_id}", headers={"X-API-Key": "dev-operator-a"}
        )
        foreign_tenant = await client.get(
            f"{TASK_URL}/{task_id}", headers={"X-API-Key": "dev-operator-b"}
        )
        unknown = await client.get(
            f"{TASK_URL}/{uuid4()}", headers={"X-API-Key": "dev-operator-a"}
        )

        assert same_tenant.status_code == 200
        assert same_tenant.json()["id"] == task_id
        assert same_tenant.json()["instruction"] == BODY["instruction"]
        assert same_tenant.json()["plan"] is not None
        assert foreign_tenant.status_code == 403
        assert "O1001" not in foreign_tenant.text
        assert unknown.status_code == 404

    async with SessionLocal() as session:
        denial = await session.scalar(
            select(AuditLog).where(
                AuditLog.tenant_id == TENANT_A,
                AuditLog.task_id == UUID(task_id),
                AuditLog.action == "security.access_denied",
                AuditLog.entity_type == "task",
            )
        )
    assert denial is not None
    assert denial.evidence is not None
    assert denial.evidence["status_code"] == 403


@pytest.mark.asyncio
async def test_created_task_has_pending_l2_approvals(seeded_db):
    async with _client() as client:
        created = await client.post(
            TASK_URL, json=BODY, headers=_headers(key="approval-1")
        )
        assert created.status_code == 200
        task_id = UUID(created.json()["id"])

    async with SessionLocal() as session:
        task = await session.scalar(
            select(TaskRun).where(
                TaskRun.id == task_id,
                TaskRun.tenant_id == TENANT_A,
            )
        )
        assert task is not None
        assert task.status == "awaiting_approval"
        assert task.plan is not None

        write_nodes = [
            node
            for node in task.plan["nodes"]
            if node["action"] in WRITE_ACTIONS
        ]
        assert write_nodes
        assert all(node["requires_approval"] for node in write_nodes)
        assert all(node["risk"] == "L2" for node in write_nodes)
        assert task.plan["requires_l3"] is False

        approvals = list(
            (
                await session.scalars(
                    select(Approval).where(
                        Approval.tenant_id == TENANT_A,
                        Approval.task_id == task_id,
                    )
                )
            ).all()
        )
        assert approvals
        assert {approval.action for approval in approvals} == {
            node["action"] for node in write_nodes
        }
        assert len(approvals) == len(write_nodes)
        now = datetime.now(UTC)
        for approval in approvals:
            assert approval.status == "pending"
            assert approval.risk_level == "L2"
            assert approval.expires_at > now
            assert approval.tenant_id == TENANT_A
            if approval.order_id is not None:
                assert approval.order_id

        record = await session.scalar(
            select(IdempotencyKey).where(
                IdempotencyKey.tenant_id == TENANT_A,
                IdempotencyKey.scope == "task.create",
                IdempotencyKey.key == "approval-1",
            )
        )
        assert record is not None
        assert record.response is not None
        assert record.response["id"] == str(task_id)

        split_nodes = [
            node for node in task.plan["nodes"] if node["action"] == "split_order"
        ]
        assert len(split_nodes) >= 1


@pytest.mark.asyncio
async def test_l3_threshold_marks_every_split_node(seeded_db, monkeypatch):
    monkeypatch.setattr(get_settings(), "l3_batch_threshold", 3)

    async with _client() as client:
        created = await client.post(TASK_URL, json=BODY, headers=_headers(key="l3-1"))
        assert created.status_code == 200

    payload = created.json()
    nodes = payload["plan"]["nodes"]
    split_nodes = [node for node in nodes if node["action"] == "split_order"]
    assert len(split_nodes) == 3
    assert all(node["risk"] == "L3" for node in split_nodes)
    assert all(node["requires_approval"] is True for node in split_nodes)
    assert payload["plan"]["requires_l3"] is True

    change_nodes = [node for node in nodes if node["action"] == "change_address"]
    assert change_nodes
    assert all(
        node["risk"] == "L2" and node["requires_approval"] is True
        for node in change_nodes
    )

    block_nodes = [node for node in nodes if node["action"] == "block_order"]
    assert block_nodes
    assert all(
        node["risk"] == "L0" and node["requires_approval"] is False
        for node in block_nodes
    )

    async with SessionLocal() as session:
        approvals = list(
            (
                await session.scalars(
                    select(Approval).where(Approval.task_id == UUID(payload["id"]))
                )
            ).all()
        )

    split_approvals = [
        approval for approval in approvals if approval.action == "split_order"
    ]
    change_approvals = [
        approval for approval in approvals if approval.action == "change_address"
    ]
    assert len(split_approvals) == 3
    assert all(approval.risk_level == "L3" for approval in split_approvals)
    assert len(change_approvals) == 1
    assert change_approvals[0].risk_level == "L2"
    assert len(approvals) == 4


@pytest.mark.asyncio
async def test_l3_threshold_is_inclusive_at_the_boundary(seeded_db, monkeypatch):
    monkeypatch.setattr(get_settings(), "l3_batch_threshold", 4)

    async with _client() as client:
        created = await client.post(TASK_URL, json=BODY, headers=_headers(key="l3-2"))
        assert created.status_code == 200

    payload = created.json()
    split_nodes = [
        node for node in payload["plan"]["nodes"] if node["action"] == "split_order"
    ]
    assert len(split_nodes) == 3
    assert all(node["risk"] == "L2" for node in split_nodes)
    assert payload["plan"]["requires_l3"] is False

    async with SessionLocal() as session:
        approvals = list(
            (
                await session.scalars(
                    select(Approval).where(Approval.task_id == UUID(payload["id"]))
                )
            ).all()
        )
    assert {approval.risk_level for approval in approvals} == {"L2"}


@pytest.mark.asyncio
async def test_invalid_cutoff_returns_422(seeded_db):
    async with _client() as client:
        response = await client.post(
            TASK_URL,
            json={**BODY, "cutoff": "yesterday"},
            headers=_headers(key="bad-cutoff"),
        )
        assert response.status_code == 422

    async with SessionLocal() as session:
        assert (await session.scalars(select(TaskRun))).all() == []


@pytest.mark.asyncio
async def test_plan_without_write_nodes_stays_planned(seeded_db):
    async with _client() as client:
        response = await client.post(
            TASK_URL,
            json={**BODY, "warehouse": "south"},
            headers=_headers(key="no-orders"),
        )
        assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "planned"
    assert payload["plan"]["nodes"] == []

    async with SessionLocal() as session:
        task = await session.scalar(
            select(TaskRun).where(TaskRun.id == UUID(payload["id"]))
        )
        assert task is not None
        assert task.status == "planned"
        approvals = (
            await session.scalars(
                select(Approval).where(Approval.task_id == task.id)
            )
        ).all()
        assert approvals == []
