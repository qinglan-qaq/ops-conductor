"""基于 LangGraph 的执行层：对已审批的计划节点做 dry-run、写入、校验与补偿。

执行器在构造时绑定单个租户，任务、审批与 ``task_step`` 查询都限定在该租户内。
审批门禁位于本模块之外（Task 11 负责）：写入是否放行只由持久化的审批行决定，
不信任调用方传入的标志。

Invariants:

- Task 11 的审批行是唯一的写入门禁；``pending`` 或 ``expired`` 审批会让任务
  回到 ``awaiting_approval``，且不写入任何内容。
- dry-run 任一节点失败都会短路：整个运行在任何真实写入之前中止，因此无需补偿。
- 工具调用的幂等键固定为 ``task_id:node_id``；已成功的 ``TaskStep`` 在重复执行
  时直接重放，不再调用工具。
- 补偿范围：校验失败是全局失败，补偿全部已完成的写入；写入失败时只补偿失败
  订单已完成的节点，成功订单的写入保留。
- 执行器不持有任务级锁；可重入性依赖持久化的 ``task_step`` 与工具幂等键。
"""

import uuid
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opsconductor.domain.enums import ApprovalStatus, StepStatus, TaskStatus
from opsconductor.domain.models import Approval, TaskRun, TaskStep
from opsconductor.observability.trace import TraceRecorder
from opsconductor.orchestrator.graph import ExecutionState, build_graph
from opsconductor.orchestrator.verifier import Verifier

WRITE_ACTIONS = {"split_order", "change_address"}
TOOL_NAMES = {
    "split_order": "order_split",
    "change_address": "order_change_address",
}
COMPENSATION_TOOLS = {
    "split_order": "order_revert_split",
    "change_address": "order_revert_address",
}
COMPENSATION_TOOL_NAMES = frozenset(COMPENSATION_TOOLS.values())
UNRESOLVED_APPROVAL_STATUSES = {
    ApprovalStatus.pending.value,
    ApprovalStatus.expired.value,
}


class ExecutionResult(BaseModel):
    """一次执行器运行的最终结果，同时作为任务 ``result`` 的持久化载荷。

    Attributes:
        task_id: 被执行的运营任务 ID。
        status: 最终 ``TaskStatus`` 值。
        reason: 状态的人类可读原因；成功时为空。
        verified: 确定性校验是否通过。
        succeeded: 写入成功的计划节点 ID 列表。
        skipped: 被审批拒绝或跳过的计划节点 ID 列表。
        failed: 写入失败的计划节点 ID 列表。
        compensated: 已成功补偿的计划节点 ID 列表。
        failed_compensations: 补偿失败的计划节点 ID 列表。
    """

    task_id: str
    status: str
    reason: str = ""
    verified: bool = False
    succeeded: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)
    compensated: list[str] = Field(default_factory=list)
    failed_compensations: list[str] = Field(default_factory=list)


class ToolClient(Protocol):
    """可注入的 ERP 工具调用客户端。

    Note:
        ``ErpToolClient`` 是生产绑定；测试可传入内存实现来记录调用或注入故障。
        工具抛出异常即视为该节点失败。
    """

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _utcnow() -> datetime:
    return datetime.now(UTC)


class _TracedNodes:
    """把每个图节点包装为一个已提交的生产 trace span。

    每个节点执行完成后立即提交，因此检查点线程只是一次调用内的便利设施，
    持久化的 ``task_step`` 与任务状态才是重入时的真实来源。
    """

    def __init__(self, executor: "TaskExecutor") -> None:
        self._executor = executor

    async def _run(
        self, name: str, state: ExecutionState, node: Any
    ) -> dict[str, Any]:
        task_id = UUID(state["task_id"])
        async with TraceRecorder(self._executor.session).start(
            name,
            task_id=task_id,
            tenant_id=self._executor.tenant_id,
            attributes={"source": "production", "node": name},
        ):
            result = await node(state)
        await self._executor.session.commit()
        return result

    async def load(self, state: ExecutionState) -> dict[str, Any]:
        return await self._run("executor.load", state, self._executor.load)

    async def dry_run(self, state: ExecutionState) -> dict[str, Any]:
        return await self._run("executor.dry_run", state, self._executor.dry_run)

    async def execute(self, state: ExecutionState) -> dict[str, Any]:
        return await self._run("executor.execute", state, self._executor.execute)

    async def verify(self, state: ExecutionState) -> dict[str, Any]:
        return await self._run("executor.verify", state, self._executor.verify)

    async def compensate(self, state: ExecutionState) -> dict[str, Any]:
        return await self._run(
            "executor.compensate", state, self._executor.compensate
        )

    async def report(self, state: ExecutionState) -> dict[str, Any]:
        return await self._run("executor.report", state, self._executor.report)


