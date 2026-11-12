# 台前调度台 v1.2 实施计划（阶段工作台 + Vue 3 + 平台集成边界）

> **给执行者：** 使用 `executing-plans` 或 `subagent-driven-development` 按任务顺序执行。每个任务结束都要跑测试并提交，不允许跳过失败的测试。

**目标：** 把现有单页调度台升级为「场景目录 + 今日态势 + 阶段工作台」，前端迁移到 Vue 3 + TypeScript，并为电商平台数据获取/控制接口建立 canonical model、端口、Adapter Registry 与 Mock Adapter。

**架构：** 保留现有六边形 `dispatch` 切片。领域层新增不可变阶段结果、canonical 平台模型和 typed ports；应用层新增阶段目录、聚合视图、Adapter Registry 与 ControlService；适配层新增 MockPlatformAdapter、阶段/集成 API 和 Vue 静态托管。前端只通过 HTTP + Zod 读取后端，capability 驱动动作门禁。

**技术栈：** Python 3.11、FastAPI、Pydantic v2、pytest、ruff、mypy；Vue 3.5、TypeScript strict、Vite、Vue Router 4、Pinia、@tanstack/vue-query、Zod、Vitest、Vue Test Utils、Playwright。

**Spec：** [docs/specs/2026-11-12-dispatch-console-enhancement-design.md](../specs/2026-11-12-dispatch-console-enhancement-design.md)

**状态：** 已执行（2026-11-12）。后端 87 passed；Vitest 13 passed；Playwright 9 passed；ruff/mypy/typecheck/build 通过。

## 全局约束

- 现有 53 个后端测试必须继续通过；新增字段只做增量，破坏性断言先更新夹具再改实现。
- 领域层不得导入 FastAPI、SQLAlchemy、Pydantic；应用层不得导入 `dispatch.adapters`。
- 新增/修改 Python 代码使用中文 Google 风格多行 docstring，并带完整类型标注；行宽 ≤100。
- `StageResult`、`Artifact`、`Metric`、canonical model、`ControlCommand/Result` 使用 frozen dataclass；`metrics` 用元组。
- 所有平台差异限制在 Adapter/manifest/canonical 映射；Vue 组件不得出现 `if (platform === 'tiktok')`。
- 前端 TS strict；所有 API 响应先过 Zod；禁止 `v-html`；所有交互元素 ≥44×44px。
- 1440/1024/375 三档不得出现页面级横向滚动：`document.documentElement.scrollWidth === window.innerWidth`。
- API 错误映射：未知阶段/审批/异常 → 404，重复裁决 → 409，参数/领域取值错误 → 422。
- 每次提交只包含一个可独立验证的增量；提交信息使用 `feat:` / `test:` / `docs:` / `chore:`。

---

## Task 1：领域层阶段结果与平台 canonical model

**Files:**
- Modify: `src/opsconductor/dispatch/domain/enums.py`
- Modify: `src/opsconductor/dispatch/domain/errors.py`
- Modify: `src/opsconductor/dispatch/domain/models.py`
- Modify: `src/opsconductor/dispatch/domain/ports.py`
- Test: `tests/dispatch/test_domain.py`

**Interfaces:**
- Produces: `ArtifactKind`, `Artifact`, `Metric`, `DataProvenance`, `StageResult`, `StageStep`, `StageDefinition`；`ControlStatus`、`SyncStatus`、`IntegrationStatus`、`IntegrationMode`、`Freshness`、`IntegrationCapability`；`PlatformRef` 与 9 个 canonical model；`ControlCommand`、`ControlResult`、`IntegrationError`、`DataQuery`、`DataPage[T]`、`DataQuality`、`SyncRun`、`AdapterManifest`、`IntegrationHealth`；`CommerceDataPort`、`PlatformControlPort`、`PlatformAdapter`。
- `ApprovalDraft` / `ApprovalCase` / `ExceptionCase` 新增 `stage_id: str`。

- [ ] **Step 1：写失败测试**

