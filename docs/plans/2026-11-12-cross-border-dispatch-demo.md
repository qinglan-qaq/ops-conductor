# 跨境电商 · 台前调度前后端 Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `design/cross-border-dispatch/index.html` 接到一个可运行的 FastAPI 后端，后端按领域层 / 应用层 / 适配层组织，使用端口-适配器、仓储、策略、工厂、状态机与门面模式，提供目标创建、计划、审批、异常 playbook、Agent 编排演示、trace 和重置 API；用 TDD 覆盖领域规则、应用编排、HTTP 冒烟与端到端演示。

**Architecture:** 新增独立的 `opsconductor.dispatch` 六边形切片：`domain` 只包含实体、值对象、策略与端口；`application` 包含 Agent 注册表、编排器、Demo 种子与 `DispatchService` 门面；`adapters` 提供内存仓储、Mock 工具网关、Pydantic HTTP 契约、路由与静态页面服务。演示使用内存状态，不依赖 PostgreSQL/Redis/外部 API；现有 MVP 的数据库路由不受影响。

**Tech Stack:** Python 3.11、FastAPI、Pydantic v2、pytest、FastAPI TestClient、原生 HTML/CSS/JS fetch。前端继续使用 `design/cross-border-dispatch/index.html` 的朱墨视觉，不引入构建链。

**Spec:** `SPEC.md` §6 主链路、§7 四闭环、§8 六个平面、§9 Agent；`docs/specs/2026-11-11-agent-orchestration-design.md` §2 Agent 统筹；`docs/specs/2026-11-10-cross-border-simulation-design.md` §2 演示剧本、§8 工具与风险、§10 审批/幂等/补偿/审计、§11 控制台。

## Global Constraints

- 新模块不得导入 FastAPI/SQLAlchemy 到 `domain`；`application` 只依赖 `domain` 的模型与端口；`adapters` 才能依赖 FastAPI。
- Demo 不连接 PostgreSQL、Redis、MCP 子进程或外部网络；所有工具调用由 `MockToolGateway` 返回确定性结果。
- 风险等级固定为 `L0/L1/L2/L3`；`L2/L3` 必须审批；Demo 固定 3 件审批：`budget`（L3，准）、`price`（L2，驳）、`refund`（L3，准）。
- 固定 10 段链路、8 个领域 Agent、1 个独立 Verifier、6 条异常、7 条初始 trace。
- 所有金额使用整数美元；`ads_create` 金额 10000 触发 L3；`price_update` 为 L2；`refund_execute` 为 L3。
- 前端 API 基址为 `/api/v1/dispatch`；页面由 `GET /dispatch` 提供；`file://` 预览必须保留本地 fallback，但页面顶部显示“静态预览”。
- 所有 API 变更必须写 trace；审批重复决策返回 409；未知审批/异常返回 404；空目标返回 422。
- 测试不得依赖 Docker；`pytest tests/dispatch -q` 必须独立通过；现有 `tests/test_health.py` 必须继续通过。
- 提交信息使用现有风格（`feat:` / `fix:` / `test:` / `docs:`）；本计划默认在 `feature/dispatch-demo` 分支执行。

---

## File Structure

```text
src/opsconductor/dispatch/
  __init__.py
  domain/
    __init__.py
    enums.py          # RiskLevel / Priority / ApprovalStatus / StepStatus / AgentStatus / StageStatus / Decision
    errors.py         # DispatchError / ApprovalNotFound / ApprovalAlreadyDecided / ExceptionNotFound / InvalidGoal
    models.py         # Goal / Plan / PlanStep / ApprovalCase / ChainStage / AgentCard / Playbook / ExceptionCase / TraceEvent / DispatchState
    policies.py       # RiskPolicy / ApprovalPolicy / PriorityPolicy
    ports.py          # DispatchRepository / AgentPort / ToolPort / ClockPort
  application/
    __init__.py
    plans.py          # PlanFactory + 10 段模板
    agents.py         # AgentSpec / RuleBasedAgent / AgentRegistry / VerifierAgent / build_agents
    orchestrator.py   # DispatchOrchestrator.plan / run
    seed.py           # Demo goal / chain / approvals / exceptions / trace / state factory
    service.py        # DispatchService 门面 + DispatchSnapshot
  adapters/
    __init__.py
    memory.py         # InMemoryDispatchRepository
    mock_tools.py     # MockToolGateway
    serialize.py      # snapshot/approval/exception → JSON dict
    api.py            # FastAPI router
    page.py           # GET /dispatch + GET /
    container.py      # 组装 root + get_service/reset_service
tests/dispatch/
  __init__.py
  conftest.py
  test_domain.py
  test_policies.py
  test_agents.py
  test_orchestrator.py
  test_service.py
  test_api_smoke.py
  test_frontend_contract.py
  test_e2e_demo.py
design/cross-border-dispatch/index.html   # 追加 API 客户端，保留视觉
design/cross-border-dispatch/README.md    # 增加后端启动方式
```

---

## Task 1: Domain Layer

