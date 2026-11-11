# 跨境电商全流程模拟演示系统 · 实施计划

> 先做一条可演示的垂直链路，再把 Mock 世界补全；不做大而全的横向铺层。

**Goal:** 在 5–6 周内交付「最小演示版」，8–10 周内交付「完整评测版」；若 1.5–2 人并行，可压缩到 4 周 / 6–7 周。演示 Agent 从一句运营目标出发，完成选品 → 内容 → 上架 → 投流 → 订单 → 履约 → 影刀 RPA → 结算 → 报告的全流程，并具备审批、幂等、补偿、审计、trace 和失败注入。

**Architecture:** FastAPI 接入层 + LangGraph 编排 + MCP 工具网关 + 独立 Mock World + 影刀 RPA 桥接 + Jinja2/HTMX 控制台；PostgreSQL 作为业务事实源。

**Tech Stack:** Python 3.11、FastAPI、Pydantic、SQLAlchemy 2.x async + psycopg 3、PostgreSQL 16、LangGraph、MCP Python SDK、Jinja2/HTMX、Playwright、pytest、ruff、mypy。

**Spec:** [模拟演示系统需求规格](../specs/2026-11-10-cross-border-simulation-design.md) ｜ [跨境电商能力地图](../specs/2026-11-10-cross-border-ecommerce-platform-design.md) ｜ [系统设计](../design.md)

## Global Constraints

- 所有业务数据带 `tenant_id`、`store_id`；跨租户返回 403 并写审计。
- 所有写操作必须先审批、再 dry-run、再执行；幂等键必填。
- L2 二次确认，L3 人工审批；广告预算 > 1000 美元、退款、赔付、批量动作一律 L3。
- Mock World 与主应用分进程；Agent 只通过 MCP 工具访问外部世界。
- 默认使用 stub 模型和 Mock API；真实模型、真实影刀只做冒烟/演示。
- 固定种子 `DEMO_SEED=20261110`；一键重置 ≤ 30 秒。
- 测试不调用真实平台 API；不使用真实 PII 或真实资金。
- 每个 Phase 结束必须有一个可演示的垂直切片，不允许只交付「底层能力」。
- 提交信息使用 `feat:`、`test:`、`chore:` 前缀；每个任务结束前跑 `pytest -q` 和 `ruff check .`。

## 1. 组件依赖图

```text
配置/环境
  │
  ├── Mock World（独立进程）
  │     ├── 通用框架（鉴权/幂等/限流/失败注入）
  │     ├── TikTok Shop Mock
  │     ├── 物流 Mock
  │     ├── 支付/结算 Mock
  │     ├── 广告 Mock
  │     ├── 趋势/内容 Mock
  │     └── Mock 数据生成/重置
  │
  ├── MCP 工具网关
  │     ├── 工具注册表 + 风险元数据
  │     ├── Mock World 客户端
  │     ├── Mini ERP 客户端
  │     └── RPA 桥接客户端
  │
  ├── 影刀 RPA 桥接（独立进程）
  │     ├── 真实影刀 Adapter
  │     ├── Mock Playwright Adapter
  │     └── 旧版供应商门户
  │
  ├── Agent 编排
  │     ├── Planner（stub + 真实模型）
  │     ├── Executor（重试/超时/检查点/补偿）
  │     ├── Verifier（确定性 + 独立模型）
  │     └── 审批/幂等/审计/trace
  │
  └── 控制台
        ├── 任务/计划/审批
        ├── trace/审计/报告
        ├── Mock 数据浏览/场景控制
        └── 演示脚本/重置
```

## 2. 阶段总览

| Phase | 周期 | 目标 | 退出标准 | 可演示产出 |
|---|---|---|---|---|
| P0 冻结契约与骨架 | 3–4 天 | 演示剧本、Mock 契约、工程骨架、种子数据 | 一条命令启动；Mock 数据可重置 | `curl /health` + 种子数据 |
| P1 Mock 世界 | 2–2.5 周 | TikTok/物流/支付/广告/趋势/内容 Mock | 契约测试通过；失败注入可用 | Mock API 文档 + 订单/结算数据 |
| P2 Agent 运行时与工具 | 3–3.5 周 | MCP 工具、Planner/Executor/Verifier、审批/幂等/补偿 | 单订单拆单端到端跑通 | 目标 → 计划 → 审批 → 拆单 → 报告 |
| P3 影刀 RPA 桥接 | 1–1.5 周 | 旧版门户、真实/模拟 Adapter、截图/审计 | RPA 补货流程成功 + 失败转人工 | 影刀操作录屏 + 截图 |
| P4 控制台与演示 | 1 周 | 任务/计划/审批/trace/报告/Mock 数据 | 8 分钟全流程演示 | 标准演示脚本 |
| P5 评测与硬化 | 1–1.5 周 | 30 条 Golden Tasks、失败注入、指标 | 评测报告可复现 | 评测报告 + 5 分钟录屏 |