```python
def test_stage_result_rejects_duplicate_metrics():
    with pytest.raises(ValueError):
        StageResult(
            stage_id="order", agent_id="order", status=StageStatus.alert,
            summary="分类 6 单异常", artifacts=(), evidence=(),
            metrics=(Metric("exceptions", 6), Metric("exceptions", 7)),
            provenance=_provenance(), at="11:02",
        )


def test_stage_result_rejects_blank_summary():
    with pytest.raises(ValueError):
        StageResult(
            stage_id="order", agent_id="order", status=StageStatus.alert,
            summary="   ", artifacts=(), metrics=(), evidence=(),
            provenance=_provenance(), at="11:02",
        )


def test_canonical_order_preserves_external_id_and_raw_ref():
    order = CanonicalOrder(
        external_id="NW-1001", status="paid", currency="USD", total_usd=89,
        lines=(OrderLine(sku="NW-101", quantity=1, amount_usd=89),),
        shipping_address="San Francisco, CA", updated_at="2026-11-12T10:42:00Z",
        raw_ref="mock://orders/NW-1001",
    )
    assert order.external_id == "NW-1001"
    assert order.raw_ref == "mock://orders/NW-1001"
```

- [ ] **Step 2：跑测试确认失败**

Run: `pytest tests/dispatch/test_domain.py -q`
Expected: FAIL（`StageResult` / `CanonicalOrder` 未定义）。

- [ ] **Step 3：实现枚举、错误、模型与端口**

枚举值必须与 spec §6.7.2 逐字一致，例如 `IntegrationCapability.data_orders = "data.orders"`。`StageResult.__post_init__` 校验 `stage_id`、`agent_id`、`summary` 非空，且 metric key 唯一。`DataProvenance.__post_init__` 校验 platform/shop_id/adapter 非空。`CanonicalOrder` 的金额字段使用 `total_usd`/`amount_usd`，禁止 float 账单计算。

- [ ] **Step 4：跑领域测试**

Run: `pytest tests/dispatch/test_domain.py -q`
Expected: PASS。

- [ ] **Step 5：提交**

```bash
git add src/opsconductor/dispatch/domain tests/dispatch/test_domain.py
git commit -m "feat: add stage result and platform canonical domain contracts"
```

---

## Task 2：阶段目录、结果种子与聚合视图

**Files:**
- Create: `src/opsconductor/dispatch/application/stages.py`
- Modify: `src/opsconductor/dispatch/application/agents.py`
- Modify: `src/opsconductor/dispatch/application/seed.py`
- Modify: `src/opsconductor/dispatch/application/service.py`
- Test: `tests/dispatch/test_stages.py`
- Test: `tests/dispatch/test_service.py`

**Interfaces:**
- Produces: `STAGE_CATALOG: tuple[StageDefinition, ...]`（顺序：selection→content→listing→organic→paid→order→fulfillment→logistics→settlement→aftersales）；`STAGE_RESULTS: dict[str, StageResult]`；`CONTROL_NAV`；`StageNavigation`、`StageDetail`、`ApprovalProgress`、`StatusSummary`；`DispatchService.get_stage_detail(stage_id)`、`DispatchService.navigation()`、`status_summary()`、`approval_progress()`。
- 审批归属：`budget → paid`、`price → listing`、`refund → settlement`。异常归属：ORD-01/03/04→order，INV-01→fulfillment，LOG-03→logistics，PAY-02→settlement。

- [ ] **Step 1：写失败测试**