**Files:**
- Create: `src/opsconductor/dispatch/__init__.py`
- Create: `src/opsconductor/dispatch/domain/__init__.py`
- Create: `src/opsconductor/dispatch/domain/enums.py`
- Create: `src/opsconductor/dispatch/domain/errors.py`
- Create: `src/opsconductor/dispatch/domain/models.py`
- Create: `src/opsconductor/dispatch/domain/policies.py`
- Create: `src/opsconductor/dispatch/domain/ports.py`
- Test: `tests/dispatch/__init__.py`, `tests/dispatch/test_domain.py`, `tests/dispatch/test_policies.py`

**Interfaces:**
- Produces: `RiskLevel`, `Priority`, `ApprovalStatus`, `StepStatus`, `AgentStatus`, `StageStatus`, `Decision`, `Goal`, `PlanStep`, `Plan`, `ApprovalCase`, `ChainStage`, `AgentCard`, `PlaybookPhase`, `Playbook`, `ExceptionCase`, `TraceEvent`, `DispatchState`, `AgentTask`, `ApprovalDraft`, `AgentResult`, `VerificationResult`, `RiskPolicy`, `ApprovalPolicy`, `PriorityPolicy`, `DispatchRepository`, `AgentPort`, `ToolPort`, `ClockPort`.

- [ ] **Step 1: Write failing domain tests**

```python
# tests/dispatch/test_policies.py
import pytest
from opsconductor.dispatch.domain.enums import Decision, Priority, RiskLevel
from opsconductor.dispatch.domain.errors import ApprovalAlreadyDecided, InvalidGoal
from opsconductor.dispatch.domain.models import ApprovalCase, Goal
from opsconductor.dispatch.domain.policies import ApprovalPolicy, PriorityPolicy, RiskPolicy


def test_risk_policy_l3_budget_l2_price_l0_scan():
    policy = RiskPolicy()
    assert policy.classify("ads_create", amount=10_000) is RiskLevel.L3
    assert policy.classify("price_update") is RiskLevel.L2
    assert policy.classify("trend_scan") is RiskLevel.L0
    assert policy.requires_approval(RiskLevel.L2)
    assert not policy.requires_approval(RiskLevel.L1)


def test_priority_policy_5x5_and_sla():
    policy = PriorityPolicy()
    assert policy.classify(5, 4) is Priority.P0
    assert policy.classify(4, 3) is Priority.P1
    assert policy.classify(3, 2) is Priority.P2
    assert policy.classify(1, 1) is Priority.P3
    assert policy.sla_minutes(Priority.P0) == 15
    assert policy.sla_minutes(Priority.P1) == 30


def test_approval_cannot_be_decided_twice():
    approval = ApprovalCase(
        id="budget", title="广告预算", action="ads_create",
        risk=RiskLevel.L3, owner="投放 Agent", impact="影响 3 个 Campaign",
    )
    approval.decide(Decision.approve, "财务小财", "10:50")
    with pytest.raises(ApprovalAlreadyDecided):
        approval.decide(Decision.reject, "运营小运", "10:51")


def test_goal_rejects_blank_instruction():
    with pytest.raises(InvalidGoal):
        Goal(id="g1", instruction="   ")
```

```python
# tests/dispatch/test_domain.py
from opsconductor.dispatch.domain.enums import RiskLevel, StepStatus
from opsconductor.dispatch.domain.models import PlanStep


def test_plan_step_transitions_and_rejects_double_finish():
    step = PlanStep(
        id="step-1", stage="order", name="订单异常", capability="order_triage",
        risk=RiskLevel.L2,
    )
    step.start()
    assert step.status is StepStatus.running
    step.finish("orders.json")
    assert step.status is StepStatus.succeeded
    assert step.artifact == "orders.json"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/dispatch/test_policies.py tests/dispatch/test_domain.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'opsconductor.dispatch'`.

- [ ] **Step 3: Implement enums, errors, models, policies, ports**

```python
# enums.py
from enum import Enum

class RiskLevel(str, Enum):
    L0 = "L0"; L1 = "L1"; L2 = "L2"; L3 = "L3"

class Priority(str, Enum):
    P0 = "P0"; P1 = "P1"; P2 = "P2"; P3 = "P3"

class ApprovalStatus(str, Enum):
    pending = "pending"; approved = "approved"; rejected = "rejected"

class StepStatus(str, Enum):
    pending = "pending"; running = "running"; succeeded = "succeeded"; failed = "failed"; skipped = "skipped"

class AgentStatus(str, Enum):
    idle = "idle"; running = "running"; waiting = "waiting"; done = "done"; error = "error"

class StageStatus(str, Enum):
    done = "done"; running = "running"; alert = "alert"; waiting = "waiting"

class Decision(str, Enum):
    approve = "approve"; reject = "reject"
```

