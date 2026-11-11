# OpsConductor MVP 项目代码审查（五轴复审）

**审查方法**：`code-review-and-quality` skill 的五轴审查（正确性、可读性、架构、安全、性能）  
**审查范围**：`main..HEAD`，`2af335f..10ea169`，35 个提交，完整 MVP 实现  
**规格**：[MVP 设计规格](../specs/2026-11-04-mvp-order-exception-design.md)  
**已知缺口**：[KNOWN_GAPS.md](../KNOWN_GAPS.md)  
**日期**：2026-11-04  
**结论**：**Request changes**（存在必须修复的正确性/安全问题）

> 本文档按新安装的 `code-review-and-quality` skill 重新生成，替代此前的两轴审查版本。旧版本仍保留在 git 历史中。

## 0. 结论摘要

项目可以作为可演示的订单异常 MVP：写路径、审批、幂等、补偿、审计、trace、控制台和 Golden Tasks 都已落地，测试基线为 **164 passed + 5 xfailed**，`ruff`/`mypy` 通过。

但当前不能按“生产形态”批准：

1. **改址场景会写入伪造地址**：模板 Planner 在地址为空时直接生成 `city+district+"世纪大道100号"`，API 没有接收用户目标地址；GT-03 把伪造值当作通过。
2. **审批没有绑定具体 payload**：guard 只按 task/order/action 匹配，审批后可以换一批 shipments 或另一个地址；补偿工具仍暴露在同一 MCP 面。
3. **执行没有任务级锁，终态可重入**：`/execute` 可重复执行 succeeded 任务，并发执行会竞争 TaskStep；补偿后的订单因保留 cancelled shipment 而永久无法再次拆单。
4. **GT-18 是假绿**：harness 改写 `expires_at` 让审批“复活”，生产端超时后没有 re-arm 路径。
5. **CI 跑不通**：测试固定 PostgreSQL `localhost:15432`，CI 没有启动数据库。

## 1. 审查上下文

- 目标：把“处理今天华东仓超时未发货的订单”翻译成可拆解、可审批、可回滚、可审计的 ERP 操作。
- 范围：订单异常场景，拆单 + 改址；不包含 JD 阶段的 ERP Adapter、SKILL、Memory、RAG、RPA、多模型。
- 关键运行路径：

```text
POST /tasks → Planner → Plan + Approval
→ approve/reject → ApprovalService → running
→ POST /execute → TaskExecutor → LangGraph
→ MCP tools → require_approved_write → write_service → PostgreSQL
→ verify → compensate → report + audit/trace
```

- 测试优先：先看 `tests/` 与 `tests/eval/`，再做一次变异验证；见 §2。

## 2. 测试先行与验证

### 2.1 测试拓扑

- 单元/集成：模型、仓储、MCP、写路径、审批、执行器、控制台。
- Golden Tasks：28 条，**23 条完全满足，5 条 xfail**（GT-08/09/12/17/26）。
- 全量本地结果：`164 passed + 5 xfailed`，约 2:46。
- `ruff check .`：通过；`mypy src`：42 files 通过。

### 2.2 变异验证

在 `orchestrator/policy.py:59` 将 `count >= l3_batch_threshold` 改为 `count > l3_batch_threshold`，运行相关测试：

```text
FAILED tests/test_approvals.py::test_batch_split_threshold_upgrades_split_approvals_to_l3
FAILED tests/test_tasks_api.py::test_l3_threshold_marks_every_split_node
2 failed, 1 passed
```

随后已恢复文件，`git diff` 为空。说明 L3 阈值测试**确实能抓住回归**。但这不能证明 Golden Tasks 的 GT-16 边界也被同一次运行覆盖；该变异只跑了 focused tests。

### 2.3 测试可信度

- `tests/eval/harness.py` 1,568 行，`cases.py` 889 行；`assert_case` 按 `case.id` 分支，新增 case 需要修改 harness。
- GT-18、GT-21/22/25/26 的实现由 harness 补行为或改写状态；详见 §6。
- CI 不启动 PostgreSQL：`.github/workflows/ci.yml:19-20` 直接 `pytest`，`tests/conftest.py:13-15` 固定 `localhost:15432`。