**估算口径：** 按 1 人全职、每天 6–8 小时估算；串行约 9–10 周。P3 与 P4 可部分并行，P5 可在 P4 后半段启动，压缩到 8–10 周；1.5–2 人并行可压缩到 6–7 周。

**切线规则：**

- 时间不足先砍：Amazon/Temu Mock、真实影刀、真实模型、完整控制台样式。
- 不能砍：审批、幂等、补偿、审计、trace、影刀 Mock 演示、30 条评测（可降到 20 条）。
- 最小演示版 = P0 + P1 核心 + P2 核心 + P3 Mock + P4 最小；约 5–6 周（1 人全职），2 人并行约 4 周。
- 完整评测版 = 全部 Phase；约 8–10 周（1 人全职），2 人并行约 6–7 周。

## 3. Phase 0：冻结契约与骨架（3 天）

### Task P0-T1：冻结演示剧本与验收标准

**交付物：**
- `docs/demo/2026-11-10-demo-script.md`
- `demo/scenarios/weekly_gmv.yaml`

**验收标准：**
- [ ] 剧本包含 8 个步骤、3 次审批、1 次拒绝、1 次补偿、1 次 RPA、1 次对账差异。
- [ ] 每个步骤写清输入、工具、预期输出、失败注入点。
- [ ] 明确演示时长 ≤ 8 分钟、重置 ≤ 30 秒。

**依赖：** 无 ｜ **估算：** 0.5 天

### Task P0-T2：工程骨架与 Docker Compose

**交付物：**
- `src/opsconductor/mock_world/`（FastAPI 独立 app）
- `src/opsconductor/rpa/bridge/`（FastAPI 独立 app）
- `src/opsconductor/rpa/legacy_portal/`（HTML 表单）
- `docker-compose.yml` 增加 `mock-world`、`rpa-bridge`、`legacy-portal`
- `Makefile`：`up`、`seed`、`demo`、`reset-demo`、`test`

**验收标准：**
- [ ] `docker compose up -d` 启动 PostgreSQL、Mock World、RPA Bridge、Legacy Portal、主应用。
- [ ] 每个服务有 `/health`，端口分别为 8000/8100/8200/8300。
- [ ] `make up` 在 60 秒内完成冷启动。

**依赖：** P0-T1 ｜ **估算：** 1 天

### Task P0-T3：配置与环境变量

**交付物：**
- `src/opsconductor/config.py` 增加 `mock_world_url`、`rpa_bridge_url`、`legacy_portal_url`、`demo_seed`、`yingdao_mode`、`mock_latency_ms`、`l3_ad_budget_threshold`、`l3_batch_threshold`。
- `.env.example` 更新。

**验收标准：**
- [ ] 环境变量有默认值，缺省即可跑 Mock 模式。
- [ ] 配置测试覆盖默认值和环境覆盖。

**依赖：** P0-T2 ｜ **估算：** 0.5 天

### Task P0-T4：Mock 数据 schema 与种子脚本

**交付物：**
- `src/opsconductor/mock_world/models.py`
- `scripts/seed_demo.py`
- `scripts/reset_demo.py`
- `demo/data/` 小样本（不入 Git 的全量数据由脚本生成）

**验收标准：**
- [ ] 生成 10 店、5000 SKU、3 仓、5000 订单、90 天结算、20 广告计划、20 达人、50 寄样、20 政策。
- [ ] 固定种子，重复生成结果一致。
- [ ] `make reset-demo` ≤ 30 秒恢复初始状态。
- [ ] 数据全部合成，无真实 PII。

**依赖：** P0-T3 ｜ **估算：** 1 天

### Task P0-T5：一键启动冒烟

**交付物：**
- `scripts/demo_smoke.py`
- `tests/test_demo_smoke.py`

**验收标准：**
- [ ] `make up && make seed && make smoke` 通过。
- [ ] 能查询 1 个店铺、10 个 SKU、1 个订单、1 个结算单。
- [ ] CI 可在无真实 API 密钥的情况下跑通。

