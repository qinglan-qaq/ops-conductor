# Agent 运行可观测（A 切片）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有只读 Demo 投影升级为真实、可回放、可解释的 Agent Run：后端记录 10 步执行事实，前端用导演模式展示多 Agent 接力、交接、审批门与治理收尾。

**Architecture:** 在 `opsconductor.dispatch` 六边形切片内新增 `AgentRun` 领域聚合、`RunBuilder` 应用构建器、内存 `RunRepository` 与 Run API；前端新增 `features/runs`、`useRunPlayer`、执行链组件与 `/dispatch/runs/:runId` 路由。Run 是只读投影，不改变审批/Agent 卡片/链路状态；旧 `/demo/run` 由同一执行路径派生，保持兼容。

**Tech Stack:** Python 3.11、FastAPI、Pydantic、dataclasses、pytest、ruff、mypy；Vue 3、TypeScript、TanStack Query、Zod、Vitest、Playwright；配置用标准库 `tomllib`，不新增依赖。

**Spec:** `docs/specs/2026-11-18-agent-run-observability-design.md`

## 执行状态（2026-11-19）

- 代码已实现：Run 领域模型/构建器/内存仓储/API、配置与凭据边界、Vue Run 页、执行链组件、Overview 入口与最近运行、集成凭据徽标。
- 后端验证：`pytest tests/dispatch tests/test_config.py tests/test_health.py -q` → **149 passed**；`ruff check .` 通过；`mypy src` 通过（76 files）。
- 前端验证：`npm run typecheck` 通过；`npm run test:unit` → **48 passed**；`npm run build` 通过；完整 Playwright 套件 → **15 passed**（含 Run 页 5 条、375px、4x 回放）。
- 完整 `pytest -q` 未执行：本机 Docker PostgreSQL 未启动；CI 已补 `pgvector/pgvector:pg16` service 与前端 job。
- 计划中的 `git commit` 步骤未执行：按仓库约定，提交需用户明确要求；工作区改动待确认后再提交。

## Global Constraints

- 所有领域值对象在 `__post_init__` 中校验，非法输入抛 `ValueError`；计数拒绝 `bool`。
- 分层严格单向：`domain ← application ← adapters`；`domain` 不导入 FastAPI/SQLAlchemy/Pydantic；`application` 不导入 `adapters`。
- 前端 `features/**` 不直接调用 `fetch` 或导入 `api/client`；数据经 `api/dispatch.ts` 与 `queries/*`。
- Run 只读：`POST /runs` 不改变 `snapshot.approvals`、`snapshot.agents`、`snapshot.chain`。
- 旧 `/api/v1/dispatch/demo/run` 保持 28 个事件、2 准 1 驳、Verifier 否决项。
- 事件固定 51 个；10 步、8 Agent、8 次交接、3 个门禁（2 准 1 驳）、10 个产物、1 次补偿、3 笔对账。
- 平台配置 `config/platforms.toml` 不含密钥；密钥只通过 `CredentialProvider` 读取；run/API/日志不含密钥。
- 不新增 Python/前端依赖；配置解析用 `tomllib`，泳道/SVG/播放器用现有 CSS/SVG/setTimeout。
- 测试不使用 `sleep`；后端固定 `ClockPort`/run ID，前端用 Vitest fake timers。
- 每个任务先写失败测试，再写最小实现，最后重构；每个任务结束运行 `pytest tests/dispatch -q`、`ruff check .`、`mypy src`（前端任务另加 `npm run typecheck && npm run test:unit`）。

---

### Task 1: TDD 地基、值对象与聚合校验

**Files:**
- Create: `src/opsconductor/dispatch/domain/runs.py`
- Modify: `src/opsconductor/dispatch/domain/models.py`（新增 `ToolCallRecord`，供 `AgentResult` 与 `RunStep` 共用）
- Create: `tests/dispatch/test_runs.py`
- Create: `tests/dispatch/test_layering.py`

**Interfaces:**
- Produces: `RunStatus`, `RunMode`, `RunStepStatus`, `RunEventKind`, `RunToolCall = ToolCallRecord`, `RunStep`, `RunAgent`, `RunEvent`, `RunGate`, `RunHandoff`, `RunArtifact`, `RunMetrics`, `AgentRun`；`ToolCallRecord(tool, params, result, status, duration_ms)`。
- Produces: `AgentRun` 构造时校验全部聚合不变量；后续 Task 3 用 `RunBuilder` 构造它。

- [ ] **Step 1: 写失败测试 `tests/dispatch/test_runs.py`**

