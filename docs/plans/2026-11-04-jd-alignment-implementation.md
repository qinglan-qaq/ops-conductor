# JD 对齐阶段实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 MVP 完成后用 3 周补齐 JD 能力：ERP Adapter + 聚水潭契约、SKILL、Memory/反思、RAG 退款资格判定、Playwright RPA、多模型路由与 60+ 评测。

**Architecture:** 在现有 FastAPI + LangGraph + MCP + PostgreSQL 骨架上增加 `erp/`、`skills/`、`memory/`、`rag/`、`rpa/`、`llm/` 六个能力模块；ERP 通过 Adapter 抽象，真实端点与契约 mock 可替换；RAG 只做退款资格判定，不接真实支付；RPA 只做旧系统浏览器兜底。

**Tech Stack:** Python 3.11、FastAPI、Pydantic 2、SQLAlchemy 2 async、PostgreSQL 16 + pgvector、LangGraph、MCP 2.3、Playwright、BGE-M3/BM25/重排、httpx、pytest、ruff、mypy。

**Spec:** [JD 对齐设计方案](../specs/2026-11-04-jd-alignment-design.md) ｜ [订单异常 MVP 实施计划](2026-11-04-mvp-order-exception-implementation.md)

## Global Constraints

- 本计划在 MVP 计划 Task 1–15 全部通过后开始；未完成的接口以 MVP 计划为准。
- ERP 集成使用 Adapter 接口；`MiniErpAdapter` 与 `JushuitanContractAdapter` 必须跑同一组契约测试。
- 聚水潭契约只使用公开文档形态和测试密钥；不得使用真实商家凭据、真实生产接口或真实 PII。
- RAG 只输出退款资格与金额建议，不调用支付/退款接口，不产生真实资金操作。
- RPA 只做浏览器自动化；桌面自动化不在范围。
- 所有租户相关查询、检索、工具调用和审计必须带 `tenant_id`。
- RAG/RPA 依赖较重，使用 optional extras 安装：
  - `pip install -e ".[dev,rag,rpa]"`
  - `playwright install chromium`
- 测试默认使用 stub embedder、stub 模型和本地 mock server；真实模型/浏览器测试单独标记。

---

### Task 1: ERP Adapter 与聚水潭契约 mock

**Files:**
- Modify: `pyproject.toml`（增加 `httpx` 已有，新增 `respx` 可选测试依赖）
- Create: `src/opsconductor/erp/adapter.py`
- Create: `src/opsconductor/erp/mini.py`
- Create: `src/opsconductor/erp/jushuitan.py`
- Create: `src/opsconductor/erp/mock_server.py`
- Create: `tests/erp/test_contract.py`
- Modify: `src/opsconductor/tools/server.py`
- Modify: `src/opsconductor/config.py`

**Interfaces:**
- `ErpAdapter` Protocol：`list_overdue_orders`、`get_order`、`get_inventory`、`list_shipments`、`split_order`、`change_address`。
- `MiniErpAdapter(session_factory)`：包装现有 repositories/write_service。
- `JushuitanContractAdapter(base_url, app_key, app_secret)`：httpx 调用契约 mock。
- `create_mock_app() -> FastAPI`：聚水潭形状的测试服务。

- [ ] **Step 1: 写契约测试**

`tests/erp/test_contract.py`：

```python
import pytest

from opsconductor.domain.seed import TENANT_A
from opsconductor.erp.mini import MiniErpAdapter
from opsconductor.erp.jushuitan import JushuitanContractAdapter
from opsconductor.erp.mock_server import create_mock_app


@pytest.mark.asyncio
async def test_adapters_have_same_order_shape(seeded_db):
    import httpx

    mini = MiniErpAdapter()
    jst = JushuitanContractAdapter(
        base_url="http://testserver", app_key="test-key", app_secret="test-secret",
        transport=httpx.ASGITransport(app=create_mock_app()),
    )
    tenant_id = str(TENANT_A)
    mini_result = await mini.get_order(tenant_id, "O1001")
    jst_result = await jst.get_order(tenant_id, "O1001")
    assert set(mini_result) == set(jst_result)
    assert mini_result["order_no"] == jst_result["order_no"]
```