## 3. 五轴发现

### 3.1 正确性（Correctness）

#### Critical：改址场景会写入伪造地址

`planner.py:183-191` 只在地址已无效时生成 `change_address`，参数是 `normalized_address(order)`；`address.py:81-101` 在 `address_detail` 为空时直接拼接 `city + district + "世纪大道100号"`。`TaskCreate` 没有“目标地址”字段，默认模板 Planner 下，所谓“改址”实际上是把一个编造的地址写进订单。

证据：`tests/eval/cases.py:264-277` 的 GT-03 期望这个编造值；`tests/eval/harness.py:1088-1091` 只验证该值被写入。这与 GT-06“非法地址拒绝”以及“改址应使用用户提供的新地址”的语义冲突。

**Remedy**：在 `TaskCreate` 增加结构化目标地址（或明确的“修正后地址”参数）；没有目标地址时不要生成 `change_address`，应 `block_order` 或转人工；删除生产路径中的 `normalized_address` 伪造逻辑。若保留为演示快捷方式，必须写入 `KNOWN_GAPS.md`，不能标记 GT-03 完全满足。

#### Critical：执行没有任务级锁，终态可重入

`executor.py:157-168,209-249` 只按任务/审批加载，没有锁定 `TaskRun`；`tasks.py:447-477` 的 `/execute` 没有状态检查；`test_execute_api.py:305` 明确重复执行 `succeeded` 任务。`_begin_step` 在 `executor.py:944-977` 会把已有步骤重置为 `running`，并发 `/execute` 会互相覆盖 TaskStep。

规格 §4.6 禁止从终态恢复；当前 `succeeded`/`partially_compensated` 任务可以再次运行。

**Remedy**：`load` 阶段对 `TaskRun` 做 `SELECT ... FOR UPDATE`；只允许 `running`/`planned` 进入执行；终态返回 409；`/execute` 用单次 CAS 状态迁移（`UPDATE ... WHERE status IN (...)`），并补并发测试。

#### Required：补偿后订单永久不可处理

`cancel_split` 把订单恢复为 `pending_shipment`，但保留 `Shipment.status="cancelled"`（`write_service.py:1220-1229`）。`split_order` 与 `change_address` 都以“存在任何 shipment”为拒绝条件（`write_service.py:1044-1050`、`808-814`），模板 Planner 也把有 shipment 的订单分类为 `already_split`（`planner.py:160-165`）。结果：GT-25 补偿后订单看似回到待发货，实际不能再次拆单/改址。

**Remedy**：所有前置条件只把 `status="created"` 的 shipment 视为活动；Planner/Verifier 使用同一判定；增加“补偿后重新拆单”的回归测试。

#### Required：GT-18 是 false green，审批超时没有恢复路径

harness 把 `expires_at` 改到过去，执行后又在 approve 前改到未来（`harness.py:596-623,726-733`）。生产代码在 `approval.py:270-275` 对过期审批返回 409，`316-344` 将其标为 `expired`，`executor.py:304-312` 让任务回到 `awaiting_approval`，没有 re-arm/重提路径。`KNOWN_GAPS.md` 却把 GT-18 列为完全满足。

**Remedy**：实现显式 re-submit/re-arm（创建新的 pending approval 行并写审计），或把 GT-18 移入 `KNOWN_GAPS.md`；测试必须走生产端点，不能直接改 ORM。

#### Required：L3 角色拒绝没有审计

`approval.py:346-356` 的 `_check_roles` 抛出 `ApprovalForbidden`，没有 `write_access_denied` 审计；`test_approvals.py:184-188` 证明两次 403 后审计行数为 0。规格 §6.5 要求未授权尝试可审计。

**Remedy**：角色拒绝统一走 `write_access_denied`，并在 L3 角色测试中断言审计行。

#### Required：DAG 依赖只校验，不驱动执行

`schemas.py:68,131-158` 校验 `depends_on` 存在且无环，但 `executor.py:321-333` 仅按 `plan["nodes"]` 列表顺序筛选 write actions；依赖关系没有参与调度。含依赖/并行语义的计划可能以错误顺序执行。