```python
def test_stage_catalog_has_ten_stages_in_scenario_order():
    assert [stage.id for stage in STAGE_CATALOG] == [
        "selection", "content", "listing", "organic", "paid",
        "order", "fulfillment", "logistics", "settlement", "aftersales",
    ]


def test_stage_results_cover_every_operational_stage():
    assert set(STAGE_RESULTS) == {stage.id for stage in STAGE_CATALOG}


def test_stage_detail_filters_approvals_and_exceptions_by_stage(client):
    order = client.get("/api/v1/dispatch/stages/order").json()
    assert [item["id"] for item in order["exceptions"]] == ["ORD-01", "ORD-03", "ORD-04"]
    assert order["approvals"] == []

    paid = client.get("/api/v1/dispatch/stages/paid").json()
    assert [item["id"] for item in paid["approvals"]] == ["budget"]


def test_status_summary_counts_chain_agents_approvals_exceptions(client):
    summary = client.get("/api/v1/dispatch/snapshot").json()["status_summary"]
    assert summary["chain"]["alert"] == 2
    assert summary["agents"]["running"] == 4
    assert summary["approvals"]["pending"] == 3
    assert summary["exceptions"] == {"P0": 2, "P1": 1, "P2": 2, "P3": 1}
```

- [ ] **Step 2：跑测试确认失败**

Run: `pytest tests/dispatch/test_stages.py -q`
Expected: FAIL（模块/端点不存在）。

- [ ] **Step 3：实现阶段目录与结果**

`STAGE_RESULTS` 必须逐字使用 spec §6.3 的摘要、产物名、指标与证据；金额/数量不得另编。`provenance` 固定为 `platform=mock`、`shop_id=nestwell-us`、`adapter=MockPlatformAdapter`、`schema_version=1.0`。`Metric.value` 为 `str | int`，`roas` 使用字符串 `"2.5"`。

- [ ] **Step 4：扩展种子与服务**

`DispatchState` 增加 `results: dict[str, StageResult]`；`build_seed_state` 填入 `STAGE_RESULTS`。`build_approvals`/`build_exceptions` 写入 `stage_id`。服务聚合：

```python
@dataclass(frozen=True)
class ApprovalProgress:
    total: int
    pending: int
    approved: int
    rejected: int
    decided_percent: int
    l2_total: int
    l3_total: int
```

导航 = 10 个阶段 + 1 个控制塔；控制塔 `order_label="—"`、全局计数。`get_stage_detail("control")` 和未知 ID 都抛 `StageNotFound`。

- [ ] **Step 5：跑服务与阶段测试**

Run: `pytest tests/dispatch/test_stages.py tests/dispatch/test_service.py -q`
Expected: PASS。

- [ ] **Step 6：提交**

```bash
git add src/opsconductor/dispatch/application tests/dispatch/test_stages.py tests/dispatch/test_service.py
git commit -m "feat: add stage catalog, results and status aggregation"
```

---

## Task 3：Adapter Registry、MockPlatformAdapter 与 ControlService

**Files:**
- Create: `src/opsconductor/dispatch/application/integrations.py`
- Create: `src/opsconductor/dispatch/application/control_service.py`
- Create: `src/opsconductor/dispatch/adapters/integration/__init__.py`
- Create: `src/opsconductor/dispatch/adapters/integration/mock_platform.py`
- Modify: `src/opsconductor/dispatch/adapters/container.py`
- Test: `tests/dispatch/test_integrations.py`

**Interfaces:**
- Produces: `AdapterRegistry.register/get/manifests/health`；`CapabilityRouter.resolve(capability, ref)`；`SourceOfTruthPolicy`；`MockPlatformAdapter.manifest()/health()`；`GET /api/v1/dispatch/integrations`；`ControlService.execute(command)`。
- 本期只读集成 API；不实现 `POST /sync-runs` 或 `POST /control/commands` 路由。

- [ ] **Step 1：写失败测试**

