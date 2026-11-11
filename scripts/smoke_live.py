#!/usr/bin/env python
"""Live-model smoke test for the five MVP main-path golden scenarios.

This script is intentionally outside pytest: a live model call must never gate
the deterministic suite. It reads the ``OPSCONDUCTOR_LLM_*`` settings, drives
five main-path tasks through the real planner, approval API, executor, and MCP
stdio tool server, then reports each result as JSON.

Without ``OPSCONDUCTOR_LLM_API_KEY`` and ``OPSCONDUCTOR_LLM_BASE_URL`` it prints
``SKIPPED`` and exits 0. With a key it reseeds the configured database before
each case (point ``OPSCONDUCTOR_SMOKE_DATABASE_URL`` at a disposable database)
and exits 0 even when a model run fails, unless ``--strict`` is passed.

Usage::

    python scripts/smoke_live.py [--strict] [--keep-db]
"""

import argparse
import asyncio
import json
import os
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import UUID, uuid4

# ruff: noqa: E402

# A dedicated smoke database keeps the app's development data out of reach.
_SMOKE_DATABASE_URL = os.environ.get("OPSCONDUCTOR_SMOKE_DATABASE_URL")
if _SMOKE_DATABASE_URL:
    os.environ["OPSCONDUCTOR_DATABASE_URL"] = _SMOKE_DATABASE_URL

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from opsconductor.api.main import app
from opsconductor.config import get_settings
from opsconductor.db import SessionLocal, engine
from opsconductor.domain import Base
from opsconductor.domain.models import (
    Inventory,
    SalesOrder,
    Shipment,
    ShipmentLine,
    TaskRun,
    TaskStep,
)
from opsconductor.domain.seed import SKU_IDS, TENANT_A, WAREHOUSE_EAST, seed
from opsconductor.orchestrator.executor import TaskExecutor
from opsconductor.tools.client import ErpToolClient

TASK_URL = "/api/v1/tasks"
OPERATOR_KEY = "dev-operator-a"
APPROVER_KEY = "dev-approver-a"
WAREHOUSE = "east"
CUTOFF = "2026-11-04T00:00:00Z"
WRITE_ACTIONS = {"split_order", "change_address"}
SKU_CODE_BY_ID = {value: key for key, value in SKU_IDS.items()}


@dataclass(frozen=True)
class SmokeCase:
    """One main-path scenario and its observable post-conditions."""

    id: str
    instruction: str
    expected_orders: dict[str, str] = field(default_factory=dict)
    expected_shipments: dict[str, int] = field(default_factory=dict)
    expected_lines: dict[str, tuple[tuple[str, int], ...]] = field(
        default_factory=dict
    )
    expected_inventory: dict[str, tuple[int, int]] = field(default_factory=dict)
    expected_address: dict[str, str] = field(default_factory=dict)


CASES: tuple[SmokeCase, ...] = (
    SmokeCase(
        id="live-01",
        instruction=(
            "把订单 O1001 按订单行拆成多个发货单，每个发货单只包含一个 SKU 行。"
        ),
        expected_orders={"O1001": "split"},
        expected_shipments={"O1001": 2},
        expected_lines={"O1001": (("SKU-001", 2), ("SKU-002", 1))},
        expected_inventory={"SKU-001": (98, 2), "SKU-002": (99, 1)},
    ),
    SmokeCase(
        id="live-02",
        instruction=(
            "把订单 O1001 拆单，发货单行数量合计必须与订单行数量完全一致。"
        ),
        expected_orders={"O1001": "split"},
        expected_shipments={"O1001": 2},
        expected_lines={"O1001": (("SKU-001", 2), ("SKU-002", 1))},
        expected_inventory={"SKU-001": (98, 2), "SKU-002": (99, 1)},
    ),
    SmokeCase(
        id="live-03",
        instruction="把订单 O1002 的收货地址修改为：上海市浦东新区世纪大道100号。",
        expected_orders={"O1002": "pending_shipment"},
        expected_shipments={"O1002": 0},
        expected_address={"O1002": "上海市浦东新区世纪大道100号"},
    ),
    SmokeCase(
        id="live-04",
        instruction=(
            "把订单 O1001 拆单，并把订单 O1002 的收货地址修改为："
            "上海市浦东新区世纪大道100号。"
        ),
        expected_orders={"O1001": "split", "O1002": "pending_shipment"},
        expected_shipments={"O1001": 2, "O1002": 0},
        expected_lines={"O1001": (("SKU-001", 2), ("SKU-002", 1))},
        expected_inventory={"SKU-001": (98, 2), "SKU-002": (99, 1)},
        expected_address={"O1002": "上海市浦东新区世纪大道100号"},
    ),
    SmokeCase(
        id="live-05",
        instruction="把订单 O1001、O1004、O1006 分别拆单，不要重复写入。",
        expected_orders={"O1001": "split", "O1004": "split", "O1006": "split"},
        expected_shipments={"O1001": 2, "O1004": 1, "O1006": 1},
        expected_inventory={
            "SKU-001": (98, 2),
            "SKU-002": (99, 1),
            "SKU-004": (99, 1),
            "SKU-006": (98, 2),
        },
    ),
)