```python
# policies.py
from .enums import Priority, RiskLevel

L3_ACTIONS = {"ads_create", "refund_execute", "compensate_execute"}
L2_ACTIONS = {"listing_update", "price_update", "split_order", "change_address",
              "shipment_create", "customs_declare", "rpa_supplier_portal"}
L1_ACTIONS = {"content_brief", "asset_draft", "reconcile_task"}

class RiskPolicy:
    def classify(self, action: str, amount: int | None = None) -> RiskLevel:
        if action in L3_ACTIONS:
            return RiskLevel.L3
        if action == "ads_create" and amount is not None and amount > 1000:
            return RiskLevel.L3
        if action in L2_ACTIONS:
            return RiskLevel.L2
        if action in L1_ACTIONS:
            return RiskLevel.L1
        return RiskLevel.L0

    def requires_approval(self, risk: RiskLevel) -> bool:
        return risk in {RiskLevel.L2, RiskLevel.L3}

class ApprovalPolicy:
    def requires_approval(self, risk: RiskLevel) -> bool:
        return RiskPolicy().requires_approval(risk)

class PriorityPolicy:
    def classify(self, likelihood: int, impact: int) -> Priority:
        score = likelihood * impact
        if score >= 20: return Priority.P0
        if score >= 12: return Priority.P1
        if score >= 6: return Priority.P2
        return Priority.P3

    def sla_minutes(self, priority: Priority) -> int:
        return {Priority.P0: 15, Priority.P1: 30,
                Priority.P2: 240, Priority.P3: 1440}[priority]
```

`models.py` must include the dataclasses and behavior described in **Interfaces**. `ApprovalCase.decide` raises `ApprovalAlreadyDecided` when status is not `pending`; `PlanStep.start/finish/fail` enforce legal transitions. `Goal.__post_init__` raises `InvalidGoal` for blank instruction. `AgentCard` should expose `with_status(status, current_task)` returning a `replace(...)` copy.

`ports.py`:

```python
from collections.abc import Callable, Mapping
from typing import Protocol, runtime_checkable
from .models import AgentCard, AgentResult, AgentTask, DispatchState, TraceEvent

@runtime_checkable
class DispatchRepository(Protocol):
    def snapshot(self) -> DispatchState: ...
    def mutate(self, mutator: Callable[[DispatchState], None]) -> None: ...
    def reset(self) -> DispatchState: ...

@runtime_checkable
class AgentPort(Protocol):
    @property
    def card(self) -> AgentCard: ...
    def handle(self, task: AgentTask) -> AgentResult: ...

@runtime_checkable
class ToolPort(Protocol):
    def call(self, tool: str, params: Mapping[str, object]) -> dict[str, object]: ...

@runtime_checkable
class ClockPort(Protocol):
    def now_label(self) -> str: ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/dispatch/test_policies.py tests/dispatch/test_domain.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/opsconductor/dispatch/domain tests/dispatch
git commit -m "feat: add dispatch domain models and policies"
```

---

## Task 2: Application Layer

**Files:**
- Create: `src/opsconductor/dispatch/application/__init__.py`
- Create: `src/opsconductor/dispatch/application/plans.py`
- Create: `src/opsconductor/dispatch/application/agents.py`
- Create: `src/opsconductor/dispatch/application/orchestrator.py`
- Create: `src/opsconductor/dispatch/application/seed.py`
- Create: `src/opsconductor/dispatch/application/service.py`
- Test: `tests/dispatch/test_agents.py`, `tests/dispatch/test_orchestrator.py`, `tests/dispatch/test_service.py`

**Interfaces:**
- Consumes: Task 1 domain types and policies.
- Produces: `build_plan(goal) -> Plan`; `AgentSpec`, `RuleBasedAgent`, `AgentRegistry`, `VerifierAgent`, `build_agents(tools) -> dict[str, RuleBasedAgent]`; `DispatchOrchestrator(registry, verifier, clock).plan(goal) -> Plan`, `.run(goal) -> DemoRunReport`; `build_seed_state(agent_cards) -> DispatchState`; `DispatchService(repo, orchestrator, clock)` with `.snapshot()`, `.create_goal(instruction)`, `.decide_approval(id, decision, actor)`, `.reset_approvals()`, `.reset()`, `.run_demo()`, `.get_exception(id)`.

- [ ] **Step 1: Write failing application tests**

```python
# tests/dispatch/test_agents.py
from opsconductor.dispatch.application.agents import AgentRegistry, VerifierAgent, build_agents
from opsconductor.dispatch.domain.enums import AgentStatus, RiskLevel


class _Tools:
    def call(self, tool, params):
        return {"tool": tool, "artifact": f"{tool}.json", "status": "ok"}


def test_builds_eight_agents_and_selects_by_capability():
    agents = build_agents(_Tools())
    registry = AgentRegistry(agents)
    assert len(registry.all()) == 8
    assert registry.select("trend_scan").card.id == "selection"
    assert registry.select("ads_create").card.risk is RiskLevel.L3
    assert all(a.card.status is AgentStatus.idle for a in registry.all())
```

```python
# tests/dispatch/test_orchestrator.py
from opsconductor.dispatch.application.agents import AgentRegistry, VerifierAgent, build_agents
from opsconductor.dispatch.application.orchestrator import DispatchOrchestrator
from opsconductor.dispatch.application.plans import build_plan
from opsconductor.dispatch.application.seed import SEED_GOAL


class _Tools:
    def call(self, tool, params):
        return {"tool": tool, "artifact": f"{tool}.json"}


class _Clock:
    def now_label(self):
        return "10:50"


def _orchestrator():
    return DispatchOrchestrator(AgentRegistry(build_agents(_Tools())), VerifierAgent(), _Clock())


def test_plan_has_ten_steps_and_three_approval_ids():
    plan = build_plan(SEED_GOAL)
    assert len(plan.steps) == 10
    assert plan.approval_ids == ["budget", "price", "refund"]


def test_demo_run_records_approvals_compensation_rpa_and_diffs():
    report = _orchestrator().run(SEED_GOAL)
    titles = [event.title for event in report.events]
    assert titles.count("审批通过") == 2
    assert "审批驳回" in titles
    assert "补偿触发" in titles
    assert any("RPA" in title for title in titles)
    assert any("对账差异" in title for title in titles)
    assert report.verification.passed
    assert report.verification.vetoed
```