**依赖：** P0-T4 ｜ **估算：** 0.5 天

## 4. Phase 1：Mock 世界（2–2.5 周）

### Task P1-T1：Mock 通用框架

**交付物：**
- `src/opsconductor/mock_world/common/auth.py`
- `common/idempotency.py`
- `common/errors.py`
- `common/failures.py`
- `common/pagination.py`

**验收标准：**
- [ ] Bearer token 映射 tenant/store/role；缺失/越权返回 401/403。
- [ ] `Idempotency-Key` 同键同 body 返回首次响应；同键不同 body 返回 409。
- [ ] 限流返回 429 + `Retry-After`。
- [ ] `X-Mock-Failure` 支持 timeout、rate_limit、server_error、stock_conflict、customs_hold、settlement_mismatch、rpa_selector_failure。
- [ ] 统一错误模型包含 `error_code`、`message`、`retryable`、`request_id`、`details`。

**依赖：** P0-T4 ｜ **估算：** 2 天

### Task P1-T2：TikTok Shop Mock（垂直切片优先）

**交付物：**
- `mock_world/routers/tiktok.py`
- 商品、订单、结算、退货、达人、寄样接口
- 先实现 `GET /tiktok/orders`、`GET /tiktok/orders/{id}`、`POST /tiktok/orders/{id}/split`、`POST /tiktok/orders/{id}/address` 四个关键接口

**验收标准：**
- [ ] 订单列表支持按店铺、状态、时间过滤。
- [ ] 订单详情包含 `paid_at`、`ship_deadline`、`items[].warehouse_id`、地址、版本。
- [ ] 拆单生成发货单并预占库存；库存不足返回 `INSUFFICIENT_STOCK`。
- [ ] 改址只在 `pending_shipment` 且无发货单时允许，否则 `INVALID_STATE`。
- [ ] 重复拆单/改址用幂等键返回首次结果。

**依赖：** P1-T1 ｜ **估算：** 2.5 天

### Task P1-T3：物流 Mock

**交付物：**
- `mock_world/routers/logistics.py`

**验收标准：**
- [ ] 报价支持 direct/air/sea/express，返回成本、时效、限制。
- [ ] 创建发货单支持幂等；重复请求返回首次结果。
- [ ] 轨迹查询返回至少 3 个节点。
- [ ] 报关失败返回 `CUSTOMS_HOLD`，可注入。

**依赖：** P1-T1 ｜ **估算：** 1.5 天

### Task P1-T4：支付/结算 Mock

**交付物：**
- `mock_world/routers/payment.py`

**验收标准：**
- [ ] 结算单包含 `gross_sales`、`platform_fee`、`payment_fee`、`refunds`、`chargebacks`、`net_amount`。
- [ ] 支持按店铺/周期查询；90 天数据可查。
- [ ] 退款接口 L3，幂等，重复请求返回首次结果。
- [ ] 汇率为固定种子；费用明细可下钻。

**依赖：** P1-T1 ｜ **估算：** 1.5 天

### Task P1-T5：广告/趋势/内容 Mock

**交付物：**
- `mock_world/routers/ads.py`
- `trend.py`
- `content.py`

**验收标准：**
- [ ] 趋势接口返回趋势分、搜索量、竞争、价格带、内容角度。
- [ ] 广告计划支持创建、调预算、暂停、效果查询；预算超阈值返回 `POLICY_VIOLATION` 或要求审批。
- [ ] 内容 Brief/素材接口返回占位 URL、合规标记、版本。
- [ ] 所有写接口支持幂等。

**依赖：** P1-T1 ｜ **估算：** 2 天

### Task P1-T6：Mock 数据异常用例

**交付物：**
- `demo/data/anomalies.yaml`
- `scripts/seed_demo.py` 支持异常用例开关

**验收标准：**
- [ ] 6 个订单异常：超时、缺货、地址异常、已拆单、跨租户、重复提交。
- [ ] 3 个结算差异：少结、多扣、退款漏记。
- [ ] 3 个广告异常：超预算、低 ROAS、政策拒审。
- [ ] 3 个 RPA 异常：选择器失败、登录失败、PO 重复。
- [ ] 每个异常有固定 ID，Golden Tasks 可直接引用。

**依赖：** P1-T2/T3/T4/T5 ｜ **估算：** 1.5 天