@dataclass
class CaseResult:
    """Rendered outcome of one live scenario."""

    case_id: str
    instruction: str
    passed: bool = False
    task_id: str | None = None
    task_status: str | None = None
    plan_actions: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    error: str | None = None
    duration_s: float = 0.0
    task_result: dict[str, Any] | None = None
    failed_steps: list[dict[str, Any]] = field(default_factory=list)


async def _reset_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    async with SessionLocal() as session:
        await seed(session)


async def _load_task(task_id: UUID) -> TaskRun | None:
    async with SessionLocal() as session:
        return await session.get(TaskRun, task_id)


async def _failed_steps(task_id: UUID) -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        steps = list(
            (
                await session.scalars(
                    select(TaskStep)
                    .where(
                        TaskStep.task_id == task_id,
                        TaskStep.status == "failed",
                    )
                    .order_by(TaskStep.node_id)
                )
            ).all()
        )
    return [
        {
            "node_id": step.node_id,
            "status": step.status,
            "input": step.input,
            "error": step.error,
        }
        for step in steps
    ]


def _plan_actions(plan: dict[str, Any] | None) -> list[str]:
    return [
        f"{node.get('action')}:{node.get('node_id')}"
        for node in (plan or {}).get("nodes", [])
    ]


async def _create_task(
    client: AsyncClient, case: SmokeCase
) -> dict[str, Any]:
    response = await client.post(
        TASK_URL,
        json={
            "instruction": case.instruction,
            "warehouse": WAREHOUSE,
            "cutoff": CUTOFF,
        },
        headers={
            "X-API-Key": OPERATOR_KEY,
            "Idempotency-Key": f"smoke-{case.id}-{uuid4().hex}",
        },
    )
    response.raise_for_status()
    return response.json()


async def _approve_task(
    client: AsyncClient, task_id: UUID
) -> dict[str, Any]:
    response = await client.post(
        f"{TASK_URL}/{task_id}/approve",
        headers={"X-API-Key": APPROVER_KEY},
    )
    response.raise_for_status()
    return response.json()


async def _execute(task_id: UUID) -> Any:
    async with ErpToolClient() as tool_client:
        async with SessionLocal() as session:
            executor = TaskExecutor(session, tool_client, TENANT_A)
            return await executor.start(task_id)


async def _shipment_line_totals(
    session: Any, order_id: UUID
) -> Counter[str]:
    shipments = list(
        (
            await session.scalars(
                select(Shipment).where(
                    Shipment.tenant_id == TENANT_A,
                    Shipment.order_id == order_id,
                )
            )
        ).all()
    )
    if not shipments:
        return Counter()
    lines = list(
        (
            await session.scalars(
                select(ShipmentLine).where(
                    ShipmentLine.tenant_id == TENANT_A,
                    ShipmentLine.shipment_id.in_(
                        [shipment.id for shipment in shipments]
                    ),
                )
            )
        ).all()
    )
    totals: Counter[str] = Counter()
    for line in lines:
        code = SKU_CODE_BY_ID.get(line.sku_id)
        if code is not None:
            totals[code] += line.qty
    return totals


async def _check_outcome(case: SmokeCase) -> list[str]:
    failures: list[str] = []
    async with SessionLocal() as session:
        for order_no, expected_status in case.expected_orders.items():
            order = await session.scalar(
                select(SalesOrder).where(
                    SalesOrder.tenant_id == TENANT_A,
                    SalesOrder.order_no == order_no,
                )
            )
            if order is None:
                failures.append(f"{order_no}: order missing")
                continue
            if order.status != expected_status:
                failures.append(
                    f"{order_no}: expected {expected_status}, got {order.status}"
                )
            expected_address = case.expected_address.get(order_no)
            if (
                expected_address is not None
                and order.address_detail != expected_address
            ):
                failures.append(
                    f"{order_no}: expected address {expected_address!r}, "
                    f"got {order.address_detail!r}"
                )
            expected_count = case.expected_shipments.get(order_no)
            if expected_count is None:
                continue
            shipments = list(
                (
                    await session.scalars(
                        select(Shipment).where(
                            Shipment.tenant_id == TENANT_A,
                            Shipment.order_id == order.id,
                        )
                    )
                ).all()
            )
            if len(shipments) != expected_count:
                failures.append(
                    f"{order_no}: expected {expected_count} shipments, "
                    f"got {len(shipments)}"
                )
            elif any(shipment.status != "created" for shipment in shipments):
                failures.append(f"{order_no}: non-created shipments")
            expected_lines = case.expected_lines.get(order_no)
            if expected_lines is not None:
                totals = await _shipment_line_totals(session, order.id)
                if tuple(sorted(totals.items())) != expected_lines:
                    failures.append(
                        f"{order_no}: shipment lines {sorted(totals.items())} "
                        f"!= {sorted(expected_lines)}"
                    )

        for sku_code, expected in case.expected_inventory.items():
            inventory = await session.scalar(
                select(Inventory).where(
                    Inventory.tenant_id == TENANT_A,
                    Inventory.sku_id == SKU_IDS[sku_code],
                    Inventory.warehouse_id == WAREHOUSE_EAST,
                )
            )
            if inventory is None:
                failures.append(f"{sku_code}: inventory row missing")
            elif (inventory.available, inventory.reserved) != expected:
                failures.append(
                    f"{sku_code}: expected available/reserved {expected}, "
                    f"got {(inventory.available, inventory.reserved)}"
                )
    return failures


