# 3 分钟演示脚本：订单异常拆单 / 改址可写闭环

本脚本演示一条真实的端到端链路：**提交任务 → 查看计划 → 审批 → 执行 → 验证 → 审计/trace**，最后用既有评测用例演示失败补偿。

- 演示环境：仓库根目录、Git Bash（Windows）或任意 bash；conda 环境 `opsconductor` 已创建。
- 数据库：Docker PostgreSQL 16，主机端口 **15432**；原生 PostgreSQL 12 占用 5432，应用默认值仍为 5432，因此脚本和命令都必须显式设置 15432。
- Redis：MVP 不依赖，`scripts/demo.sh` 不会启动它。
- 模型：演示使用确定性模板 Planner（`OPSCONDUCTOR_STUB_LLM=true`），不需要模型凭据。真实模型冒烟（`scripts/smoke_live.py`）需要 `OPSCONDUCTOR_LLM_API_KEY` / `OPSCONDUCTOR_LLM_BASE_URL`，不在本演示范围内。

## 0. 启动（终端 1，约 30 秒）

```bash
cd /path/to/ops-conductor
bash scripts/demo.sh
```

脚本会依次执行：

1. `docker compose up -d postgres`（只启动 PostgreSQL，不启动 Redis）
2. 等待 `pg_isready`
3. `alembic upgrade head`
4. `python -m opsconductor.domain.seed`
5. `uvicorn opsconductor.api.main:app`

看到 `Uvicorn running on http://127.0.0.1:8000` 后继续。重复执行是安全的：迁移与种子数据都是幂等的。

验证：

```bash
curl -sS http://127.0.0.1:8000/health
# {"status":"ok","version":"0.1.0","env":"development"}
```

## 1. 提交任务（终端 2，0:30–1:00）

```bash
BASE=http://127.0.0.1:8000
IDEMPOTENCY_KEY="demo-$(date +%s)"

# 请求体写入文件：Git Bash 下 curl -d 直接传中文可能被控制台编码破坏，
# 用 --data-binary @file 保证 UTF-8 字节原样发送。
cat > /tmp/ops-task.json <<'JSON'
{"instruction":"处理今天华东仓超时未发货的订单","warehouse":"east","cutoff":"2026-11-04T00:00:00Z"}
JSON

TASK_JSON=$(curl -sS -X POST "$BASE/api/v1/tasks" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-operator-a" \
  -H "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --data-binary @/tmp/ops-task.json)

echo "$TASK_JSON" | python -m json.tool
TASK_ID=$(echo "$TASK_JSON" | python -c "import sys, json; print(json.load(sys.stdin)['id'])")
echo "TASK_ID=$TASK_ID"
```

预期：`status` 为 `awaiting_approval`，计划包含 3 个 `split_order`、1 个 `change_address`、1 个 `block_order`（O1003 库存不足）。O1005 在种子里已经是 `split`，不会进入「超时待处理」查询。

幂等验证（可选，10 秒，需在同一个终端会话中执行）：用同一个 `IDEMPOTENCY_KEY` 再提交一次，返回同一个任务：

```bash
curl -sS -X POST "$BASE/api/v1/tasks" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-operator-a" \
  -H "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --data-binary @/tmp/ops-task.json \
  | python -m json.tool
```

## 2. 查看计划与控制台（1:00–1:20）

```bash
curl -sS "$BASE/api/v1/tasks/$TASK_ID" \
  -H "X-API-Key: dev-operator-a" | python -m json.tool

python -m webbrowser "$BASE/console/tasks/$TASK_ID?api_key=dev-operator-a"
```

控制台展示：计划节点、风险等级（拆单/改址为 L2；批次达到阈值时拆单升 L3）、订单号、审批记录、trace 时间线。

## 3. 审批（1:20–1:50）

使用审批人身份 `dev-approver-a`（L2/L3 均可审批；纯 operator 不能审批 L3）：

```bash
curl -sS -X POST "$BASE/api/v1/tasks/$TASK_ID/approve" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-approver-a" \
  -d '{"comment":"demo approval"}' | python -m json.tool
```

预期：`status` 从 `awaiting_approval` 变为 `running`，4 条写操作 Approval 全部为 `approved`。

也可以走控制台：用 `?api_key=dev-approver-a` 打开任务详情，填写 comment 后提交审批表单。

注意：审批是**数据库中的任务/审批状态机**，不是 LangGraph interrupt。执行前必须已有 `approved` 的 Approval 行；没有审批行或审批被拒绝的节点会被跳过。

## 4. 执行（1:50–2:30）

```bash
curl -sS -X POST "$BASE/api/v1/tasks/$TASK_ID/execute" \
  -H "X-API-Key: dev-operator-a" | python -m json.tool
```

执行入口是 `POST /api/v1/tasks/{task_id}/execute`，内部使用 `TaskExecutor` + 真实 `ErpToolClient`（MCP stdio，带认证租户）：

