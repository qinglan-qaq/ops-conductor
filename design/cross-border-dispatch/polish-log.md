# Polish Log

## Round 1 · 桌面与移动首轮

检查方式：Chrome headless 截图 + 375px 真机视口（CDP `Emulation.setDeviceMetricsOverride`）。

看到的最伤三处与修复：

1. **移动端主标题溢出**：`一句话，调度十条链路。` 在 375px 下超过容器。
   修复：移动端字号降到 28px、字距收紧到 `.02em`，并确认 375px 下完整显示。
2. **链路连接线没有穿过节点**：连接线 `top:40px`，节点中心在 `23px`。
   修复：连接线改为 `top:23px`，与节点圆点对齐。
3. **移动端流程步骤横向滚动导致标签折行**：六步在 170px 固定宽内折成两行。
   修复：移动端改为纵向步骤流，去掉横向滚动；桌面保持横向步进。

其他修复：

- 关键标签从 11–11.5px 统一到 12px；L2 金色改用更深的 `#7a5c2a` 提高对比度。
- 审批「准 / 驳」按钮从 40px 提升到 44px；导航与 ghost 按钮也保证 44px 触控高度。
- 移动端 trace 去掉 `max-height`，完整展示 7 条事件。
- 移动端十段链路增加「左右滑动查看十段链路」提示。
- 页脚从 flex 换行改为三列网格，统计标签回到右侧。
- Agent 支撑条改为 2×2 网格，Verifier / Memory / MCP / RPA 更整齐。
- 审批 KPI 的圆点与待批数量联动，批准一件后从 3 个点变为 2 个点。
- 十段链路增加状态图例：已完成 / 进行中 / 异常 / 待开始。

## Round 2 · 最终检查

在 375×812 真机视口下：

- `innerWidth = 375`
- `document.documentElement.scrollWidth = 375`
- `document.body.scrollWidth = 375`
- 无横向溢出

交互验证：

- 点击「收款结算」链路节点 → 详情切换为 `收款与结算 L3`
- 批准「广告预算」→ 待批计数 3 → 2，朱印显示「准」，class 包含 `decided approved`
- 点击 `ORD-01 超时未发货` → 抽屉打开，标题正确，playbook 阶段数 3
- 重置审批 → 待批恢复 3，已决策项 0，流程回到「审批进行中」
- 浏览器控制台错误：0

最终截图：

- `screenshots/desktop-1440x900.png`
- `screenshots/desktop-full.png`
- `screenshots/mobile-375x812.png`
- `screenshots/mobile-full.png`
- `screenshots/drawer-ord01.png`
- `screenshots/mobile-drawer.png`

## 已知限制

- `design_lint.py check` 需要 Python 版 Playwright；本机未安装，体检被跳过。已用 Chrome + CDP 做 375/1440 视口、交互和控制台检查。
- 字体依赖本机 Noto Serif SC / 华文宋体 / 华文仿宋 / 华文楷体；没有时回退到宋体/仿宋，整体版式不受影响。
- 页面是交互原型：审批、异常与 trace 为 Mock 状态，刷新后回到初始剧本。

## Backend Integration · 2026-11-12

前后端切片已完成并验证：

- `pytest tests/dispatch tests/test_health.py -q` → **53 passed**
- 真实 uvicorn（8010 端口，8000 被已有进程占用）：
  - `GET /health` → `{"status":"ok",...}`
  - `GET /api/v1/dispatch/snapshot` → 3 件待批、6 条异常、7 条 trace、10 段链路、8 个 Agent
  - `GET /dispatch` → 200，页面含 `DISPATCH_API`
- Chrome + CDP 真 375px 视口：
  - `innerWidth = 375`、`scrollWidth = 375`、无横向溢出
  - 页面显示「后端已连接」
  - 批准预算 → 待批 3 → 2，朱印「准」
  - 打开 `ORD-01` → 3 个 playbook 阶段
  - 重置 → 恢复 3 件待批
  - 控制台错误 0
- 架构：domain / application / adapters 三层；端口-适配器、仓储、策略、工厂、状态机、门面、依赖注入；审批重复裁决 409，未知异常/审批 404，所有写操作写 trace。
- 说明：Dispatch 切片使用内存仓储与 Mock 工具，不依赖 PostgreSQL/Redis；现有 MVP 数据库路由未改动。

## Startup Script Verification

- `bash scripts/demo_dispatch.sh` was verified on port 8013: `/health` 200, `/dispatch` 200.
- The script resolves the conda env path directly (avoids `conda run` buffering) and converts Git Bash `PYTHONPATH` to a Windows path with `;` separators.
- Port 8000 is occupied by an unrelated existing process; use `PORT=8010 bash scripts/demo_dispatch.sh` (the live verification used 8010).