```python
import pytest

from opsconductor.dispatch.domain.enums import (
    ApprovalStatus,
    ArtifactKind,
    Decision,
    RiskLevel,
)
from opsconductor.dispatch.domain.models import Goal, VerificationResult
from opsconductor.dispatch.domain.runs import (
    AgentRun,
    RunAgent,
    RunArtifact,
    RunEvent,
    RunEventKind,
    RunGate,
    RunHandoff,
    RunMetrics,
    RunMode,
    RunStatus,
    RunStep,
    RunStepStatus,
    RunToolCall,
)


def _tool_call(**overrides):
    values = dict(tool="trend_scan", params={"capability": "trend_scan"}, result={"status": "ok"}, status="ok", duration_ms=1)
    values.update(overrides)
    return RunToolCall(**values)


def _step(**overrides):
    values = dict(
        index=1, id="step-1", stage="selection", name="市场与选品",
        agent_id="selection", capability="trend_scan", risk=RiskLevel.L1,
        status=RunStepStatus.succeeded, summary="完成选品", artifact="trend_scan.json",
        tool_calls=(_tool_call(),), approval_id=None, duration_ms=1, error=None,
    )
    values.update(overrides)
    return RunStep(**values)


def _agent(**overrides):
    values = dict(id="selection", name="选品 Agent", role="趋势", risk=RiskLevel.L1, capabilities=("trend_scan",), step_ids=("step-1",))
    values.update(overrides)
    return RunAgent(**values)


def _event(seq=1, **overrides):
    values = dict(seq=seq, kind=RunEventKind.agent_started, at="10:43", step_id="step-1", agent_id="selection", gate_id=None, title="Agent 启动", detail="选品 Agent · 市场与选品")
    values.update(overrides)
    return RunEvent(**values)


def _gate(**overrides):
    values = dict(id="budget", step_id="step-1", stage="selection", title="预算", action="ads_create", risk=RiskLevel.L3, owner="财务", impact="$10,000", recommended=Decision.approve, status=ApprovalStatus.approved, decision=Decision.approve, actor="财务小财", decided_at="10:44")
    values.update(overrides)
    return RunGate(**values)


def _artifact(**overrides):
    values = dict(name="trend_scan.json", kind=ArtifactKind.json, uri="mock://trend_scan.json", step_id="step-1", agent_id="selection", description="选品 Agent · 市场与选品")
    values.update(overrides)
    return RunArtifact(**values)


def _metrics(**overrides):
    values = dict(step_count=1, succeeded_steps=1, failed_steps=0, agent_count=1, handoff_count=0, gate_count=1, approved_gates=1, rejected_gates=0, artifact_count=1, compensation_count=0, reconciliation_count=0, duration_ms=1)
    values.update(overrides)
    return RunMetrics(**values)


def _run(**overrides):
    values = dict(
        id="run-test", goal=Goal(id="goal-demo", instruction="测试目标"), plan_id="plan-demo",
        status=RunStatus.succeeded, mode=RunMode.demo, started_at="10:43", finished_at="10:44",
        summary="1 步完成", steps=(_step(),), agents=(_agent(),), events=(_event(),),
        gates=(_gate(),), handoffs=(), artifacts=(_artifact(),),
        verification=VerificationResult(passed=True, checks=("trace",), vetoed=()),
        metrics=_metrics(),
    )
    values.update(overrides)
    return AgentRun(**values)


@pytest.mark.parametrize("field,value", [("tool", ""), ("status", ""), ("duration_ms", -1)])
def test_tool_call_rejects_invalid_fields(field, value):
    with pytest.raises(ValueError, match=field):
        _tool_call(**{field: value})


def test_step_rejects_negative_duration():
    with pytest.raises(ValueError, match="duration_ms"):
        _step(duration_ms=-1)


def test_step_rejects_blank_id():
    with pytest.raises(ValueError, match="id"):
        _step(id="   ")


def test_agent_rejects_duplicate_capabilities():
    with pytest.raises(ValueError, match="capabilities"):
        _agent(capabilities=("trend_scan", "trend_scan"))


def test_event_rejects_missing_association_for_agent_started():
    with pytest.raises(ValueError, match="step_id"):
        _event(step_id=None)


def test_handoff_event_uses_receiving_agent_and_step():
    event = _event(kind=RunEventKind.handoff, step_id="step-2", agent_id="content", title="Agent 交接", detail="选品 → 内容")
    assert event.step_id == "step-2"
    assert event.agent_id == "content"


def test_gate_rejects_inconsistent_decision():
    with pytest.raises(ValueError, match="decision"):
        _gate(status=ApprovalStatus.approved, decision=Decision.reject)


def test_gate_rejects_pending_with_actor():
    with pytest.raises(ValueError, match="actor"):
        _gate(status=ApprovalStatus.pending, decision=None, actor="某人", decided_at="10:44")


def test_metrics_reject_impossible_counts():
    with pytest.raises(ValueError, match="succeeded_steps"):
        _metrics(step_count=1, succeeded_steps=2)


def test_run_rejects_non_contiguous_event_seq():
    with pytest.raises(ValueError, match="seq"):
        _run(events=(_event(seq=2),))


def test_run_rejects_handoff_between_non_adjacent_steps():
    handoff = RunHandoff(event_seq=1, from_agent_id="selection", to_agent_id="content", from_step_id="step-1", to_step_id="step-9", artifact="trend_scan.json", note="远距离交接")
    with pytest.raises(ValueError, match="adjacent"):
        _run(handoffs=(handoff,))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `conda run -n opsconductor python -m pytest tests/dispatch/test_runs.py -q`
Expected: FAIL，`ModuleNotFoundError: opsconductor.dispatch.domain.runs`。

- [ ] **Step 3: 实现 `domain/runs.py` 与 `models.py` 的 `ToolCallRecord`**

在 `domain/models.py` 的 `AgentResult` 前新增：

```python
@dataclass(frozen=True)
class ToolCallRecord:
    tool: str
    params: Mapping[str, object]
    result: Mapping[str, object]
    status: str
    duration_ms: int

    def __post_init__(self) -> None:
        if not self.tool.strip():
            raise ValueError("tool must not be blank")
        if not self.status.strip():
            raise ValueError("status must not be blank")
        if not isinstance(self.params, Mapping):
            raise ValueError("params must be a mapping")
        if not isinstance(self.result, Mapping):
            raise ValueError("result must be a mapping")
        if isinstance(self.duration_ms, bool) or not isinstance(self.duration_ms, int) or self.duration_ms < 0:
            raise ValueError("duration_ms must be a non-negative integer")
```

`AgentResult` 增加 `tool_calls: tuple[ToolCallRecord, ...] = ()`。`domain/runs.py` 定义枚举与 dataclass；`RunToolCall = ToolCallRecord`；`__post_init__` 使用 `_text`/`_non_negative`/`_mapping` 辅助函数；`AgentRun` 校验 `seq`/`index` 连续、Agent 引用、交接相邻、门禁与步骤一致、artifact 一致、metrics 计算一致。

- [ ] **Step 4: 写分层测试 `tests/dispatch/test_layering.py`**

```python
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "src" / "opsconductor" / "dispatch"
FORBIDDEN_DOMAIN = ("opsconductor.dispatch.application", "opsconductor.dispatch.adapters", "fastapi", "sqlalchemy", "pydantic")
FORBIDDEN_APPLICATION = ("opsconductor.dispatch.adapters",)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_domain_does_not_import_outer_layers():
    for path in (ROOT / "domain").glob("*.py"):
        for name in _imports(path):
            assert not any(name.startswith(prefix) for prefix in FORBIDDEN_DOMAIN), f"{path.name} imports {name}"