**Remedy**：执行前按 `depends_on` 拓扑排序，或明确限制 MVP 计划为线性并在 schema 中拒绝非线形依赖；不要让校验和执行语义分叉。

#### Required：CI 无法运行测试

`.github/workflows/ci.yml:19-20` 仅 `pytest`，没有 PostgreSQL service；`tests/conftest.py:13-15` 固定 `localhost:15432`。当前 CI 会连接失败。

**Remedy**：加 `postgres:16` service，创建 `opsconductor_test`，设置 `OPSCONDUCTOR_DATABASE_URL`；或提供可切换的 SQLite 测试配置并明确差异。

### 3.2 可读性与简单性（Readability & Simplicity）

#### Required：`write_service.py` 已成为 1,489 行的 god module

六个写入口（`change_address`、`revert_address`、`split_order`、`cancel_split`、`cancel_shipment`、`release_inventory`）重复同一套事务壳：replay → lock → precondition → mutate → audit → stage idempotency → `_commit_or_replay` → rollback（约 `741-1489`）。文件已经超过健康边界，新增动作会继续放大。

**Remedy**：抽取 `run_idempotent_write(command)` / `WriteContext`，按动作拆成 `address_writes.py`、`split_writes.py`、`compensation.py`；动作参数用类型化命令对象，而不是六组重复签名。

#### Consider：重复的状态机与 step upsert

`approval.py:252-344` 的 targeted/bulk 决策共享大部分状态机；`executor.py:931-1107` 有五个近似相同的 step upsert；`verifier.py` 与 `write_service.py` 各有一份 shipment coverage 逻辑。

**Remedy**：`ApprovalDecision` 用一个共享状态迁移函数；`_upsert_step(status, ...)` 统一 step 写入；coverage 抽到 domain 的单一 helper。

#### Consider：测试 harness 自身是复杂子系统

`tests/eval/harness.py` 1,568 行、`cases.py` 889 行；`assert_case` 按 `case.id` 分支（`harness.py:1070-1130`），新增 case 需要改 harness。三套 MCP dispatcher（`tools/server.py:191-455`、`tests/test_executor.py:50-116`、`tests/eval/harness.py:157-311`）维护成本高。

**Remedy**：拆成 `fixtures / drivers / assertions`；用共享的 in-process tool client；让 case 断言数据驱动，而不是在通用函数里堆 `if case.id`。

#### Nit

- `compensating`/`compensated` 状态从未产生（`enums.py:51-52`）。
- `TaskReport`/`ApprovalDecision` 未使用（`schemas.py:91-114`）。
- `executor.py:189-207` 的 `resume(approved)` 参数被丢弃。
- `client.py:78-82` 忽略 `mcp_server_command/args`。
- `test_tasks_api.py:250` 的“boundary”测试实际测的是 below-threshold（threshold 4，split 3）。

### 3.3 架构（Architecture）

#### Required：动作扩展是 shotgun surgery

新增一个写动作会同时修改 `schemas.py`、`policy.py`、`planner.py`、`executor.py`、`verifier.py`、`guard.py`、`tasks.py`、`tools/service.py`、`tools/server.py` 和四张测试动作表。这是典型的 **Shotgun Surgery**；动作（action）没有单一注册表。

**Remedy**：建立 `ActionRegistry`，集中声明 action 的风险、工具、参数 schema、补偿动作、审批需求和 verifier；Planner/Executor/Verifier/Guard/Console 从注册表读取，而不是各自 switch。

#### Required：路由层混合了编排与 HTTP

`api/routes/tasks.py` 同时负责 Planner 选择、审批行构建、幂等、任务读取和 `/execute`；`routes/approvals.py`/`console.py` 又各自复制任务/审批查询。HTTP 层难以独立测试，审批/幂等策略也容易漂移。

**Remedy**：引入 `application/task_service.py` 与 `approval_service` 的应用服务边界；route 只做认证/协议转换/错误映射。

#### Consider：领域层反向依赖基础设施/可观测

