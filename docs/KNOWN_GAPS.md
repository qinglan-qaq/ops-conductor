# Known Gaps in the 28 Golden Tasks

This table lists golden cases whose spec outcome is **not fully implemented** by the
current product. They remain in the golden table and are executed, but
`tests/eval/harness.py` marks them `pytest.xfail` after their verifiable
assertions run. Their current passing assertions are not treated as a full
meeting of the spec, and no assertion was weakened to manufacture a green result.

| ID | Category | Scenario | Why it is a known gap | Evidence |
|---|---|---|---|---|
| GT-08 | 校验/状态 | Planner 输出非法计划 | Invalid output is rejected at task creation with HTTP 500 and a full rollback. There is no failed `TaskRun`, failed-step record, or human-handoff artifact for "任务失败，转人工". | `tests/eval/test_golden_tasks.py::test_golden_task[GT-08]` (xfail); `api/routes/tasks.py::create_task` raises before commit. |
| GT-09 | 校验/状态 | 订单不存在 | The case plan contains only the missing order, so the executor ends `failed`; the spec wording says the task is "部分失败" (`partially_succeeded`). `NOT_FOUND` and fail-closed no-write behavior are correct. | `tests/eval/test_golden_tasks.py::test_golden_task[GT-09]` (xfail); task row status `failed`. |
| GT-12 | 库存 | 并发预占冲突 | The write path uses `SELECT ... FOR UPDATE` row-lock waiting and version increments, not the spec's bounded optimistic-lock retry. One task wins; the loser waits, then fails with `INVALID_STATE` without a retry attempt. | `tests/eval/test_golden_tasks.py::test_golden_task[GT-12]` (xfail); failed step: `order ... is 'split', expected 'pending_shipment'`. |
| GT-17 | 审批 | L3 拒绝 | There is no task-level `rejected` status. A rejected batch ends `partially_succeeded` with `rejected` Approval rows and skipped write steps. | `tests/eval/test_golden_tasks.py::test_golden_task[GT-17]` (xfail); `TaskRun.status` and Approval rows. |
| GT-26 | 失败/补偿 | 补偿工具失败 | `partially_compensated` and the failed-compensation node list are recorded, but there is no human-escalation queue or handoff record for "转人工". | `tests/eval/test_golden_tasks.py::test_golden_task[GT-26]` (xfail); `task.result["failed_compensations"]`. |

## Resolved by the hardening pass

- GT-24 now asserts per-order compensation: only the failed order is eligible
  for compensation, and successful orders keep their writes.
- GT-27 now exercises the real API boundary: cross-tenant task reads and
  approval decisions return 403 and commit a `security.access_denied` audit
  row plus a production `security.denied` trace span.
- GT-28 now uses the production approval guard in
  `src/opsconductor/tools/guard.py`; a missing, unapproved, or mismatched write
  context is denied with 403 and an audit row, and the harness no longer owns a
  private authorization decision.

## Not covered by xfail

The remaining 23 cases are fully met: GT-01..07, GT-10, GT-11, GT-13..16,
GT-18..25, GT-27, GT-28. See the Task 14 report for the exact run counts.