def test_application_does_not_import_adapters():
    for path in (ROOT / "application").glob("*.py"):
        for name in _imports(path):
            assert not any(name.startswith(prefix) for prefix in FORBIDDEN_APPLICATION), f"{path.name} imports {name}"
```

- [ ] **Step 5: 运行测试**

Run: `conda run -n opsconductor python -m pytest tests/dispatch/test_runs.py tests/dispatch/test_layering.py -q`
Expected: PASS。

- [ ] **Step 6: 跑现有测试、ruff、mypy**

Run: `conda run -n opsconductor python -m pytest tests/dispatch -q && conda run -n opsconductor python -m ruff check . && conda run -n opsconductor python -m mypy src`
Expected: 全绿；`domain/runs.py` 不引入反向依赖。

- [ ] **Step 7: Commit**

```bash
git add src/opsconductor/dispatch/domain/runs.py src/opsconductor/dispatch/domain/models.py tests/dispatch/test_runs.py tests/dispatch/test_layering.py
git commit -m "feat: add run domain models and invariants"
```

---

### Task 2: 平台配置、凭据与脱敏边界

**Files:**
- Create: `src/opsconductor/dispatch/domain/config.py`
- Create: `src/opsconductor/dispatch/domain/redaction.py`
- Modify: `src/opsconductor/dispatch/domain/errors.py`（新增 `InvalidConfig`）
- Modify: `src/opsconductor/dispatch/domain/ports.py`（新增 `CredentialProvider`）
- Create: `src/opsconductor/dispatch/adapters/config_file.py`
- Create: `src/opsconductor/dispatch/adapters/credentials.py`
- Create: `config/platforms.toml`
- Create: `config/README.md`
- Modify: `.env.example`
- Create: `tests/dispatch/test_platform_config.py`
- Create: `tests/dispatch/test_credentials.py`
- Create: `tests/dispatch/test_redaction.py`

**Interfaces:**
- Produces: `PlatformConfig`, `CredentialStatus`, `Secret`；`load_platform_configs(path=None) -> tuple[PlatformConfig, ...]`；`EnvCredentialProvider.has(ref) -> bool` / `get(ref) -> Secret | None`；`redact_mapping(value) -> dict`。
- Consumes: Task 1 的 `IntegrationCapability` 枚举与分层约束。

- [ ] **Step 1: 写配置/凭据/脱敏失败测试**

`tests/dispatch/test_platform_config.py` 覆盖：合法 mock 配置；重复 `(platform, shop_id)`；live 缺 `credential_ref`；mock 带 ref；`live + enabled=true` 拒绝；未知字段；非法能力；非正限额；配置键中无 `api_key/token/secret/password`。

`tests/dispatch/test_credentials.py` 覆盖：`EnvCredentialProvider` 存在/缺失/空值；`Secret.reveal()`；`repr`/`str` 为 `***`。

`tests/dispatch/test_redaction.py` 覆盖：嵌套 Mapping/List、大小写不敏感、`api_key/token/password/authorization/credential`、sentinel 密钥不出现在返回 JSON。

- [ ] **Step 2: 运行测试确认失败**

Run: `conda run -n opsconductor python -m pytest tests/dispatch/test_platform_config.py tests/dispatch/test_credentials.py tests/dispatch/test_redaction.py -q`
Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现 `domain/config.py`**

```python
class CredentialStatus(str, Enum):
    not_required = "not_required"
    configured = "configured"
    missing = "missing"

@dataclass(frozen=True, repr=False)
class Secret:
    _value: str

    def __post_init__(self) -> None:
        if not isinstance(self._value, str) or not self._value:
            raise ValueError("secret must not be blank")

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret(***)"

    def __str__(self) -> str:
        return "***"

@dataclass(frozen=True)
class PlatformConfig:
    adapter_id: str
    platform: str
    shop_id: str
    display_name: str
    mode: IntegrationMode
    enabled: bool
    capabilities: tuple[IntegrationCapability, ...]
    credential_ref: str | None
    rate_limit_per_minute: int
    timeout_ms: int
    max_attempts: int
    backoff_ms: int
```

`__post_init__` 校验：非空文本、`capabilities` 非空唯一、mock 不允许 ref、live 必须有 ref、限额正数、`enabled` 为 bool。`live + enabled` 的拒绝放在 loader（便于测试错误信息）。

- [ ] **Step 4: 实现 loader、`EnvCredentialProvider`、`redact_mapping`**

`load_platform_configs` 用 `tomllib`，拒绝未知键、重复 `adapter_id`/`(platform, shop_id)`，`live + enabled=true` 抛 `InvalidConfig("live adapters are not implemented: ...")`。

`EnvCredentialProvider`：

```python
class EnvCredentialProvider:
    def has(self, ref: str) -> bool:
        return bool(ref) and bool(os.environ.get(ref))

    def get(self, ref: str) -> Secret | None:
        value = os.environ.get(ref)
        return Secret(value) if value else None