`domain.write_service` 依赖 `observability.audit`，`observability.audit` 又依赖 `domain.models`；`domain.seed` 依赖 `db`。这形成层次反向依赖，领域服务无法脱离数据库/审计实现单测。

**Remedy**：在应用层注入 `AuditSink`/`TraceSink` 端口；领域层只依赖协议/值对象。

#### FYI：空占位模块

`agents/`、`memory/`、`rag/` 仍是空包；`skills/`、`erp/` 不存在。JD 阶段能力未实现，文档不应把 MVP 与完整平台混为一谈。

### 3.4 安全（Security）

#### Critical：审批没有绑定 payload

`Approval` 只保存 task/order/action/risk/status（`models.py:344-362`），`guard.py:105-118` 只按 task/order/action 匹配。正常执行器使用持久化 plan，所以默认路径安全；但持有某个 approved approval 的 MCP 调用方可以换 shipments 或地址，审批记录无法证明“批准了什么”。

**Remedy**：Approval 保存规范化参数或参数哈希；`require_approved_write` 校验 payload hash；在审批 UI 展示同一份规范化参数。

#### Critical：补偿工具暴露在同一 MCP 面

`tools/server.py:310-455` 公开 `shipment_cancel`、`inventory_release`、`order_revert_split`，没有审批守卫；`tenant_id`/`actor_id` 由调用方提供。`revert_address` 也没有 `pending_shipment` 前置条件（`write_service.py:879-969`），可能改写已拆单订单的地址。

**Remedy**：补偿工具放到独立的 internal server 或用内部 token/进程边界保护；`revert_address` 增加状态前置条件；审计拒绝路径。

#### Consider：读工具与租户上下文

读工具由调用方传 `tenant_id`，`order_get` 返回原始手机号（`tools/service.py:39-46`），没有统一的审计/限流/脱敏。开发控制台把 API key 放在 URL（`console.py:52-57`），没有 CSRF 防护。

**Remedy**：网关统一注入可信租户上下文；读工具也写审计/限流；控制台使用短时 cookie/session，API key 不进 URL；文档明确仅限 localhost。

### 3.5 性能（Performance）

#### Consider：Planner 的 N+1 查询

`planner.py:108-126` 每个订单 2+ 次查询、每行一次库存查询；批量订单会线性放大。应一次批量读取 orders/lines/inventory/shipments，再在内存组装 `_OrderContext`。

#### Consider：列表与 trace 无分页

`console.py:326-332` 加载所有任务；trace 页面也按任务加载全部 span。需要 `limit/offset` 或 cursor。

#### Consider：每次 execute 启动 MCP 子进程

`tasks.py:402-414` 的 `/execute` 每个请求启动 Python MCP 子进程；高频执行成本高。应复用长生命周期 MCP 客户端或进程池。

#### Nit

- 工具调用没有统一超时（`executor.py`/`client.py`）。
- 没有非注入失败的工具成功率统计；Golden 指标依赖 harness。

## 4. 优先级与结构整改

| 优先级 | 事项 | 具体动作 |
|---|---|---|
| Critical | 改址伪造地址 | 增加目标地址参数；无地址时 block/转人工；删除 `normalized_address` 生产路径 |
| Critical | 执行并发/终态重入 | `TaskRun FOR UPDATE` + 只允许 planned/running + `/execute` CAS；补并发测试 |
| Critical | 审批 payload 绑定 | Approval 存参数/哈希；guard 校验；补偿工具内部化 |
| Required | 补偿后不可再处理 | 只把 `created` shipment 视为活动；补偿后可重拆的回归测试 |
| Required | GT-18 假绿 | 实现 re-arm 或移入 KNOWN_GAPS；测试走生产端点 |
| Required | CI | 加 Postgres service + test DB + env；或 SQLite 配置 |
| Required | DAG 依赖 | 拓扑排序执行，或限制线性计划并拒绝非线形 |
| Required | 角色拒绝审计 | `write_access_denied` + 断言 |
| Required | 结构拆分 | `run_idempotent_write`、ActionRegistry、application service |
| Consider | N+1/分页/子进程 | 批量查询、分页、MCP 客户端复用 |
| Nit/FYI | 死代码/未使用字段/测试边界 | 清理或标记 |

