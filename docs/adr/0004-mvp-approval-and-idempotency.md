# ADR 0004：MVP 审批状态机、幂等作用域与补偿边界

- 状态：已接受
- 日期：2026-11-04

## 背景

MVP 需要把「拆单 / 改址」做成可写闭环，而写操作涉及库存与订单状态。要实现可演示、可测试、可审计的执行路径，必须明确四个问题：

1. 审批发生在哪里：图内暂停（LangGraph `interrupt`）还是图外的持久化状态机？
2. 重复提交、超时重试和补偿重放如何避免重复写入？
3. 「拆单」在领域模型里是子订单还是发货单？
4. 失败后补偿到什么边界，哪些能力明确留作 known gap？

早期任务简报里出现过「审批采用外部任务状态 + LangGraph interrupt」的表述。实际实现（Task 11 与 Task 12）没有使用 `interrupt`：`orchestrator/graph.py` 的注释和代码都表明审批门禁在 LangGraph 之外。本 ADR 记录代码中的真实决策，避免文档继续传播与实现不符的说法。

## 决策

### 1. 审批是持久化的任务/审批状态机，不在 LangGraph 图内暂停

- 任务创建时，`api/routes/tasks.py::create_task` 生成 `Approval` 行：每个需要审批的写节点一行，状态 `pending`，带 `task_id`、`order_id`、`action`、`risk_level`、`expires_at`、`tenant_id`。
- `TaskRun.status` 在有待审批行时为 `awaiting_approval`；无写节点时为 `planned`。
- `orchestrator/approval.py::ApprovalService.decide` 是唯一的审批决策入口：
  - 决定 `approved` / `rejected`，记录 `approver_id`、`comment`、`decided_at`；
  - 拒绝跨租户任务（403）与缺失任务（404）；
  - 过期审批标记为 `expired`，重复相同决策幂等返回，反向决策返回 409；
  - L3 只允许 `approver` / `admin` 角色；
  - 所有待审批行解决后，任务从 `awaiting_approval` 变为 `running`。
- 执行由 `POST /api/v1/tasks/{id}/execute`（Task 15 新增）或内部 `TaskExecutor.start` 触发。`TaskExecutor.load` **重新读取 Approval 行**：
  - 仍有 `pending` / `expired` 行：返回 `awaiting_approval`，不调用任何工具；
  - 只有 `approved` 行对应的节点进入执行；
  - `rejected` 或无匹配审批行的节点被跳过；
  - 调用方无法用「approved 布尔值」绕过审批（`resume(task_id, approved=True)` 也会忽略入参）。
- LangGraph 只负责 `load → dry_run → execute → verify → compensate → report`，没有 `interrupt` 节点，也没有把线程 checkpoint 当作审批真相。

### 2. 幂等分两个作用域：任务创建与写工具

**任务创建**

- 作用域：`task.create`，键来自 `Idempotency-Key` 请求头。
- 唯一约束：`(tenant_id, scope, key)`；同时保存 `request_hash` 与首次响应。
- 相同键 + 相同请求体：返回首次存储的 `TaskRead`，不重复规划或创建任务。
- 相同键 + 不同请求体：409 idempotency key conflict。
- 并发插入冲突时，回滚后重新读取赢家的记录并重放。

**写工具**

- 每个工具按「资源 + 动作」划分作用域，而不是只按任务：
  - `order.split:{order_id}`
  - `order.change_address:{order_id}`
  - `order.split.cancel:{order_id}`（拆单补偿）
  - `order.change_address.revert:{order_id}`（改址补偿）
  - `shipment.cancel:{shipment_id}`
  - `inventory.release:{order_id}`
- 执行器生成的键为 `{task_id}:{node_id}`，补偿为 `{task_id}:{node_id}:compensate`；同一节点重试复用同一键。
- 写服务在提交前检查键与 `request_hash`；重复键同请求返回首次响应，不同请求返回 `CONFLICT`。并发唯一约束冲突时回滚并重放赢家响应。
- dry-run 只锁行、校验并回滚，不写幂等记录；只有真实写入成功才落幂等行。
- 超时重试（GT-21）和超时后重试（GT-22）依赖该键保证「已提交但响应丢失」不会重复拆单。

### 3. 拆单建模为发货单，不生成子订单

- `SalesOrder` 保持一行：拆单成功后 `status = "split"`，原订单行不变。
- 拆单结果写入 `Shipment` + `ShipmentLine`：每个发货单包含仓库与若干 SKU 行；订单行与发货单行按 SKU 总量做多重集校验，不允许少发、多发或出现订单外 SKU。
- 库存通过 `Inventory`（available/reserved/version）与 `InventoryLedger` 记录预占与释放；预占原因 `order_split`，补偿原因 `split_compensation`。
- 补偿 `cancel_split` 取消发货单、依据 ledger 归还库存，并把订单恢复为 `pending_shipment`。
- 没有 child order 表，也没有「父订单/子订单」状态聚合。

