# Agent 运行可观测（A 切片）设计

**状态：** 已实施（A 切片）  
**日期：** 2026-11-18  
**补充：** 2026-11-19（值对象校验、分层/TDD、执行链可视化、平台配置/凭据边界）  
**归属：** 跨境电商台前调度台 v1.3 · 子项目 A  
**范围：** 真实 Agent Run 记录 + 导演模式回放 + Run 详情页 + 执行链可视化 + 平台配置/凭据安全边界  
**关联：** [跨境调度台说明](../../design/cross-border-dispatch/README.md)、[台前调度扩展设计](2026-11-12-dispatch-console-enhancement-design.md)

## 0. 结论先行

- 当前“播放演示”是只读投影：`DispatchOrchestrator.run()` 把事件放在内存列表后返回 `DemoRunReport`，`DispatchService.run_demo()` 不落库、不改状态；Agent 状态与经营图表来自种子常量。
- 本切片新增真实 `AgentRun` 记录：10 步、8 个 Agent、8 次交接、3 个审批门、真实工具调用与实测耗时。
- 前端不做 SSE，而是“导演模式”：一次取回完整 run，由 `useRunPlayer` 按 450–900ms/事件播放，支持暂停、单步、后退、倍速、重播。
- Run 是只读投影：创建 run 不改变审批、Agent 卡片或链路状态；页面明确标注 `DEMO` 与“只读回放，审批状态未改变”。
- 主叙事是“多 Agent 接力与分工”：8 条泳道、10 个步骤块、8 条交接箭头；审批门在第二幕统一批阅（2 准 1 驳）。
- 旧 `/demo/run` 端点与 `DemoRunReport` 保持兼容；现有 89 个 dispatch 测试保持通过，新增 `credential_status` 的集成断言同步更新。
- 所有领域值对象与不可变聚合在 `__post_init__` 中做 Python 校验，非法数据在领域边界 fail-fast，不进入 API 或 UI。
- 分层严格单向：`domain ← application ← adapters`；前端 `api → queries → features`。新增 AST 分层测试，防止反向依赖。
- 执行链不止一条泳道：顶部接力链条（10 节点 + 8 条交接连接 + 1 条同 Agent 延续）、交接账本（8 行）、步骤抽屉上下游、尾部治理链（Verifier → 补偿 → RPA → 对账 → 报告）。
- 平台配置与密钥分离：`config/platforms.toml` 只放非密钥配置；密钥只通过 `CredentialProvider` 从环境/密钥管理读取；run payload、事件、日志全程脱敏。

## 1. 背景与问题

### 1.1 当前实现

| 位置 | 现状 |
|---|---|
| `src/opsconductor/dispatch/application/orchestrator.py:86` | `run()` 顺序执行 10 步，事件只存在局部列表，返回后丢弃 |
| `src/opsconductor/dispatch/application/service.py:431` | `run_demo()` 只返回报告，不持久化、不生成 run ID |
| `src/opsconductor/dispatch/application/seed.py:49` | 8 个 Agent 的状态是静态种子：done/running/waiting |
| `src/opsconductor/dispatch/application/analytics.py:32` | Agent 调用量、成功率、平均耗时是静态常量 |
| `src/opsconductor/dispatch/application/agents.py:155` | `select()` 按能力取第一个匹配项，无可用性、负载、成本 |
| `src/opsconductor/dispatch/domain/models.py:323` | `TraceEvent` 只有 `at/title/detail`，无 step、agent、耗时、工具关联 |
| `frontend/src/features/overview/OverviewView.vue:56` | “播放演示”只弹 toast，页面状态不变 |
| `frontend/src/queries/useSnapshotQuery.ts:11` | 快照 `staleTime=5s`，无轮询/SSE，页面不会自行更新 |

### 1.2 问题

- **不可验证**：观众无法确认 Agent 真的执行过，只能看到一段结果摘要。
- **不可解释**：没有“哪个 Agent 在何时接手、调用了什么工具、产物是什么、哪一步需要人批”。
- **不可复用**：`DemoRunReport` 是展示专用结构，无法支撑后续多 Agent 调度控制面（B 切片）和场景包（C 切片）。
- **不可回放**：没有 run ID、事件序号和持久内容，刷新页面或换人讲解无法复现同一条运行。

### 1.3 机会

现有切片已经具备真实执行的基础：8 个规则型 Agent、能力注册表、Mock 工具网关、独立 Verifier、3 个审批草稿和确定性 trace。本切片不新增 Agent，只把“已经发生的执行”记录成可观察、可回放的运行事实。

## 2. 目标与非目标

### 2.1 目标

1. 每次“运行 Agent 团队”生成一条真实、不可变的 `AgentRun`，包含步骤、Agent、事件、工具调用、产物、审批门、交接和 Verifier 结论。
2. 提供 `/dispatch/runs/:runId` 导演回放页，以“多 Agent 接力与分工”为主叙事，让非技术观众在 30 秒内看懂谁在做什么、人在哪里介入。
3. 提供步骤级抽屉，展示能力匹配原因、工具参数与返回、产物 URI、真实耗时和关联审批。
4. 保持只读边界：创建 run 不改变审批状态、Agent 卡片状态或十段链路状态。
5. 保持旧接口兼容：`/api/v1/dispatch/demo/run`、`DemoRunReport` 不变；现有测试保持通过，新增配置/凭据字段的断言同步更新。
6. 补齐可回放所需的质量门禁：领域不变量、Run 构建确定性、API 契约、播放器单测、组件测试和 E2E。
7. 值对象在构造时校验：非空文本、非负计数、唯一键、门禁状态一致、事件关联完整；每条约束都有失败测试。
8. 执行链可被快速讲清：观众无需打开事件流，就能按 10 个节点复述 Agent 顺序、8 次交接和下一步接手人。
9. 建立平台配置与凭据边界：配置文件不含密钥，Agent 不接触密钥，集成页只显示凭据状态，不显示值。

### 2.2 非目标

- 不做 SSE/WebSocket 实时推送；本期是“真实 run + 前端导演”。
- 不接真实 LLM token/成本，不接真实平台 API；工具调用仍是 Mock，页面明确标注 `DEMO`。
- 不做审批暂停/恢复；审批门禁只读展示，留给 B 切片。
- 不做数据库持久化、多租户、权限改造；run 只存内存，服务重启即丢。
- 不新增场景包、不新增 Agent、不改 10 步计划模板。
- 不做独立运行列表页；Overview 只展示最近 3 条。
- 不引入图表/动画库，不改变现有朱墨视觉语言。
- 不实现真实平台 API 调用、OAuth、签名、限流重试；不实现密钥托管后台、配置编辑 UI、热加载或自动轮换。
- 不把 `credential_ref`、密钥值或密钥指纹暴露给前端；集成页只显示 `credential_status`。

### 2.3 成功标准

- 从 Overview 一次点击即可看到一条真实 run 的完整回放。
- 观众能指出每个步骤由哪个 Agent 执行、调用了什么工具、上一个 Agent 交接了什么产物。
- 审批门在裁决事件出现前保持“待批”，出现后才翻“准/驳”。
- 创建 run 前后 `snapshot.approvals` 完全一致。
- 旧 `/demo/run` 的 28 个事件、2 准 1 驳、Verifier 否决项与现有测试全部保持。
- 每个值对象的非法输入都有测试，且构造时直接抛 `ValueError`；API 不会返回半成品。
- 观众能在 10 秒内指出 10 步 Agent 顺序、8 次交接和下一步接手人；链条节点、交接账本和抽屉上下游都能互相定位。
- `config/platforms.toml` 中没有任何密钥；带 sentinel 密钥的工具参数经过 run payload、事件和日志后不出现原值；集成页只显示凭据状态。

## 3. 设计原则

1. **Run 是事实，播放是表达。** 后端记录真实步骤、工具调用与产物；播放节奏只存在于前端，不把演示延时写进运行数据。
2. **单一执行路径。** `run_agent()` 是唯一执行入口，`run()` 从它派生旧报告，避免两套逻辑漂移。
3. **只读投影。** run 不改变业务状态；审批仍由人裁决，run 只记录“如果演示会怎么批”。
4. **事件驱动展示。** 所有页面状态从 `cursor` + 事件流派生，不维护第二套步骤状态。
5. **贴合现有分层。** 领域模型、应用构建器、内存仓储、序列化、FastAPI 路由、Vue 组件，逐层落位。
6. **不引入新依赖。** 泳道用 CSS Grid，交接箭头用一层 SVG，播放用 `setTimeout`，配置解析用 Python 3.11 标准库 `tomllib`。
7. **分层单向。** `domain` 不依赖 `application` / `adapters` / FastAPI / SQLAlchemy；`application` 不依赖 `adapters`；前端 `features` 不直接调用 `fetch` 或 `api/client`。
8. **TDD 先行。** 每个后端/前端任务先写失败测试，再写最小实现，最后重构；修 bug 也必须先复现。
9. **配置与密钥分离。** 配置描述“连哪个平台、用哪个 Adapter、限额多少”，密钥描述“凭据是什么”；两者不在同一文件、同一 payload、同一日志里。

### 3.1 分层与依赖方向