### Task P1-T7：Mock 契约测试

**交付物：**
- `tests/test_mock_contracts.py`

**验收标准：**
- [ ] 每个域至少 1 个 happy path + 1 个错误路径。
- [ ] 验证鉴权、幂等、限流、失败注入、错误码。
- [ ] OpenAPI schema 可导出，字段与需求规格一致。
- [ ] 测试不依赖网络，使用 TestClient/httpx。

**依赖：** P1-T2/T3/T4/T5 ｜ **估算：** 1 天

## 5. Phase 2：Agent 运行时与工具（3–3.5 周）

### Task P2-T1：MCP 工具网关与注册表

**交付物：**
- `src/opsconductor/tools/registry.py`
- `src/opsconductor/tools/server.py`
- `src/opsconductor/tools/gateway.py`

**验收标准：**
- [ ] 工具元数据含名称、描述、参数/返回 Schema、风险、写标志、dry-run、幂等、超时、补偿。
- [ ] MCP Server 以 stdio 启动；编排器通过 MCP 客户端调用。
- [ ] 网关统一注入 tenant/store、鉴权、限流、审计、trace。
- [ ] 未注册工具/越权工具调用被拒绝并写审计。

**依赖：** P1-T1 ｜ **估算：** 1.5 天

### Task P2-T2：Mock World 工具客户端

**交付物：**
- `src/opsconductor/tools/clients/mock_world.py`
- `src/opsconductor/tools/clients/errors.py`

**验收标准：**
- [ ] 封装 httpx，统一超时、重试、错误映射、幂等键。
- [ ] 429/5xx 按可重试处理；4xx 不重试。
- [ ] 每次调用生成 trace span 和审计记录。
- [ ] 支持 `X-Mock-Failure` 场景注入。

**依赖：** P2-T1 ｜ **估算：** 1.5 天

### Task P2-T3：选品/内容/上架工具

**交付物：**
- `tools/selection.py`
- `tools/content.py`
- `tools/listing.py`

**验收标准：**
- [ ] `trend_scan`、`product_score`、`compliance_check` 返回结构化评分。
- [ ] `content_brief_generate`、`asset_generate` 返回 Brief/占位素材/合规标记。
- [ ] `listing_create` / `listing_update` 支持 dry-run、幂等、审批检查。
- [ ] 负毛利/合规不通过的 SKU 被 Verifier 拦截。

**依赖：** P2-T2 ｜ **估算：** 1.5 天

### Task P2-T4：订单/库存/履约工具（垂直切片）

**交付物：**
- `tools/order.py`
- `tools/inventory.py`
- `tools/fulfillment.py`

**验收标准：**
- [ ] `order_list`、`order_get`、`order_split`、`order_change_address` 可用。
- [ ] `inventory_get`、`inventory_reserve`、`inventory_release` 可用。
- [ ] `logistics_quote`、`shipment_create`、`customs_declare` 可用。
- [ ] 拆单「全有或全无」；失败补偿：取消发货单、释放预占、回退状态。
- [ ] 单订单拆单端到端测试通过，含审计和 trace。

**依赖：** P2-T2 ｜ **估算：** 2.5 天

### Task P2-T5：广告/结算/售后工具

**交付物：**
- `tools/ads.py`
- `tools/settlement.py`
- `tools/after_sales.py`

**验收标准：**
- [ ] 广告创建/调预算/暂停走 L3/L2 审批；预算超限被拦截。
- [ ] `settlement_get`、`reconcile_run` 返回差异列表和归因。
- [ ] `refund_create` L3，幂等，政策引用可追溯。
- [ ] 对账差异不自动打款，只生成任务。

**依赖：** P2-T2 ｜ **估算：** 1.5 天

### Task P2-T6：Planner（stub + 模板 + 真实模型接口）

**交付物：**
- `orchestrator/planner.py`
- `orchestrator/plan_schema.py`
- `orchestrator/templates/weekly_gmv.yaml`

**验收标准：**
- [ ] 计划 schema 校验：节点、依赖、工具、风险、超时、终止条件、补偿。
- [ ] stub 模型输出固定计划；模板兜底可用。
- [ ] 真实模型接口可切换；失败修复一次后转模板/人工。
- [ ] 计划预览包含影响范围和证据。

**依赖：** P2-T1 ｜ **估算：** 2 天

### Task P2-T7：Executor（重试/超时/检查点/补偿）