### 4. 按订单隔离失败，验证失败全局补偿；known gap 显式保留

- 执行前先对全部批准节点做 dry-run；任一 dry-run 失败则在任何真实写入前中止。
- 真实写入失败时，失败节点及其订单的后续节点被跳过；其他订单已成功的写入不回滚（GT-24）。
- 验证失败是全局后置条件失败：所有已完成写入按逆序补偿（GT-25）。
- 补偿工具失败时任务进入 `partially_compensated`，`task.result.failed_compensations` 记录失败节点（GT-26）。
- 最终状态：全部成功 `succeeded`；有跳过/补偿 `partially_succeeded`；无任何成功写入且失败 `failed`；补偿失败 `partially_compensated`。
- `docs/KNOWN_GAPS.md` 明确保留 5 个未满足规格的行为：
  - GT-08：非法计划在创建阶段 500 + 全量回滚，没有 failed TaskRun 或转人工记录；
  - GT-09：仅含缺失订单的任务以 `failed` 结束，而非规格字面的 `partially_succeeded`；
  - GT-12：使用 `SELECT ... FOR UPDATE` 等锁，不是规格的有界乐观锁重试；竞争失败方安全失败但不重试；
  - GT-17：没有任务级 `rejected` 状态，拒绝批次的终态是 `partially_succeeded`；
  - GT-26：补偿失败有结果记录，但没有人工升级队列或 work-queue 工件。
- 因此当前口径是 **23/28 完全满足 + 5 条 xfail**，不宣称 28/28 全绿。

### 5. MCP 写工具走审批与租户守卫；补偿工具依赖内部调用边界

- `order_split` 与 `order_change_address` 在 MCP server 内先调用 `require_approved_write`：
  - `tenant_id` 与 `task_id` 必填；
  - 任务必须存在于该租户；
  - 必须存在 `task_id + order_id + action + status=approved` 的 Approval 行；
  - 任一条件不满足：写 `security.access_denied` 审计行与 `security.denied` trace span，并以 403 / `TOOL_ACCESS_DENIED` 拒绝。
- dry-run 也走同一守卫，因为 dry-run 发生在审批之后，且必须证明调用上下文有审批。
- 所有读写工具的数据库查询都带 `tenant_id`；跨租户订单在写服务中表现为 `NOT_FOUND`，不泄露存在性（GT-27/GT-28）。
- 补偿工具（`order_revert_split`、`order_revert_address`、`shipment_cancel`、`inventory_release`）**不再要求新的 Approval 行**：它们只应由执行器在已批准的写操作之后调用，依赖租户参数、任务上下文和幂等键约束。MVP 的 MCP server 是应用进程启动的本地 stdio 子进程，不以网络服务暴露；若未来改为远程 MCP 服务，需要为补偿工具补上同等级别的调用方认证或签名。

## 后果

正面：

- 审批状态可查询、可审计、可跨进程/重启恢复；HTTP API 与控制台共享同一份状态。
- 执行器不信任调用方标志，重复执行、超时重试、重复审批都安全。
- 拆单落在既有发货单模型上，写入与补偿路径短，容易做确定性验证。
- 每个写操作都有审计行、幂等行与 trace span，失败注入可复现。

负面与限制：

- 没有 LangGraph 图内暂停/恢复 UX；审批超时没有后台清扫器，过期状态在下次决策或执行读取时才被标记。
- 没有任务级 `rejected` 状态、没有人工升级队列；GT-08/17/26 仍是 known gap。
- 补偿是尽力而为（best effort）：补偿失败只记录，不自动重试或转人工。
- 幂等记录没有 TTL 清理；长期运行需要归档策略。
- 并发竞争使用行锁等待，不是有界乐观锁重试（GT-12）。
- 补偿工具缺少独立的审批行校验，安全边界依赖本地 stdio 部署形态。

## 备选方案

- **LangGraph interrupt + checkpoint 审批**：图内暂停更「原生」，但审批入口是 HTTP/控制台，可能跨进程、跨天、跨重启；把审批真相放进图线程会让 API、控制台和审计难以一致。若未来需要图内交互式暂停，可在保留数据库审批真相的前提下增加 interrupt 作为 UI 层。
- **子订单模型**：语义更接近「一拆多订单」，但需要新增父/子订单表、状态聚合、库存与物流归属规则，MVP 收益不足；发货单已能表达拆单结果。
- **Redis 幂等 / 队列**：当前环境 Redis 镜像不可用，且 MVP 不依赖 Redis；数据库唯一约束已经提供原子性与持久性。后续引入队列时可把幂等存储迁到 Redis，但需保留数据库审计。
- **Saga / 事务消息框架**：对两个写动作的 MVP 过重；当前「逐订单 + 逆序补偿 + 审计」足够演示和测试。
- **乐观锁重试**：可实现 GT-12 的字面语义，但会增加冲突重试与幂等交互的复杂度；当前选择行锁保证正确性，并把差异记录为 known gap。