契约测试必须使用 `httpx.ASGITransport(app=create_mock_app())` 注入 mock；两个 Adapter 共用同一组断言。真实端点后续只需替换 `base_url`。

- [ ] **Step 2: 实现 Adapter 接口**

`erp/adapter.py`：

```python
from typing import Any, Protocol


class ErpAdapter(Protocol):
    async def list_overdue_orders(self, tenant_id: str, warehouse: str | None = None) -> list[dict[str, Any]]: ...
    async def get_order(self, tenant_id: str, order_id: str) -> dict[str, Any]: ...
    async def get_inventory(self, tenant_id: str, sku_id: str, warehouse_id: str) -> dict[str, Any]: ...
    async def list_shipments(self, tenant_id: str, order_id: str) -> list[dict[str, Any]]: ...
    async def split_order(self, tenant_id: str, order_id: str, shipments: list[dict], idempotency_key: str, dry_run: bool) -> dict[str, Any]: ...
    async def change_address(self, tenant_id: str, order_id: str, address: dict, idempotency_key: str, dry_run: bool) -> dict[str, Any]: ...
```

`MiniErpAdapter` 使用 `SessionLocal`，把现有 service/write_service 的返回值映射成统一 dict；所有方法内部用 `async with SessionLocal()`。

`JushuitanContractAdapter`：

```python
class JushuitanContractAdapter:
    def __init__(self, base_url: str, app_key: str, app_secret: str, transport=None):
        self.base_url = base_url.rstrip("/")
        self.app_key = app_key
        self.app_secret = app_secret
        self.transport = transport

    def _sign(self, timestamp: str) -> str:
        import hashlib
        raw = f"{self.app_key}{timestamp}{self.app_secret}"
        return hashlib.md5(raw.encode()).hexdigest()

    async def get_order(self, tenant_id: str, order_id: str) -> dict:
        import time
        import httpx
        timestamp = str(int(time.time()))
        async with httpx.AsyncClient(base_url=self.base_url, timeout=10, transport=self.transport) as client:
            response = await client.get(
                "/open/orders/detail",
                params={"app_key": self.app_key, "timestamp": timestamp, "sign": self._sign(timestamp), "order_id": order_id},
                headers={"X-Tenant-Id": tenant_id},
            )
            response.raise_for_status()
            return response.json()["data"]
```

`erp/mock_server.py` 提供 `/open/orders/query`、`/open/orders/detail`、`/open/inventory/query`、`/open/orders/split`、`/open/orders/address`，用 `X-Tenant-Id` 注入租户；签名校验失败返回 401。数据来自 Mini ERP 种子库或进程内 fixture，不接真实商家数据。

- [ ] **Step 3: 切换 MCP 工具到 Adapter**

`tools/server.py` 根据 `settings.erp_adapter` 创建 `MiniErpAdapter` 或 `JushuitanContractAdapter`；工具名和返回结构保持不变，内部调用 Adapter。增加配置：

```python
erp_adapter: str = "mini"
jushuitan_base_url: str = "http://127.0.0.1:8100"
jushuitan_app_key: str = "test-key"
jushuitan_app_secret: str = "test-secret"
```

- [ ] **Step 4: 运行契约测试**

```bash
pip install respx
pytest tests/erp/test_contract.py -q
```

预期：两个 Adapter 返回同一形状；签名错误被拒绝；跨租户请求被拒绝。

- [ ] **Step 5: 提交**

```bash
git add src/opsconductor/erp src/opsconductor/tools/server.py src/opsconductor/config.py tests/erp
git commit -m "feat: add ERP adapter and Jushuitan contract mock"
```

### Task 2: SKILL 注册表与订单异常技能

**Files:**
- Create: `src/opsconductor/skills/models.py`
- Create: `src/opsconductor/skills/registry.py`
- Create: `src/opsconductor/skills/order_exception.yaml`
- Create: `tests/skills/test_registry.py`
- Modify: `src/opsconductor/orchestrator/planner.py`