**交付物：**
- `orchestrator/executor.py`
- `orchestrator/compensation.py`
- `orchestrator/checkpoint.py`

**验收标准：**
- [ ] 依赖满足才执行；可并行节点并行。
- [ ] 瞬时错误有限重试；业务错误不重试；后置条件失败进入补偿。
- [ ] 每个节点写 `task_step`；检查点可恢复。
- [ ] 补偿按逆序执行；补偿失败标记 `partially_compensated`。

**依赖：** P2-T6 ｜ **估算：** 2 天

### Task P2-T8：Verifier

**交付物：**
- `orchestrator/verifier.py`
- `verifier/checks.py`

**验收标准：**
- [ ] 确定性检查：库存非负、订单状态合法、发货单行匹配、地址合法、预算未超、毛利达标、幂等键存在。
- [ ] 独立模型复核可开关；离线模式用 stub。
- [ ] 否决时阻塞输出/写入，并写审计。
- [ ] Golden Task 中至少 3 条验证否决路径。

**依赖：** P2-T7 ｜ **估算：** 1.5 天

### Task P2-T9：审批/幂等/审计/trace 集成

**交付物：**
- `orchestrator/approval.py`
- `observability/trace.py`
- `observability/audit.py`

**验收标准：**
- [ ] L2/L3 审批记录完整；审批动作幂等。
- [ ] 重复提交/重复审批不产生第二次业务影响。
- [ ] 每个任务至少包含计划、工具、审批、补偿、报告 span。
- [ ] trace 完整率 100%。

**依赖：** P2-T7 ｜ **估算：** 1.5 天

### Task P2-T10：端到端垂直切片

**交付物：**
- `tests/test_e2e_order_exception.py`
- `scripts/run_task.py`

**验收标准：**
- [ ] 目标 → 计划 → 审批 → 拆单 → 验证 → 报告全链路跑通。
- [ ] 失败注入库存冲突 → 补偿 → 部分成功报告。
- [ ] 审计、trace、幂等断言通过。

**依赖：** P2-T3/T4/T5/T8/T9 ｜ **估算：** 1 天

## 6. Phase 3：影刀 RPA 桥接（1–1.5 周）

### Task P3-T1：旧版供应商门户

**交付物：**
- `rpa/legacy_portal/app.py`
- `rpa/legacy_portal/templates/`（登录、库存、PO、下载）
- `tests/test_legacy_portal.py`

**验收标准：**
- [ ] 登录、库存查询、创建 PO、下载 PO PDF、订单列表五页可用。
- [ ] 无 API，只有 HTML 表单；数据来自 Mock World。
- [ ] 错误路径：登录失败、SKU 不存在、库存不足。

**依赖：** P1-T2 ｜ **估算：** 1.5 天

### Task P3-T2：RPA Adapter 接口 + Mock Playwright Adapter

**交付物：**
- `rpa/bridge/main.py`
- `rpa/bridge/adapters/base.py`
- `rpa/bridge/adapters/mock_playwright.py`

**验收标准：**
- [ ] `POST /rpa/runs` 接收 `flow_id`、`params`、`idempotency_key`、`timeout_seconds`。
- [ ] `GET /rpa/runs/{id}` 返回状态、输出、截图、日志、耗时。
- [ ] Mock adapter 用 Playwright 完成供应商补货流程，截图落 `artifacts/rpa/{run_id}/`。
- [ ] 重复请求用幂等键返回首次结果。

**依赖：** P3-T1 ｜ **估算：** 1.5 天

### Task P3-T3：真实影刀 Adapter

**交付物：**
- `rpa/bridge/adapters/yingdao.py`
- `.env.example` 增加 `YINGDAO_*`

**验收标准：**
- [ ] 通过影刀开放 API 或本地桥接触发已录制流程。
- [ ] 支持同步/异步状态查询；超时、登录失败、选择器失败可分类。
- [ ] 真实模式失败时自动降级到 mock（可配置）。
- [ ] 凭据只从环境变量读取，不写日志。
- [ ] 影刀流程内部通过 HTTP 指令调用 Mock API（拉取 SKU、回写 PO 状态），证明 RPA 与 API 混合编排。

**依赖：** P3-T2 ｜ **估算：** 1 天

### Task P3-T4：RPA 工具与审计

**交付物：**
- `tools/rpa.py`
- `tests/test_rpa_tool.py`