## 5. 验证

**已执行**

- `pytest -q`：164 passed + 5 xfailed（约 2:46）
- `ruff check .`：通过
- `mypy src`：42 files 通过
- L3 阈值变异：2 个测试失败，随后恢复，工作区干净
- `scripts/demo.sh`：真实 MCP 客户端审批/执行/重复 no-op/跨租户 403/控制台 trace

**未执行/限制**

- 真实 LLM 冒烟未运行（无凭据）；`scripts/smoke_live.py` 只验证 SKIPPED。
- CI 未验证：没有 PostgreSQL service。
- 没有动态安全测试；审批 payload/补偿工具边界仅按代码审查判断。
- 本次审查覆盖 MVP 规格；JD 阶段的 ERP Adapter、SKILL、Memory、RAG、RPA 不在已实现范围。

## 6. 已知缺口与测试可信度

`docs/KNOWN_GAPS.md` 披露 5 条：

| ID | 缺口 |
|---|---|
| GT-08 | 非法计划创建时 500，没有失败 TaskRun/转人工记录 |
| GT-09 | 单缺失订单结束 `failed`，不是 `partially_succeeded` |
| GT-12 | 使用 `FOR UPDATE` 等待，不是有限乐观锁重试 |
| GT-17 | 没有任务级 `rejected` 状态 |
| GT-26 | 记录 failed_compensations，但没有转人工/工作队列产物 |

**未披露/测试可信度问题**：

- GT-18 没有 re-arm，harness 改写 `expires_at` 制造通过；应移入 known gaps 或实现恢复。
- GT-21/22 的“retry”是测试手动 `_execute` 两次，不是生产重试。
- GT-25/26 使用 `FailingVerifier` stub，不是真实后置条件失败。
- GT-24 的 per-order 补偿断言在单节点失败场景下是空洞的（`compensated == []` 不能证明成功订单未受影响）。

## 7. 审查清单

```markdown
### Context
- [x] 理解变更目标与 MVP 规格
- [x] 确认已知缺口与 JD 范围边界

### Correctness
- [ ] 改址使用用户目标地址，而不是伪造值
- [ ] 终态不可重入；并发执行有任务锁
- [ ] 补偿后订单可重新处理
- [x] 写路径、审批、幂等、审计主路径测试覆盖
- [ ] GT-18 真实可恢复
- [ ] CI 可运行 PostgreSQL 测试

### Readability
- [x] 中文 Google 风格 docstring 覆盖核心模块
- [ ] write_service/executor 拆分到健康大小
- [ ] 测试 harness 数据驱动化

### Architecture
- [x] 顶层模块边界（API/Orchestrator/Domain/Tools/Observability）
- [ ] action registry 消除 shotgun surgery
- [ ] application service 层
- [ ] 领域层不反向依赖 DB/observability

### Security
- [x] 写工具审批守卫与跨租户 403
- [ ] 审批绑定 payload
- [ ] 补偿工具内部化
- [ ] 读工具审计/限流/脱敏
- [ ] 控制台不使用 URL API key

### Performance
- [ ] Planner 批量化
- [ ] 列表/trace 分页
- [ ] MCP 客户端复用
- [ ] 工具超时

### Verification
- [x] 164 passed + 5 xfailed
- [x] ruff/mypy
- [x] 变异测试
- [ ] CI 可复现
```

## 8. 最终结论

**Verdict: Request changes。**

最小合并门禁：先修 3 个 Critical（改址伪造、执行并发/终态、审批 payload 绑定 + 补偿工具内部化），再修 4 个 Required（补偿后可重拆、GT-18、CI、DAG 依赖/角色审计），然后重新跑 28 条 Golden Tasks 和生产测试。结构拆分（`write_service`、ActionRegistry、application service）可作为紧随其后的 Required 重构；不要继续在 1,489 行的 `write_service.py` 上叠加新动作。

**Approval standard**：当前代码已经明显改善整体健康（可运行、可审计、可演示），但上述 Critical/Required 问题会影响真实 ERP 写操作的正确性与安全性，因此不批准为“可合并/可生产”状态。