**Interfaces:**
- `Skill`：`id`、`version`、`intent`、`steps`、`tools`、`risk`、`preconditions`、`postconditions`、`prompt`。
- `SkillRegistry.load(path)`、`SkillRegistry.get(skill_id)`、`SkillRegistry.select(intent)`。
- `TemplatePlanner(session, registry).plan(task)` 读取技能模板。

- [ ] **Step 1: 写注册表测试**

覆盖：YAML 加载；重复 id 拒绝；缺失字段拒绝；未知工具拒绝；按 intent 选择技能；版本冲突拒绝。

- [ ] **Step 2: 实现 SKILL 模型与加载器**

`skills/models.py`：

```python
from pydantic import BaseModel, Field


class SkillStep(BaseModel):
    node_id: str
    action: str
    tool: str
    risk: str = "L2"
    depends_on: list[str] = Field(default_factory=list)


class Skill(BaseModel):
    id: str
    version: str
    intent: str
    tools: list[str]
    steps: list[SkillStep]
    preconditions: list[str] = Field(default_factory=list)
    postconditions: list[str] = Field(default_factory=list)
    prompt: str = ""
```

`registry.py` 使用 `yaml.safe_load`，校验工具白名单，按 `intent` 返回最高版本。

`skills/order_exception.yaml`：

```yaml
id: order_exception
version: "1.0"
intent: order_exception
tools:
  - order_list_overdue
  - order_get
  - inventory_get
  - address_validate
  - shipment_list
  - order_split
  - order_change_address
steps:
  - node_id: query
    action: query
    tool: order_list_overdue
    risk: L0
  - node_id: split
    action: split_order
    tool: order_split
    risk: L2
    depends_on: [query]
  - node_id: address
    action: change_address
    tool: order_change_address
    risk: L2
    depends_on: [query]
preconditions:
  - order.status == pending_shipment
postconditions:
  - order.status == split
  - inventory.available >= 0
prompt: "先查询超时订单，再按库存和地址异常生成拆单/改址计划。"
```

- [ ] **Step 3: 让 Planner 使用 SKILL**

`TemplatePlanner` 加载 `order_exception` 技能，使用技能的工具白名单和步骤生成 `PlanNode`；未知动作/工具直接拒绝。保留原有规则作为技能参数。

- [ ] **Step 4: 运行测试并提交**

```bash
pytest tests/skills/test_registry.py -q
git add src/opsconductor/skills src/opsconductor/orchestrator/planner.py tests/skills
git commit -m "feat: add skill registry and order exception skill"
```

### Task 3: Memory、失败记忆与反思

**Files:**
- Create: `src/opsconductor/memory/models.py`
- Create: `src/opsconductor/memory/store.py`
- Create: `src/opsconductor/orchestrator/reflection.py`
- Create: `migrations/versions/0002_failure_memory.py`
- Create: `tests/memory/test_failure_memory.py`

**Interfaces:**
- `FailureMemory`：`tenant_id`、`signature`、`strategy`、`success_count`、`failure_count`。
- `record_failure(session, tenant_id, signature, strategy)`。
- `lookup_strategy(session, tenant_id, signature) -> str | None`。
- `Reflection.decide(error, memory) -> "retry" | "replan" | "handoff"`。

- [ ] **Step 1: 写记忆测试**

```python
import pytest

from opsconductor.db import SessionLocal
from opsconductor.domain.seed import TENANT_A
from opsconductor.memory.store import lookup_strategy, record_failure


@pytest.mark.asyncio
async def test_failure_memory_roundtrip(seeded_db):
    async with SessionLocal() as session:
        await record_failure(session, TENANT_A, "TOOL_TIMEOUT:order_split", "retry")
        assert await lookup_strategy(session, TENANT_A, "TOOL_TIMEOUT:order_split") == "retry"
        assert await lookup_strategy(session, TENANT_A, "unknown") is None
```

- [ ] **Step 2: 实现模型、存储与反思**