**验收标准：**
- [ ] `rpa_yingdao_run_flow` 支持 dry-run、幂等、审批检查。
- [ ] 工具返回结构化 output + 截图路径 + 日志摘要。
- [ ] RPA 调用写审计与 trace；截图可在控制台查看。
- [ ] 失败时转人工，保留已完成步骤。

**依赖：** P3-T2 ｜ **估算：** 1 天

### Task P3-T5：RPA 失败注入与契约测试

**交付物：**
- `tests/test_rpa_failures.py`

**验收标准：**
- [ ] 选择器超时 → 备用选择器/转人工。
- [ ] 登录失败 → 不无限重试。
- [ ] PO 重复 → 返回首次 PO。
- [ ] 截图缺失 → 验证失败。

**依赖：** P3-T4 ｜ **估算：** 0.5 天

## 7. Phase 4：控制台与演示（1 周）

### Task P4-T1：任务/计划/审批页面

**交付物：**
- `api/templates/tasks.html`
- `tasks_detail.html`
- `approvals.html`
- `api/routes/console.py`

**验收标准：**
- [ ] 提交目标、查看计划 DAG、查看影响范围。
- [ ] L2 确认/L3 审批按钮可用；拒绝后任务状态正确。
- [ ] 页面不依赖前端构建链。

**依赖：** P2-T9 ｜ **估算：** 1.5 天

### Task P4-T2：trace/审计/报告/RPA 截图

**交付物：**
- `api/templates/trace.html`
- `audit.html`
- `report.html`
- `rpa.html`

**验收标准：**
- [ ] trace 时间线可展开查看工具/模型摘要。
- [ ] 审计展示谁、何时、依据、前后值。
- [ ] 报告含 GMV/毛利/异常/审批/对账差异/RPA 截图。
- [ ] 可导出 Markdown/JSON。

**依赖：** P4-T1 ｜ **估算：** 1.5 天

### Task P4-T3：Mock 数据浏览与场景控制

**交付物：**
- `api/templates/mock_data.html`
- `scenario_control.html`
- `api/routes/admin.py`

**验收标准：**
- [ ] 可浏览 SKU/订单/库存/结算。
- [ ] 可切换失败注入、种子、重置。
- [ ] 重置不影响主应用数据。

**依赖：** P4-T1 ｜ **估算：** 1 天

### Task P4-T4：演示脚本与录屏

**交付物：**
- `scripts/demo.py`
- `docs/demo/2026-11-10-demo-script.md`
- `artifacts/demo/` 截图/录屏

**验收标准：**
- [ ] 一条命令跑完 8 分钟剧本。
- [ ] 演示包含 3 次审批、1 次拒绝、1 次补偿、1 次 RPA、1 次对账差异。
- [ ] 失败注入可复现。
- [ ] 录屏可离线播放。

**依赖：** P4-T2/T3 ｜ **估算：** 1 天

## 8. Phase 5：评测与硬化（1–1.5 周）

### Task P5-T1：30 条 Golden Tasks

**交付物：**
- `tests/golden/` + `tests/test_golden_tasks.py`

**验收标准：**
- [ ] 覆盖选品/内容 6、上架/广告 6、订单/履约 8、结算/售后 5、RPA 3、安全 2。
- [ ] 每条断言最终业务状态、必需工具调用、禁止动作、审批、审计。
- [ ] stub 模型下全部可复现。

**依赖：** P2/P3/P4 ｜ **估算：** 2 天

### Task P5-T2：失败注入套件

**交付物：**
- `tests/failures/` + `scripts/inject.py`

**验收标准：**
- [ ] 覆盖超时、限流、库存冲突、报关失败、对账差异、RPA 失败、重复请求。
- [ ] 每次注入可复现，固定种子/任务开关。
- [ ] 断言补偿后的最终一致性和报告状态。

**依赖：** P5-T1 ｜ **估算：** 1 天

### Task P5-T3：指标与成本看板

**交付物：**
- `observability/metrics.py`
- `api/templates/metrics.html`

**验收标准：**
- [ ] 任务成功率、工具成功率、审批覆盖率、重复/越权写入、补偿成功率、trace 完整率。
- [ ] 模型 token/成本、Mock 调用耗时。
- [ ] 演示结束自动生成摘要。

**依赖：** P4-T2 ｜ **估算：** 1 天

### Task P5-T4：真实模型冒烟

**交付物：**
- `scripts/smoke_real_model.py`
- 冒烟报告