```text
┌──────────────────────────────────────────────────────────────┐
│ adapters  FastAPI 路由 / 内存仓储 / TOML 加载 / 凭据读取 / JSON │
│           可依赖 domain、application、stdlib、fastapi、tomllib  │
└───────────────────────────┬──────────────────────────────────┘
                            │ 单向
┌───────────────────────────▼──────────────────────────────────┐
│ application  Orchestrator / RunBuilder / DispatchService      │
│              可依赖 domain、stdlib；不得依赖 adapters            │
└───────────────────────────┬──────────────────────────────────┘
                            │ 单向
┌───────────────────────────▼──────────────────────────────────┐
│ domain  AgentRun / RunStep / RunGate / 配置值对象 / 端口         │
│         只依赖 stdlib + 既有 domain 模型；无 FastAPI/SQLAlchemy   │
└──────────────────────────────────────────────────────────────┘
```

| 层 | 文件 | 允许依赖 | 禁止依赖 |
|---|---|---|---|
| 领域 | `dispatch/domain/runs.py`、`config.py`、`redaction.py`、`ports.py` | 标准库、既有 domain 模型/枚举 | `application`、`adapters`、FastAPI、SQLAlchemy、Pydantic |
| 应用 | `dispatch/application/run_builder.py`、`orchestrator.py`、`service.py` | domain、标准库、其他 application 模块 | adapters、FastAPI、SQLAlchemy |
| 适配 | `dispatch/adapters/run_memory.py`、`config_file.py`、`credentials.py`、`serialize.py`、`api.py`、`container.py` | domain、application、标准库、FastAPI、`tomllib`、`os` | 反向被 domain/application 导入 |
| 前端 API | `frontend/src/api/client.ts`、`dispatch.ts`、`schemas.ts` | 浏览器 API、Zod | Vue 组件、Pinia、路由 |
| 前端查询 | `frontend/src/queries/*` | `api/*`、TanStack Query | 直接 `fetch` |
| 前端视图 | `frontend/src/features/**` | `queries/*`、`api/types`、`api/schemas`、UI 组件 | `api/client`、直接 `fetch`、后端实现细节 |

约束落地：

- 新增 `tests/dispatch/test_layering.py`，用 `ast` 扫描 `dispatch/domain/*.py` 与 `dispatch/application/*.py` 的 import，发现反向依赖直接失败。
- 新增 `frontend/src/tests/unit/layering.spec.ts`，扫描 `src/features/**`，禁止 `from '@/api/client'` 与裸 `fetch(`。
- `dispatch/domain/config.py` 只定义 `PlatformConfig`、`CredentialStatus`、`Secret` 值对象和校验；TOML 读取在 `adapters/config_file.py`。
- `DispatchService` 只依赖 `RunRepository` 端口，不依赖 `InMemoryRunRepository` 具体类。
- `RunView` 只通过 `useRunQuery` / `useStartRunMutation` 取数，不直接拼 URL。

### 3.2 TDD 工作流

每个任务按 **Red → Green → Refactor** 执行：

1. **Red**：先写一个会失败的测试，测试名描述行为，不描述实现。
2. **Green**：写最小实现让测试通过，不提前加未来才需要的分支。
3. **Refactor**：在测试保护下消除重复、收紧类型、补文档字符串；保持全绿。

测试先行顺序：

| 顺序 | 先写的失败测试 | 再实现的代码 |
|---:|---|---|
| 1 | `test_runs.py`：空文本、负数、重复键、门禁状态不一致、事件缺关联 | `domain/runs.py` 的 `__post_init__` 与聚合不变量 |
| 2 | `test_platform_config.py`：重复 platform+shop、live 缺 credential_ref、mock 带 ref、未知字段、非法能力 | `domain/config.py` + `adapters/config_file.py` |
| 3 | `test_credentials.py`：缺失/存在/空值、`repr` 不泄露、集成健康状态 | `domain/ports.py` + `adapters/credentials.py` |
| 4 | `test_redaction.py`：嵌套 params/result 中的 token/password/api_key 被替换 | `domain/redaction.py` 的 `redact_mapping`（序列化层复用） |
| 5 | `test_run_builder.py`：51 事件、10 步、8 交接、3 门禁、工具调用、确定性 | `application/run_builder.py` + `orchestrator.py` 重构 |
| 6 | `test_run_repository.py`：深拷贝、最新在前、20 条淘汰 | `adapters/run_memory.py` |
| 7 | `test_run_api.py`：POST/GET/latest/list、404、422、只读边界 | `application/service.py` + `adapters/api.py` |
| 8 | `schemas.spec.ts`：RunSchema 解析 fixture、缺字段失败、credential_status | `frontend/src/api/schemas.ts` |
| 9 | `use-run-player.spec.ts`：播放/暂停/单步/后退/倍速/seek/showAll/门禁遮罩 | `useRunPlayer.ts` |
| 10 | `RunChainStrip` / `RunHandoffLedger` / `RunGovernanceStrip` / `RunStepDrawer` 单测 | 对应 Vue 组件 |
| 11 | `run.spec.ts`：完整回放、链条定位、抽屉、375px | 页面收尾 |

规则：

- 不使用 `sleep`；播放器测试用 Vitest fake timers，后端时间用注入的 `ClockPort` 与固定 run ID。
- 每个不变量至少一个失败用例；不要只测 happy path。
- 修 bug 必须先写复现测试，再修。
- 每个任务的定义完成：失败测试 → 实现 → 重构 → 新旧测试全绿 → 无新增依赖 → 文档同步。
- 覆盖率不是目标；每个新增约束必须有对应测试，避免“行覆盖高但边界没测”。

## 4. 运行模型

### 4.1 枚举

新增于 `src/opsconductor/dispatch/domain/runs.py`：

```python
class RunStatus(str, Enum):
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class RunMode(str, Enum):
    demo = "demo"
    live = "live"


class RunStepStatus(str, Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"


class RunEventKind(str, Enum):
    run_started = "run_started"
    agent_started = "agent_started"
    tool_called = "tool_called"
    step_completed = "step_completed"
    handoff = "handoff"
    approval_requested = "approval_requested"
    approval_decided = "approval_decided"
    verification_passed = "verification_passed"
    compensation_triggered = "compensation_triggered"
    rpa_executed = "rpa_executed"
    reconciliation_found = "reconciliation_found"
    report_generated = "report_generated"
    run_completed = "run_completed"
```

`RunStatus` 与 `RunStepStatus` 为后续失败场景预留；本期 Demo 生成的所有 run 与步骤均为 `succeeded`。播放时的“进行中”是前端遮罩，不写回存储。

### 4.2 值对象

```python
@dataclass(frozen=True)
class RunToolCall:
    tool: str
    params: Mapping[str, object]
    result: Mapping[str, object]
    status: str
    duration_ms: int


@dataclass(frozen=True)
class RunStep:
    index: int
    id: str
    stage: str
    name: str
    agent_id: str
    capability: str
    risk: RiskLevel
    status: RunStepStatus
    summary: str
    artifact: str | None
    tool_calls: tuple[RunToolCall, ...]
    approval_id: str | None
    duration_ms: int
    error: str | None = None


@dataclass(frozen=True)
class RunAgent:
    id: str
    name: str
    role: str
    risk: RiskLevel
    capabilities: tuple[str, ...]
    step_ids: tuple[str, ...]


@dataclass(frozen=True)
class RunEvent:
    seq: int
    kind: RunEventKind
    at: str
    step_id: str | None
    agent_id: str | None
    gate_id: str | None
    title: str
    detail: str


@dataclass(frozen=True)
class RunGate:
    id: str
    step_id: str
    stage: str
    title: str
    action: str
    risk: RiskLevel
    owner: str
    impact: str
    recommended: Decision | None
    status: ApprovalStatus
    decision: Decision | None
    actor: str | None
    decided_at: str | None


@dataclass(frozen=True)
class RunHandoff:
    event_seq: int
    from_agent_id: str
    to_agent_id: str
    from_step_id: str
    to_step_id: str
    artifact: str
    note: str


@dataclass(frozen=True)
class RunArtifact:
    name: str
    kind: ArtifactKind
    uri: str
    step_id: str
    agent_id: str
    description: str


@dataclass(frozen=True)
class RunMetrics:
    step_count: int
    succeeded_steps: int
    failed_steps: int
    agent_count: int
    handoff_count: int
    gate_count: int
    approved_gates: int
    rejected_gates: int
    artifact_count: int
    compensation_count: int
    reconciliation_count: int
    duration_ms: int


@dataclass(frozen=True)
class AgentRun:
    id: str
    goal: Goal
    plan_id: str
    status: RunStatus
    mode: RunMode
    started_at: str
    finished_at: str
    summary: str
    steps: tuple[RunStep, ...]
    agents: tuple[RunAgent, ...]
    events: tuple[RunEvent, ...]
    gates: tuple[RunGate, ...]
    handoffs: tuple[RunHandoff, ...]
    artifacts: tuple[RunArtifact, ...]
    verification: VerificationResult
    metrics: RunMetrics
```

### 4.2.1 值对象校验

所有值对象在 `__post_init__` 中校验，非法数据直接抛 `ValueError`，与现有 `Artifact`、`Metric`、`DataProvenance` 的做法一致。校验失败视为实现错误，不进入 API/UI；`PlatformConfig` 校验失败则启动失败，服务不带着错误配置运行。