```

`redact_mapping` 递归处理 Mapping/list/tuple；敏感键替换 `"***"`；键名转字符串。

- [ ] **Step 5: 写配置文件与文档**

`config/platforms.toml` 使用规格 6.6.1 的示例（mock 启用、live 禁用、`credential_ref="TIKTOK_SHOP_US_TOKEN"`）。`config/README.md` 说明本地 `.env`、CI secrets、生产 Vault/AWS/GCP、轮换重启。`.env.example` 增加注释和空的 `TIKTOK_SHOP_US_TOKEN=`。

- [ ] **Step 6: 跑测试与检查**

Run: `conda run -n opsconductor python -m pytest tests/dispatch/test_platform_config.py tests/dispatch/test_credentials.py tests/dispatch/test_redaction.py tests/dispatch/test_layering.py -q && conda run -n opsconductor python -m ruff check . && conda run -n opsconductor python -m mypy src`
Expected: PASS；`domain/config.py`/`redaction.py` 不导入 adapters。

- [ ] **Step 7: Commit**

```bash
git add src/opsconductor/dispatch/domain/config.py src/opsconductor/dispatch/domain/redaction.py src/opsconductor/dispatch/domain/errors.py src/opsconductor/dispatch/domain/ports.py src/opsconductor/dispatch/adapters/config_file.py src/opsconductor/dispatch/adapters/credentials.py config .env.example tests/dispatch/test_platform_config.py tests/dispatch/test_credentials.py tests/dispatch/test_redaction.py
git commit -m "feat: add platform config and credential boundary"
```

---

### Task 3: 工具调用采集、RunBuilder 与编排器兼容重构

**Files:**
- Create: `src/opsconductor/dispatch/application/run_builder.py`
- Modify: `src/opsconductor/dispatch/application/agents.py`（真实工具调用记录）
- Modify: `src/opsconductor/dispatch/application/orchestrator.py`（`run_agent()` + `run()` 派生）
- Create: `tests/dispatch/test_run_builder.py`
- Modify: `tests/dispatch/test_agents.py`（补工具调用断言）

**Interfaces:**
- Consumes: Task 1 的 `AgentRun` 等模型、`ToolCallRecord`；Task 2 的 `redact_mapping`。
- Produces: `RunBuilder(run_id, goal, plan, clock)`，方法 `run_started()`, `agent_started(step, agent) -> int`, `tool_called(step, agent, call) -> int`, `step_completed(step, agent, artifact) -> int`, `handoff(...) -> RunHandoff`, `gate_requested(case, step_id, stage) -> int`, `gate_decided(case) -> int`, `tail(...) -> int`, `finish(verification, summary) -> AgentRun`。
- Produces: `DispatchOrchestrator.run_agent(goal) -> AgentRun`；`run(goal) -> DemoRunReport` 保持旧输出。

- [ ] **Step 1: 写失败测试 `tests/dispatch/test_run_builder.py`**

断言：51 个事件；10 步；8 Agent；8 交接且 `event_seq` 指向 handoff 事件；3 门禁 2 准 1 驳；每步 1 个工具调用；2 次运行步骤/事件标题/交接顺序一致；`run()` 仍 28 事件（兼容旧测试）。

- [ ] **Step 2: 运行失败**

Run: `conda run -n opsconductor python -m pytest tests/dispatch/test_run_builder.py -q`
Expected: FAIL（`run_agent` 不存在）。

- [ ] **Step 3: 实现 `RuleBasedAgent` 工具调用记录与 `RunBuilder`**

`RuleBasedAgent.handle` 用 `perf_counter()` 包裹 `ToolPort.call`，构造 `ToolCallRecord(tool=spec.tool, params={"capability": task.capability}, result=dict(tool_result), status=str(tool_result.get("status", "ok")), duration_ms=...)`，返回 `AgentResult(..., tool_calls=(record,))`。

`RunBuilder` 内部维护 `seq`、steps、agents（按首次出现）、events、gates、handoffs、artifacts；`finish()` 计算 `RunMetrics` 并构造 `AgentRun`。

- [ ] **Step 4: 重构 `orchestrator.py`**

`run_agent(goal)` 按规格 4.4 生成事件；`run(goal)` 调用 `run_agent()`，筛选旧版事件类型得到 28 个 `TraceEvent`，并把 `RunStep`/`RunGate` 映射为 `PlanStep`/`ApprovalCase`。保持 summary/detail/actor/stage 与旧输出一致。

- [ ] **Step 5: 跑测试**

Run: `conda run -n opsconductor python -m pytest tests/dispatch/test_run_builder.py tests/dispatch/test_agents.py tests/dispatch/test_orchestrator.py tests/dispatch/test_e2e_demo.py -q`
Expected: PASS；旧 `/demo/run` 事件计数和标题不变。

- [ ] **Step 6: 全量 dispatch 测试 + lint**

Run: `conda run -n opsconductor python -m pytest tests/dispatch -q && conda run -n opsconductor python -m ruff check . && conda run -n opsconductor python -m mypy src`
Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add src/opsconductor/dispatch/application/run_builder.py src/opsconductor/dispatch/application/agents.py src/opsconductor/dispatch/application/orchestrator.py tests/dispatch/test_run_builder.py tests/dispatch/test_agents.py
git commit -m "feat: record agent runs and preserve demo report"
```

---

### Task 4: Run 仓储、Service、API 与序列化

**Files:**
- Modify: `src/opsconductor/dispatch/domain/ports.py`（`RunRepository`）
- Create: `src/opsconductor/dispatch/adapters/run_memory.py`
- Modify: `src/opsconductor/dispatch/application/service.py`
- Modify: `src/opsconductor/dispatch/adapters/serialize.py`
- Modify: `src/opsconductor/dispatch/adapters/api.py`
- Create: `tests/dispatch/test_run_repository.py`
- Create: `tests/dispatch/test_run_api.py`
- Modify: `tests/dispatch/test_service.py`（注入 run repo）

**Interfaces:**
- Consumes: Task 3 的 `run_agent()`；Task 1 的模型。
- Produces: `InMemoryRunRepository.save/get/list/latest`；`DispatchService.start_run/get_run/latest_run/list_runs`；API `POST /runs`、`GET /runs/latest`、`GET /runs/{id}`、`GET /runs?limit=3`；`run_payload`/`run_list_payload`。