async def _run_case(
    case: SmokeCase, *, keep_db: bool
) -> CaseResult:
    result = CaseResult(case_id=case.id, instruction=case.instruction)
    started = time.perf_counter()
    try:
        if not keep_db:
            await _reset_database()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://smoke",
            timeout=60,
        ) as client:
            created = await _create_task(client, case)
            task_id = UUID(created["id"])
            result.task_id = str(task_id)
            plan = created.get("plan") or {}
            result.plan_actions = _plan_actions(plan)
            if created["status"] == "awaiting_approval":
                await _approve_task(client, task_id)
        execution = await _execute(task_id)
        task = await _load_task(task_id)
        if task is None:
            result.error = "task disappeared after execution"
            return result
        result.task_status = task.status
        result.task_result = task.result
        if task.status not in {"succeeded", "partially_succeeded"}:
            result.failures.append(f"task status {task.status!r}")
        if task.result is not None:
            failed_nodes = task.result.get("failed") or []
            if failed_nodes:
                result.failures.append(f"failed nodes: {failed_nodes}")
        result.failures.extend(await _check_outcome(case))
        result.failed_steps = await _failed_steps(task_id)
        if result.failed_steps:
            result.failures.append(
                "failed steps: "
                + ", ".join(step["node_id"] for step in result.failed_steps)
            )
        result.passed = not result.failures and not result.error
        if execution.status != task.status:
            result.failures.append(
                f"executor reported {execution.status}, task row is {task.status}"
            )
            result.passed = False
    except Exception as exc:  # noqa: BLE001 - a live smoke reports, never raises
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        result.duration_s = round(time.perf_counter() - started, 2)
    return result


def _print_result(result: CaseResult) -> None:
    status = "PASS" if result.passed else "FAIL"
    print(
        f"[{status}] {result.case_id} task={result.task_status} "
        f"duration={result.duration_s}s"
    )
    if result.plan_actions:
        print(f"  plan: {', '.join(result.plan_actions)}")
    for failure in result.failures:
        print(f"  - {failure}")
    if result.error is not None:
        print(f"  - error: {result.error}")


async def _run(*, keep_db: bool) -> int:
    settings = get_settings()
    print(
        "Live model smoke: "
        f"model={settings.llm_model_planner} "
        f"base_url={settings.llm_base_url} "
        f"db={settings.database_url} "
        f"keep_db={keep_db}"
    )
    results: list[CaseResult] = []
    if keep_db:
        async with SessionLocal() as session:
            await seed(session)
    for case in CASES:
        result = await _run_case(case, keep_db=keep_db)
        results.append(result)
        _print_result(result)

    passed = sum(1 for result in results if result.passed)
    print(f"SUMMARY: {passed}/{len(results)} live main-path cases passed")
    print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))
    return 1 if passed != len(results) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when any live case fails (default: report only, exit 0)",
    )
    parser.add_argument(
        "--keep-db",
        action="store_true",
        help="do not reset the configured database before each case",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.llm_api_key or not settings.llm_base_url:
        print(
            "SKIPPED: OPSCONDUCTOR_LLM_API_KEY and OPSCONDUCTOR_LLM_BASE_URL "
            "must be set for the live smoke run"
        )
        return 0

    settings.stub_llm = False
    try:
        exit_code = asyncio.run(_run(keep_db=args.keep_db))
    except Exception as exc:  # noqa: BLE001 - setup errors are reported, not raised
        print(f"SMOKE SETUP ERROR: {type(exc).__name__}: {exc}")
        return 1
    if args.strict:
        return exit_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