共享辅助函数放在 `domain/runs.py` / `domain/config.py`：

- `_text(value, field)`：必须是字符串，`strip()` 后非空；ID、名称、标题、URI 等使用。
- `_non_negative(value, field)`：必须是 `int` 且 `>= 0`；拒绝 `bool`（`True` 是 `int` 子类）。
- `_mapping(value, field)`：必须是 `Mapping`；键必须是字符串。深层 JSON-safe 由序列化测试保证。
- `_unique(values, field)`：序列内不得有重复项。

| 值对象 | 校验 |
|---|---|
| `RunToolCall` | `tool`、`status` 非空；`params`、`result` 为字符串键 `Mapping`；`duration_ms >= 0` |
| `RunStep` | `index >= 1`；`id`、`stage`、`name`、`agent_id`、`capability`、`summary` 非空；`risk`、`status` 枚举正确；`duration_ms >= 0`；`tool_calls` 为 `RunToolCall` 元组；`artifact`、`approval_id`、`error` 非空或 `None` |
| `RunAgent` | `id`、`name`、`role` 非空；`capabilities` 非空且唯一；`step_ids` 非空且唯一；每个 step ID 非空 |
| `RunEvent` | `seq >= 1`；`at`、`title`、`detail` 非空；`kind` 枚举正确；可选关联字段非空或 `None`；关联规则见 4.3 |
| `RunGate` | `id`、`step_id`、`stage`、`title`、`action`、`owner`、`impact` 非空；`risk`、`status` 枚举正确；`recommended` 为 `Decision` 或 `None`；`approved ↔ decision=approve`、`rejected ↔ decision=reject`、`pending ↔ decision=None`；`pending` 时 `actor`/`decided_at` 均为 `None`，已裁决时均非空 |
| `RunHandoff` | `event_seq >= 1`；`from_agent_id`、`to_agent_id` 非空且不同；`from_step_id`、`to_step_id` 非空且不同；`artifact`、`note` 非空 |
| `RunArtifact` | `name`、`uri`、`step_id`、`agent_id`、`description` 非空；`kind` 枚举正确；本期 `uri` 必须以 `mock://` 开头 |
| `RunMetrics` | 所有计数为 `int >= 0`；`succeeded_steps + failed_steps <= step_count`；`approved_gates + rejected_gates <= gate_count`；`duration_ms >= 0` |
| `Secret` | 值非空；`__repr__` / `__str__` 只返回 `"***"`；仅 `reveal()` 返回原值 |
| `PlatformConfig` | 见 6.6.1：ID/名称非空、能力非空且唯一、限额为正、`mode` 与 `credential_ref` 匹配 |
| `AgentRun` | 聚合不变量见 4.3；值对象通过后再校验聚合 |

`AgentRun` 的聚合校验在构造末尾执行；任何子对象失败先抛出自身字段错误，便于定位。API DTO（如 `RunListItem`）由已验证的聚合派生，不单独接收未校验输入。

### 4.3 不变量

`AgentRun` 在构造时校验，非法数据直接抛 `ValueError`：

- `events` 的 `seq` 从 1 开始严格递增且连续。
- `steps` 的 `index` 从 1 开始连续；每个 `step.agent_id` 必须出现在 `agents` 中。
- `agents` 按首次出现顺序排列；`step_ids` 与步骤顺序一致。
- `handoffs` 只在相邻且 Agent 不同的步骤之间出现；`from_step_id` 与 `to_step_id` 必须相邻。
- 每个 `handoff.event_seq` 必须指向一个 `handoff` 事件，且该事件的 `step_id == to_step_id`、`agent_id == to_agent_id`。
- 每个 `gate.step_id` 必须存在；`approved` ↔ `decision=approve`，`rejected` ↔ `decision=reject`，`pending` ↔ `decision=None`。
- `artifacts` 的每个 `step_id` 必须存在；每个 `step.artifact` 非空时，必须存在且仅存在一个同 `step_id`、同 `name` 的 `RunArtifact`；`metrics` 必须等于从实体计算出的值。
- 每个 `gate.stage` 必须等于其 `step_id` 对应步骤的 `stage`；每个 `step.approval_id` 非空时，必须存在同 `step_id` 的 gate。
- 事件关联必须完整：
  - `agent_started` / `tool_called` / `step_completed`：`step_id` 与 `agent_id` 非空，`gate_id` 为空。
  - `handoff`：`step_id` 为接手的下一步，`agent_id` 为接手的 Agent，`gate_id` 为空；detail 中写明 `{from} → {to} · {artifact}`。
  - `approval_requested` / `approval_decided`：`gate_id` 与 `step_id` 非空，`agent_id` 为空。
  - `run_started`、`verification_passed`、`compensation_triggered`、`rpa_executed`、`reconciliation_found`、`report_generated`、`run_completed`：`step_id` / `agent_id` / `gate_id` 均为空。
- 本期只生成 `status=succeeded` 且全部步骤成功的 run；`failed` 状态的校验语义留给后续切片，本期不实现失败路径。

### 4.4 事件类型与顺序

一次 Demo run 固定 51 个事件：

| 事件 | 数量 | 标题 | 说明 | 必填关联 |
|---|---:|---|---|---|
| `run_started` | 1 | 运行开始 | 目标、10 步计划 | 无 |
| `agent_started` | 10 | Agent 启动 | Agent 名 · 步骤名 | `step_id`、`agent_id` |
| `tool_called` | 10 | 工具调用 | 工具名 · 实测耗时 | `step_id`、`agent_id` |
| `step_completed` | 10 | Agent 完成 | Agent 名 · 产物名 | `step_id`、`agent_id` |
| `handoff` | 8 | Agent 交接 | 上一个 Agent → 下一个 Agent · 产物 | `step_id`=接手步骤、`agent_id`=接手 Agent |
| `approval_requested` | 3 | 审批待决 | 门禁标题 · 风险 · owner | `gate_id`、`step_id` |
| `approval_decided` | 3 | 审批通过 / 审批驳回 | 门禁标题 · 裁决人 | `gate_id`、`step_id` |
| `verification_passed` | 1 | Verifier 通过 | 否决项 · 检查项 | 无 |
| `compensation_triggered` | 1 | 补偿触发 | 拆单库存冲突 · 回滚预占 | 无 |
| `rpa_executed` | 1 | RPA 执行 | 影刀旧版供应商门户 · 截图与审计 | 无 |
| `reconciliation_found` | 1 | 对账差异 | 3 笔差异 → 财务任务 | 无 |
| `report_generated` | 1 | 报告生成 | 指标 / 证据 / trace | 无 |
| `run_completed` | 1 | 运行完成 | 10 步 · 8 Agent · 8 交接 · 2 准 1 驳 | 无 |

`handoff` 事件的 `agent_id` 指向接手方而不是交出方，这样前端高亮和事件流都自然落在“下一步谁来做”。交出方、产物和交接说明放在 `detail`，并通过 `RunHandoff` 的结构化字段提供。

固定顺序：

```text
run_started
→ (agent_started → tool_called → step_completed → [handoff]) × 10
→ (approval_requested → approval_decided) × 3
→ verification_passed
→ compensation_triggered
→ rpa_executed
→ reconciliation_found
→ report_generated
→ run_completed
```

第一幕是 Agent 接力；第二幕是案桌批阅；第三幕是验证、补偿与报告收尾。交接事件只在上一步与下一步的 Agent 不同时产生，因此 10 步产生 8 次交接。

### 4.5 门禁与交接

审批门按 `plan.approval_ids` 顺序排列，与现有剧本人一致：

| 门禁 | 步骤 | 阶段 | 风险 | 剧本裁决 | 裁决人 |
|---|---|---|---|---|---|
| `budget` | `step-5` | paid | L3 | approve | 财务小财 |
| `price` | `step-3` | listing | L2 | reject | 运营小运 |
| `refund` | `step-9` | settlement | L3 | approve | 财务小财 |

交接顺序：

```text
选品 → 内容 → 定价 → 内容 → 投放 → 订单 → 履约 → 结算 → 合规
```

对应 8 条 `RunHandoff`：`selection→content`、`content→pricing`、`pricing→content`、`content→ads`、`ads→order`、`order→fulfillment`、`fulfillment→settlement`、`settlement→compliance`。`fulfillment` Agent 连续执行第 7、8 步，因此这两步之间没有交接。

### 4.6 指标

`RunMetrics` 全部由实体计算：

- `step_count = len(steps)`，`succeeded_steps` / `failed_steps` 按状态计数。
- `agent_count = len(agents)`，本期固定 8。
- `handoff_count = len(handoffs)`，本期固定 8。
- `gate_count / approved_gates / rejected_gates` 按门禁状态计数，本期 3 / 2 / 1。
- `artifact_count = len(artifacts)`，本期 10。
- `compensation_count` 本期固定 1（对应剧本中的拆单库存冲突）。
- `reconciliation_count` 本期固定 3（对应剧本中的 3 笔对账差异）。
- `duration_ms` 为真实执行耗时，使用 `time.perf_counter()` 测量；允许为 0，前端显示 `<1ms`。

## 5. 执行路径

### 5.1 单一执行路径

`DispatchOrchestrator` 新增：

```python
def run_agent(self, goal: Goal) -> AgentRun: ...
def run(self, goal: Goal) -> DemoRunReport: ...  # 由 run_agent 派生
```

