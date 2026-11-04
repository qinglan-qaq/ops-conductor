"""Execution graph: dry-run, write, verify, and compensate approved plan nodes.

The approval gate is external (Task 11). This module assumes approval decisions
are resolved and executes only approved write nodes, recording every plan node
in ``task_step``. Completed writes are compensated in reverse order when
execution or verification fails.
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
    """Final result of one executor run."""

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
    """Injectable ERP tool client; ``ErpToolClient`` is the production binding."""

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _utcnow() -> datetime:
    return datetime.now(UTC)


class _TracedNodes:
    """Wrap every graph node with a committed production trace span."""

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
    """Run approved plan nodes through the LangGraph execution state machine.

    The executor is bound to one tenant at construction; every task, approval,
    and task-step lookup is scoped to that tenant. Approval decisions are read
    from the Task 11 rows, never inferred from a caller-provided flag.
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
        """Execute a task whose approval decisions are already resolved."""

        return await self._invoke(task_id)

    async def resume(
        self, task_id: UUID | str, approved: bool
    ) -> ExecutionResult:
        """Re-enter execution; persisted approval rows are authoritative.

        ``approved`` is accepted for interface compatibility but never bypasses
        the Task 11 gate: only nodes whose approval row is ``approved`` run.
        """

        del approved
        return await self.start(task_id)

    async def _invoke(self, task_id: UUID | str) -> ExecutionResult:
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
        """Load the task, resolve approvals, and decide whether to execute."""

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
        """Dry-run every approved write node before any write is executed."""

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
        """Execute approved write nodes and record every plan node as a step."""

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
        """Record skipped non-write, rejected, and aborted write nodes.

        With ``unexecuted_reason`` set, approved write nodes that are still
        ``running`` from a successful dry run are closed as skipped because the
        run aborted before execution.
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
        """Run deterministic post-condition checks for executed writes."""

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
        """Compensate completed writes for orders that failed execution.

        A verification failure is global, so every completed write is
        compensated. A write/execution failure is order-scoped: only completed
        nodes for the failed order are compensated, and successful orders keep
        their writes.
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
        """Persist the final task status and return the execution result."""

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
        """Call one ERP tool and commit a production tool span for it.

        The span is committed even when the tool raises, so failed writes and
        failed compensations remain visible in the trace timeline.
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
