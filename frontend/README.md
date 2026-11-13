# 运筹跨境 · 台前调度 Vue 前端

Vue 3 + TypeScript 的调度台。生产由 FastAPI 托管 `dist/`；开发用 Vite，`/api` 代理到 `http://127.0.0.1:8010`。

## 开发

```bash
# 终端 1：后端（仓库根目录）
PORT=8010 bash scripts/demo_dispatch.sh

# 终端 2
cd frontend
npm install
npm run dev
# http://127.0.0.1:5173/dispatch
```

## 构建与验证

```bash
bash scripts/build_frontend.sh   # npm ci + vue-tsc + vite build
cd frontend
npm run typecheck
npm run test:unit
npm run build
E2E_BASE_URL=http://127.0.0.1:8010 npm run test:e2e
```

E2E 使用本机 Chrome（`channel: 'chrome'`），不下载 Playwright 浏览器。运行前必须启动后端；`npm.run test:e2e` 会重置 Demo 种子。

## 结构

| 目录 | 职责 |
|---|---|
| `src/api/` | HTTP client、Zod 契约、离线 fixture |
| `src/queries/` | Vue Query 缓存与 mutation |
| `src/stores/` | Pinia 纯客户端 UI 状态 |
| `src/components/layout/` | AppShell、Topbar、Sidebar |
| `src/features/` | overview（态势 + 经营图表）/ stage / approvals / exceptions / integrations / trace |
| `src/styles/` | 朱墨 tokens 与响应式布局 |
| `src/tests/unit/` | Vitest + Vue Test Utils |
| `e2e/` | Playwright 冒烟、375 抽屉与截图 |

## 边界

- 数据以 `GET /api/v1/dispatch/snapshot`、`/stages/{id}`、`/integrations` 为准；离线 fixture 由 `scripts/export_dispatch_fixtures.py` 从后端种子导出，仅用于断网展示。
- 未接真实平台凭据；`MockPlatformAdapter` 只返回确定性数据。所有控制写必须经后端 `ControlService`。
- 不使用 `v-html`；API 字符串通过 Vue 插值转义。
