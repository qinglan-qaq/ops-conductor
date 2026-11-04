"""LangGraph execution state machine: load -> dry_run -> execute -> verify.

The approval gate lives outside this graph (Task 11 owns it). Execution only
starts once approval decisions are resolved, so no ``interrupt`` appears on the
normal path. Verification failures are routed through compensation before the
final report is written.
"""

from typing import Any, Protocol, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph


class ExecutionState(TypedDict, total=False):
    """JSON-friendly state passed between graph nodes."""

    task_id: str
    tenant_id: str | None
    mode: str
    approved: bool | None
    gate: str
    reason: str
    plan: dict[str, Any]
    executable: list[str]
    rejected: list[str]
    skipped_writes: list[str]
    results: dict[str, dict[str, Any]]
    completed: list[str]
    succeeded: list[str]
    failed: list[str]
    compensated: list[str]
    failed_compensations: list[str]
    verified: bool
    verification_reason: str
    final_status: str
    report: dict[str, Any]


class ExecutionNodes(Protocol):
    """Node provider compiled into the execution graph."""

    async def load(self, state: ExecutionState) -> dict[str, Any]: ...

    async def dry_run(self, state: ExecutionState) -> dict[str, Any]: ...

    async def execute(self, state: ExecutionState) -> dict[str, Any]: ...

    async def verify(self, state: ExecutionState) -> dict[str, Any]: ...

    async def compensate(self, state: ExecutionState) -> dict[str, Any]: ...

    async def report(self, state: ExecutionState) -> dict[str, Any]: ...


def _after_load(state: ExecutionState) -> str:
    return "dry_run" if state.get("gate") == "execute" else "report"


def _after_verify(state: ExecutionState) -> str:
    return "report" if state.get("verified") else "compensate"


def build_graph(nodes: ExecutionNodes):
    """Compile the execution graph with in-memory checkpointing."""

    builder = StateGraph(ExecutionState)
    builder.add_node("load", nodes.load)
    builder.add_node("dry_run", nodes.dry_run)
    builder.add_node("execute", nodes.execute)
    builder.add_node("verify", nodes.verify)
    builder.add_node("compensate", nodes.compensate)
    builder.add_node("report", nodes.report)

    builder.add_edge(START, "load")
    builder.add_conditional_edges(
        "load", _after_load, {"dry_run": "dry_run", "report": "report"}
    )
    builder.add_edge("dry_run", "execute")
    builder.add_edge("execute", "verify")
    builder.add_conditional_edges(
        "verify", _after_verify, {"report": "report", "compensate": "compensate"}
    )
    builder.add_edge("compensate", "report")
    builder.add_edge("report", END)
    return builder.compile(checkpointer=InMemorySaver())
