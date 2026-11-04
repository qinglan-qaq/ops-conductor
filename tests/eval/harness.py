"""Test harness for the 28 MVP golden tasks.

The harness drives the production HTTP API (task creation), the production
approval service, and the production LangGraph executor. Only the MCP transport
is replaced: ``GoldenToolClient`` is a fault-aware in-process gateway that calls
the real write services and records trace spans, just as the MCP gateway would.
"""

import asyncio
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid5

import pytest
from cases import (
    CASE_BY_ID,
    CATEGORY_APPROVAL,
    CATEGORY_INVENTORY,
    GOLDEN_CASES,
    SKU_IDS,
    ApprovalDirective,
    GoldenCase,
    ToolFault,
    build_plan,
    order_id,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from opsconductor.api.deps import Identity
from opsconductor.api.main import app
from opsconductor.api.routes import tasks as tasks_routes
from opsconductor.config import get_settings
from opsconductor.db import SessionLocal
from opsconductor.domain import repositories
from opsconductor.domain.enums import ApprovalStatus
from opsconductor.domain.models import (
    Approval,
    AuditLog,
    IdempotencyKey,
    Inventory,
    SalesOrder,
    Shipment,
    ShipmentLine,
    TaskRun,
    TaskStep,
    TraceSpan,
)
from opsconductor.domain.seed import TENANT_A, TENANT_B, WAREHOUSE_EAST
from opsconductor.observability.audit import write_audit
from opsconductor.observability.trace import TraceRecorder
from opsconductor.orchestrator.approval import ApprovalService
from opsconductor.orchestrator.executor import ExecutionResult, TaskExecutor
from opsconductor.orchestrator.verifier import VerificationResult, Verifier
from opsconductor.tools import faults
from opsconductor.tools.service import ErpToolService

TASK_URL = "/api/v1/tasks"
CASE_SKU_IDS = SKU_IDS
DEFAULT_CUTOFF = "2026-11-04T00:00:00Z"
COMPENSATION_TOOLS = {"order_revert_split", "order_revert_address"}
WRITE_TOOLS = {"order_split", "order_change_address"}
ACTION_FOR_TOOL = {
    "order_split": "split_order",
    "order_change_address": "change_address",
}
BUSINESS_WRITES = {"order_split", "order_change_address"}
TASK_KEYS = {"tenant-a": TENANT_A, "tenant-b": TENANT_B}
ORDER_NUMBERS = ("O1001", "O1002", "O1003", "O1004", "O1005", "O1006")

OPERATOR_A = Identity(
    TENANT_A, uuid5(NAMESPACE_DNS, "opsconductor.user-operator-a"), "operator"
)
APPROVER_A = Identity(
    TENANT_A, uuid5(NAMESPACE_DNS, "opsconductor.user-approver-a"), "approver"
)
OPERATOR_B = Identity(
    TENANT_B, uuid5(NAMESPACE_DNS, "opsconductor.user-operator-b"), "operator"
)

ORDER_IDS = {order_no: order_id(order_no) for order_no in ORDER_NUMBERS}
ORDER_NO_BY_ID = {value: key for key, value in ORDER_IDS.items()}
SKU_CODE_BY_ID = {value: key for key, value in CASE_SKU_IDS.items()}


def _as_uuid(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (AttributeError, TypeError, ValueError):
        return None


def _order_no(value: Any) -> str | None:
    parsed = _as_uuid(value)
    return ORDER_NO_BY_ID.get(parsed) if parsed is not None else None


def _task_key(case: GoldenCase, suffix: str = "") -> str:
    return f"golden-{case.id.lower()}-create{suffix}"


@dataclass
class ToolCall:
    """One recorded gateway invocation."""

    name: str
    arguments: dict[str, Any]
    phase: str
    ok: bool
    result: dict[str, Any] | None = None
    error: BaseException | None = None

    @property
    def order_no(self) -> str | None:
        return _order_no(self.arguments.get("order_id"))

    @property
    def dry_run(self) -> bool:
        return bool(self.arguments.get("dry_run"))


class ToolAccessDenied(RuntimeError):
    """Gateway denial with an HTTP-style status code and stable error code."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 403,
        code: str = "PERMISSION_DENIED",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class TraceSink:
    """Write committed trace spans around harness phases."""

    async def record(
        self,
        name: str,
        task_id: UUID | None,
        tenant_id: UUID,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        async with SessionLocal() as session:
            recorder = TraceRecorder(session)
            async with recorder.start(
                name,
                task_id=task_id,
                tenant_id=tenant_id,
                attributes=attributes or {},
            ):
                pass
            await session.commit()


@dataclass
class _ActiveFault:
    spec: ToolFault
    remaining: int


class GoldenToolClient:
    """Fault-aware in-process MCP gateway backed by the real write services."""

    def __init__(
        self,
        *,
        trace: TraceSink,
        fault_policy: Iterable[ToolFault] = (),
        enforce_tenant_guard: bool = False,
    ) -> None:
        self.trace = trace
        self.enforce_tenant_guard = enforce_tenant_guard
        self.calls: list[ToolCall] = []
        self.errors: list[BaseException] = []
        self._faults = [
            _ActiveFault(spec=fault, remaining=fault.times)
            for fault in fault_policy
        ]

    def clear_faults(self) -> None:
        self._faults.clear()

    @property
    def call_log(self) -> list[ToolCall]:
        return self.calls

    @staticmethod
    def _phase(name: str, arguments: dict[str, Any]) -> str:
        if arguments.get("dry_run") is True:
            return "dry_run"
        if name in COMPENSATION_TOOLS:
            return "compensation"
        return "execute"

    def _match_fault(
        self, name: str, arguments: dict[str, Any], phase: str
    ) -> _ActiveFault | None:
        for active in self._faults:
            spec = active.spec
            if active.remaining <= 0 or spec.tool != name:
                continue
            if spec.phase is not None and spec.phase != phase:
                continue
            if spec.order_no is not None and spec.order_no != _order_no(
                arguments.get("order_id")
            ):
                continue
            active.remaining -= 1
            return active
        return None

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        phase = self._phase(name, arguments)

        # The same contextvar hook used by the production ErpToolClient.
        faults.check(name)

        active = self._match_fault(name, arguments, phase)
        if active is not None and active.spec.mode in {"timeout", "upstream"}:
            error: BaseException
            if active.spec.mode == "timeout":
                error = TimeoutError(f"injected {name} timeout")
            else:
                error = RuntimeError(f"injected {name} upstream error")
            await self._record(name, arguments, phase, None, error)
            raise error

        try:
            await self._authorize(name, arguments)
        except ToolAccessDenied as exc:
            await self._record(name, arguments, phase, None, exc)
            raise

        try:
            result = await self._invoke(name, arguments)
        except BaseException as exc:  # noqa: BLE001 - tool errors are the point
            await self._record(name, arguments, phase, None, exc)
            raise

        if active is not None and active.spec.mode == "timeout_after_commit":
            error = TimeoutError(f"injected {name} timeout after commit")
            await self._record(name, arguments, phase, result, error)
            raise error
        if active is not None and active.spec.mode == "corrupt_inventory":
            await self._corrupt_inventory()

        await self._record(name, arguments, phase, result, None)
        return result

    async def _authorize(
        self, name: str, arguments: dict[str, Any]
    ) -> None:
        if name not in WRITE_TOOLS | COMPENSATION_TOOLS:
            return
        tenant_id = _as_uuid(arguments.get("tenant_id"))
        if tenant_id is None:
            raise ToolAccessDenied(
                "tenant_id is required", status_code=401, code="PERMISSION_DENIED"
            )

        order_id_value = _as_uuid(arguments.get("order_id"))
        if self.enforce_tenant_guard and order_id_value is not None:
            async with SessionLocal() as session:
                order = await session.get(SalesOrder, order_id_value)
            if order is None:
                await self._audit_denial(
                    name, arguments, "order not found", "NOT_FOUND"
                )
                raise ToolAccessDenied(
                    "order not found for this tenant",
                    status_code=404,
                    code="NOT_FOUND",
                )
            if order.tenant_id != tenant_id:
                await self._audit_denial(
                    name, arguments, "cross-tenant access", "PERMISSION_DENIED"
                )
                raise ToolAccessDenied(
                    "order belongs to another tenant",
                    status_code=403,
                    code="PERMISSION_DENIED",
                )

        task_id = _as_uuid(arguments.get("task_id"))
        if name in WRITE_TOOLS and task_id is not None:
            action = ACTION_FOR_TOOL[name]
            async with SessionLocal() as session:
                approved = await session.scalar(
                    select(Approval.id).where(
                        Approval.tenant_id == tenant_id,
                        Approval.task_id == task_id,
                        Approval.order_id == order_id_value,
                        Approval.action == action,
                        Approval.status == ApprovalStatus.approved.value,
                    )
                )
            if approved is None:
                await self._audit_denial(
                    name,
                    arguments,
                    "no approved approval for tool call",
                    "PERMISSION_DENIED",
                )
                raise ToolAccessDenied(
                    f"{name} requires an approved approval",
                    status_code=403,
                    code="PERMISSION_DENIED",
                )

    async def _audit_denial(
        self,
        name: str,
        arguments: dict[str, Any],
        reason: str,
        code: str,
    ) -> None:
        tenant_id = _as_uuid(arguments.get("tenant_id"))
        if tenant_id is None:
            return
        task_id = _as_uuid(arguments.get("task_id"))
        actor_id = _as_uuid(arguments.get("actor_id"))
        async with SessionLocal() as session:
            await write_audit(
                session,
                tenant_id=tenant_id,
                task_id=task_id,
                actor_id=actor_id,
                action="tool.denied",
                entity_type="tool",
                entity_id=name,
                before=None,
                after={
                    "tool": name,
                    "order_id": str(arguments.get("order_id") or ""),
                    "reason": reason,
                },
                evidence={"code": code, "denied": True},
            )
            await session.commit()

    async def _invoke(
        self, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        async with SessionLocal() as session:
            service = ErpToolService(session)
            tenant_id = UUID(arguments["tenant_id"])
            order_id_value = UUID(arguments["order_id"])
            task_id = _as_uuid(arguments.get("task_id"))
            actor_id = _as_uuid(arguments.get("actor_id"))
            key = arguments["idempotency_key"]

            if name == "order_split":
                return await service.order_split(
                    tenant_id,
                    order_id_value,
                    arguments["shipments"],
                    key,
                    dry_run=arguments.get("dry_run", False),
                    actor_id=actor_id,
                    task_id=task_id,
                )
            if name == "order_change_address":
                return await service.order_change_address(
                    tenant_id,
                    order_id_value,
                    arguments["address"],
                    key,
                    dry_run=arguments.get("dry_run", False),
                    actor_id=actor_id,
                    task_id=task_id,
                )
            if name == "order_revert_split":
                return await service.order_revert_split(
                    tenant_id, order_id_value, key, task_id=task_id
                )
            if name == "order_revert_address":
                return await service.order_revert_address(
                    tenant_id,
                    order_id_value,
                    arguments["before_address"],
                    key,
                    task_id=task_id,
                )
        raise AssertionError(f"unexpected tool: {name}")

    async def _corrupt_inventory(self) -> None:
        async with SessionLocal() as session:
            inventory = await session.scalar(
                select(Inventory).where(
                    Inventory.tenant_id == TENANT_A,
                    Inventory.sku_id == CASE_SKU_IDS["SKU-001"],
                    Inventory.warehouse_id == WAREHOUSE_EAST,
                )
            )
            assert inventory is not None
            inventory.available = -1
            await session.commit()

    async def _record(
        self,
        name: str,
        arguments: dict[str, Any],
        phase: str,
        result: dict[str, Any] | None,
        error: BaseException | None,
    ) -> None:
        call = ToolCall(
            name=name,
            arguments=dict(arguments),
            phase=phase,
            ok=error is None,
            result=result,
            error=error,
        )
        self.calls.append(call)
        if error is not None:
            self.errors.append(error)
        tenant_id = _as_uuid(arguments.get("tenant_id"))
        if tenant_id is None:
            return
        attributes = {
            "phase": phase,
            "dry_run": bool(arguments.get("dry_run")),
            "order_id": str(arguments.get("order_id") or ""),
            "idempotency_key": str(arguments.get("idempotency_key") or ""),
            "status": "error" if error is not None else "ok",
        }
        if error is not None:
            attributes["error"] = str(error)[:200]
        await self.trace.record(
            f"tool.{name}",
            _as_uuid(arguments.get("task_id")),
            tenant_id,
            attributes,
        )


class FailingVerifier:
    """Verifier double that rejects every plan."""

    def __init__(self, reason: str = "injected verification failure") -> None:
        self.reason = reason

    async def verify(
        self, task: Any, plan: Any, results: Any
    ) -> VerificationResult:
        return VerificationResult(passed=False, reason=self.reason)


class CorruptingVerifier:
    """Commit an inventory corruption, then run the real verifier read-only.

    The corruption must not ride on the executor's session: flushing there
    leaves an open row lock, and the compensation worker (a separate session)
    would block on it forever. A short-lived session commits the injected
    corruption and releases its lock; a second fresh session then runs the
    production verifier so the committed corruption is visible.
    """

    async def verify(
        self, task: Any, plan: Any, results: Any
    ) -> VerificationResult:
        async with SessionLocal() as corrupt_session:
            inventory = await repositories.get_inventory(
                corrupt_session,
                task.tenant_id,
                CASE_SKU_IDS["SKU-001"],
                WAREHOUSE_EAST,
            )
            assert inventory is not None
            inventory.available = -1
            await corrupt_session.commit()
        async with SessionLocal() as verify_session:
            return await Verifier(verify_session).verify(task, plan, results)


@dataclass
class CaseRun:
    """Everything the generic assertions need from one golden run."""

    case: GoldenCase
    task_id: UUID | None = None
    second_task_id: UUID | None = None
    created: dict[str, Any] | None = None
    second_created: dict[str, Any] | None = None
    results: list[ExecutionResult] = field(default_factory=list)
    first_status: str | None = None
    gateway: GoldenToolClient | None = None
    second_gateway: GoldenToolClient | None = None
    denial_statuses: list[int] = field(default_factory=list)
    creation_status: int | None = None


def _client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        timeout=30,
    )


def _identity_for(case: GoldenCase) -> Identity:
    return APPROVER_A if case.decider == "approver" else OPERATOR_A


async def _post_task(
    client: AsyncClient,
    case: GoldenCase,
    monkeypatch: pytest.MonkeyPatch,
    *,
    key: str,
) -> Any:
    if case.plan is not None:
        plan_name = case.plan

        async def _stub_plan(session: Any, planner_task: Any) -> Any:
            del session
            return build_plan(plan_name, str(planner_task.id))

        monkeypatch.setattr(tasks_routes, "_generate_plan", _stub_plan)
    return await client.post(
        TASK_URL,
        json={
            "instruction": case.instruction,
            "warehouse": "east",
            "cutoff": DEFAULT_CUTOFF,
        },
        headers={"X-API-Key": case.api_key, "Idempotency-Key": key},
    )


async def _apply_pre_setup(case: GoldenCase) -> None:
    async with SessionLocal() as session:
        for name in case.pre_setup:
            if name == "invalidate_o1002_phone":
                order = await session.scalar(
                    select(SalesOrder).where(
                        SalesOrder.tenant_id == TENANT_A,
                        SalesOrder.order_no == "O1002",
                    )
                )
                assert order is not None
                order.phone = "12345"
            elif name == "zero_sku_002":
                inventory = await session.scalar(
                    select(Inventory).where(
                        Inventory.tenant_id == TENANT_A,
                        Inventory.sku_id == CASE_SKU_IDS["SKU-002"],
                        Inventory.warehouse_id == WAREHOUSE_EAST,
                    )
                )
                assert inventory is not None
                inventory.available = 0
            else:
                raise AssertionError(f"unknown pre-setup {name}")
        await session.commit()


async def _apply_post_create_setup(
    case: GoldenCase, task_id: UUID
) -> None:
    async with SessionLocal() as session:
        for name in case.post_create_setup:
            if name == "move_o1004_to_tenant_b":
                order = await session.scalar(
                    select(SalesOrder).where(
                        SalesOrder.tenant_id == TENANT_A,
                        SalesOrder.order_no == "O1004",
                    )
                )
                assert order is not None
                order.tenant_id = TENANT_B
            elif name == "expire_approvals":
                approvals = list(
                    (
                        await session.scalars(
                            select(Approval).where(
                                Approval.task_id == task_id,
                                Approval.tenant_id == TENANT_A,
                            )
                        )
                    ).all()
                )
                past = datetime.now(UTC) - timedelta(minutes=1)
                for approval in approvals:
                    approval.expires_at = past
            else:
                raise AssertionError(f"unknown post-create setup {name}")
        await session.commit()


async def _decide_approvals(
    case: GoldenCase,
    task_id: UUID,
    trace: TraceSink,
    *,
    duplicate: bool = False,
) -> None:
    identity = _identity_for(case)
    for directive in case.approvals:
        await _decide_directive(case, task_id, directive, identity, trace)
        if duplicate:
            await _decide_directive(case, task_id, directive, identity, trace)


async def _decide_directive(
    case: GoldenCase,
    task_id: UUID,
    directive: ApprovalDirective,
    identity: Identity,
    trace: TraceSink,
) -> None:
    order_uuid = ORDER_IDS[directive.order_no]
    async with SessionLocal() as session:
        statement = select(Approval).where(
            Approval.task_id == task_id,
            Approval.tenant_id == TENANT_A,
            Approval.order_id == order_uuid,
        )
        if directive.action is not None:
            statement = statement.where(Approval.action == directive.action)
        approvals = list((await session.scalars(statement)).all())
        assert approvals, f"no approval for {directive}"
        service = ApprovalService(session)
        await service.decide(
            task_id,
            identity,
            directive.approved,
            comment=f"{case.id} {'approve' if directive.approved else 'reject'}",
            order_id=order_uuid,
        )
    await trace.record(
        "approval",
        task_id,
        TENANT_A,
        {
            "order_id": str(order_uuid),
            "action": directive.action or "any",
            "approved": directive.approved,
            "decider": identity.role,
        },
    )


def _verifier_for(case: GoldenCase) -> Any:
    if case.verifier == "failing":
        return FailingVerifier()
    if case.verifier == "corrupt_inventory":
        return CorruptingVerifier()
    return None


async def _execute(
    case: GoldenCase,
    task_id: UUID,
    gateway: GoldenToolClient,
) -> ExecutionResult:
    with faults.inject(**case.faults):
        async with SessionLocal() as session:
            executor = TaskExecutor(
                session,
                gateway,
                TENANT_A,
                verifier=_verifier_for(case),
            )
            return await executor.start(task_id)


async def _expire_approvals(task_id: UUID) -> None:
    async with SessionLocal() as session:
        approvals = list(
            (
                await session.scalars(
                    select(Approval).where(Approval.task_id == task_id)
                )
            ).all()
        )
        past = datetime.now(UTC) - timedelta(minutes=1)
        for approval in approvals:
            approval.expires_at = past
        await session.commit()


async def _refresh_approvals(task_id: UUID) -> None:
    async with SessionLocal() as session:
        approvals = list(
            (
                await session.scalars(
                    select(Approval).where(Approval.task_id == task_id)
                )
            ).all()
        )
        future = datetime.now(UTC) + timedelta(minutes=30)
        for approval in approvals:
            approval.expires_at = future
        await session.commit()


async def run_case(
    case: GoldenCase, monkeypatch: pytest.MonkeyPatch
) -> CaseRun:
    """Drive one golden case through API, approvals, and the executor."""

    settings = get_settings()
    monkeypatch.setattr(settings, "stub_llm", True)
    if case.l3_threshold is not None:
        monkeypatch.setattr(settings, "l3_batch_threshold", case.l3_threshold)

    await _apply_pre_setup(case)
    trace = TraceSink()
    run = CaseRun(case=case)

    if case.driver == "creation_failure":
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await _post_task(
                client, case, monkeypatch, key=_task_key(case)
            )
        run.creation_status = response.status_code
        return run

    gateway = GoldenToolClient(
        trace=trace,
        fault_policy=case.fault_plan,
        enforce_tenant_guard=case.driver == "security_cross_tenant",
    )
    run.gateway = gateway

    async with _client() as client:
        response = await _post_task(
            client, case, monkeypatch, key=_task_key(case)
        )
        assert response.status_code == 200, response.text
        created = response.json()
        run.created = created
        task_id = UUID(created["id"])
        run.task_id = task_id
        await trace.record(
            "plan_task",
            task_id,
            TENANT_A,
            {"status": created["status"], "source": "golden-stub"},
        )
        await _apply_post_create_setup(case, task_id)

        if case.driver == "security_cross_tenant":
            await _run_cross_tenant(client, case, run, gateway, trace)
            return run
        if case.driver == "security_unauthorized_tool":
            await _run_unauthorized_tool(case, run, gateway, trace)
            return run

        if case.driver == "duplicate_create":
            second = await _post_task(
                client, case, monkeypatch, key=_task_key(case)
            )
            assert second.status_code == 200, second.text
            run.second_created = second.json()

        if case.driver == "concurrent":
            second_task_id = await _create_second_task(client, case, monkeypatch)
            run.second_task_id = second_task_id
            await trace.record(
                "plan_task",
                second_task_id,
                TENANT_A,
                {"status": "awaiting_approval", "source": "golden-stub"},
            )
            await _decide_approvals(case, task_id, trace)
            await _decide_approvals(case, second_task_id, trace)
            second_gateway = GoldenToolClient(trace=trace)
            run.second_gateway = second_gateway
            results = await asyncio.gather(
                _execute(case, task_id, gateway),
                _execute(case, second_task_id, second_gateway),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException):
                    raise result
                run.results.append(result)
            first_final = await _load_task(task_id)
            second_final = await _load_task(second_task_id)
            await trace.record(
                "report",
                task_id,
                TENANT_A,
                {"status": first_final.status, "mode": "concurrent"},
            )
            await trace.record(
                "report",
                second_task_id,
                TENANT_A,
                {"status": second_final.status, "mode": "concurrent"},
            )
            return run

        if case.driver == "await_then_resume":
            await _expire_approvals(task_id)
            first = await _execute(case, task_id, gateway)
            run.first_status = first.status
            await _refresh_approvals(task_id)
            await _decide_approvals(case, task_id, trace)
            run.results.append(first)
            run.results.append(await _execute(case, task_id, gateway))
        elif case.driver == "duplicate_approve":
            await _decide_approvals(case, task_id, trace, duplicate=True)
            run.results.append(await _execute(case, task_id, gateway))
        elif case.driver == "retry":
            await _decide_approvals(case, task_id, trace)
            first = await _execute(case, task_id, gateway)
            run.first_status = first.status
            gateway.clear_faults()
            run.results.append(first)
            run.results.append(await _execute(case, task_id, gateway))
        else:
            await _decide_approvals(case, task_id, trace)
            run.results.append(await _execute(case, task_id, gateway))
            if case.driver == "execute_twice":
                run.results.append(await _execute(case, task_id, gateway))

        final = await _load_task(task_id)
        await trace.record(
            "report",
            task_id,
            TENANT_A,
            {"status": final.status, "mode": case.driver},
        )
    return run


async def _create_second_task(
    client: AsyncClient,
    case: GoldenCase,
    monkeypatch: pytest.MonkeyPatch,
) -> UUID:
    response = await _post_task(
        client, case, monkeypatch, key=_task_key(case, suffix="-2")
    )
    assert response.status_code == 200, response.text
    return UUID(response.json()["id"])


async def _run_cross_tenant(
    client: AsyncClient,
    case: GoldenCase,
    run: CaseRun,
    gateway: GoldenToolClient,
    trace: TraceSink,
) -> None:
    assert run.task_id is not None
    forbidden = await client.get(
        f"{TASK_URL}/{run.task_id}", headers={"X-API-Key": "dev-operator-b"}
    )
    denied_approval = await client.post(
        f"{TASK_URL}/{run.task_id}/approve",
        headers={"X-API-Key": "dev-operator-b"},
    )
    run.denial_statuses.extend([forbidden.status_code, denied_approval.status_code])
    assert "O1001" not in forbidden.text
    assert "世纪大道" not in forbidden.text
    assert "张三" not in forbidden.text
    assert "13800138000" not in forbidden.text

    with pytest.raises(ToolAccessDenied) as excinfo:
        await gateway.call(
            "order_split",
            {
                "tenant_id": str(TENANT_B),
                "order_id": str(ORDER_IDS["O1001"]),
                "shipments": _split_shipments("O1001"),
                "idempotency_key": "cross-tenant-attempt",
            },
        )
    run.denial_statuses.append(excinfo.value.status_code)
    await trace.record(
        "security.denied",
        run.task_id,
        TENANT_B,
        {"reason": "cross-tenant", "tool": "order_split"},
    )


async def _run_unauthorized_tool(
    case: GoldenCase,
    run: CaseRun,
    gateway: GoldenToolClient,
    trace: TraceSink,
) -> None:
    assert run.task_id is not None
    with pytest.raises(ToolAccessDenied) as excinfo:
        await gateway.call(
            "order_split",
            {
                "tenant_id": str(TENANT_A),
                "order_id": str(ORDER_IDS["O1001"]),
                "shipments": _split_shipments("O1001"),
                "idempotency_key": "unauthorized-tool-attempt",
                "task_id": str(run.task_id),
                "actor_id": str(OPERATOR_A.user_id),
            },
        )
    run.denial_statuses.append(excinfo.value.status_code)
    await trace.record(
        "security.denied",
        run.task_id,
        TENANT_A,
        {"reason": "missing-approved-approval", "tool": "order_split"},
    )


def _split_shipments(order_no: str) -> list[dict[str, Any]]:
    lines = {
        "O1001": (("SKU-001", 2), ("SKU-002", 1)),
        "O1004": (("SKU-004", 1),),
    }[order_no]
    return [
        {
            "warehouse_id": str(WAREHOUSE_EAST),
            "lines": [{"sku_id": str(CASE_SKU_IDS[sku]), "qty": qty}],
        }
        for sku, qty in lines
    ]


async def _load_task(task_id: UUID) -> TaskRun:
    async with SessionLocal() as session:
        task = await session.get(TaskRun, task_id)
    assert task is not None
    return task


async def _approvals(task_id: UUID) -> list[Approval]:
    async with SessionLocal() as session:
        return list(
            (
                await session.scalars(
                    select(Approval)
                    .where(Approval.task_id == task_id)
                    .order_by(Approval.id)
                )
            ).all()
        )


async def _steps(task_id: UUID) -> list[TaskStep]:
    async with SessionLocal() as session:
        return list(
            (
                await session.scalars(
                    select(TaskStep)
                    .where(TaskStep.task_id == task_id)
                    .order_by(TaskStep.node_id)
                )
            ).all()
        )


async def _audits(task_id: UUID) -> list[AuditLog]:
    async with SessionLocal() as session:
        return list(
            (
                await session.scalars(
                    select(AuditLog)
                    .where(AuditLog.task_id == task_id)
                    .order_by(AuditLog.id)
                )
            ).all()
        )


async def _spans(task_id: UUID) -> list[TraceSpan]:
    async with SessionLocal() as session:
        return list(
            (
                await session.scalars(
                    select(TraceSpan).where(TraceSpan.task_id == task_id)
                )
            ).all()
        )


async def _shipments(order_no: str, tenant_id: UUID = TENANT_A) -> list[Shipment]:
    async with SessionLocal() as session:
        return list(
            (
                await session.scalars(
                    select(Shipment).where(
                        Shipment.tenant_id == tenant_id,
                        Shipment.order_id == ORDER_IDS[order_no],
                    )
                )
            ).all()
        )


async def _shipment_lines(
    order_no: str, tenant_id: UUID = TENANT_A
) -> Counter[str]:
    shipments = await _shipments(order_no, tenant_id)
    async with SessionLocal() as session:
        lines = list(
            (
                await session.scalars(
                    select(ShipmentLine).where(
                        ShipmentLine.tenant_id == tenant_id,
                        ShipmentLine.shipment_id.in_(
                            [shipment.id for shipment in shipments]
                        ),
                    )
                )
            ).all()
        )
    totals: Counter[str] = Counter()
    for line in lines:
        totals[SKU_CODE_BY_ID[line.sku_id]] += line.qty
    return totals


async def _order(
    order_no: str, tenant_id: UUID = TENANT_A
) -> SalesOrder | None:
    async with SessionLocal() as session:
        return await session.scalar(
            select(SalesOrder).where(
                SalesOrder.tenant_id == tenant_id,
                SalesOrder.order_no == order_no,
            )
        )


async def _inventory(sku_code: str) -> Inventory:
    async with SessionLocal() as session:
        inventory = await session.scalar(
            select(Inventory).where(
                Inventory.tenant_id == TENANT_A,
                Inventory.sku_id == CASE_SKU_IDS[sku_code],
                Inventory.warehouse_id == WAREHOUSE_EAST,
            )
        )
    assert inventory is not None
    return inventory


async def _action_idempotency(task_id: UUID) -> list[IdempotencyKey]:
    async with SessionLocal() as session:
        records = list(
            (
                await session.scalars(
                    select(IdempotencyKey).where(
                        IdempotencyKey.tenant_id == TENANT_A
                    )
                )
            ).all()
        )
    return [
        record
        for record in records
        if record.scope != "task.create"
        and record.key.startswith(str(task_id))
    ]


def _successful_write_pairs(gateway: GoldenToolClient) -> set[str]:
    return {
        f"{call.name}:{call.order_no}"
        for call in gateway.calls
        if call.ok
        and call.name in BUSINESS_WRITES
        and call.phase == "execute"
        and call.order_no is not None
    }


def _successful_compensation_pairs(gateway: GoldenToolClient) -> set[str]:
    return {
        f"{call.name}:{call.order_no}"
        for call in gateway.calls
        if call.ok
        and call.name in COMPENSATION_TOOLS
        and call.order_no is not None
    }


def _expected_audit_counts(case: GoldenCase) -> Counter[str]:
    counts: Counter[str] = Counter()
    for pair in case.expected_writes:
        tool = pair.split(":", 1)[0]
        counts["order.split" if tool == "order_split" else "order.change_address"] += 1
    for pair in case.expected_compensations:
        tool = pair.split(":", 1)[0]
        counts[
            "order.split.cancel"
            if tool == "order_revert_split"
            else "order.change_address.revert"
        ] += 1
    return counts


async def assert_case(case: GoldenCase, run: CaseRun) -> None:
    """Assert the spec's observable outcome for one golden task."""

    if case.driver == "creation_failure":
        await _assert_creation_failure(run)
        return

    assert run.task_id is not None
    task = await _load_task(run.task_id)

    if case.driver == "concurrent":
        await _assert_concurrent(case, run, task)
        return

    if case.driver == "security_cross_tenant":
        await _assert_security(case, run, task, tenant_id=TENANT_B)
        return

    if case.driver == "security_unauthorized_tool":
        await _assert_security(case, run, task, tenant_id=TENANT_A)
        return

    assert task.status == case.expected_status, (
        f"{case.id}: expected task {case.expected_status}, got {task.status}"
    )
    if case.expected_first_status is not None:
        assert run.first_status == case.expected_first_status

    if case.id == "GT-19":
        assert run.second_created is not None
        assert run.second_created["id"] == run.created["id"]
        assert await count_tasks() == 1
    if case.id in {"GT-03", "GT-04"}:
        changed = await _order("O1002")
        assert changed is not None
        assert changed.address_detail == "上海市浦东新区世纪大道100号"
    if case.id in {"GT-21", "GT-22"}:
        # The retry must reuse the original write key, not mint a new one.
        assert run.gateway is not None
        retry_keys = {
            call.arguments["idempotency_key"]
            for call in run.gateway.calls
            if call.name == "order_split"
            and call.phase == "execute"
            and call.order_no == "O1001"
        }
        assert len(retry_keys) == 1, retry_keys
    if case.l3_threshold is not None:
        assert task.plan is not None
        assert task.plan["requires_l3"] is True
        approvals = await _approvals(run.task_id)
        split_approvals = [
            approval
            for approval in approvals
            if approval.action == "split_order"
        ]
        assert split_approvals
        assert {approval.risk_level for approval in split_approvals} == {"L3"}

    if run.results and task.result is not None:
        assert task.result["status"] == case.expected_status
        if case.id in {"GT-13", "GT-25"}:
            assert task.result["verified"] is False
            assert task.result["compensated"]
        if case.id == "GT-26":
            assert task.result["failed_compensations"]
            assert "compensation failed for" in task.result["reason"]
        if case.id in {"GT-15", "GT-17"}:
            assert task.result["skipped"]

    for order_no, expected_status in case.expected_orders.items():
        tenant_label = case.expected_order_tenants.get(order_no, "tenant-a")
        order = await _order(order_no, TASK_KEYS[tenant_label])
        assert order is not None, f"{case.id}: order {order_no} missing"
        assert order.status == expected_status, (
            f"{case.id}: order {order_no} expected {expected_status}, "
            f"got {order.status}"
        )

    for order_no, expected_count in case.expected_shipments.items():
        tenant_label = case.expected_order_tenants.get(order_no, "tenant-a")
        order_shipments = await _shipments(order_no, TASK_KEYS[tenant_label])
        assert len(order_shipments) == expected_count, (
            f"{case.id}: order {order_no} expected {expected_count} shipments, "
            f"got {len(order_shipments)}"
        )
        expected_shipment_status = case.expected_shipment_statuses.get(order_no)
        if expected_shipment_status is not None:
            assert {
                shipment.status for shipment in order_shipments
            } == {expected_shipment_status}

    for order_no, expected_lines in case.expected_shipment_lines.items():
        tenant_label = case.expected_order_tenants.get(order_no, "tenant-a")
        totals = await _shipment_lines(order_no, TASK_KEYS[tenant_label])
        assert tuple(sorted(totals.items())) == expected_lines

    for sku_code, (available, reserved) in case.expected_inventory.items():
        inventory = await _inventory(sku_code)
        assert (inventory.available, inventory.reserved) == (available, reserved), (
            f"{case.id}: {sku_code} expected {available}/{reserved}, "
            f"got {inventory.available}/{inventory.reserved}"
        )

    assert run.gateway is not None
    write_pairs = _successful_write_pairs(run.gateway)
    assert write_pairs == set(case.expected_writes), (
        f"{case.id}: writes {sorted(write_pairs)} != "
        f"{sorted(case.expected_writes)}"
    )
    compensation_pairs = _successful_compensation_pairs(run.gateway)
    assert compensation_pairs == set(case.expected_compensations), (
        f"{case.id}: compensations {sorted(compensation_pairs)} != "
        f"{sorted(case.expected_compensations)}"
    )
    for forbidden in case.forbidden_writes:
        assert not any(
            call.ok
            and call.name == forbidden
            and call.phase == "execute"
            for call in run.gateway.calls
        ), f"{case.id}: forbidden write {forbidden} executed"

    error_codes = {
        getattr(error, "code", None) for error in run.gateway.errors
    }
    for expected_code in case.expected_error_codes:
        assert expected_code in error_codes, (
            f"{case.id}: expected error code {expected_code}, got {error_codes}"
        )
    if case.expected_error_text is not None:
        haystack = " | ".join(
            str(error) for error in run.gateway.errors
        )
        haystack += " | " + " | ".join(
            step.error or "" for step in await _steps(run.task_id)
        )
        assert case.expected_error_text in haystack, (
            f"{case.id}: {case.expected_error_text!r} not found in {haystack!r}"
        )

    await _assert_approvals(case, run)
    await _assert_audit(case, run, task)
    await _assert_idempotency(case, run)
    await _assert_steps(case, run, task)
    await _assert_trace(case, run, trace_tenant=TENANT_A)


async def _assert_creation_failure(run: CaseRun) -> None:
    assert run.creation_status == 500
    async with SessionLocal() as session:
        task_count = len((await session.scalars(select(TaskRun))).all())
        approval_count = len((await session.scalars(select(Approval))).all())
        audit_count = len((await session.scalars(select(AuditLog))).all())
        idempotency_count = len(
            (await session.scalars(select(IdempotencyKey))).all()
        )
        attempted_shipments = len(
            (
                await session.scalars(
                    select(Shipment).where(
                        Shipment.order_id.in_(
                            [ORDER_IDS["O1001"], ORDER_IDS["O1004"]]
                        )
                    )
                )
            ).all()
        )
    assert task_count == 0
    assert approval_count == 0
    assert audit_count == 0
    assert idempotency_count == 0
    assert attempted_shipments == 0


async def _assert_approvals(case: GoldenCase, run: CaseRun) -> None:
    assert run.task_id is not None
    approvals = await _approvals(run.task_id)
    task = await _load_task(run.task_id)
    write_nodes = [
        node
        for node in (task.plan or {}).get("nodes", [])
        if node.get("action") in {"split_order", "change_address"}
    ]
    assert len(approvals) == len(write_nodes)
    if case.expected_approval_status is None:
        return
    assert {approval.status for approval in approvals} == {
        case.expected_approval_status
    }
    for approval in approvals:
        if approval.status in {
            ApprovalStatus.approved.value,
            ApprovalStatus.rejected.value,
        }:
            assert approval.approver_id == _identity_for(case).user_id
            assert approval.decided_at is not None
            assert approval.comment == (
                f"{case.id} "
                f"{'approve' if approval.status == 'approved' else 'reject'}"
            )
        else:
            assert approval.approver_id is None

    audits = await _audits(run.task_id)
    decision_audits = [
        audit
        for audit in audits
        if audit.action in {"approval.approve", "approval.reject"}
    ]
    assert len(decision_audits) == len(case.approvals)


async def _assert_audit(
    case: GoldenCase, run: CaseRun, task: TaskRun
) -> None:
    assert run.task_id is not None
    audits = await _audits(run.task_id)
    actual = Counter(
        audit.action
        for audit in audits
        if audit.action
        in {
            "order.split",
            "order.change_address",
            "order.split.cancel",
            "order.change_address.revert",
        }
    )
    assert actual == _expected_audit_counts(case)
    for audit in audits:
        if audit.action in {"order.split", "order.change_address"}:
            assert audit.before is not None
            assert audit.after is not None
            assert audit.evidence is not None
        if audit.action == "order.change_address":
            assert audit.before["address_detail"] == ""
            assert audit.after["address_detail"] == "上海市浦东新区世纪大道100号"
    if case.id == "GT-26":
        assert task.result is not None
        failed = task.result["failed_compensations"]
        assert len(failed) == 2
        for node_id in failed:
            assert node_id in task.result["reason"]


async def _assert_idempotency(case: GoldenCase, run: CaseRun) -> None:
    assert run.task_id is not None
    async with SessionLocal() as session:
        record = await session.scalar(
            select(IdempotencyKey).where(
                IdempotencyKey.tenant_id == TENANT_A,
                IdempotencyKey.scope == "task.create",
                IdempotencyKey.key == _task_key(case),
            )
        )
        duplicates = list(
            (
                await session.scalars(
                    select(IdempotencyKey).where(
                        IdempotencyKey.tenant_id == TENANT_A,
                        IdempotencyKey.scope == "task.create",
                        IdempotencyKey.key == _task_key(case),
                    )
                )
            ).all()
        )
    assert record is not None
    assert len(duplicates) == 1
    assert record.response is not None
    assert record.response["id"] == str(run.task_id)

    action_records = await _action_idempotency(run.task_id)
    expected_count = len(case.expected_writes) + len(
        case.expected_compensations
    )
    assert len(action_records) == expected_count, (
        f"{case.id}: expected {expected_count} action idempotency rows, "
        f"got {[record.key for record in action_records]}"
    )
    keys = {record.key for record in action_records}
    task = await _load_task(run.task_id)
    plan_nodes = {
        node["node_id"]: node for node in (task.plan or {}).get("nodes", [])
    }
    for pair in case.expected_writes:
        node = _node_for_pair(plan_nodes, pair)
        assert f"{run.task_id}:{node['node_id']}" in keys
    for pair in case.expected_compensations:
        node = _node_for_pair(plan_nodes, pair)
        assert f"{run.task_id}:{node['node_id']}:compensate" in keys


def _node_for_pair(
    plan_nodes: dict[str, dict[str, Any]], pair: str
) -> dict[str, Any]:
    tool, order_no = pair.split(":", 1)
    action = ACTION_FOR_TOOL[tool] if tool in ACTION_FOR_TOOL else (
        "split_order" if tool == "order_revert_split" else "change_address"
    )
    for node in plan_nodes.values():
        if (
            node.get("action") == action
            and _order_no(node.get("order_id")) == order_no
        ):
            return node
    raise AssertionError(f"no plan node for {pair}")


async def _assert_steps(
    case: GoldenCase, run: CaseRun, task: TaskRun
) -> None:
    assert run.task_id is not None
    if not run.results:
        return
    steps = await _steps(run.task_id)
    plan_nodes = {
        node["node_id"]: node for node in (task.plan or {}).get("nodes", [])
    }
    assert {step.node_id for step in steps} == set(plan_nodes)
    status_by_node = {
        node_id: next(step.status for step in steps if step.node_id == node_id)
        for node_id in plan_nodes
    }
    for pair in case.expected_writes:
        node = _node_for_pair(plan_nodes, pair)
        assert status_by_node[node["node_id"]] in {
            "succeeded",
            "compensated",
            "failed",
        }
    for pair in case.expected_compensations:
        node = _node_for_pair(plan_nodes, pair)
        assert status_by_node[node["node_id"]] == "compensated"
    if case.id == "GT-23":
        # A failed write keeps its idempotency key and error for a later retry.
        failed_steps = [step for step in steps if step.status == "failed"]
        assert len(failed_steps) == 1
        failed_step = failed_steps[0]
        assert failed_step.input is not None
        key = failed_step.input["args"]["idempotency_key"]
        assert key.startswith(f"{run.task_id}:")
        assert failed_step.error is not None
        assert "upstream error" in failed_step.error


async def _assert_trace(
    case: GoldenCase, run: CaseRun, trace_tenant: UUID
) -> None:
    assert run.task_id is not None
    spans = await _spans(run.task_id)
    names = {span.name for span in spans}
    assert "plan_task" in names
    if run.results:
        assert "report" in names
    if case.approvals:
        assert "approval" in names
    if run.gateway is not None and any(
        call.arguments.get("task_id") for call in run.gateway.calls
    ):
        assert any(name.startswith("tool.") for name in names)


async def _assert_concurrent(
    case: GoldenCase, run: CaseRun, task: TaskRun
) -> None:
    assert run.task_id is not None
    assert run.second_task_id is not None
    statuses = sorted(result.status for result in run.results)
    assert statuses == ["failed", "succeeded"], statuses
    assert task.status in {"failed", "succeeded"}
    second = await _load_task(run.second_task_id)
    assert second.status in {"failed", "succeeded"}

    order = await _order("O1001")
    assert order is not None and order.status == "split"
    shipments = await _shipments("O1001")
    assert len(shipments) == 2
    inventory_1 = await _inventory("SKU-001")
    inventory_2 = await _inventory("SKU-002")
    assert (inventory_1.available, inventory_1.reserved) == (98, 2)
    assert (inventory_2.available, inventory_2.reserved) == (99, 1)

    sorted_results = sorted(run.results, key=lambda result: result.status)
    loser = sorted_results[0]
    assert loser.status == "failed"
    assert loser.failed or loser.failed_compensations

    total_action_records = (
        await _action_idempotency(run.task_id)
        + await _action_idempotency(run.second_task_id)
    )
    assert len(total_action_records) == 1
    async with SessionLocal() as session:
        task_create_count = len(
            (
                await session.scalars(
                    select(IdempotencyKey).where(
                        IdempotencyKey.tenant_id == TENANT_A,
                        IdempotencyKey.scope == "task.create",
                        IdempotencyKey.key.in_(
                            [_task_key(case), _task_key(case, suffix="-2")]
                        ),
                    )
                )
            ).all()
        )
    assert task_create_count == 2

    assert run.gateway is not None
    assert run.second_gateway is not None
    combined = run.gateway.calls + run.second_gateway.calls
    assert len(
        [
            call
            for call in combined
            if call.ok
            and call.name == "order_split"
            and call.phase == "execute"
        ]
    ) == 1
    for task_id in (run.task_id, run.second_task_id):
        names = {span.name for span in await _spans(task_id)}
        assert "plan_task" in names
        assert "approval" in names
        assert "report" in names


async def _assert_security(
    case: GoldenCase,
    run: CaseRun,
    task: TaskRun,
    *,
    tenant_id: UUID,
) -> None:
    assert run.task_id is not None
    assert task.status == case.expected_status
    assert task.result is None
    order = await _order("O1001")
    assert order is not None and order.status == "pending_shipment"
    assert await _shipments("O1001") == []
    assert run.denial_statuses
    expected = case.expected_denial_status
    assert expected is not None
    assert expected in run.denial_statuses

    async with SessionLocal() as session:
        denial = await session.scalar(
            select(AuditLog).where(
                AuditLog.tenant_id == tenant_id,
                AuditLog.action == "tool.denied",
            )
        )
    assert denial is not None
    assert denial.evidence is not None
    assert denial.evidence["denied"] is True

    approvals = await _approvals(run.task_id)
    assert approvals
    assert {approval.status for approval in approvals} == {"pending"}

    assert await _action_idempotency(run.task_id) == []

    spans = await _spans(run.task_id)
    names = {span.name for span in spans}
    assert "plan_task" in names
    assert "security.denied" in names


def assert_case_table() -> None:
    """Validate that exactly GT-01..GT-28 are present with spec categories."""

    expected_ids = tuple(f"GT-{index:02d}" for index in range(1, 29))
    assert tuple(case.id for case in GOLDEN_CASES) == expected_ids
    counts = Counter(case.category for case in GOLDEN_CASES)
    assert counts[CATEGORY_APPROVAL] == 5
    assert counts[CATEGORY_INVENTORY] == 4
    assert set(CASE_BY_ID) == set(expected_ids)
    for case in GOLDEN_CASES:
        assert case.instruction
        assert case.api_key


async def count_tasks() -> int:
    async with SessionLocal() as session:
        return len((await session.scalars(select(TaskRun))).all())