1. `load`：读取已解决的审批行，只允许 `approved` 节点执行。
2. `dry_run`：先对全部写节点做 dry-run，任何失败都在写入前中止。
3. `execute`：按订单执行拆单/改址，幂等键为 `{task_id}:{node_id}`。
4. `verify`：确定性后置条件校验（订单状态、发货单行、库存、审计行）。
5. `compensate`：验证或写入失败时按逆序补偿；写失败按订单隔离。
6. `report`：写回 `TaskRun.status` / `TaskRun.result`。

预期：`status` 为 `succeeded`，`result.verified` 为 `true`，`result.succeeded` 含 4 个写节点，`result.failed` 为空。O1001/O1004/O1006 变为 `split`，O1002 地址更新；O1003 的 `block_order` 节点在 `task_step` 中记为 `skipped`（非写节点不进入 `result.skipped`），不产生写入。O1005 已是 `split`，不在本次超时查询中。

重复执行同一任务（可选）：再次调用 execute 不会重复写入，已成功的 task_step 会被跳过。

## 5. 最终状态、审计与 trace（2:30–3:00）

```bash
curl -sS "$BASE/api/v1/tasks/$TASK_ID" \
  -H "X-API-Key: dev-operator-a" | python -m json.tool

python -m webbrowser "$BASE/console/tasks/$TASK_ID/trace?api_key=dev-operator-a"

docker compose exec -T postgres psql -U ops -d opsconductor -c \
  "SELECT action, entity_type, entity_id FROM audit_log WHERE task_id = '$TASK_ID' ORDER BY created_at;"

docker compose exec -T postgres psql -U ops -d opsconductor -c \
  "SELECT name, started_at, ended_at FROM trace_span WHERE task_id = '$TASK_ID' ORDER BY started_at;"
```

应看到 `plan_task`、`approval`、`executor.load/dry_run/execute/verify/report` 以及 `tool.order_split` / `tool.order_change_address` 等 trace span；审计包含 `approval.approve`、`order.split`、`order.change_address`。

## 失败注入演示（附加，不计入 3 分钟主流程）

MVP 没有为演示新增 HTTP 故障注入开关；失败注入使用仓库中已有的 Golden Task 评测用例（真实执行器 + 真实写服务 + 注入故障），不伪造行为：

```bash
pytest -q \
  "tests/eval/test_golden_tasks.py::test_golden_task[GT-13]" \
  "tests/eval/test_golden_tasks.py::test_golden_task[GT-25]"
```

- **GT-13（后置库存不一致）**：Verifier 读到注入的负库存后否决，执行器补偿已完成的拆单；最终任务 `partially_succeeded`、`verified=false`，发货单取消、库存回滚。
- **GT-25（已执行拆单后验证失败）**：两个订单的拆单都已写入后验证失败，按订单逆序补偿；最终任务 `partially_succeeded`，`result.compensated` 列出补偿节点。

用例定义在 `tests/eval/cases.py`，断言在 `tests/eval/harness.py`。pytest 使用 `opsconductor_test` 数据库（15432），不会污染演示库 `opsconductor`。

## Known gaps（演示口径）

28 条 Golden Tasks 中 23 条完全满足，GT-08/09/12/17/26 以 xfail 显式记录，详见 `docs/KNOWN_GAPS.md`。演示和汇报不得表述为 28/28 全绿；上节 GT-13/GT-25 是已满足的补偿用例，不属于 known gap。

## 3 分钟时间分配

| 时间 | 内容 |
|---|---|
| 0:00–0:30 | 启动 `scripts/demo.sh`，`/health` 验证 |
| 0:30–1:00 | 提交任务，展示计划 JSON 与幂等重放 |
| 1:00–1:20 | 打开控制台，讲解计划、风险、审批与 trace 入口 |
| 1:20–1:50 | 审批人审批，任务进入 `running` |
| 1:50–2:30 | 调用 execute，展示 dry-run → 写入 → 验证结果 |
| 2:30–3:00 | 最终状态、审计 SQL、trace 页面 |
| 附加 | GT-13 / GT-25 失败补偿用例 |

## 演示账号与地址

| 身份 | API Key | 用途 |
|---|---|---|
| tenant-a operator | `dev-operator-a` | 创建任务、发起执行 |
| tenant-a approver | `dev-approver-a` | 审批 L2/L3 |
| tenant-b operator | `dev-operator-b` | 跨租户拒绝演示 |

控制台：`http://127.0.0.1:8000/console/tasks?api_key=dev-operator-a`

## 重置演示数据

```bash
# 警告：会删除 Docker 数据卷中的全部演示数据
docker compose down -v
bash scripts/demo.sh
```

`bash scripts/demo.sh` 本身可以重复执行；只有需要“干净种子状态”（例如订单已被拆单、演示无法再次拆同一单）时才需要删除卷。