class TaskExecutor:
    """通过 LangGraph 执行状态机运行已审批的计划节点。

    执行器在构造时绑定单个租户；任务、审批和 task-step 查询都限定在该租户内。
    审批决策只读取 Task 11 的审批行，绝不根据调用方传入的布尔值推断。

    Attributes:
        session: 用于读写任务、步骤、审批与 trace 的会话。
        tool_client: 注入的 ERP 工具客户端。
        tenant_id: 该执行器唯一可访问的租户。
        verifier: 确定性后置校验器，默认使用 :class:`Verifier`。

    Note:
        执行器不获取任务级锁：重复执行依赖成功的 ``TaskStep`` 重放与工具幂等键，
        不会重复产生业务副作用。
    """

    def __init__(
        self,
        session: AsyncSession,
        tool_client: ToolClient,
        tenant_id: UUID | str,
        verifier: Verifier | None = None,
    ) -> None:
        self.session = session
        self.tool_client = tool_client
        self.tenant_id = UUID(str(tenant_id))
        self.verifier = verifier or Verifier(session)
        self._graph = build_graph(_TracedNodes(self))

    async def start(self, task_id: UUID | str) -> ExecutionResult:
        """执行一个审批决策已全部落定的任务。

        Args:
            task_id: 要执行的任务 ID；必须属于执行器的租户。

        Returns:
            最终状态、原因以及按结果分组的节点 ID。

        Raises:
            ValueError: ``task_id`` 无法解析为 UUID 时由 ``UUID`` 转换抛出。

        Note:
            任务缺失、计划缺失、存在未解决审批或 dry-run 失败都会收敛为一条
            最终报告，而不是向调用方抛出异常。
        """

        return await self._invoke(task_id)

    async def resume(
        self, task_id: UUID | str, approved: bool
    ) -> ExecutionResult:
        """重新进入执行；持久化的审批行才是权威。

        Args:
            task_id: 要重新执行的任务 ID。
            approved: 为接口兼容而保留的布尔参数，会被忽略。

        Returns:
            与 :meth:`start` 相同的最终执行结果。

        Note:
            ``approved`` 永远不会绕过 Task 11 门禁：只有审批行为 ``approved``
            的节点才会执行，因此传 ``True`` 也不会写入未审批节点。
        """

        del approved
        return await self.start(task_id)

    async def _invoke(self, task_id: UUID | str) -> ExecutionResult:
        """以全新的线程 ID 运行一次完整图流程。

        每次调用生成新的 ``thread_id``，因此检查点不跨调用复用；重入的正确性
        来自持久化的 ``task_step`` 与任务状态。若图没有产出报告，则回退为
        ``failed`` 结果。
        """
        initial: ExecutionState = {
            "task_id": str(task_id),
            "tenant_id": str(self.tenant_id),
            "gate": "",
            "reason": "",
            "plan": {},
            "executable": [],
            "rejected": [],
            "skipped_writes": [],
            "results": {},
            "completed": [],
            "succeeded": [],
            "failed": [],
            "compensated": [],
            "failed_compensations": [],
            "verified": False,
            "verification_reason": "",
            "final_status": "",
            "report": {},
        }
        # A fresh thread id per invocation makes the checkpointer disposable:
        # task_step/database state is the durable source of truth for re-entry.
        config = {
            "configurable": {
                "thread_id": f"{task_id}:{uuid.uuid4().hex}",
            }
        }
        final = await self._graph.ainvoke(initial, config)
        report = final.get("report") or {
            "task_id": str(task_id),
            "status": TaskStatus.failed.value,
            "reason": "execution graph produced no report",
        }
        return ExecutionResult.model_validate(report)

    async def _load_task(self, task_id: UUID) -> TaskRun | None:
        return await self.session.scalar(
            select(TaskRun).where(
                TaskRun.id == task_id,
                TaskRun.tenant_id == self.tenant_id,
            )
        )

    # Graph nodes ---------------------------------------------------------

    async def load(self, state: ExecutionState) -> dict[str, Any]:
        """加载任务、解析审批并决定是否进入执行。

        Args:
            state: 初始执行状态，至少包含 ``task_id``。

        Returns:
            状态增量：放行时包含 ``gate="execute"``、计划、可执行/被拒节点与
            重置的累积字段；不可执行时包含 ``gate="report"``、``reason`` 与
            ``final_status``。

        Note:
            存在 ``pending`` 或 ``expired`` 审批时直接路由到 report 并返回
            ``awaiting_approval``，不写入任何内容。任务被放行后会把状态置为
            ``running`` 并提交。没有 ``approved`` 审批行的写入节点进入
            ``rejected``，非写入节点稍后统一记为跳过。
        """

        task_id = UUID(state["task_id"])
        task = await self._load_task(task_id)
        if task is None:
            return {
                "gate": "report",
                "reason": f"task {task_id} not found for this tenant",
                "final_status": TaskStatus.failed.value,
            }
        if task.plan is None:
            return {
                "gate": "report",
                "reason": f"task {task_id} has no plan",
                "final_status": TaskStatus.failed.value,
            }

        approvals = list(
            (
                await self.session.scalars(
                    select(Approval).where(
                        Approval.task_id == task.id,
                        Approval.tenant_id == self.tenant_id,
                    )
                )
            ).all()
        )
        if any(
            approval.status in UNRESOLVED_APPROVAL_STATUSES
            for approval in approvals
        ):
            return {
                "gate": "report",
                "reason": "task has pending or expired approvals",
                "final_status": TaskStatus.awaiting_approval.value,
            }

        plan = task.plan
        approval_status = {
            (approval.action, str(approval.order_id)): approval.status
            for approval in approvals
        }
        executable: list[str] = []
        rejected: list[str] = []
        for node in plan.get("nodes", []):
            action = node.get("action")
            if action not in WRITE_ACTIONS:
                continue
            node_id = str(node["node_id"])
            status = approval_status.get((action, str(node.get("order_id"))))
            if status == ApprovalStatus.approved.value:
                executable.append(node_id)
            else:
                rejected.append(node_id)

        if task.status != TaskStatus.running.value:
            task.status = TaskStatus.running.value
            await self.session.commit()

        return {
            "gate": "execute",
            "reason": "",
            "tenant_id": str(task.tenant_id),
            "plan": plan,
            "executable": executable,
            "rejected": rejected,
            "results": {},
            "completed": [],
            "succeeded": [],
            "failed": [],
            "compensated": [],
            "failed_compensations": [],
            "verified": False,
            "verification_reason": "",
            "final_status": "",
        }

    async def dry_run(self, state: ExecutionState) -> dict[str, Any]:
        """在执行任何真实写入之前对所有已审批写入节点做 dry-run。

        Args:
            state: 包含可执行节点、计划与累积结果的执行状态。

        Returns:
            更新后的 ``results``、``completed``、``succeeded``、``failed``
            与 ``skipped_writes``。

        Note:
            已成功（``succeeded``）的 ``TaskStep`` 直接重放其输出，不再调用
            工具。任一节点 dry-run 失败都会让本次运行在任何写入之前中止，
            因此无需补偿；其余未执行的计划节点仍会各写一条跳过步骤，失败节点
            留下 ``failed`` 步骤。
        """

        task = await self._execution_task(state)
        if task is None:
            return {}
        plan_by_id = self._plan_by_id(state)
        results = dict(state.get("results") or {})
        completed = list(state.get("completed") or [])
        succeeded = list(state.get("succeeded") or [])
        failed = list(state.get("failed") or [])

        for node_id in state.get("executable", []):
            node = plan_by_id.get(node_id)
            if node is None:
                failed.append(node_id)
                continue
            step = await self._existing_step(task.id, node_id)
            if step is not None and step.status == StepStatus.succeeded.value:
                results[node_id] = step.output or {}
                completed.append(node_id)
                succeeded.append(node_id)
                continue

            action = node.get("action")
            tool = TOOL_NAMES.get(action) if isinstance(action, str) else None
            try:
                arguments = self._write_arguments(task, node, dry_run=True)
            except Exception as exc:  # malformed plan node
                await self._fail_step(
                    task, node, {}, f"dry run failed: {exc}"
                )
                failed.append(node_id)
                continue
            assert tool is not None  # _write_arguments rejects unknown actions
            await self._begin_step(task, node, arguments)
            try:
                await self._call_tool(task, tool, arguments)
            except Exception as exc:  # noqa: BLE001 - any tool error is a node failure
                await self._fail_step(task, node, arguments, f"dry run failed: {exc}")
                failed.append(node_id)

        skipped_writes = list(state.get("skipped_writes") or [])
        if failed:
            # Abort before any write. Nothing written in this run needs
            # compensation, but every remaining plan node still gets a step.
            skipped_writes.extend(
                await self._record_skipped_nodes(
                    task,
                    state,
                    unexecuted_reason="not executed after dry-run failure",
                )
            )

        return {
            "results": results,
            "completed": _unique(completed),
            "succeeded": _unique(succeeded),
            "failed": _unique(failed),
            "skipped_writes": _unique(skipped_writes),
        }

    async def execute(self, state: ExecutionState) -> dict[str, Any]:
        """执行已审批的写入节点，并为每个计划节点记录一条步骤。

        Args:
            state: dry-run 之后包含可执行节点与计划的状态。

        Returns:
            更新后的 ``results``、``completed``、``succeeded``、``failed``
            与 ``skipped_writes``。

        Note:
            已成功的步骤会被重放并跳过，保证重复执行不重复写入。同一订单的
            某节点失败后，该订单剩余节点会记为跳过而不继续写入，其他订单不受
            影响。工具调用使用 ``task_id:node_id`` 作为幂等键。
        """

        task = await self._execution_task(state)
        if task is None:
            return {}
        plan_by_id = self._plan_by_id(state)
        results = dict(state.get("results") or {})
        completed = list(state.get("completed") or [])
        succeeded = list(state.get("succeeded") or [])
        failed = list(state.get("failed") or [])
        skipped_writes = list(state.get("skipped_writes") or [])
        failed_orders: set[str] = set()

        for node_id in state.get("executable", []):
            node = plan_by_id.get(node_id)
            if node is None:
                continue
            step = await self._existing_step(task.id, node_id)
            if step is not None and step.status == StepStatus.succeeded.value:
                continue
            if node_id in failed:
                continue
            order_key = str(node.get("order_id"))
            if order_key in failed_orders:
                await self._skip_step(
                    task,
                    node,
                    f"not executed after failure for order {order_key}",
                )
                skipped_writes.append(node_id)
                continue

            try:
                tool = TOOL_NAMES[node["action"]]
                arguments = self._write_arguments(task, node, dry_run=False)
            except Exception as exc:  # malformed plan node
                await self._fail_step(task, node, {}, f"execution failed: {exc}")
                failed.append(node_id)
                failed_orders.add(order_key)
                continue
            await self._begin_step(task, node, arguments)
            try:
                output = await self._call_tool(task, tool, arguments)
            except Exception as exc:  # noqa: BLE001 - any tool error is a node failure
                await self._fail_step(
                    task, node, arguments, f"execution failed: {exc}"
                )
                failed.append(node_id)
                failed_orders.add(order_key)
                continue

            await self._succeed_step(task, node, output)
            results[node_id] = output
            completed.append(node_id)
            succeeded.append(node_id)

        skipped_writes.extend(await self._record_skipped_nodes(task, state))

        return {
            "results": results,
            "completed": _unique(completed),
            "succeeded": _unique(succeeded),
            "failed": _unique(failed),
            "skipped_writes": _unique(skipped_writes),
        }

    async def _record_skipped_nodes(
        self,
        task: TaskRun,
        state: ExecutionState,
        *,
        unexecuted_reason: str | None = None,
    ) -> list[str]:
        """记录被跳过的非写入、被拒绝以及中止的写入节点。

        Args:
            task: 步骤所归属的任务。
            state: 提供计划与拒绝节点集合的执行状态。
            unexecuted_reason: 设置后，dry-run 成功但仍处于 ``running`` 的
                已审批写入节点会以该原因关闭为跳过，因为本次运行在写入前
                已经中止。

        Returns:
            本次新记为跳过的节点 ID 列表。
        """

        skipped: list[str] = []
        rejected = set(state.get("rejected") or [])
        for node in state.get("plan", {}).get("nodes", []):
            node_id = str(node["node_id"])
            action = node.get("action")
            if action in WRITE_ACTIONS:
                if node_id in rejected:
                    await self._skip_step(task, node, "approval rejected")
                    skipped.append(node_id)
                elif unexecuted_reason is not None:
                    step = await self._existing_step(task.id, node_id)
                    if (
                        step is not None
                        and step.status == StepStatus.running.value
                    ):
                        await self._skip_step(task, node, unexecuted_reason)
                        skipped.append(node_id)
            else:
                await self._skip_step(task, node, f"non-write action: {action}")
        return skipped

    async def verify(self, state: ExecutionState) -> dict[str, Any]:
        """对已执行的写入运行确定性后置校验。

        Args:
            state: 包含 ``gate``、计划、结果与失败节点列表的执行状态。

        Returns:
            包含 ``verified`` 与 ``verification_reason`` 的状态增量；未进入
            执行分支时返回空字典。

        Note:
            有写入失败时不再校验，直接把失败节点汇总为原因。校验器抛出的任何
            异常都视为校验失败，交由补偿节点处理；校验本身只读，不写业务数据。
        """

        if state.get("gate") != "execute":
            return {}
        failed = state.get("failed") or []
        if failed:
            return {
                "verified": False,
                "verification_reason": "write execution failed: "
                + ", ".join(failed),
            }

        task = await self._execution_task(state)
        if task is None:
            return {
                "verified": False,
                "verification_reason": "task disappeared before verification",
            }
        try:
            result = await self.verifier.verify(
                task,
                state.get("plan") or {},
                state.get("results") or {},
            )
        except Exception as exc:  # noqa: BLE001 - verification errors compensate
            return {
                "verified": False,
                "verification_reason": f"verifier error: {exc}",
            }
        return {"verified": result.passed, "verification_reason": result.reason}

    async def compensate(self, state: ExecutionState) -> dict[str, Any]:
        """按完成顺序逆序补偿失败订单已完成的写入。

        Args:
            state: 包含已完成节点、失败节点、计划与结果的执行状态。

        Returns:
            包含 ``compensated`` 与 ``failed_compensations`` 的状态增量；没有
            需要补偿的节点时返回空字典。

        Note:
            校验失败是全局的，此时补偿每个已完成的写入。写入失败则按订单归属
            补偿：只处理失败订单已完成的节点，成功订单的写入保持不动。缺失
            补偿工具或补偿调用失败都会记为补偿失败，不会中断其余节点的补偿。
        """

        completed = state.get("completed") or []
        if not completed:
            return {}
        task = await self._execution_task(state)
        if task is None:
            return {}
        plan_by_id = self._plan_by_id(state)
        failed = state.get("failed") or []
        if failed:
            failed_orders = {
                str(plan_by_id[node_id].get("order_id"))
                for node_id in failed
                if node_id in plan_by_id
            }
            completed = [
                node_id
                for node_id in completed
                if node_id in plan_by_id
                and str(plan_by_id[node_id].get("order_id")) in failed_orders
            ]
            if not completed:
                return {}
        results = dict(state.get("results") or {})
        compensated: list[str] = []
        failures: list[str] = []

        for node_id in reversed(completed):
            node = plan_by_id.get(node_id)
            if node is None:
                failures.append(node_id)
                continue
            action = node.get("action")
            tool = (
                COMPENSATION_TOOLS.get(action)
                if isinstance(action, str)
                else None
            )
            output = results.get(node_id) or {}
            if tool is None:
                await self._compensation_failed_step(
                    task, node, output, "no compensation tool for action"
                )
                failures.append(node_id)
                continue
            try:
                arguments = self._compensation_arguments(task, node, output)
                compensation = await self._call_tool(task, tool, arguments)
            except Exception as exc:  # noqa: BLE001 - compensation failure is recorded
                await self._compensation_failed_step(task, node, output, str(exc))
                failures.append(node_id)
                continue
            await self._compensated_step(task, node, output, compensation)
            compensated.append(node_id)

        return {
            "compensated": _unique(compensated),
            "failed_compensations": _unique(failures),
        }

    async def report(self, state: ExecutionState) -> dict[str, Any]:
        """持久化最终任务状态并返回执行结果。

        Args:
            state: 执行结束时的状态。

        Returns:
            包含 ``final_status`` 与 ``report`` 的状态增量。

        Note:
            门禁未放行时按 ``final_status`` 或 ``failed`` 落报告，不改写任务。
            进入执行分支时按 :meth:`_final_status` 映射状态，把报告写入
            ``task.result``，仅在 ``failed`` 时写入 ``task.error``，并提交。
        """

        if state.get("gate") != "execute":
            status = state.get("final_status") or TaskStatus.failed.value
            reason = state.get("reason") or "task could not be executed"
            report = self._build_report(state, status, reason)
            return {"final_status": status, "report": report}

        status = self._final_status(state)
        reason = self._final_reason(state, status)
        report = self._build_report(state, status, reason)
        task = await self._execution_task(state)
        if task is not None:
            task.status = status
            task.result = report
            task.error = reason if status == TaskStatus.failed.value else None
            await self.session.commit()
        return {"final_status": status, "report": report}

    # Execution helpers ---------------------------------------------------

    async def _execution_task(
        self, state: ExecutionState
    ) -> TaskRun | None:
        return await self._load_task(UUID(state["task_id"]))

    @staticmethod
    def _plan_by_id(state: ExecutionState) -> dict[str, dict[str, Any]]:
        return {
            str(node["node_id"]): node
            for node in state.get("plan", {}).get("nodes", [])
        }

    async def _call_tool(
        self, task: TaskRun, tool: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """调用一个 ERP 工具，并为它提交一条生产 tool span。

        Args:
            task: 该调用归属的任务。
            tool: 工具名，例如 ``order_split``。
            arguments: 工具参数，包含幂等键与 ``dry_run`` 标记。

        Returns:
            工具返回的字典结果。

        Raises:
            Exception: 原样重新抛出工具抛出的异常。

        Note:
            span 属性记录 ``phase``（``dry_run``、``execute`` 或
            ``compensation``）、订单与幂等键，即使工具失败也会提交，因此失败
            的写入与补偿仍会出现在 trace 时间线上。
        """

        if arguments.get("dry_run") is True:
            phase = "dry_run"
        elif tool in COMPENSATION_TOOL_NAMES:
            phase = "compensation"
        else:
            phase = "execute"
        attributes = {
            "source": "production",
            "phase": phase,
            "tool": tool,
            "order_id": str(arguments.get("order_id") or ""),
            "idempotency_key": str(arguments.get("idempotency_key") or ""),
        }
        error: Exception | None = None
        result: dict[str, Any] | None = None
        async with TraceRecorder(self.session).start(
            f"tool.{tool}",
            task_id=task.id,
            tenant_id=self.tenant_id,
            attributes=attributes,
        ) as span:
            try:
                result = await self.tool_client.call(tool, arguments)
            except Exception as exc:
                error = exc
                span.attributes = {
                    **(span.attributes or {}),
                    "status": "error",
                    "error": str(exc)[:200],
                }
            else:
                span.attributes = {
                    **(span.attributes or {}),
                    "status": "ok",
                }
        await self.session.commit()
        if error is not None:
            raise error
        assert result is not None
        return result

    def _write_arguments(
        self,
        task: TaskRun,
        node: dict[str, Any],
        *,
        dry_run: bool,
    ) -> dict[str, Any]:
        """构造写入工具参数，并校验动作与计划参数的形状。

        Args:
            task: 提供租户、任务与操作者的任务。
            node: 计划节点，必须包含受支持的 ``action``。
            dry_run: 是否以 dry-run 模式调用。

        Returns:
            含 ``tenant_id``、``order_id``、幂等键 ``task_id:node_id``、
            ``dry_run``、``task_id`` 与 ``actor_id`` 的参数；拆分节点附带
            ``shipments``，改址节点附带 ``address``。

        Raises:
            ValueError: 动作不受支持，或拆分/改址节点缺少必需参数。
        """
        action = node["action"]
        if action not in TOOL_NAMES:
            raise ValueError(f"unsupported write action {action!r}")
        params = node.get("params") or {}
        arguments: dict[str, Any] = {
            "tenant_id": str(task.tenant_id),
            "order_id": str(node.get("order_id")),
            "idempotency_key": f"{task.id}:{node['node_id']}",
            "dry_run": dry_run,
            "task_id": str(task.id),
            "actor_id": str(task.user_id),
        }
        if action == "split_order":
            shipments = params.get("shipments")
            if not isinstance(shipments, list) or not shipments:
                raise ValueError(
                    f"split node {node['node_id']} has no shipments"
                )
            arguments["shipments"] = shipments
        else:
            address = params.get("address")
            if address is None:
                raise ValueError(
                    f"change_address node {node['node_id']} has no address"
                )
            arguments["address"] = address
        return arguments

    def _compensation_arguments(
        self,
        task: TaskRun,
        node: dict[str, Any],
        output: dict[str, Any],
    ) -> dict[str, Any]:
        """构造补偿工具参数。

        Args:
            task: 提供租户与任务标识的任务。
            node: 被补偿的计划节点。
            output: 原写入返回的结果，改址补偿需要其中的 ``before`` 快照。

        Returns:
            幂等键为 ``task_id:node_id:compensate`` 的参数；改址补偿额外携带
            ``before_address``。

        Raises:
            ValueError: 改址节点缺少可用的 ``before`` 地址快照。
        """
        arguments: dict[str, Any] = {
            "tenant_id": str(task.tenant_id),
            "order_id": str(node.get("order_id")),
            "idempotency_key": f"{task.id}:{node['node_id']}:compensate",
            "task_id": str(task.id),
        }
        if node["action"] == "change_address":
            before = output.get("before") if isinstance(output, dict) else None
            if not isinstance(before, dict) or not before:
                raise ValueError(
                    f"node {node['node_id']} has no before-address snapshot"
                )
            arguments["before_address"] = before
        return arguments

    def _build_report(
        self, state: ExecutionState, status: str, reason: str
    ) -> dict[str, Any]:
        result = ExecutionResult(
            task_id=state["task_id"],
            status=status,
            reason=reason,
            verified=bool(state.get("verified")),
            succeeded=_unique(list(state.get("succeeded") or [])),
            skipped=_unique(
                list(state.get("rejected") or [])
                + list(state.get("skipped_writes") or [])
            ),
            failed=_unique(list(state.get("failed") or [])),
            compensated=_unique(list(state.get("compensated") or [])),
            failed_compensations=_unique(
                list(state.get("failed_compensations") or [])
            ),
        )
        return result.model_dump()

    @staticmethod
    def _final_status(state: ExecutionState) -> str:
        """把执行状态映射为最终 ``TaskStatus`` 值。

        映射顺序：

        - 存在补偿失败 -> ``partially_compensated``。
        - 全部失败（无任何完成或补偿）-> ``failed``。
        - 存在拒绝、跳过、失败或补偿 -> ``partially_succeeded``。
        - 其余情况 -> ``succeeded``。
        """
        if state.get("failed_compensations"):
            return TaskStatus.partially_compensated.value
        failed = state.get("failed") or []
        completed = state.get("completed") or []
        compensated = state.get("compensated") or []
        if failed and not completed and not compensated:
            return TaskStatus.failed.value
        if (
            state.get("rejected")
            or state.get("skipped_writes")
            or failed
            or compensated
        ):
            return TaskStatus.partially_succeeded.value
        return TaskStatus.succeeded.value

    @staticmethod
    def _final_reason(state: ExecutionState, status: str) -> str:
        if status == TaskStatus.partially_compensated.value:
            return "compensation failed for: " + ", ".join(
                state.get("failed_compensations") or []
            )
        if status == TaskStatus.failed.value:
            failed = state.get("failed") or []
            if failed:
                return "write execution failed: " + ", ".join(failed)
            return state.get("verification_reason") or state.get("reason") or ""
        if status == TaskStatus.partially_succeeded.value:
            return state.get("verification_reason") or (
                "some approved writes were skipped or compensated"
            )
        return ""

    # Task step helpers ---------------------------------------------------

    async def _existing_step(
        self, task_id: UUID, node_id: str
    ) -> TaskStep | None:
        """返回租户内某任务某节点第一次尝试的步骤（``attempt == 1``）。"""
        return await self.session.scalar(
            select(TaskStep).where(
                TaskStep.tenant_id == self.tenant_id,
                TaskStep.task_id == task_id,
                TaskStep.node_id == node_id,
                TaskStep.attempt == 1,
            )
        )

    async def _begin_step(
        self,
        task: TaskRun,
        node: dict[str, Any],
        arguments: dict[str, Any],
    ) -> None:
        """把节点步骤置为 ``running`` 并立即提交。

        已存在的步骤会被重置输入、输出与错误，使其可安全重入；``started_at``
        在每次开始时刷新。
        """
        step = await self._existing_step(task.id, node["node_id"])
        now = _utcnow()
        payload = {"args": arguments}
        if step is None:
            self.session.add(
                TaskStep(
                    tenant_id=task.tenant_id,
                    task_id=task.id,
                    node_id=node["node_id"],
                    status=StepStatus.running.value,
                    attempt=1,
                    input=payload,
                    started_at=now,
                )
            )
        else:
            step.status = StepStatus.running.value
            step.input = payload
            step.output = None
            step.error = None
            step.started_at = now
            step.finished_at = None
        await self.session.commit()

    async def _succeed_step(
        self,
        task: TaskRun,
        node: dict[str, Any],
        output: dict[str, Any],
    ) -> None:
        step = await self._existing_step(task.id, node["node_id"])
        if step is None:
            return
        step.status = StepStatus.succeeded.value
        step.output = output
        step.error = None
        step.finished_at = _utcnow()
        await self.session.commit()

    async def _fail_step(
        self,
        task: TaskRun,
        node: dict[str, Any],
        arguments: dict[str, Any],
        error: str,
    ) -> None:
        step = await self._existing_step(task.id, node["node_id"])
        now = _utcnow()
        if step is None:
            self.session.add(
                TaskStep(
                    tenant_id=task.tenant_id,
                    task_id=task.id,
                    node_id=node["node_id"],
                    status=StepStatus.failed.value,
                    attempt=1,
                    input={"args": arguments},
                    error=error[:1000],
                    started_at=now,
                    finished_at=now,
                )
            )
        else:
            step.status = StepStatus.failed.value
            if arguments:
                step.input = {"args": arguments}
            step.output = None
            step.error = error[:1000]
            step.finished_at = now
        await self.session.commit()

    async def _skip_step(
        self, task: TaskRun, node: dict[str, Any], reason: str
    ) -> None:
        """把节点步骤标记为跳过，但不覆盖已经成功的步骤。"""
        step = await self._existing_step(task.id, node["node_id"])
        if step is not None and step.status == StepStatus.succeeded.value:
            return
        now = _utcnow()
        payload = {
            "node_id": node["node_id"],
            "action": node.get("action"),
            "reason": reason,
        }
        if step is None:
            self.session.add(
                TaskStep(
                    tenant_id=task.tenant_id,
                    task_id=task.id,
                    node_id=node["node_id"],
                    status=StepStatus.skipped.value,
                    attempt=1,
                    input=payload,
                    error=reason[:1000],
                    started_at=now,
                    finished_at=now,
                )
            )
        else:
            step.status = StepStatus.skipped.value
            step.input = payload
            step.output = None
            step.error = reason[:1000]
            step.finished_at = now
        await self.session.commit()

    async def _compensated_step(
        self,
        task: TaskRun,
        node: dict[str, Any],
        output: dict[str, Any],
        compensation: dict[str, Any],
    ) -> None:
        step = await self._existing_step(task.id, node["node_id"])
        if step is None:
            return
        step.status = StepStatus.compensated.value
        step.output = {"result": output, "compensation": compensation}
        step.error = None
        step.finished_at = _utcnow()
        await self.session.commit()

    async def _compensation_failed_step(
        self,
        task: TaskRun,
        node: dict[str, Any],
        output: dict[str, Any],
        error: str,
    ) -> None:
        step = await self._existing_step(task.id, node["node_id"])
        now = _utcnow()
        message = f"compensation failed: {error}"[:1000]
        if step is None:
            self.session.add(
                TaskStep(
                    tenant_id=task.tenant_id,
                    task_id=task.id,
                    node_id=node["node_id"],
                    status=StepStatus.failed.value,
                    attempt=1,
                    input={"node_id": node["node_id"]},
                    output={"result": output},
                    error=message,
                    started_at=now,
                    finished_at=now,
                )
            )
        else:
            step.status = StepStatus.failed.value
            step.output = {"result": output}
            step.error = message
            step.finished_at = now
        await self.session.commit()