```python
def test_adapter_registry_rejects_duplicate_id():
    registry = AdapterRegistry()
    adapter = MockPlatformAdapter()
    registry.register(adapter)
    with pytest.raises(ValueError):
        registry.register(adapter)


def test_control_service_requires_approval_for_l3():
    service = ControlService(_registry(), approved=lambda _: True)
    command = make_command(risk=RiskLevel.L3, approval_id=None)
    with pytest.raises(ApprovalRequired):
        service.execute(command)


def test_control_service_rejects_unapproved_approval_id():
    service = ControlService(_registry(), approved=lambda _: False)
    with pytest.raises(ApprovalRequired):
        service.execute(make_command(risk=RiskLevel.L3, approval_id="budget"))


def test_integrations_endpoint_exposes_mock_health(client):
    data = client.get("/api/v1/dispatch/integrations").json()
    assert data["default_platform"] == "mock-nestwell-us"
    platform = data["platforms"][0]
    assert platform["status"] == "mock"
    assert "data.orders" in platform["capabilities"]
    assert platform["freshness"] == "fresh"
```

- [ ] **Step 2：跑测试确认失败**

Run: `pytest tests/dispatch/test_integrations.py -q`
Expected: FAIL（模块/端点不存在）。

- [ ] **Step 3：实现 Adapter Registry 与 Mock Adapter**

`MockPlatformAdapter` 声明 manifest（adapter_id=`mock-nestwell-us`、platform=`mock`、version=`1.0`、Mock 支持的 data/control capabilities、`supports_dry_run=True`、`supports_idempotency=True`）。`health()` 返回 `status=mock`、`mode=mock`、`last_sync_at="10:42"`、`freshness=fresh`、`warnings=()`。

数据方法返回 `DataPage`，`source` 为 `DataProvenance`；`execute()` 对未声明 capability 抛 `CapabilityNotSupported`，`dry_run=True` 返回 `accepted`，否则返回 `succeeded`。所有返回值带 `evidence` 与 `adapter_meta`。

- [ ] **Step 4：实现 ControlService 硬规则**

顺序：resolve adapter → capability 门禁 → L2/L3 必须 `approval_id` 且 `approved(approval_id)` 为真 → 幂等键校验 → 执行。同键同 body 返回首次结果；同键不同 body 抛 `IdempotencyConflict`。失败结果必须包含 `IntegrationError`。

- [ ] **Step 5：装配与集成 API**

`container.py` 构建 `AdapterRegistry`、注册一个 `MockPlatformAdapter`，暴露 `get_integration_registry()`；测试用 `reset_service()` 同时重建注册表。API 返回 `default_platform` + `platforms`（platform/shop_id/name/status/mode/capabilities/last_sync_at/freshness/warnings）。

- [ ] **Step 6：跑集成测试**

Run: `pytest tests/dispatch/test_integrations.py -q`
Expected: PASS。

- [ ] **Step 7：提交**

```bash
git add src/opsconductor/dispatch tests/dispatch/test_integrations.py
git commit -m "feat: add adapter registry, mock platform adapter and control guard"
```

---

## Task 4：阶段详情 API 与 snapshot 契约扩展

**Files:**
- Modify: `src/opsconductor/dispatch/adapters/serialize.py`
- Modify: `src/opsconductor/dispatch/adapters/api.py`
- Modify: `tests/dispatch/test_api_smoke.py`
- Test: `tests/dispatch/test_stages.py`

**Interfaces:**
- Produces: `GET /api/v1/dispatch/stages/{stage_id}`；snapshot 新增 `navigation`、`status_summary`、`approval_progress`；approval/exception JSON 新增 `stage_id`；`stage_result_payload`、`stage_definition_payload`、`stage_detail_payload`、`navigation_payload`、`status_summary_payload`、`approval_progress_payload`、`integrations_payload`。

- [ ] **Step 1：更新失败契约断言**

在 `test_api_smoke.py` 的 `set(data)` 中加入 `navigation`、`status_summary`、`approval_progress`；`APPROVAL_FIELDS` 与 `EXCEPTION_FIELDS` 加入 `stage_id`。新增：