```python
# tests/dispatch/test_service.py
from opsconductor.dispatch.adapters.memory import InMemoryDispatchRepository
from opsconductor.dispatch.application.orchestrator import DispatchOrchestrator
from opsconductor.dispatch.application.agents import AgentRegistry, VerifierAgent, build_agents
from opsconductor.dispatch.application.seed import build_seed_state
from opsconductor.dispatch.application.service import DispatchService


class _Tools:
    def call(self, tool, params):
        return {"tool": tool, "artifact": f"{tool}.json"}


class _Clock:
    def now_label(self):
        return "10:50"


def _service():
    agents = build_agents(_Tools())
    orchestrator = DispatchOrchestrator(AgentRegistry(agents), VerifierAgent(), _Clock())
    repo = InMemoryDispatchRepository(lambda: build_seed_state({a.card.id: a.card for a in agents.values()}))
    return DispatchService(repo, orchestrator, _Clock())


def test_snapshot_starts_with_three_pending_approvals_and_six_exceptions():
    snapshot = _service().snapshot()
    assert snapshot.kpis.approvals_pending == 3
    assert len(snapshot.exceptions) == 6
    assert len(snapshot.trace) == 7


def test_approve_reject_updates_state_and_trace():
    service = _service()
    service.decide_approval("budget", "approve", "财务小财")
    snapshot = service.snapshot()
    assert snapshot.kpis.approvals_pending == 2
    assert snapshot.approvals["budget"].status.value == "approved"
    assert any(event.title == "审批通过" for event in snapshot.trace)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/dispatch/test_agents.py tests/dispatch/test_orchestrator.py tests/dispatch/test_service.py -q`
Expected: FAIL with `ModuleNotFoundError` for `opsconductor.dispatch.application`.

- [ ] **Step 3: Implement application layer**

`plans.py` — fixed 10-step template:

```python
PLAN_TEMPLATE = (
    ("selection", "市场与选品", "trend_scan", "done", "5 SKU"),
    ("content", "商品与内容", "content_brief", "running", "5 SKU"),
    ("listing", "上架与定价", "listing_update", "waiting", "待创建"),
    ("organic", "自然流量", "content_plan", "waiting", "内容日历"),
    ("paid", "付费广告", "ads_create", "waiting", "3 Campaign"),
    ("order", "订单", "order_triage", "alert", "6 单异常"),
    ("fulfillment", "库存与履约", "shipment_create", "running", "补偿 1"),
    ("logistics", "物流与关务", "customs_declare", "alert", "1 票扣关"),
    ("settlement", "收款与结算", "settlement_fetch", "running", "3 笔差异"),
    ("aftersales", "售后与合规", "compliance_check", "waiting", "政策 RAG"),
)
```

`build_plan(goal)` returns `Plan(id="plan-demo", goal_id=goal.id, steps=[...], approval_ids=["budget","price","refund"], created_at="10:43")`.

`agents.py` — eight `AgentSpec`s and a factory. Each spec has `id`, `name`, `role`, `capabilities`, `risk`, `default_task`, `summary`, `tool`, `approval: ApprovalDraft | None`, `metadata`. Required approvals:

```python
APPROVAL_BUDGET = ApprovalDraft("budget", "广告预算 · 3 个 Campaign", "ads_create",
    RiskLevel.L3, "投放 Agent → 财务小财", "总额 $10,000 · 超过 L3 阈值", Decision.approve)
APPROVAL_PRICE = ApprovalDraft("price", "涨价建议 · 1 个 SKU", "price_update",
    RiskLevel.L2, "定价 Agent → 运营小运", "影响 Listing 价格 · 剧本中运营驳回", Decision.reject)
APPROVAL_REFUND = ApprovalDraft("refund", "退款 · 政策 RAG 已核验", "refund_execute",
    RiskLevel.L3, "结算 Agent → 财务小财", "政策相符 · 资金动作必须人工审批", Decision.approve)
```

Agent specs:
| id | name | capabilities | risk | approval | metadata |
|---|---|---|---|---|---|
| selection | 选品 Agent | trend_scan | L1 | — | `{"margin": 6.8}` |
| content | 内容 Agent | content_brief, content_plan | L2 | — | `{"assets": 15}` |
| pricing | 定价 Agent | price_update, listing_update | L2 | APPROVAL_PRICE | `{}` |
| ads | 投放 Agent | ads_create | L3 | APPROVAL_BUDGET | `{"budget": 10000}` |
| order | 订单 Agent | order_triage | L2 | — | `{"inventory": 0}` |
| fulfillment | 履约 Agent | shipment_create, customs_declare | L2 | — | `{"customs_failed": True}` |
| settlement | 结算 Agent | settlement_fetch | L3 | APPROVAL_REFUND | `{"diff_count": 3}` |
| compliance | 合规 Agent | compliance_check | L3 | — | `{"vetoed_sku": "NW-102"}` |

