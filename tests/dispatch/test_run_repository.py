"""InMemoryRunRepository 行为测试。"""

from __future__ import annotations

import pytest

from opsconductor.dispatch.adapters.run_memory import InMemoryRunRepository
from opsconductor.dispatch.application.agents import (
    AgentRegistry,
    VerifierAgent,
    build_agents,
)
from opsconductor.dispatch.application.orchestrator import DispatchOrchestrator
from opsconductor.dispatch.application.seed import SEED_GOAL


class _Tools:
    def call(self, tool, params):
        return {"tool": tool, "artifact": f"{tool}.json", "status": "ok"}


class _Clock:
    def now_label(self):
        return "10:50"


def _run(run_id: str):
    orchestrator = DispatchOrchestrator(
        AgentRegistry(build_agents(_Tools())), VerifierAgent(), _Clock()
    )
    return orchestrator.run_agent(SEED_GOAL, run_id=run_id)


def test_save_and_get_returns_deep_copy() -> None:
    repo = InMemoryRunRepository()
    run = _run("run-1")

    repo.save(run)
    retrieved = repo.get("run-1")

    assert retrieved is not None
    assert retrieved is not run
    assert retrieved.steps[0].tool_calls[0].params is not run.steps[0].tool_calls[0].params
    assert retrieved.id == "run-1"


def test_unknown_run_returns_none() -> None:
    assert InMemoryRunRepository().get("missing") is None


def test_list_returns_newest_first_and_respects_limit() -> None:
    repo = InMemoryRunRepository()
    repo.save(_run("run-1"))
    repo.save(_run("run-2"))
    repo.save(_run("run-3"))

    assert [run.id for run in repo.list(2)] == ["run-3", "run-2"]
    assert repo.latest().id == "run-3"


def test_evicts_oldest_when_capacity_exceeded() -> None:
    repo = InMemoryRunRepository(max_runs=2)
    repo.save(_run("run-1"))
    repo.save(_run("run-2"))
    repo.save(_run("run-3"))

    assert repo.get("run-1") is None
    assert repo.get("run-2") is not None
    assert repo.get("run-3") is not None
    assert [run.id for run in repo.list(10)] == ["run-3", "run-2"]


def test_empty_repository_returns_none() -> None:
    assert InMemoryRunRepository().latest() is None
    assert InMemoryRunRepository().list(3) == ()


def test_rejects_invalid_capacity() -> None:
    with pytest.raises(ValueError, match="max_runs"):
        InMemoryRunRepository(max_runs=0)