`run_agent()` 使用 `RunBuilder` 逐步记录事件、步骤、工具调用、门禁与交接。`run()` 只做转换，不重复执行：

- `DemoRunReport.events`：从 run 事件中筛选旧版事件类型（`agent_started`、`step_completed`、`approval_decided`、`verification_passed`、`compensation_triggered`、`rpa_executed`、`reconciliation_found`、`report_generated`），保持原有 28 个事件、标题、detail 与顺序。
- `DemoRunReport.steps`：由 `RunStep` 映射为 `PlanStep`。
- `DemoRunReport.approvals`：由 `RunGate` 映射为 `ApprovalCase`，顺序按 `plan.approval_ids`。
- `DemoRunReport.verification` 与 `summary`：与 run 同一份数据。

这样 `/demo/run` 的输出与现有测试完全兼容，同时新 run 页拿到更丰富的事件。

### 5.2 工具调用采集

`AgentResult` 增加 `tool_calls: tuple[RunToolCall, ...] = ()`，默认空元组，现有构造与测试不受影响。`RuleBasedAgent.handle` 在调用 `ToolPort` 前后记录：

- `tool`：`AgentSpec.tool`。
- `params`：`{"capability": task.capability}`。
- `result`：工具网关返回的 JSON-safe 字典。
- `status`：`result.get("status", "ok")`。
- `duration_ms`：`perf_counter()` 实测，向下取整毫秒。

`RunBuilder` 把该步骤的全部 `tool_calls` 挂到对应 `RunStep`（本期每步恰好 1 次），并由 `step.artifact` 生成 `RunArtifact`：

- `name`：工具产物文件名，例如 `trend_scan.json`。
- `kind`：`ArtifactKind.json`。
- `uri`：`mock://{name}`。
- `description`：`{agent_name} · {step.name}`。

**脱敏边界**：`RunToolCall.params` / `result` 在写入 run 前经过 `redact_mapping`，键名匹配 `api_key|token|secret|password|authorization|credential`（大小写不敏感）的值替换为 `"***"`，并递归处理嵌套 `Mapping` / `list`。`RunEvent.detail` 只使用工具名、耗时、产物名等非敏感字段，不插值原始参数。Agent 本身不接触凭据；真实场景由 ToolGateway/Adapter 在调用边界解析并注入，run 只记录脱敏后的调用形状。本期 MockToolGateway 不含密钥，脱敏用 sentinel 测试做防御性验证。

### 5.3 真实耗时与演示时长

- `RunStep.duration_ms` 与 `RunMetrics.duration_ms` 是真实执行耗时。
- 播放时长由前端按事件类型累加，不写入后端。
- Run 页面头部同时展示“真实执行 Xms”和“演示回放约 29s（1x）”，明确区分事实与表演。
- 事件 `at` 使用 `ClockPort.now_label()`（`HH:MM`），保留真实时间标签；播放进度使用独立的已播放计时器，不伪造每事件时间。

### 5.4 错误处理（本期）

本期只覆盖确定性成功路径：

- Mock 工具不抛异常；若底层意外抛错，`run_agent()` 让异常上抛，API 返回 500，不生成半成品 run。
- 未知 run ID 返回 404。
- 空白目标不进入本切片：run 始终使用当前已存在的目标；目标创建仍由 `/goals` 校验。
- 重复点击“运行 Agent 团队”会生成多条 run；前端在请求中禁用按钮，后端不做幂等去重。

## 6. 仓储、API 与配置边界

### 6.1 InMemoryRunRepository

新增 `src/opsconductor/dispatch/adapters/run_memory.py`：

- `RLock` + `OrderedDict`，最多保留 20 条 run。
- `save(run)` 写入深拷贝；超过 20 条时淘汰最旧一条。
- `get(run_id)` 返回深拷贝或 `None`。
- `list(limit)` 按最新在前返回深拷贝。
- `latest()` 返回最新一条或 `None`。
- 服务重启即丢；本期不引入 PostgreSQL。

`RunRepository` 协议加入 `domain/ports.py`，与现有 `DispatchRepository` 并列。

### 6.2 Service 方法

`DispatchService` 新增：

```python
def start_run(self) -> AgentRun: ...          # 用当前 goal 执行并保存
def get_run(self, run_id: str) -> AgentRun | None: ...
def latest_run(self) -> AgentRun | None: ...
def list_runs(self, limit: int = 3) -> tuple[AgentRun, ...]: ...
```

`start_run()` 只调用 `orchestrator.run_agent()` 与 `run_repo.save()`，不修改 `DispatchRepository`。`run_demo()` 保持原语义：执行但不保存 run。

### 6.3 Endpoints

| 方法 | 路径 | 返回 | 说明 |
|---|---|---|---|
| POST | `/api/v1/dispatch/runs` | `AgentRun` payload | 用当前 goal 创建并保存一条 run，返回 200 |
| GET | `/api/v1/dispatch/runs/latest` | `AgentRun` payload | 无记录时 404 |
| GET | `/api/v1/dispatch/runs/{run_id}` | `AgentRun` payload | 未知 ID 404 |
| GET | `/api/v1/dispatch/runs?limit=3` | `{"runs": [RunListItem, ...]}` | `limit` 默认 3，范围 1–20 |

**路由顺序**：`/runs/latest` 必须声明在 `/runs/{run_id}` 之前，否则 `latest` 会被当作 `run_id`。FastAPI 按声明顺序匹配，这是实现约束。

### 6.4 Payload 契约

`AgentRun` payload：

```json
{
  "id": "run-6f1c2a9b3d4e",
  "goal": { "...": "同 Goal payload" },
  "plan_id": "plan-demo",
  "status": "succeeded",
  "mode": "demo",
  "started_at": "10:43",
  "finished_at": "10:43",
  "summary": "10 个节点执行完成 · 审批 2 准 1 驳 · Verifier 1 项否决 · 1 次补偿 · 3 笔对账差异",
  "steps": [RunStep],
  "agents": [RunAgent],
  "events": [RunEvent],
  "gates": [RunGate],
  "handoffs": [RunHandoff],
  "artifacts": [RunArtifact],
  "verification": { "passed": true, "checks": ["margin", "inventory", "budget", "compliance", "trace"], "vetoed": ["SKU NW-102 margin 6.8% < 15%"] },
  "metrics": {
    "step_count": 10,
    "succeeded_steps": 10,
    "failed_steps": 0,
    "agent_count": 8,
    "handoff_count": 8,
    "gate_count": 3,
    "approved_gates": 2,
    "rejected_gates": 1,
    "artifact_count": 10,
    "compensation_count": 1,
    "reconciliation_count": 3,
    "duration_ms": 18
  }
}
```

字段级契约：

- `RunStep`：`index, id, stage, name, agent_id, capability, risk, status, summary, artifact, tool_calls, approval_id, duration_ms, error`
- `RunToolCall`：`tool, params, result, status, duration_ms`
- `RunAgent`：`id, name, role, risk, capabilities, step_ids`
- `RunEvent`：`seq, kind, at, step_id, agent_id, gate_id, title, detail`
- `RunGate`：`id, step_id, stage, title, action, risk, owner, impact, recommended, status, decision, actor, decided_at`
- `RunHandoff`：`event_seq, from_agent_id, to_agent_id, from_step_id, to_step_id, artifact, note`
- `RunArtifact`：`name, kind, uri, step_id, agent_id, description`
- `RunMetrics`：见 6.4 示例
- `RunListItem`：`id, status, goal_instruction, started_at, step_count, gate_count, summary`

所有枚举输出 `.value`；元组转数组；`Mapping` 必须 JSON-safe；`None` 保留为 `null`。

### 6.5 错误码

- 未知 run：`404 {"detail": "unknown run: <id>"}`。
- `limit` 越界或非整数：FastAPI 422。
- 运行意外异常：500，不写入仓储。

### 6.6 平台配置与凭据边界

本期只建立安全边界，不接真实平台。配置文件描述“连哪个平台、用哪个 Adapter、限额多少”；密钥只通过 `CredentialProvider` 从环境或密钥管理读取；Agent 不接触配置或密钥。

#### 6.6.1 配置文件

- 新增 `config/platforms.toml`，使用 Python 3.11 标准库 `tomllib` 解析，不新增依赖。
- 配置文件随 Git 版本管理，只包含非密钥字段；密钥值永远不写入该文件。
- 启动时加载并校验；配置非法则进程启动失败，不带着错误配置运行。
- 新增 `config/README.md`，说明字段、环境差异、密钥存放位置与轮换方式。

示例：

```toml
[[platforms]]
adapter_id = "mock-nestwell-us"
platform = "mock"
shop_id = "nestwell-us"
display_name = "NestWell Home US"
mode = "mock"
enabled = true
capabilities = [
  "data.orders", "data.inventory", "data.listings", "data.settlements",
  "data.ads", "data.logistics",
  "control.listing", "control.price", "control.inventory",
  "control.shipment", "control.refund",
]
credential_ref = ""
rate_limit_per_minute = 60
timeout_ms = 5000
max_attempts = 3
backoff_ms = 500

# 本期只校验、不实例化；enabled=true 的 live 配置会启动失败
[[platforms]]
adapter_id = "tiktok-us-live"
platform = "tiktok"
shop_id = "nestwell-us"
display_name = "TikTok Shop US · NestWell"
mode = "live"
enabled = false
capabilities = ["data.orders", "data.inventory", "control.refund"]
credential_ref = "TIKTOK_SHOP_US_TOKEN"
rate_limit_per_minute = 60
timeout_ms = 5000
max_attempts = 3
backoff_ms = 500
```

