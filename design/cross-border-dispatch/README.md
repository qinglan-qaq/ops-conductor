# 跨境电商 · 统一台前调度

方案一「朱墨案牍 · 批阅台」的高保真交互原型。保留纸白 / 墨 / 朱砂 / 靛青配色、宋体标题 + 仿宋正文 + 楷体批注，以及审批批阅模式；在此之上加入现代工作流步进、实时命令栏、可点击十段链路、Agent 调度表、异常 playbook 抽屉与 trace 回放。

## 打开

直接用浏览器打开 [index.html](index.html)。页面不依赖构建链、外链字体或图片，所有样式、SVG 与脚本都在单文件内。`file://` 打开时顶部显示「静态预览」，保留本地 Mock 交互。

## 运行前后端 Demo

仓库新增了独立的 `opsconductor.dispatch` 六边形切片，使用内存仓储与 Mock 工具，不需要 PostgreSQL、Redis 或外部平台 API：

```bash
# 仓库根目录：脚本自动解析 conda 环境并调用该环境的 Python
bash scripts/demo_dispatch.sh
# 若 8000 被占用：
PORT=8010 bash scripts/demo_dispatch.sh
# 浏览器打开
# http://127.0.0.1:8000/dispatch
```

也可以显式使用 conda 环境启动，不依赖全局 `uvicorn` 命令：

```bash
conda activate opsconductor
python -m opsconductor.api.serve --host 127.0.0.1 --port 8010 --reload
```

`python -m opsconductor.api.serve` 是仓库提供的 conda 原生入口，底层仍然由
`opsconductor` 环境内的 Uvicorn 提供 ASGI 服务。

### conda 环境与 uvicorn 的区别

**Uvicorn 不是环境，而是 ASGI 服务器库。** conda 负责“用哪套 Python 和依赖”，
uvicorn 负责“把 FastAPI app 跑成 HTTP 服务”。本仓库没有单独的 uvicorn 环境，
只有 `opsconductor` conda 环境，uvicorn 是该环境里的一个依赖。

| 维度 | conda 环境 | uvicorn |
|---|---|---|
| 是什么 | Python 解释器 + 依赖隔离 + 包管理 | ASGI 服务器库/命令 |
| 解决什么 | 依赖版本、隔离、可复现 | HTTP 监听、请求转发、热重载、workers |
| 能否互相替代 | 不能替代服务器 | 不能替代环境隔离 |
| 本项目 | `opsconductor` 环境 | 安装在该环境内 |
| 启动方式 | `conda activate opsconductor` | `python -m opsconductor.api.serve`（内部调用 uvicorn） |
| 优势 | 避免全局污染、可复现、二进制依赖安装方便 | ASGI 标准、开发热重载、性能与部署生态成熟 |

因此推荐用 **conda 环境 + `python -m opsconductor.api.serve`**：环境边界清楚，
命令里不出现全局 `uvicorn`；需要换 ASGI 服务器时再替换 `serve.py` 内部实现。
Windows Git Bash 下 `conda run` 可能缓冲输出或错误解析参数，优先使用
`conda activate` 或仓库脚本。

页面顶部出现「后端已连接」后：

- 「生成调度计划」调用 `POST /api/v1/dispatch/goals`
- 「准 / 驳 / 重置」调用审批端点，刷新页面仍保留状态
- 「播放调度演示」调用 `POST /api/v1/dispatch/demo/run`，使用后端 Agent 编排返回的事件
- 异常抽屉调用 `GET /api/v1/dispatch/exceptions/{id}`
- 所有状态由 `GET /api/v1/dispatch/snapshot` 一次性回填

「播放调度演示」是只读投影：后端真实执行 Agent 编排并返回事件，但不改变当前审批状态；审批状态请通过「准 / 驳」变更。

无数据库冒烟测试：

```bash
pytest tests/dispatch -q
```

后端分层：

| 层 | 目录 | 职责 |
|---|---|---|
| 领域层 | `src/opsconductor/dispatch/domain/` | 实体、值对象、风险/优先级策略、仓储与 Agent 端口 |
| 应用层 | `src/opsconductor/dispatch/application/` | 8 个 Agent、注册表、Verifier、Orchestrator、Demo 种子、`DispatchService` 门面 |
| 适配层 | `src/opsconductor/dispatch/adapters/` | 内存仓储、Mock 工具、JSON 序列化、FastAPI 路由、静态页面、依赖组装 |

设计模式：端口-适配器、仓储、策略、工厂、状态机、门面、观察者式 trace、依赖注入。审批重复裁决返回 409，未知异常/审批返回 404，所有写操作追加 trace。

## 可操作内容

- **生成调度计划**：修改顶部「令」输入框，按 Enter 或点击按钮，查看计划生成反馈。
- **播放调度演示**：右侧按钮按「目标接入 → 计划生成 → 审批 → 执行 → 验证 → 报告」逐步演示，并联动高亮对应面板。
- **十段链路**：点击任一环节，查看核心动作、典型失败、AI 可增强点、主责与指标。
- **审批案**：对 L2/L3 事项点击「准 / 驳」，计数、朱印与 trace 会同步变化；「重置」可恢复 3 件待批。
- **异常簿**：点击任一异常，打开该场景的 playbook 抽屉，含 0–30 分钟、1–4 小时、24–72 小时处置与 Agent 自动化。
- **深链接**：`?demo=1` 自动播放调度演示；`?drawer=ORD-01` 直接打开超时未发货的 playbook。

## 数据与依据

页面数字全部来自仓库现有文档与 Mock 演示剧本，不宣称真实经营数据：

- [SPEC.md](../../SPEC.md) §6 主链路、§7 四闭环、§9 Agent
- [跨境电商运营异常处理指南](../../docs/operations/2026-11-10-cross-border-ecommerce-operations-exception-guide.md) §1 全景流程、§4 定级、§5 异常目录、§6 playbook
- [跨境电商全流程模拟演示系统需求规格](../../docs/specs/2026-11-10-cross-border-simulation-design.md) §2 NestWell 剧本、§10 审批/幂等/补偿、§11 控制台
- [电商运营 Agent 统筹架构](../../docs/specs/2026-11-11-agent-orchestration-design.md) §2 Agent 分工

## 文件

| 路径 | 用途 |
|---|---|
| `index.html` | 最终页面（桌面 1440 / 移动 375） |
| `direction-approved.md` | 用户选择记录 |
| `assumptions.md` | 数据与设计假设 |
| `polish-log.md` | 两轮截图检查与修复记录 |
| `qa-cdp.mjs` | Chrome DevTools Protocol 交互与视口校验脚本 |
| `design-demos/direction-board.html` | 三方向视觉板 |
| `screenshots/` | 桌面、移动、整页与抽屉截图 |

## 本地校验

```bash
# 可选：用 CDP 做真 375px 视口 + 交互测试，并刷新截图
node qa-cdp.mjs
# 针对已启动的后端做联调验证
DISPATCH_URL=http://127.0.0.1:8010/dispatch node qa-cdp.mjs
```

脚本会启动本机 Chrome，校验 375px 无横向溢出，并测试链路切换、审批、异常抽屉与重置。需要 Node 22+ 与本机 Chrome。