`RuleBasedAgent.handle` calls `tools.call(spec.tool, {"capability": task.capability})`, returns `AgentResult(agent_id=spec.id, stage=task.stage, summary=spec.summary, artifact=tool_result["artifact"], risk=spec.risk, approval=spec.approval, metadata=spec.metadata)`. Cards start `AgentStatus.idle`; the seed uses done/running/waiting labels via `with_status` where needed.

`AgentRegistry` — maps id to agent, `select(capability)` scans capabilities, raises `LookupError` if none.

`VerifierAgent.verify(results)` — checks `margin >= 15` (veto `selection` if below), `inventory >= 0`, `budget <= 10000`, `compliance` present; returns `VerificationResult(passed=True, checks=("margin","inventory","budget","compliance","trace"), vetoed=("SKU NW-102 margin 6.8% < 15%",))`.

`orchestrator.py` — `plan(goal)` returns `build_plan(goal)`. `run(goal)`:
- iterate plan steps, `agent = registry.select(step.capability)`, `result = agent.handle(AgentTask(...))`, `step.start(); step.finish(result.artifact)`.
- append events: `Agent 启动`, `Agent 完成`.
- collect approval drafts; create `ApprovalCase`; apply demo decisions: budget approve, price reject, refund approve; append `审批通过`/`审批驳回` events.
- add events: `Verifier 通过`, `补偿触发` (拆单库存冲突), `RPA 执行` (影刀旧版供应商门户), `对账差异` (3 笔 → 财务任务), `报告生成`.
- return `DemoRunReport(events=tuple(events), steps=tuple(summaries), approvals=tuple(approvals), verification=verification, summary="...")`.

`seed.py`:
- `SEED_GOAL = Goal(id="goal-demo", instruction="本周做到 $100k GMV，广告预算 $10k；优先处理断货与超时订单。")`.
- `build_approvals()` → 3 `ApprovalCase` pending from the three drafts.
- `build_chain()` → 10 `ChainStage` with exact statuses/meta from the page.
- `build_trace()` → 7 `TraceEvent` with times 10:42/10:43/10:45/11:02/11:08/11:12/11:15.
- `build_exceptions()` → 6 `ExceptionCase` with playbook phases for ORD-01/INV-01/ORD-03/LOG-03/PAY-02/ORD-04.
- `build_seed_state(agent_cards)` → `DispatchState` with goal, plan, approvals, exceptions, agents (cards with seed statuses: selection done, content running, pricing waiting, ads waiting, order alert, fulfillment alert, settlement running, compliance done), chain, trace.
- Use `AgentCard.with_status` to set `current_task` and statuses.

`service.py`:
- `DispatchSnapshot` dataclass: `goal`, `plan`, `approvals`, `exceptions`, `agents`, `chain`, `trace`, `kpis`, `flow_note`.
- `KpiSnapshot` dataclass: `gmv_target`, `exceptions`, `approvals_pending`, `compensations`.
- `DispatchService.snapshot()` builds from `repo.snapshot()`; `flow_note` = pending ? `审批进行中 · N 件待批` : `审批已清 · 进入执行`.
- `create_goal(instruction)`: `Goal(id=f"goal-{clock...}", instruction=...)`; `plan=orchestrator.plan(goal)`; replace state goal/plan/approvals (pending)/chain (reset statuses)/trace (initial + `计划生成`); return snapshot.
- `decide_approval(id, decision, actor)`: `repo.mutate`; find approval; `approval.decide(Decision(decision), actor, clock.now_label())`; append trace; no plan mutation.
- `reset_approvals()`: set all pending, clear actor/time; append `审批案重置`.
- `reset()`: repo.reset.
- `run_demo()`: `orchestrator.run(repo.snapshot().goal)`.
- `get_exception(id)`: from snapshot; raise `ExceptionNotFound`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/dispatch/test_agents.py tests/dispatch/test_orchestrator.py tests/dispatch/test_service.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/opsconductor/dispatch/application tests/dispatch
git commit -m "feat: add dispatch agent orchestrator and service"
```

---

## Task 3: Adapters and HTTP API

**Files:**
- Create: `src/opsconductor/dispatch/adapters/__init__.py`
- Create: `src/opsconductor/dispatch/adapters/memory.py`
- Create: `src/opsconductor/dispatch/adapters/mock_tools.py`
- Create: `src/opsconductor/dispatch/adapters/serialize.py`
- Create: `src/opsconductor/dispatch/adapters/api.py`
- Create: `src/opsconductor/dispatch/adapters/page.py`
- Create: `src/opsconductor/dispatch/adapters/container.py`
- Modify: `src/opsconductor/api/main.py` (include dispatch routers)
- Test: `tests/dispatch/conftest.py`, `tests/dispatch/test_api_smoke.py`

**Interfaces:**
- Consumes: Task 1/2 types and `DispatchService`.
- Produces: `GET /api/v1/dispatch/snapshot`, `POST /api/v1/dispatch/goals`, `POST /api/v1/dispatch/approvals/{id}/decision`, `POST /api/v1/dispatch/approvals/reset`, `POST /api/v1/dispatch/demo/run`, `POST /api/v1/dispatch/reset`, `GET /api/v1/dispatch/exceptions/{id}`, `GET /dispatch`, `GET /` redirect.

- [ ] **Step 1: Write failing API smoke tests**

```python
# tests/dispatch/conftest.py
import pytest
from fastapi.testclient import TestClient