`PlatformConfig` 值对象在 `domain/config.py` 中校验：

- `adapter_id`、`platform`、`shop_id`、`display_name` 非空。
- `mode` 为 `mock` / `live`；`enabled` 为布尔。
- `capabilities` 非空、唯一，且全部属于 `IntegrationCapability`。
- 同一 `(platform, shop_id)` 不得出现两条配置。
- `mode=mock` 时 `credential_ref` 必须为空；`mode=live` 时 `credential_ref` 必须非空。
- 本期 `mode=live` 且 `enabled=true` 直接拒绝，错误信息明确“live adapters are not implemented”；`enabled=false` 允许保留并校验。
- `rate_limit_per_minute > 0`、`timeout_ms > 0`、`max_attempts >= 1`、`backoff_ms >= 0`。
- 未知字段拒绝；字段名不得出现 `api_key`、`token`、`secret`、`password`，测试扫描配置文件。

`adapters/config_file.py` 负责读取 TOML、检查未知键、构造 `PlatformConfig`；`domain/config.py` 不导入 `tomllib` 或 `os`。`container.py` 只实例化 `enabled=true` 且 `mode=mock` 的 Adapter；`live` 启用直接失败，避免“看起来接入了真实平台”。

#### 6.6.2 凭据解析与存储位置

新增端口：

```python
class CredentialProvider(Protocol):
    def has(self, ref: str) -> bool: ...
    def get(self, ref: str) -> Secret | None: ...
```

- `EnvCredentialProvider` 按 `credential_ref` 的原名读取环境变量；空值视为缺失。
- `Secret` 值对象：`reveal()` 才返回原值；`__repr__` / `__str__` 只输出 `"***"`。
- 只有适配层实现 `CredentialProvider` 并解析凭据；应用层只读取 `credential_status`，不接收 `Secret` 值；Agent 更不接收。
- 本地开发从 `.env`（已在 `.gitignore`）或 OS 环境变量读取；CI 从 GitHub Actions secrets 注入；生产使用 Vault / AWS Secrets Manager / GCP Secret Manager 的 `CredentialProvider` 适配器（后续切片实现）。
- 轮换：改密钥存储中的值即可，`credential_ref` 不变；本期需要重启进程，不做热加载。
- `.env.example` 只列变量名和空值，不填真实密钥。

| 环境 | 密钥存放位置 | 注入方式 | 备注 |
|---|---|---|---|
| 本地开发 | `.env`（gitignored）/ OS 环境变量 | `EnvCredentialProvider` | `.env.example` 只有变量名 |
| CI | GitHub Actions secrets | 环境变量 | 不在日志中 echo |
| 生产 | Vault / AWS Secrets Manager / GCP Secret Manager | 后续 `CredentialProvider` 适配器 | 本期只定义端口 |
| 禁止 | Git、`config/platforms.toml`、Docker 镜像、日志、trace、run 事件、API payload、前端 | — | 测试与代码审查共同拦截 |

#### 6.6.3 Agent 调用链

```text
Agent（AgentSpec.tool）
  → ToolPort.call(tool, params)
  → ToolGateway（真实实现留给 B；A 仍是 MockToolGateway）
  → AdapterRegistry.resolve(capability, PlatformRef)
  → PlatformAdapter（manifest / capabilities / timeout）
  → CredentialProvider.get(credential_ref)   # 只在适配器边界
  → 平台 API
```

- Agent 不读取 `config/platforms.toml`，不读取 `CredentialProvider`，不接触密钥。
- `AgentSpec.tool` 是工具名；工具到能力的映射由 ToolGateway/Adapter manifest 在 B 切片声明。A 的 `MockToolGateway` 仍返回确定性结果，不调用外部 API。
- `config/platforms.toml` 在 A 中驱动 `AdapterRegistry`、集成健康与凭据状态；它不改变 Mock 工具路径的确定性。
- run 中的 `RunToolCall` 只记录脱敏后的工具名、参数形状、结果形状和耗时；`credential_ref` 与密钥值不进入 run。

Agent 需要的调用结构：

| 层 | 结构 | 定义位置 | A 切片状态 |
|---|---|---|---|
| Agent | `AgentSpec.tool`、`capabilities`、`risk` | `application/agents.py` | 已有 |
| 工具网关 | `ToolPort.call(tool, params)`；未来 `ToolManifest`（input schema、timeout、idempotent） | `domain/ports.py`；未来 B | A 用 `MockToolGateway` |
| Adapter | `AdapterManifest`（adapter_id、platform、version、capabilities、default_risk、rate_limit、supports_dry_run、supports_idempotency） | `domain/models.py` | 已有 |
| 平台配置 | `PlatformConfig`（adapter_id、platform、shop_id、mode、enabled、credential_ref、限额） | `domain/config.py` + `config/platforms.toml` | A 新增 |
| 凭据 | `CredentialProvider.get(ref) -> Secret` | `domain/ports.py` + `adapters/credentials.py` | A 新增 |
| 平台 API | OAuth/签名/HTTP | 未来 B | 不实现 |

这张表说明：Agent 只认“工具名 + 能力”，不认 API key；工具网关和 Adapter 决定“调哪个平台、用哪个凭据”。A 切片把配置和凭据端口搭好，但不把 Mock 工具路径改成真实 HTTP。

#### 6.6.4 集成健康与凭据状态

新增：

```python
class CredentialStatus(str, Enum):
    not_required = "not_required"
    configured = "configured"
    missing = "missing"
```

- `IntegrationHealth` 增加 `credential_status: CredentialStatus`。
- Mock Adapter：`not_required`。
- Live Adapter：`CredentialProvider.has(ref)` 为真时 `configured`，否则 `missing`；`missing` 时 `warnings` 追加 `"credential missing"`，健康状态降为 `degraded`，不会伪装成 `connected`。
- `integrations_payload` 只输出 `credential_status`，绝不输出 `credential_ref` 或密钥值。
- 前端集成页显示“凭据：未要求 / 已配置 / 缺失”徽标；缺失用警示色，但不显示任何密钥信息。

#### 6.6.5 本期范围与安全约束

本期实现：

- `config/platforms.toml`、`config/README.md`、`PlatformConfig` 校验、TOML loader。
- `CredentialProvider` 端口、`EnvCredentialProvider`、`Secret`。
- `IntegrationHealth.credential_status` 与前端徽标。
- `redact_mapping` 与 sentinel 测试。
- Mock Adapter 从配置读取 adapter_id、平台、店铺、能力和限额；默认构造仍兼容现有测试。

本期不实现：

- 真实平台调用、OAuth、签名、限流器、重试执行、Webhook。
- 密钥托管后台、Vault/AWS/GCP 适配器、配置编辑 UI、热加载、自动轮换。
- `live` Adapter 实例化；`enabled=true` 的 live 配置启动失败。

安全不变量：

1. 配置文件、Git、Docker 镜像、日志、trace、run 事件、API payload、前端资源中都不出现密钥值。
2. `credential_ref` 只在适配器配置和 `CredentialProvider` 内部使用，不进入 API 或 run。
3. `Secret` 的字符串表示恒为 `"***"`。
4. `redact_mapping` 对嵌套 Mapping/List 递归脱敏，键名大小写不敏感。
5. sentinel 密钥经过 run 构建、序列化、API 响应后必须不存在于任何字段。
6. live 模式 fail closed：没有真实 Adapter 时不允许启动。

## 7. 前端设计

### 7.1 路由与入口

- 新增路由 `/dispatch/runs/:runId`，名称 `run`，`meta.title = "Agent 运行"`，路由级懒加载。
- Overview 的“播放演示”改为“运行 Agent 团队”：
  - 点击调用 `POST /runs`，成功后 `router.push({ name: 'run', params: { runId } })`。
  - 请求中禁用按钮，失败 toast 显示可归因错误。
  - 文案明确“只读回放 · 审批状态未改变”。
- Overview 新增“最近运行”卡片：`GET /runs?limit=3`，显示状态、目标摘要、时间、步骤数与门禁数；空态提示“还没有运行记录”。
- 不新增独立运行列表页；侧栏不改，Run 页作为详情路由。
- 旧 `/demo/run` 前端调用从 Overview 移除；后端端点保留给测试与兼容调用。

### 7.2 页面结构

```text
RunHeader
  ├ 返回今日态势
  ├ 目标 instruction · 状态“已完成” · DEMO 印章
  └ 指标：10 步 / 8 Agent / 8 交接 / 3 门禁（2 准 1 驳）/ 10 产物 / 1 补偿 / 3 笔对账 / 实测 18ms
RunChainStrip（10 个节点 + 8 条交接连接 + 1 条同 Agent 延续，点击定位到步骤）
RunStage
  ├ RunSwimlane（8 行 × 10 步 + 8 条 SVG 交接箭头 + 门禁徽标）
  └ RunEventStream（51 个事件，当前事件高亮，门禁卡片）
RunHandoffLedger（8 行交接账本：谁交给谁、交接什么产物）
RunGovernanceStrip（Verifier → 补偿 → RPA → 对账 → 报告）
RunControls（吸底：播放/暂停 · 上一步/下一步 · 倍速 · 进度 · 完整视图 · 跟随）
RunSummary（完成后显示）
RunStepDrawer（点击步骤块打开，含上游/下游）
```