**验收标准：**
- [ ] 5 条主路径用真实模型跑通。
- [ ] 失败时记录计划、工具参数、错误，不阻塞演示。
- [ ] 成本/延迟有记录。

**依赖：** P5-T1 ｜ **估算：** 1 天

### Task P5-T5：文档、dry run、录屏

**交付物：**
- README 演示章节
- `docs/demo/` 最终脚本
- 5 分钟录屏

**验收标准：**
- [ ] 新人按 README 可在 15 分钟内启动。
- [ ] 演示 dry run 连续 3 次成功。
- [ ] 文档写清 Mock 边界、影刀模式、已知限制。

**依赖：** 全部 ｜ **估算：** 0.5 天

## 9. 检查点

| 检查点 | 时间 | 必须通过 |
|---|---|---|
| CP-1 | P0 结束 | 一键启动、种子数据、Mock 健康检查 |
| CP-2 | P1 结束 | 契约测试、失败注入、订单/结算数据可查 |
| CP-3 | P2 结束 | 单订单拆单端到端、审批/幂等/补偿/审计/trace |
| CP-4 | P3 结束 | RPA 补货成功 + 失败转人工 + 截图证据 |
| CP-5 | P4 结束 | 8 分钟全流程演示可重复 |
| CP-6 | P5 结束 | 30 条 Golden Tasks + 指标报告 + 录屏 |

## 10. 演示脚本（8 分钟）

| 时间 | 动作 | 展示点 |
|---|---|---|
| 0:00–0:30 | 重置数据，介绍店铺与目标 | 一键重置、场景可控 |
| 0:30–1:30 | 提交目标，查看计划 DAG | 目标理解、计划、风险、影响范围 |
| 1:30–2:30 | 审批广告预算/拒绝涨价 | L2/L3、审批记录、拒绝降级 |
| 2:30–3:30 | 选品/内容/上架 | 趋势评分、毛利拦截、合规剔除、Brief |
| 3:30–4:30 | 投流与订单异常 | 广告护栏、拆单/改址、库存冲突补偿 |
| 4:30–5:30 | 履约与影刀 RPA | 物流比价、报关失败、影刀截图 |
| 5:30–6:30 | 结算对账 + 退款审批 | 差异归因、财务任务、退款 L3 通过、不自动打款 |
| 6:30–7:30 | Verifier 与报告 | 否决、补偿、报告、指标 |
| 7:30–8:00 | trace/审计回放 | 全链路可追溯 |

## 11. 最小演示版 vs 完整评测版

| 能力 | 最小演示版（5–6 周，1 人） | 完整评测版（8–10 周，1 人） |
|---|---|---|
| Mock 平台 | TikTok + 物流 + 支付/结算核心 | 全 Mock + Amazon/Temu stub |
| Mock 数据 | 5000 SKU + 6 异常订单 + 3 结算差异 | 全量异常 + 广告/RPA 异常 |
| Agent | 订单异常 + 选品/内容/上架/广告最小 | 全流程 + 真实模型冒烟 |
| 影刀 | Mock Playwright + 真实 Adapter 接口 | 真实影刀流程 + 失败注入 |
| 控制台 | 任务/审批/trace/报告 | Mock 数据浏览/场景控制/指标 |
| 评测 | 10–15 条 Golden Tasks | 30 条 + 失败注入套件 |
| 演示 | 8 分钟主路径 | 8 分钟 + 失败路径 + 指标 |

## 12. 风险与切线

| 风险 | 对策 |
|---|---|
| Mock 失真 | 契约测试 + 字段对照真实 API 文档 + Adapter 可替换 |
| 5000 SKU 生成慢 | 批量插入 + 聚合表 + 分页；演示只用 50 个 hero |
| 影刀 API 不稳定 | Mock 模式兜底；真实模式只做演示/冒烟 |
| RPA 选择器脆弱 | 确定性选择器 + 截图 + 备用选择器 + 人工确认 |
| LLM 不确定 | stub 模型跑测试；真实模型只做冒烟 |
| 范围膨胀 | 锁定剧本；切线规则；每阶段一个垂直切片 |
| 演示环境故障 | 录屏 + 快照 + 一键重置 |
| 安全/合规 | 合成数据；Mock 密钥隔离；不接真实支付/物流 |

---

**执行顺序：P0 → P1 → P2 → P3 → P4 → P5。每个 Phase 结束跑检查点；未通过不进入下一 Phase。**