```python
def test_stage_detail_endpoint_returns_agent_output(client):
    data = client.get("/api/v1/dispatch/stages/order").json()
    assert data["name"] == "订单"
    assert data["result"]["summary"].startswith("分类 6 单异常")
    assert data["result"]["metrics"]["exceptions"] == 6
    assert data["result"]["source"]["adapter"] == "MockPlatformAdapter"
    assert [artifact["name"] for artifact in data["result"]["artifacts"]] == [
        "order-exceptions.csv", "split-address-plan.json",
    ]


def test_unknown_stage_returns_404(client):
    assert client.get("/api/v1/dispatch/stages/unknown").status_code == 404


def test_control_stage_detail_returns_404(client):
    assert client.get("/api/v1/dispatch/stages/control").status_code == 404
```

- [ ] **Step 2：跑测试确认失败**

Run: `pytest tests/dispatch/test_api_smoke.py -q`
Expected: FAIL（字段缺失、端点 404）。

- [ ] **Step 3：实现序列化与端点**

`stage_detail_payload` 输出 definition 字段 + `status`/`meta`/`result`/`approvals`/`exceptions`。`stage_result_payload` 的 metrics 由元组转对象，`provenance` 序列化为 `source`。未知阶段/控制塔统一 404 `{"detail": "unknown stage: xxx"}`。

- [ ] **Step 4：跑完整后端测试**

Run: `pytest tests/dispatch tests/test_health.py -q`
Expected: 53 个既有测试（已更新断言）+ 新增测试全部 PASS。

- [ ] **Step 5：静态检查**

Run: `ruff check src/opsconductor/dispatch src/opsconductor/api tests/dispatch`
Run: `python -s -m mypy src`
Expected: 无新增错误。

- [ ] **Step 6：提交**

```bash
git add src/opsconductor/dispatch/adapters tests/dispatch/test_api_smoke.py
git commit -m "feat: expose stage detail and integration snapshot contracts"
```

---

## Task 5：Vue 3 脚手架、API 契约与离线 fixture

**Files:**
- Create: `frontend/package.json`, `vite.config.ts`, `tsconfig.json`, `vitest.config.ts`, `playwright.config.ts`, `index.html`
- Create: `frontend/src/main.ts`, `App.vue`, `router/index.ts`
- Create: `frontend/src/api/client.ts`, `schemas.ts`, `dispatch.ts`, `fixtures.ts`, `fixtures.json`, `types.ts`
- Create: `frontend/src/stores/ui.ts`
- Create: `frontend/src/queries/useSnapshotQuery.ts`, `useStageDetailQuery.ts`, `useIntegrationsQuery.ts`, `mutations.ts`
- Create: `frontend/src/tests/unit/schemas.spec.ts`, `ui-store.spec.ts`
- Create: `scripts/export_dispatch_fixtures.py`
- Test: `frontend/src/tests/unit/*.spec.ts`

**Interfaces:**
- Produces: `Snapshot`、`StageDetail`、`IntegrationsResponse` 类型（由 Zod infer）；`getSnapshot/getStageDetail/getIntegrations/createGoal/decideApproval/resetApprovals/runDemo/resetDispatch`；`useSnapshotQuery/useStageDetailQuery/useIntegrationsQuery`；`useDecisionMutation/useGoalMutation/useDemoMutation/useResetMutation`；`fallbackSnapshot/fallbackStageDetails/fallbackIntegrations`。

- [ ] **Step 1：初始化工程与依赖**

`package.json` 使用 `vue@^3.5`、`vue-router@^4.5`、`pinia@^2.3`、`@tanstack/vue-query@^5.62`、`zod@^3.24`；devDependencies 使用 `vite@^6`、`@vitejs/plugin-vue@^5`、`typescript@~5.7`、`vue-tsc@^2.2`、`vitest@^2.1`、`@vue/test-utils@^2.4`、`jsdom@^25`、`@playwright/test@^1.49`。执行 `npm install` 生成 lockfile。

- [ ] **Step 2：生成离线 fixture**

新增 `scripts/export_dispatch_fixtures.py`：`reset_service()` 后导出 `snapshot_payload`、每个 `STAGE_CATALOG` 的 `stage_detail_payload`、`integrations_payload` 到 `frontend/src/api/fixtures.json`。该脚本只读，不修改仓储。