- [ ] **Step 1: 写失败测试**

`test_run_repository.py`：保存/读取深拷贝、最新在前、limit、20 条淘汰、未知返回 `None`。
`test_run_api.py`：POST/GET/latest/list；未知 404；limit 422；创建 run 前后 `snapshot` 的 approvals/agents/chain 不变；`latest` 路由不被 `{run_id}` 吞掉。

- [ ] **Step 2: 运行失败**

Run: `conda run -n opsconductor python -m pytest tests/dispatch/test_run_repository.py tests/dispatch/test_run_api.py -q`
Expected: FAIL。

- [ ] **Step 3: 实现仓储与 Service**

`InMemoryRunRepository` 用 `RLock` + `OrderedDict`，`save` 深拷贝，超过 20 淘汰最旧，`list(limit)` 最新在前。`DispatchService.__init__` 增加 `runs: RunRepository`；`start_run()` 用当前 goal 调 `run_agent()` 并保存；`get_run/latest_run/list_runs` 读取仓储；`run_demo()` 不变。

- [ ] **Step 4: 实现序列化与 API**

`serialize.py` 增加 `run_step_payload`、`run_agent_payload`、`run_event_payload`、`run_gate_payload`、`run_handoff_payload`、`run_artifact_payload`、`run_metrics_payload`、`run_payload`、`run_list_item_payload`、`run_list_payload`；工具参数/结果经 `redact_mapping`。`api.py` 按 `/runs/latest` 在 `/runs/{run_id}` 之前声明；`limit` 用 `Query(ge=1, le=20)`。

- [ ] **Step 5: 跑测试**

Run: `conda run -n opsconductor python -m pytest tests/dispatch/test_run_repository.py tests/dispatch/test_run_api.py tests/dispatch/test_service.py tests/dispatch/test_api_smoke.py -q`
Expected: PASS；旧 API 不变。

- [ ] **Step 6: 全量 dispatch + lint**

