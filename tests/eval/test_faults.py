"""Tests for deterministic tool fault injection."""

import asyncio
from typing import Any

import pytest

from opsconductor.tools import faults
from opsconductor.tools.client import ErpToolClient


class RecordingSession:
    """Stand-in for an MCP ClientSession that records tool invocations."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))

        class Result:
            is_error = False
            structured_content = {"ok": True, "tool": name}
            content: list[Any] = []

        return Result()


def test_check_without_faults_is_a_noop():
    faults.check("order_split")


def test_inject_timeout_and_upstream_raise_typed_errors():
    with faults.inject(order_split="timeout"):
        with pytest.raises(TimeoutError, match="order_split timeout"):
            faults.check("order_split")
        faults.check("order_change_address")

    with faults.inject(order_change_address="upstream"):
        with pytest.raises(RuntimeError, match="order_change_address upstream"):
            faults.check("order_change_address")
        faults.check("order_split")


def test_nested_inject_merges_and_restores_outer_faults():
    with faults.inject(order_split="timeout"):
        with faults.inject(order_change_address="upstream"):
            with pytest.raises(TimeoutError):
                faults.check("order_split")
            with pytest.raises(RuntimeError):
                faults.check("order_change_address")

        with pytest.raises(TimeoutError):
            faults.check("order_split")
        faults.check("order_change_address")

    faults.check("order_split")
    faults.check("order_change_address")


def test_injected_fault_is_visible_across_async_tasks():
    async def probe() -> None:
        with pytest.raises(TimeoutError):
            faults.check("order_split")

    async def main() -> None:
        with faults.inject(order_split="timeout"):
            await asyncio.create_task(probe())

    asyncio.run(main())


@pytest.mark.asyncio
async def test_erp_tool_client_checks_faults_before_calling_mcp():
    client = ErpToolClient()
    session = RecordingSession()
    client._session = session

    result = await client.call("order_get", {"tenant_id": "t", "order_id": "o"})
    assert result == {"ok": True, "tool": "order_get"}
    assert [name for name, _ in session.calls] == ["order_get"]

    with faults.inject(order_split="timeout"):
        with pytest.raises(TimeoutError, match="order_split timeout"):
            await client.call("order_split", {"tenant_id": "t", "order_id": "o"})

    assert [name for name, _ in session.calls] == ["order_get"]

    with faults.inject(order_change_address="upstream"):
        with pytest.raises(RuntimeError, match="order_change_address upstream"):
            await client.call(
                "order_change_address", {"tenant_id": "t", "order_id": "o"}
            )

    assert [name for name, _ in session.calls] == ["order_get"]