### 7.3 播放器状态机

新增 `frontend/src/features/runs/useRunPlayer.ts`：

- 输入：`AgentRun`、初始 `speed`（1/2/4）、初始 `autoplay`。
- 状态：`status: 'idle' | 'playing' | 'paused' | 'finished'`、`cursor`（已揭示事件数，0..len(events)）、`speed`、`follow`、`showAll`。
- 派生：
  - `visibleEvents = events.slice(0, cursor)`。
  - `activeEvent = visibleEvents.at(-1)`。
  - `activeStepId` / `activeAgentId` 来自 `activeEvent`。
  - `completedStepIds`：可见事件中出现 `step_completed` 的步骤。
  - `runningStepId`：可见事件中 `agent_started` 已出现、`step_completed` 未出现的步骤。
  - `visibleGateStatus(gateId)`：在 `approval_decided(gate_id)` 出现前返回 `pending`，出现后返回 `gate.status`。
  - `progress = cursor / events.length`。
- 方法：`play()`、`pause()`、`toggle()`、`stepForward()`、`stepBack()`、`seek(index)`、`seekToStep(stepId)`、`seekToEvent(seq)`、`replay()`、`setSpeed(speed)`、`toggleShowAll()`。
- `seekToStep(stepId)`：找到该步骤的 `agent_started` 事件，`cursor` 设为该事件下标 + 1，暂停播放；用于链条节点、交接账本和抽屉上下游跳转。
- `seekToEvent(seq)`：把 `cursor` 设为 `seq`，暂停播放；用于治理链与事件定位。
- 显式 seek（链条、账本、治理链、抽屉上下游）会临时跟随并滚动到目标事件，即使“跟随”开关关闭；`showAll=true` 时先退出完整视图再定位。
- 调度：每个事件用 `setTimeout(duration / speed)`；暂停时清定时器；单步时清定时器并停在目标事件；重播重置 `cursor=0` 并开始播放。
- `showAll=true` 时所有步骤与事件可见，控制条只保留“返回回放”；返回回放重置 `cursor=0`、`status=paused`。
- 键盘：空格播放/暂停，←/→ 单步，R 重播，1/2/4 倍速；焦点在 `input/textarea/select` 或抽屉内时不响应。
- 默认事件时长（毫秒）：

| 事件 | 1x 时长 |
|---|---:|
| `run_started` | 600 |
| `agent_started` | 500 |
| `tool_called` | 450 |
| `step_completed` | 550 |
| `handoff` | 450 |
| `approval_requested` | 900 |
| `approval_decided` | 900 |
| `verification_passed` | 800 |
| `compensation_triggered` | 900 |
| `rpa_executed` | 700 |
| `reconciliation_found` | 700 |
| `report_generated` | 600 |
| `run_completed` | 700 |

合计 29,000ms；1x 约 29 秒，2x 约 14.5 秒，4x 约 7.25 秒。

- `prefers-reduced-motion: reduce`：初始 `autoplay=false`、`cursor=events.length`、不做脉冲与平滑滚动；用户可点“重播”手动观看。
- URL 查询参数：`?speed=1|2|4`、`?autoplay=0|1`，仅作为初始值；控制条修改不写回 URL。E2E 用 `?speed=4` 缩短时长。

### 7.4 泳道

- 桌面 ≥1600px：左侧 60% 泳道，右侧 40% 事件流；1024–1599px 泳道全宽、事件流在下，保证 10 列完整可见。8 行按 `RunAgent` 首次出现顺序排列；10 列按步骤顺序排列。
- 步骤块内容：步骤名、阶段名、状态文字、产物 chip、门禁徽标（L2/L3 + 待批/准/驳）。
- 状态派生：
  - `pending`：未出现 `agent_started`；虚线幽灵。
  - `running`：`agent_started` 已出现、`step_completed` 未出现；朱砂描边 + 鎏金脉冲。
  - `succeeded`：`step_completed` 已出现；墨色实心/浅底。
  - 门禁：`approval_requested` 出现前不显示徽标；之后显示“待批”；`approval_decided` 后显示“准/驳”。
- 交接箭头：一层 SVG 覆盖泳道，固定列宽/行高计算坐标，不逐帧测量 DOM；已完成为墨色，当前为朱砂，未来为虚线 `--line`。箭头旁不常驻文字，悬停/当前事件时显示 `{from} → {to} · {artifact}`。
- 点击步骤块：仅已完成或进行中的步骤可点；未来步骤不可点，避免剧透；`showAll` 时全部可点。
- 移动端 ≤767px：泳道降级为纵向“Agent 接力”列表，每个步骤卡带 Agent 徽标、交接连线和门禁徽标；无横向滚动。

#### 7.4.1 接力链条（RunChainStrip）

- 位于 RunHeader 与 RunStage 之间，高约 56px，作为“执行链总览”和“进度导航”，不重复事件流细节。
- 10 个节点按步骤顺序排列，节点内容：步骤序号、Agent 短名、状态点、门禁徽标；相邻连接共 9 条：8 条跨 Agent 交接连接（按 `RunHandoff` 绘制，带产物标签）+ 1 条同 Agent 延续连接（履约 Agent 第 7→8 步，细实线，无产物标签）。
- 节点状态：未来幽灵、当前脉冲、已完成实心；门禁在 `approval_requested` 前不显示，之后显示“待批/准/驳”。
- 交接连接状态：`handoff` 事件未出现为未来虚线；当前 `handoff` 事件为朱砂；`handoff` 已过或接手步骤已开始为墨色。延续连接随第 8 步状态变化，不单独产生事件。
- 延续连接由相邻步骤的 `agent_id` 相同派生，不进入 `RunHandoff`，也不产生 `handoff` 事件；它只用于让链条视觉连续。
- 点击节点调用 `player.seekToStep(stepId)`，暂停并定位到该步骤的 `agent_started`；当前节点与事件流同步高亮。
- 连接悬停/当前事件时显示 `{from} → {to} · {artifact}`，不常驻文字。
- 响应式：≥1024px 全宽展示；768–1023px 在自身容器内横向滚动（页面不横向溢出）；≤767px 折叠为单行“第 N/10 步 · Agent · 下一步”，两侧提供上一步/下一步按钮，完整链条由纵向接力列表承载。

#### 7.4.2 交接账本（RunHandoffLedger）

- 泳道下方一张 8 行表，作为 SVG 箭头的文字版和无障碍替代。
- 列：序号、`from Agent → to Agent`、交接产物、`from step → to step`、说明。
- 点击行调用 `player.seekToEvent(handoff.event_seq)`，同时高亮泳道连接；行内提供“查看下一步”按钮打开接手步骤抽屉。
- 空态不应出现：本期固定 8 条；若未来交接为 0，显示“本次没有 Agent 交接”。

#### 7.4.3 治理链（RunGovernanceStrip）

- 位于交接账本下方，5 个状态 chip：Verifier、补偿、RPA、对账、报告。
- 状态由尾部事件派生：未出现为幽灵，当前事件为活跃，已出现为完成；点击 chip 调用 `player.seekToEvent(seq)`。
- 让观众看到“Agent 跑完之后，系统还做了什么”，与第一幕的接力链形成闭环。

### 7.5 事件流

- 51 个事件按 `seq` 渲染；当前事件高亮，已过事件正常墨色，未来事件不渲染（除非 `showAll`）。
- 事件行：图标（按 kind）、`at`、`#seq`、标题、detail、Agent 徽标；`tool_called` 行显示耗时，`step_completed` 行显示产物 chip。`#seq` 表示事件顺序，不伪造每事件时间。
- 门禁事件渲染为大卡片：风险徽标、标题、owner、impact、建议裁决；`approval_decided` 后加“准/驳”印章与裁决人。
- 自动滚动：`watch(activeEvent.seq)`，`follow=true` 时滚到当前事件（`block: 'nearest'`，非 reduced-motion 用 `smooth`）；用户可关闭“跟随”。
- 不使用整块 `aria-live`；另外提供一个视觉隐藏的 `role=status aria-live=polite` 行，播报“第 N 步，某 Agent，某动作”。

### 7.6 步骤抽屉

复用 `ExceptionDrawer` 的交互模式：`Teleport` 到 body、`role=dialog`、`aria-modal=true`、ESC 关闭、背景锁定、打开时焦点移到关闭按钮。

内容：

1. 步骤头：序号、阶段、步骤名、状态、风险。
2. Agent：名称、职责、能力列表、为什么被选中（`capability` 匹配）。
3. 工具调用：工具名、参数、返回、实测耗时。
4. 产物：名称、类型、`mock://` URI、描述。
5. 门禁（如有）：标题、action、风险、owner、impact、建议裁决、实际裁决、裁决人。
6. 摘要：`RunStep.summary`。
7. 上下游：上一步的 Agent/产物（第一步显示“起点”），下一步的 Agent（最后一步显示“终点”）；提供“定位上一步/下一步”按钮，调用 `seekToStep`，让观众沿链条前后走。