- [ ] **Step 3：写 Zod schema 与契约测试**

```ts
const StageResultSchema = z.object({
  stage_id: z.string(),
  agent_id: z.string(),
  status: z.string(),
  summary: z.string().min(1),
  artifacts: z.array(z.object({
    name: z.string(), kind: z.string(), uri: z.string(), description: z.string(),
  })),
  metrics: z.record(z.union([z.string(), z.number()])),
  evidence: z.array(z.string()),
  source: z.object({
    platform: z.string(), shop_id: z.string(), adapter: z.string(),
    synced_at: z.string(), schema_version: z.string(),
  }),
  at: z.string(),
});
```

测试：合法 fixture 解析成功；删除 `summary` 或把 `metrics` 改成数组时抛 `ApiContractError`。

- [ ] **Step 4：写 API client 与 queries**

`API_BASE = import.meta.env.VITE_API_BASE ?? '/api/v1/dispatch'`。所有请求接受 `AbortSignal`，非 2xx 转 `ApiError {status, code, detail, retryable}`；Zod 失败转 `ApiContractError`。Query keys 使用 `['dispatch','snapshot']`、`['dispatch','stage',id]`、`['dispatch','integrations']`；审批 mutation 成功后同时失效 snapshot 与受影响 stage。

- [ ] **Step 5：跑类型检查与单测**

Run: `cd frontend && npm run typecheck && npm run test:unit`
Expected: PASS。

- [ ] **Step 6：提交**

```bash
git add frontend scripts/export_dispatch_fixtures.py
git commit -m "feat: scaffold vue dispatch console with typed api contracts"
```

---

## Task 6：布局、场景目录与首页今日态势

**Files:**
- Create: `frontend/src/styles/tokens.css`, `base.css`
- Create: `frontend/src/components/layout/AppShell.vue`, `AppTopbar.vue`, `AppSidebar.vue`, `MobileDrawer.vue`
- Create: `frontend/src/components/ui/StatusDot.vue`, `RiskBadge.vue`, `ProgressBar.vue`, `ArtifactChip.vue`, `Seal.vue`
- Create: `frontend/src/features/overview/OverviewView.vue`, `StatusBoard.vue`, `ApprovalProgressCard.vue`, `ChainMatrix.vue`, `AgentStatusGrid.vue`, `ExceptionDistribution.vue`, `IntegrationHealthCard.vue`
- Test: `frontend/src/tests/unit/status-board.spec.ts`, `sidebar.spec.ts`

**Interfaces:**
- Consumes: `useSnapshotQuery`、`useIntegrationsQuery`、`uiStore`、`Snapshot`。
- Produces: 11 组侧栏（10 阶段 + 控制塔）+ 固定「总览」入口；`data-sidebar`、`data-status-board` 契约钩子。

- [ ] **Step 1：写失败组件测试**

断言 `StatusBoard` 渲染审批进度 `0/3`、链路 10 格、Agent 8 个、异常 P0–P3；`AppSidebar` 渲染 11 组，当前 `order` 项有 `aria-current="page"`。

- [ ] **Step 2：实现设计 tokens 与外壳**

tokens 使用纸白 `#F7F3E9`、墨 `#17130F`、朱砂 `#A8342A`、靛青 `#2C4A56`、鎏金 `#A8894F`；标题宋体、正文仿宋、批注楷体、数字等宽。桌面侧栏 260px sticky，移动端抽屉 + 遮罩 + ESC + body 滚动锁。

- [ ] **Step 3：实现侧栏**

分组折叠；当前阶段组自动展开；组头显示序号、状态点、待批/异常计数；子流程点击进入 `/dispatch/stages/:id?step=`。路由变化时关闭移动抽屉。`nav[aria-label="场景目录"]`、`aria-expanded`、`aria-current` 齐全。

- [ ] **Step 4：实现首页态势**