`memory/models.py` 定义 `FailureMemory`，唯一约束 `(tenant_id, signature)`；`store.py` 用 upsert 语义：存在则 `success_count += 1`，否则插入。`reflection.py` 按错误类型决策：
- `TIMEOUT`/`CONFLICT` → retry（有限次数）；
- `INVALID_STATE`/`VALIDATION_ERROR` → replan；
- `PERMISSION_DENIED`/重复失败 → handoff。

- [ ] **Step 3: 接入执行器**

执行器捕获异常后调用 `Reflection.decide`，并在 `TaskStep` 记录策略；重试次数超过预算直接 handoff。测试覆盖：超时重试、非法状态重规划、权限错误转人工。

- [ ] **Step 4: 运行测试并提交**

```bash
alembic revision --autogenerate -m "failure memory"
alembic upgrade head
pytest tests/memory -q
git add src/opsconductor/memory src/opsconductor/orchestrator/reflection.py migrations/versions tests/memory
git commit -m "feat: add failure memory and reflection"
```

### Task 4: RAG 政策检索与退款资格判定

**Files:**
- Modify: `pyproject.toml`（optional extras `rag = ["pgvector", "sentence-transformers", "rank-bm25", "jieba"]`）
- Create: `src/opsconductor/rag/models.py`
- Create: `src/opsconductor/rag/ingest.py`
- Create: `src/opsconductor/rag/retrieve.py`
- Create: `src/opsconductor/rag/embeddings.py`
- Create: `src/opsconductor/domain/refund.py`
- Create: `src/opsconductor/skills/refund_eligibility.yaml`
- Create: `src/opsconductor/api/routes/refunds.py`
- Create: `migrations/versions/0003_knowledge.py`
- Create: `tests/rag/test_refund_eligibility.py`
- Create: `data/policies/*.md`（合成政策文本）

**Interfaces:**
- `KnowledgeDoc`：`tenant_id`、`doc_id`、`title`、`version`、`effective_from`、`effective_to`、`category`。
- `KnowledgeChunk`：`doc_id`、`content`、`embedding Vector(1024)`、`metadata`。
- `ingest_documents(session, tenant_id, paths)`。
- `retrieve(session, tenant_id, query, category, effective_at, top_k=5) -> list[Evidence]`。
- `calculate_refund(order, policy_evidence) -> RefundDecision`。
- `POST /api/v1/refunds/eligibility`（只读）。

- [ ] **Step 1: 写 RAG 测试**

覆盖：
- 命中正确政策并返回引用、版本、生效时间；
- 过期政策不返回；
- 冲突政策按生效时间选择；
- 跨租户不可见；
- 证据不足返回 `insufficient_evidence`；
- 金额计算包含商品、运费、优惠、已退。

- [ ] **Step 2: 实现知识表与摄取**

`rag/models.py` 使用 `pgvector.sqlalchemy.Vector(1024)`；`ingest.py` 读取 Markdown，按标题/段落切块，调用 `Embedder.embed(texts)`。`embeddings.py` 定义：
```python
class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class StubEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.01] * 1024 for _ in texts]
```
真实实现使用 `sentence-transformers` 加载 `BAAI/bge-m3`；测试注入 `StubEmbedder`。

- [ ] **Step 3: 实现混合检索与重排**

`retrieve.py`：
1. 元数据过滤（tenant、category、effective_at）；
2. 向量召回（pgvector cosine）；
3. BM25 召回（jieba 分词 + rank_bm25）；
4. RRF 融合；
5. 轻量 cross-encoder 重排（可配置，测试用恒等重排）；
6. 证据组装（来源、版本、生效时间、chunk_id）。
返回 `Evidence` 列表，引用必须包含 `doc_id`、`version`、`effective_from`。

- [ ] **Step 4: 实现退款资格判定**