Run: `conda run -n opsconductor python -m pytest tests/dispatch -q && conda run -n opsconductor python -m ruff check . && conda run -n opsconductor python -m mypy src`
Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add src/opsconductor/dispatch/domain/ports.py src/opsconductor/dispatch/adapters/run_memory.py src/opsconductor/dispatch/application/service.py src/opsconductor/dispatch/adapters/serialize.py src/opsconductor/dispatch/adapters/api.py tests/dispatch/test_run_repository.py tests/dispatch/test_run_api.py tests/dispatch/test_service.py
git commit -m "feat: persist and expose agent runs"
```

---

### Task 5: Container、Mock Adapter 与集成凭据状态

**Files:**
- Modify: `src/opsconductor/dispatch/adapters/container.py`
- Modify: `src/opsconductor/dispatch/adapters/integration/mock_platform.py`
- Modify: `src/opsconductor/dispatch/adapters/serialize.py`（`credential_status`）
- Modify: `tests/dispatch/test_integrations.py`
- Modify: `tests/dispatch/test_api_smoke.py`
- Modify: `scripts/export_dispatch_fixtures.py`（如 payload 字段变化需重生成）

**Interfaces:**
- Consumes: Task 2 的 `load_platform_configs`/`PlatformConfig`/`CredentialStatus`；Task 4 的 run repo。
- Produces: `_build_graph()` 从 `config/platforms.toml` 注册 mock adapter；`IntegrationHealth.credential_status`；集成 payload 新增 `credential_status`。

- [ ] **Step 1: 写失败测试**

在 `test_integrations.py` 断言 mock 集成 `credential_status == not_required`；新增 fake live adapter 的 `configured`/`missing` 测试；`test_api_smoke.py` 断言 `/integrations` 包含 `credential_status` 且不包含 `credential_ref`。

- [ ] **Step 2: 运行失败**

Run: `conda run -n opsconductor python -m pytest tests/dispatch/test_integrations.py tests/dispatch/test_api_smoke.py -q`
Expected: FAIL。

- [ ] **Step 3: 修改 `MockPlatformAdapter` 接受 `PlatformConfig`**

`__init__(self, config: PlatformConfig | None = None)`，默认配置保持当前 adapter_id/platform/shop/能力；manifest/health 从 config 读取；`credential_status=CredentialStatus.not_required`；`mode` 不是 mock 时抛 `ValueError`。

- [ ] **Step 4: 修改 container 与序列化**

`container._build_graph()` 加载配置，只注册 `enabled=true` 且 `mode=mock` 的 adapter；创建 `InMemoryRunRepository()` 注入 `DispatchService`。`integration_health_payload` 增加 `credential_status`。重新运行 fixture 导出脚本，确认 `frontend/src/api/fixtures.json` 更新。

- [ ] **Step 5: 跑测试与 fixture 校验**

Run: `conda run -n opsconductor python -m pytest tests/dispatch/test_integrations.py tests/dispatch/test_api_smoke.py tests/dispatch -q && conda run -n opsconductor python scripts/export_dispatch_fixtures.py`
Expected: PASS；fixture 包含 `credential_status`。

- [ ] **Step 6: Commit**

```bash
git add src/opsconductor/dispatch/adapters/container.py src/opsconductor/dispatch/adapters/integration/mock_platform.py src/opsconductor/dispatch/adapters/serialize.py frontend/src/api/fixtures.json scripts/export_dispatch_fixtures.py tests/dispatch/test_integrations.py tests/dispatch/test_api_smoke.py
git commit -m "feat: wire platform config and credential status"
```

---

### Task 6: 前端契约、Fixture 与查询

**Files:**
- Modify: `frontend/src/api/schemas.ts`
- Modify: `frontend/src/api/types.ts`（如使用推断类型）
- Modify: `frontend/src/api/dispatch.ts`
- Create: `frontend/src/queries/useRunQuery.ts`
- Create: `frontend/src/queries/useRunsQuery.ts`
- Modify: `frontend/src/queries/mutations.ts`
- Create: `frontend/src/tests/fixtures/run.ts`
- Modify: `frontend/src/tests/unit/schemas.spec.ts`
- Create: `frontend/src/tests/unit/layering.spec.ts`

**Interfaces:**
- Produces: `RunSchema`、`RunStepSchema`、`RunAgentSchema`、`RunEventSchema`、`RunGateSchema`、`RunHandoffSchema`、`RunArtifactSchema`、`RunToolCallSchema`、`RunMetricsSchema`、`RunListItemSchema`、`RunListSchema`；`startRun()`、`getRun(id)`、`getLatestRun()`、`listRuns(limit)`；`useRunQuery(runId)`、`useRunsQuery(limit)`、`useStartRunMutation()`。

- [ ] **Step 1: 用后端生成 Run fixture**

Run: `conda run -n opsconductor python - <<'PY' ...`（调用 `reset_service()`、`service.start_run()`、`run_payload`，写入 `frontend/src/tests/fixtures/run.json`）。把 JSON 包成 `export const runFixture = ... as const` 的 TS 文件，类型由 `RunSchema` 校验。fixture 仅测试用，不做生产 fallback。

- [ ] **Step 2: 写失败测试**

`schemas.spec.ts` 断言 `RunSchema.parse(runFixture)` 成功；缺字段/非法 gate 状态失败；`IntegrationPlatformSchema` 接受 `credential_status`。`layering.spec.ts` 扫描 `src/features/**`，禁止 `from '@/api/client'` 与裸 `fetch(`。

- [ ] **Step 3: 运行失败**

Run: `cd frontend && npm run test:unit -- --run src/tests/unit/schemas.spec.ts src/tests/unit/layering.spec.ts`
Expected: FAIL。

- [ ] **Step 4: 实现 Zod/API/Query**

按规格 6.4/8 定义 schema；`request` 调用 `/runs`、`/runs/latest`、`/runs/{id}`、`/runs?limit=3`；query keys `['dispatch','run',id]`、`['dispatch','runs']`；`useStartRunMutation` 成功后 `setQueryData` 并 invalidate runs。

- [ ] **Step 5: 跑前端测试与类型检查**

Run: `cd frontend && npm run typecheck && npm run test:unit`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api frontend/src/queries frontend/src/tests/unit/schemas.spec.ts frontend/src/tests/unit/layering.spec.ts frontend/src/tests/fixtures
git commit -m "feat: add run API contract and queries"
```

---

### Task 7: 播放器 `useRunPlayer`

**Files:**
- Create: `frontend/src/features/runs/useRunPlayer.ts`
- Create: `frontend/src/tests/unit/use-run-player.spec.ts`

**Interfaces:**
- Consumes: `AgentRun` type。
- Produces: `useRunPlayer(run, options?)`，返回 `status/cursor/speed/follow/showAll/visibleEvents/activeEvent/activeStepId/activeAgentId/completedStepIds/runningStepId/visibleGateStatus/progress/play/pause/toggle/stepForward/stepBack/seek/seekToStep/seekToEvent/replay/setSpeed/toggleShowAll`。

- [ ] **Step 1: 写失败测试**

用 `vi.useFakeTimers()` 覆盖：初始 idle、播放推进、暂停停止、单步/后退、2x/4x 时长、`seekToStep` 定位、`seekToEvent`、`replay`、`showAll`、reduced motion 初始完成；门禁在 `approval_requested` 后 `pending`、`approval_decided` 后 `approved/rejected`。

- [ ] **Step 2: 运行失败**

Run: `cd frontend && npm run test:unit -- --run src/tests/unit/use-run-player.spec.ts`
Expected: FAIL。

- [ ] **Step 3: 实现 composable**

按规格 7.3 实现事件时长表（600/500/450/550/450/900/900/800/900/700/700/600/700），状态机、派生 computed、`setTimeout` 调度、`seekToStep`/`seekToEvent`、reduced motion、URL 初始 speed/autoplay 由调用方传入。`showAll` 为显示模式，不改变 `cursor` 语义；`toggleShowAll` 进入时暂停。

- [ ] **Step 4: 跑测试**

Run: `cd frontend && npm run typecheck && npm run test:unit -- --run src/tests/unit/use-run-player.spec.ts`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/runs/useRunPlayer.ts frontend/src/tests/unit/use-run-player.spec.ts
git commit -m "feat: add run playback controller"
```

---

### Task 8: Run 页骨架、Header、控制条与摘要

**Files:**
- Create: `frontend/src/features/runs/RunView.vue`
- Create: `frontend/src/features/runs/RunHeader.vue`
- Create: `frontend/src/features/runs/RunControls.vue`
- Create: `frontend/src/features/runs/RunSummary.vue`
- Create: `frontend/src/styles/runs.css`
- Modify: `frontend/src/main.ts`（引入 runs.css）
- Modify: `frontend/src/router/index.ts`（`/dispatch/runs/:runId`）

**Interfaces:**
- Consumes: `useRunQuery`、`useRunPlayer`。
- Produces: Run 页面骨架；后续 Task 9/10 的组件挂载点。

- [ ] **Step 1: 写组件测试**

`RunControls`：播放/暂停/上一步/下一步/倍速/完整视图按钮存在，点击 emit 对应事件，aria-label/aria-valuenow 正确。`RunSummary`：显示 10 步/8 Agent/8 交接/2 准 1 驳/1 补偿/3 对账。`RunView`：加载态/404 空态/错误态。

- [ ] **Step 2: 运行失败**

Run: `cd frontend && npm run test:unit -- --run src/tests/unit/run-controls.spec.ts`
Expected: FAIL。

- [ ] **Step 3: 实现骨架组件**

`RunView` 负责 `useRoute` 取 `runId`、query、player；渲染 `RunHeader`、`RunChainStrip`（Task 9 占位导入）、`RunStage`（Task 10 占位导入）、`RunHandoffLedger`、`RunGovernanceStrip`、`RunControls`、`RunSummary`、`RunStepDrawer`。404/网络错误使用纸白空态，不用 fixture 伪装。

- [ ] **Step 4: 路由与样式**

新增路由 `{ path: '/dispatch/runs/:runId', name: 'run', component: () => import('@/features/runs/RunView.vue'), meta: { title: 'Agent 运行' } }`。`runs.css` 使用现有 tokens，不引入新库。

- [ ] **Step 5: 跑前端检查**

Run: `cd frontend && npm run typecheck && npm run test:unit`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/runs/RunView.vue frontend/src/features/runs/RunHeader.vue frontend/src/features/runs/RunControls.vue frontend/src/features/runs/RunSummary.vue frontend/src/styles/runs.css frontend/src/main.ts frontend/src/router/index.ts
git commit -m "feat: add run page shell and controls"
```

---

### Task 9: 执行链组件（链条、交接账本、治理链）

**Files:**
- Create: `frontend/src/features/runs/RunChainStrip.vue`
- Create: `frontend/src/features/runs/RunHandoffLedger.vue`
- Create: `frontend/src/features/runs/RunGovernanceStrip.vue`
- Create: `frontend/src/tests/unit/run-chain-strip.spec.ts`
- Create: `frontend/src/tests/unit/run-handoff-ledger.spec.ts`
- Create: `frontend/src/tests/unit/run-governance-strip.spec.ts`

**Interfaces:**
- Consumes: `run`, `player`（`activeStepId`、`completedStepIds`、`seekToStep`、`seekToEvent`、`visibleGateStatus`）。
- Produces: 10 节点 + 8 条交接连接 + 1 条同 Agent 延续；8 行账本；5 个治理 chip；点击定位。

- [ ] **Step 1: 写失败测试**

`RunChainStrip`：10 个 `[data-chain-node]`、8 个 `[data-handoff-link]`、1 个 `[data-continuation-link]`；点击第 5 个节点 emit `seek-step`；gate badge 在裁决前“待批”。`RunHandoffLedger`：8 行、顺序、产物、点击 emit `seek-event`；`RunGovernanceStrip`：5 个 chip、状态类、点击 emit `seek-event`。

- [ ] **Step 2: 运行失败**

Run: `cd frontend && npm run test:unit -- --run src/tests/unit/run-chain-strip.spec.ts src/tests/unit/run-handoff-ledger.spec.ts src/tests/unit/run-governance-strip.spec.ts`
Expected: FAIL。

- [ ] **Step 3: 实现三个组件**

链条：CSS Grid/Flex 节点，SVG 或 CSS 连接；延续连接由相邻 `agent_id` 相同派生；移动端 ≤767px 折叠为单行。账本：表格/列表，8 行，空态“本次没有 Agent 交接”。治理链：5 个 chip，状态由事件出现与否派生。

- [ ] **Step 4: 跑测试**

Run: `cd frontend && npm run typecheck && npm run test:unit`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/runs/RunChainStrip.vue frontend/src/features/runs/RunHandoffLedger.vue frontend/src/features/runs/RunGovernanceStrip.vue frontend/src/tests/unit/run-chain-strip.spec.ts frontend/src/tests/unit/run-handoff-ledger.spec.ts frontend/src/tests/unit/run-governance-strip.spec.ts
git commit -m "feat: add execution chain visualization"
```

---

### Task 10: 泳道、事件流与步骤抽屉

**Files:**
- Create: `frontend/src/features/runs/RunSwimlane.vue`
- Create: `frontend/src/features/runs/RunStepBlock.vue`
- Create: `frontend/src/features/runs/RunEventStream.vue`
- Create: `frontend/src/features/runs/RunGateCard.vue`
- Create: `frontend/src/features/runs/RunStepDrawer.vue`
- Create: `frontend/src/tests/unit/run-swimlane.spec.ts`
- Create: `frontend/src/tests/unit/run-event-stream.spec.ts`
- Create: `frontend/src/tests/unit/run-step-drawer.spec.ts`

**Interfaces:**
- Consumes: `run`, `player`、`visibleGates`。
- Produces: 8 行 × 10 步泳道、8 条 SVG 交接箭头、事件流、步骤抽屉（含上下游）。

- [ ] **Step 1: 写失败测试**

`RunSwimlane`：8 行、10 个步骤块、8 条箭头；active/completed/future 类；状态文字；未来步骤不可点。`RunEventStream`：只渲染 `visibleEvents`；`tool_called` 显示耗时；门禁卡片裁决前“待批”、裁决后“准/驳”；`aria-live` 状态行。`RunStepDrawer`：Agent、能力、工具参数/返回、产物、门禁、上下游按钮；ESC 关闭。

- [ ] **Step 2: 运行失败**

Run: `cd frontend && npm run test:unit -- --run src/tests/unit/run-swimlane.spec.ts src/tests/unit/run-event-stream.spec.ts src/tests/unit/run-step-drawer.spec.ts`
Expected: FAIL。

- [ ] **Step 3: 实现组件**

泳道用 CSS Grid + 一层 SVG 箭头；未来步骤不可点；移动端纵向接力列表。事件流按 `seq` key，自动滚动 `block:'nearest'`，`follow` 开关。抽屉复用 `ExceptionDrawer` 的 Teleport/role/ESC/body lock 模式；上下游调用 `seekToStep`。

- [ ] **Step 4: 跑测试**

Run: `cd frontend && npm run typecheck && npm run test:unit`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/runs/RunSwimlane.vue frontend/src/features/runs/RunStepBlock.vue frontend/src/features/runs/RunEventStream.vue frontend/src/features/runs/RunGateCard.vue frontend/src/features/runs/RunStepDrawer.vue frontend/src/tests/unit/run-swimlane.spec.ts frontend/src/tests/unit/run-event-stream.spec.ts frontend/src/tests/unit/run-step-drawer.spec.ts
git commit -m "feat: add run swimlane and event stream"
```

---

### Task 11: Overview 入口、最近运行与集成凭据徽标

**Files:**
- Create: `frontend/src/features/overview/RecentRunsCard.vue`
- Modify: `frontend/src/features/overview/OverviewView.vue`
- Modify: `frontend/src/queries/mutations.ts`
- Modify: `frontend/src/features/integrations/IntegrationStatus.vue`
- Modify: `frontend/src/api/schemas.ts`（`credential_status`）
- Modify: `frontend/src/tests/unit/integration-status.spec.ts`
- Create: `frontend/src/tests/unit/recent-runs-card.spec.ts`

**Interfaces:**
- Consumes: `useStartRunMutation`、`useRunsQuery`、`IntegrationPlatform.credential_status`。
- Produces: Overview“运行 Agent 团队”按钮、最近运行卡片、集成页凭据状态徽标。

- [ ] **Step 1: 写失败测试**

`RecentRunsCard`：3 条 run 摘要、空态、点击 emit 导航。`OverviewView`：点击按钮调用 `startRun` 并跳转。`IntegrationStatus`：三种 `credential_status` 徽标，不显示 ref/值。

- [ ] **Step 2: 运行失败**

Run: `cd frontend && npm run test:unit -- --run src/tests/unit/recent-runs-card.spec.ts src/tests/unit/integration-status.spec.ts`
Expected: FAIL。

- [ ] **Step 3: 实现**

Overview 移除 `useDemoMutation` 调用，改用 `useStartRunMutation` + `router.push`；新增“最近运行”卡片；集成页显示“凭据：未要求/已配置/缺失”。

- [ ] **Step 4: 跑前端检查**

Run: `cd frontend && npm run typecheck && npm run test:unit`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/overview/RecentRunsCard.vue frontend/src/features/overview/OverviewView.vue frontend/src/queries/mutations.ts frontend/src/features/integrations/IntegrationStatus.vue frontend/src/api/schemas.ts frontend/src/tests/unit/integration-status.spec.ts frontend/src/tests/unit/recent-runs-card.spec.ts
git commit -m "feat: add run entry and credential status"
```

---

### Task 12: E2E、CI、文档与最终验证

**Files:**
- Create: `frontend/e2e/run.spec.ts`
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `design/cross-border-dispatch/README.md`
- Modify: `docs/README.md`

**Interfaces:**
- Consumes: 全部完成的功能。
- Produces: Run 页 E2E、CI 后端 Postgres + 前端 job、文档更新。

- [ ] **Step 1: 写 E2E**

覆盖：Overview 点击“运行 Agent 团队” → URL `/dispatch/runs/{id}?speed=4` → 摘要出现；暂停/单步/重播；点击链条节点定位；点击交接账本行；点击步骤开抽屉；未知 run 空态；375px 无横向溢出。

- [ ] **Step 2: 运行 E2E**

Run: `bash scripts/build_frontend.sh && PORT=8010 bash scripts/demo_dispatch.sh`（后台） + `cd frontend && E2E_BASE_URL=http://127.0.0.1:8010 npm run test:e2e -- run.spec.ts`
Expected: PASS；若本机无 Chrome，记录为未执行，不伪报。

- [ ] **Step 3: 更新 CI**

后端 job 增加 `pgvector/pgvector:pg16` service（`POSTGRES_USER=ops`、`POSTGRES_PASSWORD=ops`、`POSTGRES_DB=opsconductor_test`、`15432:5432`、`pg_isready` healthcheck）。新增前端 job（Node 20，`npm ci`、`typecheck`、`test:unit`、`build`）。

- [ ] **Step 4: 更新文档**

README 增加 Run 页入口、`/runs` API、测试命令；`design/cross-border-dispatch/README.md` 增加“Agent 运行页”；`docs/README.md` 挂载本规格与计划。

- [ ] **Step 5: 最终验证**

Run:
```bash
conda run -n opsconductor python -m pytest tests/dispatch -q
conda run -n opsconductor python -m ruff check .
conda run -n opsconductor python -m mypy src
cd frontend && npm run typecheck && npm run test:unit && npm run build
```
Expected: 全绿；完整 `pytest -q` 需要 Docker PostgreSQL，若 Docker 未启动则记录为未执行。

- [ ] **Step 6: Commit**

```bash
git add frontend/e2e/run.spec.ts .github/workflows/ci.yml README.md design/cross-border-dispatch/README.md docs/README.md
git commit -m "test: cover run playback and update docs"
```

---

## Self-Review

- **Spec coverage:** 值对象校验（Task 1）、配置/凭据/脱敏（Task 2）、Run 构建与兼容（Task 3）、仓储/API（Task 4）、集成凭据状态（Task 5）、前端契约/播放器（Task 6-7）、执行链/泳道/事件流/抽屉（Task 8-10）、入口与文档（Task 11-12）。
- **Placeholder scan:** 每个任务包含具体文件、测试断言、实现要点、运行命令和 commit；无 TBD/TODO。
- **Type consistency:** `RunToolCall` 复用 `ToolCallRecord`；`RunHandoff.event_seq` 在模型、payload、前端 `seekToEvent` 中一致；`credential_status` 在 `IntegrationHealth`、payload、Zod、徽标中一致。
- **Known execution caveat:** 完整后端 `pytest -q` 依赖 Docker PostgreSQL 15432；本机 Docker 未启动时只跑 `tests/dispatch`（内存）+ lint + mypy，不伪报全量通过。E2E 依赖本地 Chrome，缺失时记录为未执行。