命令栏 + 4 KPI + 审批进度分段条 + 链路矩阵 + Agent chips + P0–P3 分布 + 集成健康卡 + 审批/异常/trace 摘要。审批后快照失效并实时更新。后端不可用时使用 fixture 并显示「离线数据」横幅，不伪造成功。

- [ ] **Step 5：跑单测与类型检查并做 1440/375 手检**

Run: `cd frontend && npm run typecheck && npm run test:unit`
手工检查 `document.documentElement.scrollWidth === window.innerWidth`。

- [ ] **Step 6：提交**

```bash
git add frontend
git commit -m "feat: add vue app shell, scenario sidebar and status board"
```

---

## Task 7：阶段工作台、审批/异常/集成视图

**Files:**
- Create: `frontend/src/features/stage/StageView.vue`, `StageWorkspace.vue`, `StageHeader.vue`, `StageFlow.vue`, `StageResultPanel.vue`, `ArtifactList.vue`, `MetricList.vue`, `EvidenceList.vue`, `StageContext.vue`
- Create: `frontend/src/features/approvals/ApprovalsView.vue`, `ApprovalCard.vue`
- Create: `frontend/src/features/exceptions/ExceptionsView.vue`, `ExceptionDrawer.vue`
- Create: `frontend/src/features/integrations/IntegrationsView.vue`, `IntegrationStatus.vue`, `CapabilityBadge.vue`, `FreshnessBadge.vue`
- Create: `frontend/src/features/trace/TraceTimeline.vue`
- Test: `frontend/src/tests/unit/stage-result.spec.ts`, `approval-card.spec.ts`, `integration-status.spec.ts`

**Interfaces:**
- Consumes: `useStageDetailQuery(stageId)`、`fallbackStageDetails[stageId]`、`useDecisionMutation`、`useIntegrationsQuery`。
- Produces: 三栏阶段工作台；`data-stage-result` 契约钩子；审批准/驳/重置；异常 playbook 抽屉；集成能力清单。

- [ ] **Step 1：写失败组件测试**

`StageResultPanel` 渲染摘要、`order-exceptions.csv`、指标 `exceptions=6`、证据、来源 `MockPlatformAdapter / NestWell Home US`；空结果渲染「本阶段暂无产出」；`CapabilityBadge` 按 data/control 分组；无 capability 时不渲染执行按钮。

- [ ] **Step 2：实现阶段视图**

三栏：流程步骤（当前 `?step=` 高亮）、Agent 产出、本阶段上下文（审批/异常/trace/文档）。加载态骨架、404「阶段不存在」、网络错误「离线数据」+ 重试。摘要最多 2 行可展开；产物列表使用书签样式；指标等宽；来源显示平台/店铺/Adapter/同步时间/schema。

- [ ] **Step 3：迁移审批与异常**

审批卡保留朱印「准/驳」、风险、影响、建议；裁决失败 toast 并回滚按钮。异常列表支持 P0–P3 过滤；抽屉展示 trigger + 3 个阶段 + automation，ESC 关闭。所有字符串用 Vue 插值，不拼接 HTML。

- [ ] **Step 4：实现集成健康页与能力门禁**

`/dispatch/integrations` 展示平台/店铺、mock/live、能力分组、最近同步、freshness、warnings；只读提示「本期 Mock，真实同步/控制未启用」。动作按钮按 capability 显示，不支持的显示「当前 Adapter 不支持此动作」。

- [ ] **Step 5：跑单测、类型检查、构建**

Run: `cd frontend && npm run typecheck && npm run test:unit && npm run build`
Expected: PASS，生成 `frontend/dist`。

- [ ] **Step 6：提交**

```bash
git add frontend
git commit -m "feat: add stage workspace, approvals, exceptions and integrations views"
```

---

## Task 8：Vue 接管 /dispatch、E2E 与收尾