`domain/refund.py` 只做计算与政策匹配，不调用支付：
```python
from decimal import Decimal

from pydantic import BaseModel


class RefundOrder(BaseModel):
    tenant_id: str
    order_id: str
    product_amount: Decimal
    shipping_fee: Decimal = Decimal("0")
    discount: Decimal = Decimal("0")
    refunded_amount: Decimal = Decimal("0")
    category: str


class RefundDecision(BaseModel):
    eligible: bool
    reason: str
    amount: Decimal
    breakdown: dict[str, Decimal]
    citations: list[dict]


async def judge_refund(order: RefundOrder, evidence: list[Evidence]) -> RefundDecision:
    if not evidence:
        return RefundDecision(
            eligible=False, reason="insufficient_evidence", amount=Decimal("0"),
            breakdown={}, citations=[],
        )
    amount = order.product_amount + order.shipping_fee - order.discount - order.refunded_amount
    amount = max(amount, Decimal("0"))
    return RefundDecision(
        eligible=amount > 0,
        reason="eligible" if amount > 0 else "no_refundable_amount",
        amount=amount,
        breakdown={
            "product": order.product_amount,
            "shipping": order.shipping_fee,
            "discount": order.discount,
            "refunded": order.refunded_amount,
        },
        citations=[{"doc_id": e.doc_id, "version": e.version, "effective_from": e.effective_from} for e in evidence],
    )
```
规则：政策必须覆盖订单类目且在有效期内；金额 = 商品金额 + 运费 - 优惠 - 已退；证据不足时 `eligible=False`。`skills/refund_eligibility.yaml` 约束工具白名单和只读风险 L0。

- [ ] **Step 5: 运行测试并提交**

```bash
pip install -e ".[dev,rag]"
alembic revision --autogenerate -m "knowledge documents"
alembic upgrade head
pytest tests/rag -q
git add pyproject.toml src/opsconductor/rag src/opsconductor/domain/refund.py src/opsconductor/skills/refund_eligibility.yaml src/opsconductor/api/routes/refunds.py migrations/versions tests/rag data/policies
git commit -m "feat: add RAG policy retrieval and refund eligibility"
```

### Task 5: Playwright 旧系统 RPA

**Files:**
- Modify: `pyproject.toml`（optional extras `rpa = ["playwright"]`）
- Create: `src/opsconductor/rpa/legacy_app.py`
- Create: `src/opsconductor/rpa/workflow.py`
- Create: `src/opsconductor/rpa/runner.py`
- Create: `src/opsconductor/rpa/legacy_print.yaml`
- Modify: `src/opsconductor/tools/server.py`
- Create: `tests/rpa/test_legacy_print.py`

**Interfaces:**
- `BrowserStep`：`action`（goto/fill/click/assert_text）、`selector`、`value`、`timeout_ms`。
- `run_workflow(base_url, workflow, screenshots_dir) -> dict`。
- MCP 工具 `legacy_print_shipment`。

- [ ] **Step 1: 写浏览器测试**

在 `pyproject.toml` 注册：

```toml
[tool.pytest.ini_options]
markers = ["browser: Playwright browser integration tests"]
```

`tests/rpa/test_legacy_print.py` 标记 `@pytest.mark.browser`：
1. 启动 legacy app（uvicorn 或 TestServer）；
2. 运行 `legacy_print.yaml`；
3. 断言页面出现「已打印」；
4. 断言截图文件存在；
5. 注入选择器错误，验证重试/失败报告。

- [ ] **Step 2: 实现旧版打单页**

`rpa/legacy_app.py` 用 FastAPI 提供：
- `GET /legacy/orders/{order_no}`：返回一个只有 Web UI 的旧版页面；
- 表单填写 `tracking_no`；
- `POST /legacy/print`：返回「已打印」并写内存记录。
不使用真实物流单号，种子数据用 `TEST-TRACKING-001`。

- [ ] **Step 3: 实现工作流 DSL 与执行器**

`rpa/legacy_print.yaml`：

```yaml
name: legacy_print
start_url: "http://127.0.0.1:8101/legacy/orders/O1001"
steps:
  - action: fill
    selector: "#tracking_no"
    value: "TEST-TRACKING-001"
  - action: click
    selector: "#print-button"
  - action: assert_text
    selector: "#status"
    value: "已打印"
```

`runner.py` 使用 Playwright 异步 API，每个步骤超时 5 秒；失败时截图到 `artifacts/rpa/`，重试一次；返回 `{status, screenshots, steps}`。

- [ ] **Step 4: 暴露 MCP 工具并接入审批**