工具参数与返回用等宽字体展示 JSON，长内容可滚动，不截断关键字段；如含脱敏字段，显示 `"***"` 并在旁边标注“已脱敏”。

### 7.7 控制条

- 按钮：播放/暂停、上一步、下一步、重播、倍速（1x/2x/4x）、完整视图、跟随开关。
- 进度：`cursor / events.length`，显示已播放时间与总时长（按当前倍速估算）。
- 吸底在移动端；桌面固定在 RunStage 底部。
- 所有按钮有 `aria-label`；进度条 `role=progressbar`、`aria-valuemin=0`、`aria-valuemax=events.length`、`aria-valuenow=cursor`。
- 键盘快捷键与 7.3 一致；显示一个“快捷键”提示（可用 `<details>`）。

### 7.8 响应式

| 断点 | 布局 |
|---|---|
| ≥1600px | 泳道 60% + 事件流 40%，控制条在内容底部 |
| 1024–1599px | 泳道全宽，事件流移到下方；10 列完整可见 |
| 768–1023px | 泳道纵向化，事件流在下；抽屉为右侧全高 |
| ≤767px | 纵向接力列表 + 事件流；控制条吸底；抽屉为底部弹层；375px 无横向溢出 |

接力链条在各断点的行为见 7.4.1；交接账本在 ≤767px 变为折叠列表，默认只显示“from → to · 产物”，展开后显示完整说明。

### 7.9 视觉

- 沿用纸白/墨/朱砂/靛青/鎏金；不给 8 个 Agent 配 8 种独立色。
- Agent 行背景在 `--paper-deep`、`--indigo-soft`、`--gold-soft` 间交替分组；活跃步骤用 `--red` 描边 + `--gold` 光晕。
- 完成步骤用墨色文字 + 浅底；未来步骤用 `--line` 虚线 + `--ink-mute` 文字。
- 状态同时有文字标签（待执行/进行中/已完成/待批/已准/已驳），不只靠颜色。
- 过渡 200ms；脉冲 1.6s；`prefers-reduced-motion` 时全部关闭。

### 7.10 性能

- 路由级懒加载，不把 Run 页打进 Overview chunk。
- 不引入图表/动画/虚拟列表依赖；51 个事件直接渲染。
- 泳道 SVG 只在挂载与 resize 时重算；播放不触发布局测量。
- 自动滚动只滚当前事件，不滚整个列表。
- 预算：Run API payload < 150KB；Run 路由 chunk < 80KB gzip；本地首屏可交互 < 2s；播放更新不产生 > 50ms 长任务。
- 构建时以 `npm run build` 输出为准；若超出预算，先拆组件，不引入新依赖。

### 7.11 可访问性

- 控制条、步骤块、门禁卡片均为可聚焦按钮/链接，焦点样式可见。
- 状态播报用独立 `role=status aria-live=polite`，不重复播报整个事件流。
- 抽屉焦点管理、ESC 关闭、`aria-modal`、关闭按钮自动聚焦。
- `prefers-reduced-motion` 关闭自动播放、脉冲和平滑滚动。
- E2E 覆盖键盘播放/暂停/单步、抽屉 ESC、375px 无横向滚动。

### 7.12 离线与错误状态

- `GET /runs/{id}` 404：整页空态“这条运行记录不存在或已被重置”，提供“返回今日态势”。
- 网络错误：整页错误态 + 重试按钮；不使用 fixture 伪装成功。
- Overview“最近运行”查询失败：显示一行“运行记录暂不可用”，不阻塞今日态势。
- `runFixture` 仅用于单元测试与组件测试，**不得**作为生产离线 fallback。

### 7.13 平台集成页的凭据状态

- `IntegrationPlatformSchema` 增加 `credential_status: 'not_required' | 'configured' | 'missing'`。
- 集成页在平台名称旁显示徽标：“凭据：未要求 / 已配置 / 缺失”；缺失使用警示色，但不显示任何密钥信息。
- 不展示 `credential_ref`、密钥值、密钥指纹或环境变量名。
- Mock 平台恒为 `not_required`；live 平台由 `CredentialProvider.has(ref)` 计算 `configured` / `missing`。
- 增加组件测试：三种状态渲染正确；payload 中不存在 `credential_ref` 和 sentinel 密钥。

## 8. 契约与 Fixture

- 后端 `adapters/serialize.py` 新增 `run_payload`、`run_list_payload`、`run_list_item_payload`，字段与 6.4 逐字一致。
- 前端 `api/schemas.ts` 新增 `RunSchema`、`RunStepSchema`、`RunAgentSchema`、`RunEventSchema`、`RunGateSchema`、`RunHandoffSchema`、`RunArtifactSchema`、`RunToolCallSchema`、`RunMetricsSchema`、`RunListItemSchema`、`RunListSchema`；`api/types.ts` 导出推断类型。`RunStep.tool_calls` 为数组，`RunGate` 含 `stage`，`RunMetrics` 含 `reconciliation_count`。
- `IntegrationPlatformSchema` 增加 `credential_status`；`integrations_payload` 同步输出，`scripts/export_dispatch_fixtures.py` 重新生成 fixture 时自动带上。
- `api/dispatch.ts` 新增 `startRun()`、`getRun(id)`、`getLatestRun()`、`listRuns(limit)`。
- 测试 fixture 放 `frontend/src/tests/fixtures/run.ts`，由 `RunSchema.parse` 校验；以后端一次真实序列化结果为基准。
- 后端契约测试断言每个 payload 的 key 集合；前端 Zod 测试断言 fixture 可解析、缺字段失败。两侧共同保证不漂移。
- `config/platforms.toml` 的契约由 `PlatformConfig` 与 loader 测试保证：未知字段拒绝、无密钥字段、mock/live 规则明确；`.env.example` 只列变量名和空值。
- `RunToolCall` 的 `params`/`result` 在序列化前必须经过 `redact_mapping`；前端收到的 payload 中不允许出现 sentinel 密钥。

## 9. 测试策略

| 层 | 文件 | 关键用例 |
|---|---|---|
| 值对象校验 | `tests/dispatch/test_runs.py` | 空文本、负数、重复键、门禁状态不一致、事件缺关联、step/artifact/gate 交叉引用；每个非法输入抛 `ValueError` |
| 领域不变量 | `tests/dispatch/test_runs.py` | `seq` 连续、步骤索引连续、Agent 引用存在、交接相邻、门禁状态一致、metrics 与实体一致 |
| 分层 | `tests/dispatch/test_layering.py` | domain 不导入 application/adapters/FastAPI/SQLAlchemy；application 不导入 adapters |
| 配置 | `tests/dispatch/test_platform_config.py` | mock 配置加载；重复 platform+shop；live 缺 ref；mock 带 ref；live enabled 拒绝；未知字段；非法能力；非正限额；无密钥字段 |
| 凭据 | `tests/dispatch/test_credentials.py` | `has/get`、空值视为缺失、`Secret.__repr__` 为 `***`、集成健康 `configured`/`missing` |
| 脱敏 | `tests/dispatch/test_redaction.py` | 嵌套 Mapping/List、大小写不敏感、sentinel 密钥不出现在 run payload/事件/日志 |
| Run 构建 | `tests/dispatch/test_run_builder.py` | 51 个事件；10 步各 1 次工具调用；8 次交接顺序正确且 `event_seq` 指向对应 handoff 事件；3 门禁 2 准 1 驳；两次运行内容确定一致 |
| 兼容性 | `tests/dispatch/test_orchestrator.py`（现有） | `run()` 仍返回 28 个事件、10 步、3 审批、2 准 1 驳、Verifier 否决项；现有断言全绿 |
| 仓储 | `tests/dispatch/test_run_repository.py` | 深拷贝隔离、最新在前、limit、20 条淘汰、未知 ID 返回 `None` |
| API | `tests/dispatch/test_run_api.py` | `POST/GET/latest/list`、未知 404、limit 422、创建 run 前后 snapshot 审批不变 |
| 序列化 | `tests/dispatch/test_api_smoke.py` 或新文件 | payload key 集合、枚举字符串、JSON-safe、`latest` 路由不被 `{run_id}` 吞掉、`credential_status` |
| 前端契约 | `frontend/src/tests/unit/schemas.spec.ts` | `RunSchema` 解析 fixture、缺字段失败、`credential_status` 枚举 |
| 前端分层 | `frontend/src/tests/unit/layering.spec.ts` | `features/**` 不导入 `api/client`、不裸调 `fetch` |
| 播放器 | `frontend/src/tests/unit/use-run-player.spec.ts` | fake timers 下播放/暂停/单步/后退/倍速/重播/seek/seekToStep/showAll；门禁裁决前后状态；reduced motion 初始完成 |
| 执行链组件 | `RunChainStrip/RunHandoffLedger/RunGovernanceStrip` 单测 | 10 节点、8 条交接连接 + 1 条延续、8 行账本、5 个治理 chip、点击 seek、上下游按钮 |
| 组件 | `RunSwimlane/RunEventStream/RunControls/RunStepDrawer` 单测 | 8 行 10 列、8 条箭头、状态文字、门禁卡片、键盘、抽屉 ESC |
| 集成页 | `IntegrationStatus` 单测 | `credential_status` 三态渲染，不出现密钥/ref |
| E2E | `frontend/e2e/run.spec.ts` | Overview 一键运行 → 自动回放 → 摘要；暂停/单步/重播；链条/账本定位；点击步骤开抽屉；未知 ID 空态；375px 无横向溢出 |