**Files:**
- Modify: `src/opsconductor/dispatch/adapters/page.py`
- Modify: `src/opsconductor/dispatch/adapters/container.py`（如需要）
- Create: `scripts/build_frontend.sh`
- Create: `frontend/e2e/dispatch.spec.ts`, `stage.spec.ts`, `mobile.spec.ts`
- Modify: `design/cross-border-dispatch/index.html`（P1 文案）
- Modify: `README.md`, `design/cross-border-dispatch/README.md`, `docs/README.md`
- Test: `tests/dispatch/test_api_smoke.py`, `frontend/e2e/*.spec.ts`

**Interfaces:**
- Produces: FastAPI 服务 `frontend/dist/index.html`；`/dispatch/{path:path}` SPA fallback；`/assets/*` 静态文件；`OPSCONDUCTOR_DISPATCH_UI=legacy` 临时回退；`bash scripts/build_frontend.sh`。

- [ ] **Step 1：写失败页面测试**

`GET /dispatch` 返回 Vue index，包含 `id="app"` 和加载的 `/assets/` 脚本；`GET /dispatch/stages/order` 返回同一 index（SPA fallback）；`GET /assets/...` 200；`OPSCONDUCTOR_DISPATCH_UI=legacy` 返回旧页面。dist 缺失时 503 且 body 提示构建命令。

- [ ] **Step 2：实现静态托管**

`page.py` 解析 `Path(__file__).parents[3] / "frontend" / "dist"`；只对 `/dispatch` 和 `/dispatch/{path}` 做 SPA fallback，不吞 `/api`。`/assets` 使用 `StaticFiles`。legacy 环境变量只服务旧 HTML。

- [ ] **Step 3：构建与启动检查**

Run: `bash scripts/build_frontend.sh`
Run: `PORT=8010 bash scripts/demo_dispatch.sh`
验证：`GET /health` 200、`GET /dispatch` 200、`GET /api/v1/dispatch/snapshot` 含新字段、控制台 0 错误、375 无横向滚动。

- [ ] **Step 4：修 P1 演示投影文案**

旧页面演示完成 toast 追加「只读投影，审批状态未改变」；Vue 演示按钮同样提示。若改为落审批，必须同步后端状态并更新测试，二选一，本期选文案修复。

- [ ] **Step 5：Playwright 冒烟**

配置 `channel: 'chrome'`，不下载浏览器。覆盖：首页状态、侧栏订单、阶段结果、审批更新、异常抽屉、集成页、375 抽屉与无溢出。若本机无 Chrome，记录为未执行，不伪报通过。

Run: `cd frontend && npm run test:e2e`

- [ ] **Step 6：全量回归**

```bash
pytest tests/dispatch tests/test_health.py -q
ruff check src/opsconductor/dispatch src/opsconductor/api tests/dispatch
python -s -m mypy src
cd frontend && npm run typecheck && npm run test:unit && npm run build
```

Expected: 全部 PASS；Playwright 结果如实记录。

- [ ] **Step 7：更新文档并提交**

更新根 README、设计 README、`docs/README.md`、`polish-log.md`：Vue 开发/构建/启动命令、Mock 边界、后续 Adapter 接入步骤、API 变更。

```bash
git add src tests frontend scripts design README.md docs
git commit -m "feat: serve vue dispatch console and complete v1.2 acceptance"
```

---

## 自检清单

- [ ] spec §6.3 的 10 个阶段结果逐字落地，未编造金额。
- [ ] snapshot 新增 navigation/status_summary/approval_progress，旧字段不删。
- [ ] approval/exception 带 stage_id；阶段详情按 stage 过滤正确。
- [ ] `/stages/control` 与未知阶段 404。
- [ ] `MockPlatformAdapter` manifest/health 可查；`/integrations` 只读。
- [ ] ControlService 对 L2/L3 强制 approval_id 与 approved 校验；幂等冲突可复现。
- [ ] Vue 无平台名分支；动作由 capability 驱动。
- [ ] 1440/1024/375 无页面级横向滚动；无 `v-html`。
- [ ] 旧 53 个测试 + 新增测试通过；ruff/mypy/typecheck/unit/build 通过。
- [ ] 文档、fixture、提交信息同步；P1 文案已修复。