`legacy_print_shipment(tenant_id, order_id, tracking_no)` 作为 L2 写工具，支持 `dry_run` 和 `idempotency_key`；执行前必须有人工确认；写审计和 trace。RPA 只作为无 API 旧系统兜底，不作为订单异常主路径。

- [ ] **Step 5: 运行测试并提交**

```bash
pip install -e ".[dev,rpa]"
playwright install chromium
pytest tests/rpa -q -m browser
git add pyproject.toml src/opsconductor/rpa src/opsconductor/tools/server.py tests/rpa
git commit -m "feat: add Playwright RPA fallback"
```

### Task 6: 多模型网关、路由与成本

**Files:**
- Modify: `src/opsconductor/llm/gateway.py`
- Create: `src/opsconductor/llm/router.py`
- Create: `src/opsconductor/observability/cost.py`
- Create: `src/opsconductor/domain/model_call.py`
- Create: `migrations/versions/0004_model_calls.py`
- Create: `tests/llm/test_router.py`

**Interfaces:**
- `ModelRouter.choose(role: Literal["planner", "router", "verifier"]) -> ChatModel`。
- `ModelCall`：`tenant_id`、`task_id`、`role`、`model`、`prompt_tokens`、`completion_tokens`、`cost`、`latency_ms`。
- `record_model_call(session, tenant_id, task_id, role, model, prompt_tokens, completion_tokens, cost, latency_ms)`、`cost_summary(session, task_id)`。

- [ ] **Step 1: 写路由测试**

覆盖：planner 使用强模型；router 使用小模型；verifier 使用独立模型；缺少密钥时 fallback 到 stub；未知角色抛错；成本按 token 计算。

- [ ] **Step 2: 实现路由与成本**

```python
class ModelRouter:
    def __init__(self, models: dict[str, ChatModel]):
        self.models = models

    def choose(self, role: str) -> ChatModel:
        if role in self.models:
            return self.models[role]
        if "fallback" in self.models:
            return self.models["fallback"]
        raise ValueError(f"no model for role {role}")
```

`HttpChatModel` 返回 token 用量（如果供应商提供）；没有时由 `len(text)//4` 估算并标注 `estimated=True`。`record_model_call` 写表；`cost_summary` 按 task 聚合。

- [ ] **Step 3: 接入 Planner/Verifier**

Planner 通过 `ModelRouter.choose("planner")`；意图/抽取用 `router`；Verifier 用 `verifier`。每个调用记录 `ModelCall` 和 trace span。

- [ ] **Step 4: 运行测试并提交**

```bash
alembic revision --autogenerate -m "model calls"
alembic upgrade head
pytest tests/llm -q
git add src/opsconductor/llm src/opsconductor/observability/cost.py src/opsconductor/domain/model_call.py migrations/versions tests/llm
git commit -m "feat: add model routing and cost tracking"
```

### Task 7: 60+ 评测与多模型对比

**Files:**
- Create: `tests/eval/cases_jd.py`
- Create: `tests/eval/test_jd_golden.py`
- Create: `scripts/compare_models.py`
- Create: `docs/eval-report.md`

**Interfaces:**
- `JDGoldenCase(id, category, expected_status, assertions)`。
- `pytest.mark.parametrize` 运行 60+ case。
- `scripts/compare_models.py` 输出模型/成本/延迟对比。

- [ ] **Step 1: 补齐 32 条新 case**

在 MVP 28 条基础上增加：
- SKILL/Memory 12：技能选择、错误技能、失败记忆复用、重规划、记忆冲突、版本回退等；
- RAG 退款判定 10：政策命中、过期、冲突、证据不足、金额明细、租户隔离、引用准确；
- RPA 5：成功、选择器失败、超时、人工确认、审计；
- 多模型 5：planner/verifier 对比、成本、延迟、降级。

总计 60 条。

- [ ] **Step 2: 写参数化评测**

