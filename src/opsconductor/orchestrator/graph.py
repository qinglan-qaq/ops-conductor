"""LangGraph 执行状态机：load -> dry_run -> execute -> verify -> report。

审批门禁位于本图之外（由 Task 11 拥有）。执行只在审批决策全部落定后开始，
因此正常路径上不会出现 ``interrupt``。校验失败先路由到 ``compensate``，再写
最终报告。

Invariants:

- ``load`` 只在门禁放行时进入 ``dry_run``，否则直接进入 ``report``。
- dry-run 存在失败节点时直接进入 ``report``，不经过 ``execute`` 或
  ``compensate``，因为此时尚未发生任何写入。
- ``verify`` 通过才进入 ``report``，否则进入 ``compensate``。
- 所有路径都以 ``report`` 结束。
"""

from typing import Any, Protocol, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph


class ExecutionState(TypedDict, total=False):
    """在图层节点之间传递的 JSON 友好状态。

    所有键都是可选的（``total=False``）；节点只返回自己修改的键，LangGraph
    会把增量合并回整体状态。

    Attributes:
        task_id: 目标任务 ID 的字符串形式。
        tenant_id: 任务所属租户的字符串形式。
        gate: ``load`` 的路由结果：``execute`` 或 ``report``。
        reason: 门禁否决或报告原因。
        plan: 计划载荷，``nodes`` 为节点列表。
        executable: 审批通过、允许执行的写入节点 ID。
        rejected: 没有 ``approved`` 审批行的写入节点 ID。
        skipped_writes: 记为跳过步骤的节点 ID。
        results: 节点 ID 到工具输出的映射。
        completed: 已完成写入的节点 ID。
        succeeded: 写入成功的节点 ID。
        failed: 写入失败的节点 ID。
        compensated: 补偿成功的节点 ID。
        failed_compensations: 补偿失败的节点 ID。
        verified: 确定性校验是否通过。
        verification_reason: 校验失败的原因。
        final_status: 报告阶段解析出的 ``TaskStatus`` 值。
        report: 最终 ``ExecutionResult`` 载荷。
    """

    task_id: str
    tenant_id: str | None
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
    """可编译进执行图的节点提供者。

    生产实现是 :class:`opsconductor.orchestrator.executor.TaskExecutor`；每个
    方法接收当前状态并返回状态增量。
    """

    async def load(self, state: ExecutionState) -> dict[str, Any]: ...

    async def dry_run(self, state: ExecutionState) -> dict[str, Any]: ...

    async def execute(self, state: ExecutionState) -> dict[str, Any]: ...

    async def verify(self, state: ExecutionState) -> dict[str, Any]: ...

    async def compensate(self, state: ExecutionState) -> dict[str, Any]: ...

    async def report(self, state: ExecutionState) -> dict[str, Any]: ...


def _after_load(state: ExecutionState) -> str:
    """门禁放行时进入 dry-run，否则直接报告。"""

    return "dry_run" if state.get("gate") == "execute" else "report"


def _after_dry_run(state: ExecutionState) -> str:
    """dry-run 存在失败节点时直接报告，不进入写入或补偿。"""

    return "report" if state.get("failed") else "execute"


def _after_verify(state: ExecutionState) -> str:
    """校验通过时报告，否则进入补偿。"""

    return "report" if state.get("verified") else "compensate"


def build_graph(nodes: ExecutionNodes):
    """编译带内存检查点的执行图。

    Args:
        nodes: 提供六个图节点实现的节点提供者。

    Returns:
        使用 ``InMemorySaver`` 检查点的已编译图。

    Note:
        检查点仅在一次调用内使用；跨调用的可重入性依赖数据库中的 ``task_step``
        与任务状态。dry-run 失败直接进入 ``report``，不执行补偿。
    """

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
    # A failed dry run aborts before any write; nothing needs compensation.
    builder.add_conditional_edges(
        "dry_run", _after_dry_run, {"execute": "execute", "report": "report"}
    )
    builder.add_edge("execute", "verify")
    builder.add_conditional_edges(
        "verify", _after_verify, {"report": "report", "compensate": "compensate"}
    )
    builder.add_edge("compensate", "report")
    builder.add_edge("report", END)
    return builder.compile(checkpointer=InMemorySaver())