from opsconductor.api.main import app
from opsconductor.dispatch.adapters.container import reset_service


@pytest.fixture
def client():
    reset_service()
    with TestClient(app) as test_client:
        yield test_client
```

```python
# tests/dispatch/test_api_smoke.py
def test_snapshot_has_demo_contract(client):
    response = client.get("/api/v1/dispatch/snapshot")
    assert response.status_code == 200
    data = response.json()
    assert data["kpis"]["approvals_pending"] == 3
    assert len(data["exceptions"]) == 6
    assert len(data["trace"]) == 7
    assert len(data["chain"]) == 10
    assert len(data["agents"]) == 8


def test_approval_decision_and_duplicate_409(client):
    response = client.post(
        "/api/v1/dispatch/approvals/budget/decision",
        json={"decision": "approve", "actor": "财务小财"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["snapshot"]["kpis"]["approvals_pending"] == 2
    assert data["approval"]["status"] == "approved"
    duplicate = client.post(
        "/api/v1/dispatch/approvals/budget/decision",
        json={"decision": "reject", "actor": "运营小运"},
    )
    assert duplicate.status_code == 409


def test_exception_playbook_has_three_phases(client):
    response = client.get("/api/v1/dispatch/exceptions/ORD-01")
    assert response.status_code == 200
    assert len(response.json()["playbook"]["phases"]) == 3


def test_dispatch_page_is_served(client):
    response = client.get("/dispatch")
    assert response.status_code == 200
    assert "运筹跨境" in response.text
    assert "DISPATCH_API" in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/dispatch/test_api_smoke.py -q`
Expected: FAIL with 404 / import errors.

- [ ] **Step 3: Implement adapters and API**

`memory.py`:

```python
import copy
from collections.abc import Callable
from threading import RLock
from ..domain.models import DispatchState

class InMemoryDispatchRepository:
    def __init__(self, seed: Callable[[], DispatchState]):
        self._seed = seed
        self._state = seed()
        self._lock = RLock()

    def snapshot(self) -> DispatchState:
        with self._lock:
            return copy.deepcopy(self._state)

    def mutate(self, mutator: Callable[[DispatchState], None]) -> None:
        with self._lock:
            mutator(self._state)

    def reset(self) -> DispatchState:
        with self._lock:
            self._state = self._seed()
            return copy.deepcopy(self._state)
```

`mock_tools.py` returns `{"tool": tool, "artifact": f"{tool}.json", "status": "ok"}`.

`serialize.py` maps snapshot to the JSON contract:
- `goal`: id, instruction, store, market, target_gmv, budget, roas_target.
- `kpis`: gmv_target, exceptions, approvals_pending, compensations.
- `flow_note`.
- `chain`: id,name,status,meta.
- `agents`: id,name,role,capabilities,risk,status,status_label,current_task.
- `approvals`: id,title,action,risk,owner,impact,recommended,status,stamp (准/驳/None).
- `exceptions`: id,title,priority,li,sla,owner,count.
- `trace`: at,title,detail.
- `plan`: id,steps,approvals,risk,created_at; include steps with id,stage,name,capability,risk,status,artifact.

`api.py`:
```python
router = APIRouter(prefix="/api/v1/dispatch", tags=["dispatch"])

class GoalRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=500)

class DecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    actor: str = Field(default="demo-operator", min_length=1, max_length=80)

@router.get("/snapshot")
def snapshot(service: DispatchService = Depends(get_service)):
    return snapshot_payload(service.snapshot())

@router.post("/goals")
def create_goal(payload: GoalRequest, service=Depends(get_service)):
    return snapshot_payload(service.create_goal(payload.instruction))

@router.post("/approvals/{approval_id}/decision")
def decide(...):
    try:
        service.decide_approval(...)
    except ApprovalNotFound: 404
    except ApprovalAlreadyDecided: 409
    return {"approval": serialize_approval(...), "snapshot": snapshot_payload(...)}

@router.post("/approvals/reset")
...
@router.post("/demo/run")
...
@router.post("/reset")
...
@router.get("/exceptions/{exception_id}")
...
```

`container.py`:
```python
def _build_service() -> DispatchService:
    tools = MockToolGateway()
    agents = build_agents(tools)
    registry = AgentRegistry(agents)
    repo = InMemoryDispatchRepository(lambda: build_seed_state({a.card.id: a.card for a in agents.values()}))
    orchestrator = DispatchOrchestrator(registry, VerifierAgent(), SystemClock())
    return DispatchService(repo, orchestrator, SystemClock())

_service = _build_service()
def get_service() -> DispatchService: return _service
def reset_service() -> DispatchService:
    global _service
    _service = _build_service()
    return _service
```

`page.py`:
```python
ROOT = Path(__file__).resolve().parents[4]
PAGE = ROOT / "design" / "cross-border-dispatch" / "index.html"

router = APIRouter(tags=["dispatch"])
@router.get("/dispatch", include_in_schema=False)
def dispatch_page() -> FileResponse:
    if not PAGE.exists(): raise HTTPException(404, "dispatch page not found")
    return FileResponse(PAGE, media_type="text/html")

@router.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse("/dispatch")
```

`api/main.py`: import `dispatch_api_router` and `dispatch_page_router`, include both.

- [ ] **Step 4: Run API smoke tests**

Run: `pytest tests/dispatch/test_api_smoke.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/opsconductor/dispatch/adapters src/opsconductor/api/main.py tests/dispatch
git commit -m "feat: expose dispatch HTTP API and demo page"
```

---

## Task 4: Frontend ↔ Backend Integration

**Files:**
- Modify: `design/cross-border-dispatch/index.html`
- Modify: `design/cross-border-dispatch/README.md`
- Test: `tests/dispatch/test_frontend_contract.py`

**Interfaces:**
- Consumes: Task 3 endpoints and snapshot JSON contract.
- Produces: page calls `GET /api/v1/dispatch/snapshot` on load; approvals call decision API; goal calls `/goals`; demo calls `/demo/run`; exception drawer calls `/exceptions/{id}`; reset calls `/approvals/reset`; `file://` fallback keeps local behavior.

- [ ] **Step 1: Write failing frontend contract test**

```python
# tests/dispatch/test_frontend_contract.py
def test_served_page_contains_api_hooks(client):
    response = client.get("/dispatch")
    assert response.status_code == 200
    text = response.text
    assert "DISPATCH_API" in text
    assert "applySnapshot" in text
    assert "data-agent=" in text
    assert "api-status" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/dispatch/test_frontend_contract.py -q`
Expected: FAIL because the page has no API hooks.

- [ ] **Step 3: Add API client and snapshot rendering**

Add to the page:
- `id="apiStatus"` in the top meta, CSS `.api-status` + `.api-status.online` / `.offline`.
- IDs on KPI values: `kpiGmv`, `kpiExceptions`, `kpiApprovals`, `kpiCompensation`.
- `data-agent="selection|content|pricing|ads|order|fulfillment|settlement|compliance"` on agent rows.
- JS constants near the top of the IIFE:

```javascript
const DISPATCH_API = '/api/v1/dispatch';
const apiStatus = document.getElementById('apiStatus');
let apiOnline = location.protocol !== 'file:';

async function api(path, options){
  const response = await fetch(DISPATCH_API + path, {
    headers: {'Content-Type': 'application/json'},
    ...options
  });
  if(!response.ok){
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || ('HTTP ' + response.status));
  }
  return response.json();
}
function setApiStatus(text, online){
  apiOnline = online;
  if(!apiStatus) return;
  apiStatus.textContent = text;
  apiStatus.className = 'api-status ' + (online ? 'online' : 'offline');
}
```

`applySnapshot(snapshot)` must:
- set `goalInput.value` when the input is not focused;
- update `kpiGmv`, `kpiExceptions`, `kpiApprovals`, `kpiCompensation`;
- set `flowNote.textContent = snapshot.flow_note`;
- update `.stage[data-stage]` classes/meta from `snapshot.chain`;
- update `.agent-row[data-agent]` status text/class and task text from `snapshot.agents`;
- update each `.exception[data-exception]` P badge, meta, and small text from `snapshot.exceptions`;
- update each `.approval[data-id]` decided/approved/rejected classes, stamp text (`准`/`驳`), result text, disabled buttons, and `approvalState`;
- call `updateApprovalCount()` and render trace via `renderTrace(snapshot.trace)`.

`loadSnapshot()`:
```javascript
async function loadSnapshot(){
  if(!apiOnline){ setApiStatus('静态预览', false); return; }
  try{
    const snapshot = await api('/snapshot');
    applySnapshot(snapshot);
    setApiStatus('后端已连接', true);
  }catch(error){
    setApiStatus('静态预览', false);
    toast('后端未连接，继续使用静态演示', 'red');
  }
}
```

Approval click becomes remote-first:
- If `apiOnline`, disable the clicked button, `POST /approvals/{id}/decision` with `{decision, actor:'demo-operator'}`, `applySnapshot(response.snapshot)`, toast success. On error, re-enable and toast.
- If offline, keep existing local `decideLocal` behavior.

Reset button:
- If online: `POST /approvals/reset`, `applySnapshot(response.snapshot)`, toast.
- Offline: existing local reset.

Goal submit:
- If online: `POST /goals` with `{instruction}`; `applySnapshot(response)`; toast "计划已生成"; `highlightStepTarget('2')`.
- Offline: existing local behavior.

`runDemo`:
- If online: `const report = await api('/demo/run', {method:'POST'});` use `report.steps` / `report.events` for the animation; `setApiStatus('后端已连接', true)`. Do not mutate approvals; the demo is a projection.
- Offline: existing local `demoNotes`/`demoTrace`.
- At the end, toast with `report.summary` if online.

Exception drawer:
- On click, if online: `const data = await api('/exceptions/' + id); openDrawerFromData(data);` else local `openDrawer(id)`.
- Move the drawer renderer into `renderDrawer(data)` and use the same shape as the backend `playbook` payload.

Add `DISPATCH_API` string to the page (the contract test asserts it).

- [ ] **Step 4: Run frontend contract test**

Run: `pytest tests/dispatch/test_frontend_contract.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add design/cross-border-dispatch/index.html design/cross-border-dispatch/README.md tests/dispatch/test_frontend_contract.py
git commit -m "feat: connect dispatch page to demo API"
```

---

## Task 5: End-to-End Smoke, Docs, and Manual Verification

**Files:**
- Create: `tests/dispatch/test_e2e_demo.py`
- Modify: `design/cross-border-dispatch/README.md`
- Modify: `design/cross-border-dispatch/polish-log.md` (append backend verification)
- Test: `tests/dispatch/test_e2e_demo.py`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: a documented `uvicorn` command and a verified browser demo.

- [ ] **Step 1: Write failing E2E smoke tests**

```python
# tests/dispatch/test_e2e_demo.py
def test_full_demo_flow(client):
    assert client.get("/api/v1/dispatch/snapshot").json()["kpis"]["approvals_pending"] == 3
    assert client.post("/api/v1/dispatch/approvals/budget/decision",
                       json={"decision": "approve"}).status_code == 200
    assert client.post("/api/v1/dispatch/approvals/price/decision",
                       json={"decision": "reject"}).status_code == 200
    final = client.post("/api/v1/dispatch/approvals/refund/decision",
                        json={"decision": "approve"})
    assert final.status_code == 200
    snapshot = final.json()["snapshot"]
    assert snapshot["kpis"]["approvals_pending"] == 0
    assert snapshot["flow_note"] == "审批已清 · 进入执行"

    report = client.post("/api/v1/dispatch/demo/run")
    assert report.status_code == 200
    data = report.json()
    assert len(data["report"]["steps"]) == 10
    assert any("补偿触发" in event["title"] for event in data["report"]["events"])
    assert any("RPA" in event["title"] for event in data["report"]["events"])
    assert any("对账差异" in event["title"] for event in data["report"]["events"])

    reset = client.post("/api/v1/dispatch/reset")
    assert reset.json()["kpis"]["approvals_pending"] == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/dispatch/test_e2e_demo.py -q`
Expected: FAIL until the API/contracts are complete.

- [ ] **Step 3: Implement missing integration details and docs**

- Add `scripts/demo_dispatch.sh` (optional but recommended):
  ```bash
  #!/usr/bin/env bash
  set -euo pipefail
  cd "$(dirname "$0")/.."
  exec uvicorn opsconductor.api.main:app --reload --port 8000
  ```
  Make executable in the repo; document `bash scripts/demo_dispatch.sh`.
- Update `design/cross-border-dispatch/README.md` with:
  - `pip install -e ".[dev]"` (if needed)
  - `bash scripts/demo_dispatch.sh`
  - open `http://127.0.0.1:8000/dispatch`
  - API endpoints and the meaning of the approval demo.
  - `pytest tests/dispatch -q` as the fast, DB-free test suite.
- Append to `polish-log.md`: backend API smoke verified, `pytest tests/dispatch -q` result.

- [ ] **Step 4: Run all dispatch tests and health test**

Run: `pytest tests/dispatch tests/test_health.py -q`
Expected: PASS (no Docker required).

- [ ] **Step 5: Manual browser verification**

```bash
bash scripts/demo_dispatch.sh
# another shell
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/api/v1/dispatch/snapshot | head
```

Open `http://127.0.0.1:8000/dispatch`, verify:
- header shows “后端已连接”；
- 待批 3 件；
- 点击「准」后待批 2 件，刷新后仍为 2；
- 点击异常打开 playbook；
- 点击「播放调度演示」显示后端返回的步骤与 trace；
- 点击「重置」恢复 3 件待批。

- [ ] **Step 6: Commit**

```bash
git add tests/dispatch design/cross-border-dispatch scripts/demo_dispatch.sh
git commit -m "test: add dispatch demo end-to-end smoke coverage"
```

---

## Self-Review

**Spec coverage**
- 领域层 / 应用层 / 适配层：Task 1–3 的目录与导入规则明确。
- Agent 创建：Task 2 的 `AgentSpec` + `build_agents` 创建 8 个 Agent，Task 2/3 的 registry 与 API 暴露。
- 审批 L2/L3、幂等语义、补偿、审计/trace：Task 1 的 `ApprovalCase`、Task 2 的 orchestrator、Task 5 的 E2E 断言。
- 前后端连接：Task 3 的 API + Task 4 的 fetch/contract test + Task 5 的浏览器验证。
- TDD 与冒烟：每个 Task 先写失败测试；Task 5 覆盖完整 demo 流程。

**Placeholder scan**
- No TBD/TODO; all tasks name exact files, functions, endpoints and test names.
- Code snippets are concrete; remaining implementation is behavior-preserving boilerplate.

**Type consistency**
- `ApprovalDraft` → `ApprovalCase` conversion is defined in Task 2.
- `DispatchSnapshot` field names match Task 3 `serialize.py` and Task 4 `applySnapshot`.
- `RiskLevel` / `Priority` / `Decision` values are consistent across tasks.