```python
@pytest.mark.parametrize("case", JD_CASES, ids=[c.id for c in JD_CASES])
@pytest.mark.asyncio
async def test_jd_golden(case, client, seeded_db):
    response = await client.post(
        "/api/v1/tasks",
        json={"instruction": case.instruction},
        headers={"X-API-Key": case.api_key, "Idempotency-Key": case.id},
    )
    assert response.status_code == 200
    task_id = response.json()["id"]
    final = await drive_case(client, task_id, case)
    assert final["status"] == case.expected_status
```

`drive_case` 定义在 `tests/eval/conftest.py`：按 case 的 `approvals` 逐条调用 approve/reject，再调用 resume，轮询 `GET /api/v1/tasks/{id}` 直到终态。断言必须覆盖：最终业务状态、审计、审批、幂等、补偿、trace 完整性；RAG case 额外断言引用和金额；RPA case 断言截图与审计。

- [ ] **Step 3: 写模型对比脚本**

`scripts/compare_models.py` 读取模型配置，对同一组主路径 case 运行 planner+verifier，输出：
- 成功率；
- P50/P95 延迟；
- 平均 token；
- 单任务成本；
- 降级次数。

结果写入 `artifacts/model-comparison.json`，不提交敏感密钥。

- [ ] **Step 4: 运行评测并提交**

```bash
pytest tests/eval -q
python scripts/compare_models.py
git add tests/eval scripts/compare_models.py docs/eval-report.md
git commit -m "test: add 60+ golden tasks and model comparison"
```

### Task 8: ADR、面试材料与收尾

**Files:**
- Create: `docs/adr/0005-erp-adapter.md`
- Create: `docs/adr/0006-skill-registry.md`
- Create: `docs/adr/0007-memory-reflection.md`
- Create: `docs/adr/0008-rag-refund-eligibility.md`
- Create: `docs/adr/0009-rpa-fallback.md`
- Create: `docs/adr/0010-model-routing.md`
- Create: `docs/interview-qa.md`
- Modify: `README.md`
- Modify: `docs/README.md`

- [ ] **Step 1: 写 ADR**

每篇 ADR 包含：状态、背景、决策、理由、后果、备选方案。重点解释：
- 为什么 Adapter 不直接绑定聚水潭 SDK；
- 为什么 SKILL 是工作流模板而不是提示词片段；
- 为什么 RAG 只做判定不做退款；
- 为什么 RPA 只做浏览器兜底；
- 为什么 Planner/Verifier 用不同模型。

- [ ] **Step 2: 写面试问答卡**

`docs/interview-qa.md` 按 JD 关键词组织：
- Planner/Executor/Memory/Tool/SKILLs/MCP 各自职责；
- ReAct vs Plan-Execute 的取舍；
- 如何保证写操作安全；
- 如何做失败补偿与幂等；
- 如何评估 RAG 与 RPA；
- 如何控制模型成本；
- 商用经验的诚实边界。

- [ ] **Step 3: 更新 README 和演示**

README 增加：
- ERP Adapter 配置；
- RAG 退款判定演示；
- RPA 演示；
- 模型配置与成本看板；
- 60+ 评测命令。

- [ ] **Step 4: 完整验证**

```bash
pytest -q
pytest tests/eval -q
ruff check .
mypy src
```

- [ ] **Step 5: 提交**

```bash
git add docs/adr docs/interview-qa.md README.md docs/README.md
git commit -m "docs: add JD alignment ADRs and interview material"
```

---

## 自检清单

- [ ] JD 覆盖矩阵中的每一项都能指到一个任务或测试。
- [ ] 两个 Adapter 共用契约测试，且没有真实凭据。
- [ ] SKILL 加载器拒绝未知工具和重复 id。
- [ ] 失败记忆和反思有测试，且不会无限重试。
- [ ] RAG 返回引用、版本、生效时间；过期/冲突/跨租户 case 有断言。
- [ ] RPA 有截图、超时、重试、人工确认和审计；不作为主路径。
- [ ] 模型路由有 planner/router/verifier 三种角色和成本记录。
- [ ] 60+ Golden Tasks 覆盖订单异常、SKILL/Memory、RAG、RPA、多模型。
- [ ] 所有商用边界在文档中写清楚，不把 mock 说成真实商用集成。
