# 跨境电商 · 统一台前调度（Vue 3）

方案一「朱墨案牍 · 批阅台」的正式实现已迁移到 Vue 3 + TypeScript。保留纸白 / 墨 / 朱砂 / 靛青 / 鎏金配色、宋体标题 + 仿宋正文 + 楷体批注，以及审批批阅模式；页面结构升级为「场景目录 + 今日态势 + 阶段工作台」。

本目录中的 [index.html](index.html) 是旧单文件原型，仅作视觉对照与回归参考，不再是 `/dispatch` 的默认入口。

## 运行

```bash
# 仓库根目录
bash scripts/build_frontend.sh          # 首次或前端改动后
PORT=8010 bash scripts/demo_dispatch.sh
# http://127.0.0.1:8010/dispatch
```

`frontend/dist` 缺失时 FastAPI 返回 503 并提示构建命令，不会静默回退旧页面。临时对照旧原型：

```bash
# /dispatch/legacy 或
OPSCONDUCTOR_DISPATCH_UI=legacy PORT=8010 bash scripts/demo_dispatch.sh
```

前端开发：

```bash
cd frontend && npm run dev   # http://127.0.0.1:5173/dispatch
```

## 页面

- **场景目录**：10 个运营阶段 + 控制塔，按电商顺序分组；每组 4–5 个子流程，支持折叠、状态点、待批/异常计数、URL 深链。
- **今日态势**：审批进度、十段链路矩阵、8 个 Agent 状态、P0–P3 异常分布、平台集成健康。
- **经营可视化**：近 7 日销售额、Agent 使用量/成功率、阶段结果交付；点击 Agent 柱筛选，点击阶段柱进入工作台。
- **阶段工作台**：流程步骤、Agent 产出（摘要/产物/指标/证据/来源）、本阶段审批/异常/上下文。
- **审批案 / 异常簿 / 平台集成**：批阅、playbook 抽屉、capability 清单与 freshness。
- **移动端**：375 抽屉目录，页面无横向滚动。

## 可操作内容

- 「生成调度计划」调用 `POST /api/v1/dispatch/goals`。
- 「准 / 驳 / 重置」调用审批端点，刷新页面仍保留状态。
- 「播放演示」调用 `POST /api/v1/dispatch/demo/run`，是**只读投影**：真实执行 Agent 编排并返回事件，但不改变当前审批状态。
- 异常抽屉读取 snapshot 中的完整 playbook；阶段详情读取 `GET /api/v1/dispatch/stages/{id}`。
- 平台集成页读取 `GET /api/v1/dispatch/integrations`，本期只有 `MockPlatformAdapter`。

## 测试

```bash
pytest tests/dispatch tests/test_health.py -q
ruff check src/opsconductor/dispatch src/opsconductor/api tests/dispatch
python -s -m mypy src
cd frontend && npm run typecheck && npm run test:unit && npm run build
E2E_BASE_URL=http://127.0.0.1:8010 npm run test:e2e
```

## 后端分层

| 层 | 目录 | 职责 |
|---|---|---|
| 领域层 | `src/opsconductor/dispatch/domain/` | 实体、值对象、风险/优先级策略、阶段结果、canonical model、仓储/Agent/平台端口 |
| 应用层 | `src/opsconductor/dispatch/application/` | 8 个 Agent、注册表、Verifier、Orchestrator、阶段目录、AdapterRegistry、ControlService、`DispatchService` |
| 适配层 | `src/opsconductor/dispatch/adapters/` | 内存仓储、Mock 工具、MockPlatformAdapter、JSON 序列化、FastAPI 路由、Vue/legacy 静态页、依赖组装 |

设计模式：端口-适配器、仓储、策略、工厂、状态机、门面、observer 式 trace、依赖注入、Adapter Registry。审批重复裁决返回 409，未知阶段/审批/异常返回 404，所有写操作追加 trace。

## 数据边界

- 经营图表标注 `MOCK`：销售额、Agent 调用量与成功率为确定性演示数据，不接真实 BI/广告/销售系统。
- 阶段结果交付直接从 `STAGE_RESULTS` 聚合，与阶段工作台同源。

## 平台边界

- 本期只实现 `MockPlatformAdapter`；真实平台凭据、OAuth、生产 API 均未接入。
- 页面动作由 `IntegrationCapability` 驱动，不按平台名写分支。
- `POST /sync-runs` 与 `POST /control/commands` 已预留、未实现；不在本期返回假成功。

## 文档

- [v1.2 设计规格](../../docs/specs/2026-11-12-dispatch-console-enhancement-design.md)
- [v1.2 实施计划](../../docs/plans/2026-11-12-dispatch-console-v1.2.md)
- [前端说明](../../frontend/README.md)