确定性要求：

- Run 内容不依赖墙钟；事件顺序、标题、步骤、门禁可精确断言。
- 真实耗时只断言 `>= 0`，不比较具体毫秒。
- 播放器测试用 Vitest fake timers，不使用真实等待。
- E2E 使用 `?speed=4` 缩短回放；等待摘要出现，不依赖固定 sleep。

## 10. 验收标准

1. Overview 点击“运行 Agent 团队”创建真实 run，并跳转 `/dispatch/runs/{id}`。
2. Run 页展示 10 步、8 Agent、8 交接、3 门禁、2 准 1 驳、1 次补偿、3 笔对账差异，全部来自后端 payload。
3. 播放/暂停/单步/后退/倍速/重播/完整视图可用；1x 约 29 秒，4x 小于 10 秒。
4. 点击任意已完成/进行中步骤，抽屉展示 Agent、能力匹配原因、工具参数/返回、产物、门禁、真实耗时。
5. 门禁在 `approval_decided` 事件出现前显示“待批”，出现后翻“准/驳”。
6. 创建 run 前后 `snapshot.approvals` 完全一致；`snapshot.agents` 与 `snapshot.chain` 也不变。
7. 原 `/api/v1/dispatch/demo/run` 响应与现有测试完全兼容。
8. 375px 无横向溢出；`prefers-reduced-motion` 下不自动播放、不做脉冲。
9. `pytest tests/dispatch`（预计 110+）、`ruff check .`、`mypy src`、`npm run typecheck`、`npm run test:unit`、`npm run build`、`run.spec.ts` E2E 全部通过。
10. CI 补上 PostgreSQL service，全量后端 pytest 可运行；新增前端 job 跑 typecheck + unit + build。
    - 后端 service 使用 `pgvector/pgvector:pg16`，环境变量 `POSTGRES_USER=ops`、`POSTGRES_PASSWORD=ops`、`POSTGRES_DB=opsconductor_test`，端口映射 `15432:5432`，并配置 `pg_isready` healthcheck。
    - 前端 job 使用 Node 20，在 `frontend/` 下执行 `npm ci`、`npm run typecheck`、`npm run test:unit`、`npm run build`；Playwright E2E 仍作为本地门禁，不进入本期 CI。
11. 每个值对象的非法输入都有失败测试，构造时抛 `ValueError`；`test_runs.py` 覆盖空文本、负数、重复键、门禁状态不一致、事件缺关联和交叉引用。
12. 执行链可独立讲清：`RunChainStrip` 渲染 10 个节点、8 条交接连接 + 1 条同 Agent 延续；点击节点 `seekToStep`；`RunHandoffLedger` 渲染 8 行；抽屉含上游/下游；观众无需事件流即可复述链路。
13. `config/platforms.toml` 可加载 mock 配置；重复 `(platform, shop)`、live 缺 `credential_ref`、mock 带 ref、未知字段、非法能力、非正限额均被拒绝；`live + enabled=true` 启动失败。
14. 凭据安全：`credential_status` 仅有 `not_required/configured/missing` 三态；`Secret` 的 `repr` 为 `***`；sentinel 密钥不出现在 run payload、事件、日志或前端；集成页不显示 ref 或值。
15. 分层测试通过：domain 不导入 application/adapters/FastAPI/SQLAlchemy；application 不导入 adapters；前端 `features` 不直接调用 `fetch` 或 `api/client`。

## 11. 风险与对策

| 风险 | 对策 |
|---|---|
| 事件太细，播放拖沓 | 51 个事件、1x 约 29 秒；支持 2x/4x、单步、后退、完整视图 |
| 泳道箭头在缩放时错位 | 固定列宽/行高计算 SVG 坐标，resize 重算；移动端降级纵向列表 |
| 页面像“假动画” | 展示实测耗时、真实工具参数/返回、产物 URI、`DEMO` 印章；数据全部来自后端 |
| 重构编排器破坏旧 Demo | 先补兼容性测试；`run()` 由 `run_agent()` 派生并筛选旧事件，保持 28 个事件不变 |
| fixture 与后端漂移 | 后端 key-set 测试 + 前端 Zod 解析测试；契约变更时同步 fixture |
| 组件过多拖慢交付 | 按职责拆分的聚焦组件 + 1 个 composable，复用现有 `StatusDot`、`RiskBadge`、`ArtifactChip`、`ProgressBar` |
| 观众误以为审批已真实执行 | 页面常驻“DEMO · 只读回放 · 审批状态未改变”；审批门显示“剧本裁决”标签 |
| 移动端泳道溢出 | 767px 以下完全降级为纵向列表，不用横向滚动承载核心信息 |
| 值对象校验遗漏 | 每个约束先写失败测试；用表驱动覆盖空值、负数、重复、枚举不一致、交叉引用缺失 |
| 分层侵蚀 | `test_layering.py` 用 AST 扫描 import；前端 `layering.spec.ts` 禁止 features 直接 fetch |
| 密钥泄露到日志/run/API | 配置无密钥字段；`Secret` 隐藏 repr；`redact_mapping` 递归脱敏；sentinel 测试扫描 run payload/事件/日志；`.env` 已 gitignore |
| live 配置被误启用 | `live + enabled=true` fail closed；没有真实 Adapter 时启动失败；集成页只显示凭据状态 |
| 执行链信息过载 | 链条只做总览与导航，细节留给泳道/账本/事件流；移动端折叠为单行，避免第二套矩阵 |
| 配置与代码漂移 | `config/README.md` 说明字段；loader 拒绝未知字段；配置测试覆盖每条规则 |

## 12. 实施顺序（设计级）

0. **TDD 地基**：先写 `test_layering.py` / `layering.spec.ts`、固定 run ID 与 `ClockPort` 测试夹具；确认现有测试可重复。
1. **值对象与聚合**：先写 `test_runs.py` 的非法输入用例，再实现 `domain/runs.py` 的 `__post_init__` 与 `AgentRun` 聚合不变量。
2. **配置与凭据边界**：先写 `test_platform_config.py`、`test_credentials.py`、`test_redaction.py`，再实现 `domain/config.py`、`PlatformConfig` loader、`EnvCredentialProvider`、`redact_mapping` 与 `credential_status`。
3. **Run 构建与兼容**：先写 `test_run_builder.py` 的事件/交接/门禁/确定性用例，再实现 `run_builder.py`、重构 `orchestrator.py`，补 `AgentResult.tool_calls`；最后跑现有兼容性测试。
4. **仓储/API/序列化**：先写 `test_run_repository.py`、`test_run_api.py`，再实现 `run_memory.py`、`service.py`、`serialize.py`、`api.py`、`container.py`。
5. **前端契约与播放器**：先写 `schemas.spec.ts`、`use-run-player.spec.ts`，再实现 Zod、`dispatch.ts`、`useRunPlayer.ts`、测试 fixture。
6. **执行链与页面**：先写 `RunChainStrip`、`RunHandoffLedger`、`RunGovernanceStrip`、`RunSwimlane`、`RunEventStream`、`RunControls`、`RunStepDrawer`、`RunSummary` 单测，再实现组件；接 `RunView`、路由、Overview 入口/最近运行卡片、集成页凭据徽标。
7. **收尾**：E2E、CI PostgreSQL service 与前端 job、`config/README.md`、README/调度台 README 更新；截图与 HR Deck 更新不作为本期验收项。

每一阶段都保持 `pytest tests/dispatch`、`ruff`、`mypy`、`typecheck`、`unit` 绿；不把大改一次性堆到最后。每个任务必须先提交失败测试，再提交实现；不允许先写实现后补测试。

## 13. 后续切片

- **B：多 Agent 调度控制面**——Agent Registry 心跳/负载/队列、并发上限、超时重试、handoff 协议、预算/token 护栏、Fleet 控制页、审批暂停/恢复；接入真实 `CredentialProvider`（Vault/AWS/GCP）、live Adapter、OAuth/签名/限流执行。
- **C：场景扩展包**——把本切片的 Run 模型作为证据载体，新增广告烧穿、超卖、扣关、拒付、差评、标错价等场景。
- **D：前端指挥中心**——Overview → Runs → Agents → Stages 的完整信息架构、增量更新与性能预算。
- **E：质量体系**——场景 golden task、replay 一致性、故障注入、并发压测、visual/a11y、CI 全量门禁。

## 14. 关联文档

- [跨境电商台前调度 Demo](../../design/cross-border-dispatch/README.md)
- [台前调度导航、阶段工作台与平台集成扩展设计](2026-11-12-dispatch-console-enhancement-design.md)
- [台前调度台 v1.2 实施计划](../plans/2026-11-12-dispatch-console-v1.2.md)
- [电商运营 Agent 统筹架构](2026-11-11-agent-orchestration-design.md)
- [Agent 归因、持久化、Skill/SOP 与数据飞轮设计](2026-11-11-agent-attribution-persistence-flywheel-design.md)
- [跨境电商运营异常处理指南](../operations/2026-11-10-cross-border-ecommerce-operations-exception-guide.md)
- [项目文档索引](../README.md)
