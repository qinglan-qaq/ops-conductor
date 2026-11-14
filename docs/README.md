# 文档索引

运筹 OpsConductor 的设计、实施与合规文档。推荐阅读顺序：

0. [总规格 SPEC.md](../SPEC.md) — 平台级目标、端到端链路、六平面架构、归因/持久化/Skill/SOP/飞轮、验收与开放问题（审查稿）。
1. [系统设计](design.md) — 系统架构、领域模型、Agent 编排、工具契约、安全、RAG、测试策略。
2. [MVP 设计规格](specs/2026-11-04-mvp-order-exception-design.md) — 订单异常可写闭环的范围、28 条评测与三周切片。
3. [3 分钟演示脚本](demo-script.md) — MVP 主流程的 3 分钟演示：创建任务、审批、执行、trace 与控制台。
4. [Known Gaps](KNOWN_GAPS.md) — 5 条 xfail（GT-08/09/12/17/26）的原因、影响与后续计划。
5. [交付状态](delivery-status.md) — 测试基线、文档字符串覆盖与验证结果。
6. [JD 对齐设计方案](specs/2026-11-04-jd-alignment-design.md) — 对照岗位要求的 3 周能力补齐、ERP Adapter、SKILL、Memory、RAG、RPA 与多模型。
7. [跨境电商全流程需求分析与能力地图（草案）](specs/2026-11-10-cross-border-ecommerce-platform-design.md) — 自营店与卖铲子的路线取舍、Amazon/Temu/TikTok 对比、5000 SKU 运营模型与能力地图。
8. [跨境电商全流程模拟演示系统 · 需求规格](specs/2026-11-10-cross-border-simulation-design.md) — Mock API、Mock 数据、Agent 工具、影刀 RPA、审批/幂等/补偿/审计/trace 与 30 条评测。
9. [跨境电商全流程模拟演示系统 · 实施计划](plans/2026-11-10-cross-border-simulation-implementation.md) — 6 个阶段、任务验收、检查点与 8 分钟演示脚本。
10. [电商运营 Agent 统筹架构](specs/2026-11-11-agent-orchestration-design.md) — Orchestrator + 领域 Agent + MCP、AI 制图、竞品比价调价、Agent 编写工作流与四道门。
11. [Agent 归因、持久化、Skill/SOP 与数据飞轮设计](specs/2026-11-11-agent-attribution-persistence-flywheel-design.md) — 归因体系、三层持久化、Skill/SOP 生命周期、数据飞轮、Agent 注册/黑板/交接、持续优化。
12. [电商运营 Orchestrator Skill](skills/ecommerce-operations-orchestrator/SKILL.md) — 可复用的多 Agent 统筹技能：目标、计划、调度、归因、持久化、飞轮与护栏。
13. [跨境运营 SOP](sop/2026-11-11-cross-border-operations-sop.md) — 日/周检查、P0–P3 升级、归因复盘、Skill/SOP 更新与交接。
14. [跨境电商运营异常处理指南](operations/2026-11-10-cross-border-ecommerce-operations-exception-guide.md) — 全流程、80 个异常场景、可能性/影响标准、18 个 playbook、指标与沟通模板。
15. [实施计划](plan.md) — 6 周排期、交付物、投递节奏与风险。
16. [数据来源与合规](data-sources.md) — 公开数据、许可状态、灌数与仓库策略。
17. [架构决策记录](adr/README.md) — 关键架构取舍及其理由。

## 文档清单

| 文档 | 内容 | 状态 |
|---|---|---|
| [总规格 SPEC.md](../SPEC.md) | 平台目标、链路、六平面架构、归因/持久化/Skill/SOP/飞轮、验收、ADR、开放问题 | 审查稿 |
| [系统设计](design.md) | 主设计文档，技术决策与接口契约 | 已确认，随实现迭代 |
| [MVP 设计规格](specs/2026-11-04-mvp-order-exception-design.md) | 订单异常可写闭环的详细需求与验收 | 已确认，待实施 |
| [JD 对齐设计方案](specs/2026-11-04-jd-alignment-design.md) | 对照岗位要求的 3 周能力补齐与商业边界 | 已确认，待实施 |
| [跨境电商全流程需求分析与能力地图](specs/2026-11-10-cross-border-ecommerce-platform-design.md) | 跨境电商全流程、平台对比、SKU/门店模型、能力地图与 MVP 切片 | 草案，待确认能力地图 |
| [跨境电商全流程模拟演示系统 · 需求规格](specs/2026-11-10-cross-border-simulation-design.md) | Mock 世界、Agent 全流程自动化、影刀 RPA、审批/幂等/补偿/审计/trace、30 条评测 | 待确认 |
| [跨境电商全流程模拟演示系统 · 实施计划](plans/2026-11-10-cross-border-simulation-implementation.md) | 6 个阶段、任务验收、检查点、最小演示版与完整评测版 | 待执行 |
| [电商运营 Agent 统筹架构](specs/2026-11-11-agent-orchestration-design.md) | Agent 分层、内容/定价/履约/结算闭环、AI 制图、竞品比价、工作流 DSL 与四道门 | 设计可用 |
| [Agent 归因、持久化、Skill/SOP 与数据飞轮设计](specs/2026-11-11-agent-attribution-persistence-flywheel-design.md) | 归因五层、JSON/DB/对象/向量持久化、Skill/SOP 生命周期、数据飞轮、Agent 注册/黑板/事件/交接、持续优化 | 设计可用 |
| [电商运营 Orchestrator Skill](skills/ecommerce-operations-orchestrator/SKILL.md) | 多 Agent 统筹 Skill：目标、计划、调度、归因、持久化、Skill 提炼、SOP、飞轮与护栏 | 可试用 |
| [跨境运营 SOP](sop/2026-11-11-cross-border-operations-sop.md) | 日/周检查、P0–P3 升级、归因复盘、Skill/SOP 更新、交接与模板 | 可用 |
| [跨境电商运营异常处理指南](operations/2026-11-10-cross-border-ecommerce-operations-exception-guide.md) | 全流程、80 个异常场景、L/I/P 标准、18 个 playbook、指标/模板/RACI | 可用 |
| [实施计划](plan.md) | 6 周排期、交付物、投递节奏与风险管理 | 进行中 |
| [MVP 实施计划](plans/2026-11-04-mvp-order-exception-implementation.md) | 订单异常 3 周任务级 TDD 计划 | 待执行 |
| [JD 对齐实施计划](plans/2026-11-04-jd-alignment-implementation.md) | ERP Adapter、SKILL、Memory、RAG、RPA、多模型任务级计划 | 待执行 |
| [跨境电商台前调度 Demo 实施计划](plans/2026-11-12-cross-border-dispatch-demo.md) | 领域/应用/适配分层、FastAPI、TDD 与端到端冒烟 | 已执行 |
| [台前调度导航、阶段工作台与平台集成扩展设计](specs/2026-11-12-dispatch-console-enhancement-design.md) | 侧边栏、首页态势、Vue 前端、阶段工作台、平台控制/数据接口与聚水潭/TikTok/Amazon/Google Trends 示例 | 已实现 |
| [台前调度台 v1.2 实施计划](plans/2026-11-12-dispatch-console-v1.2.md) | 领域/应用/适配阶段契约、Mock Adapter、Vue 3 脚手架、阶段工作台、E2E 与验收 | 已执行 |
| [HR 项目展示 Deck](../design/opsconductor-hr-deck/README.md) | 14 页跨境电商场景、多 Agent 编排、真实截图与工程证据 | 可演示 |
| [3 分钟演示脚本](demo-script.md) | MVP 主流程演示、演示账号与故障注入 | 可用 |
| [Known Gaps](KNOWN_GAPS.md) | 5 条 xfail 的原因、影响与后续计划 | 已记录 |
| [交付状态](delivery-status.md) | 测试基线、文档字符串覆盖与验证结果 | 已交付 |
| [项目代码审查](reviews/2026-11-04-project-code-review.md) | 五轴复审、结构图、P0/P1/P2 建议与已知缺口 | 已完成 |
| [数据来源与合规](data-sources.md) | 数据集、许可、灌数策略 | 部分许可待核实 |
| [ADR 0001](adr/0001-record-architecture-decisions.md) | 使用 ADR 记录架构决策 | 已接受 |
| [ADR 0002](adr/0002-plan-execute-deterministic-runtime.md) | LLM 规划 + 确定性运行时执行 | 已接受 |
| [ADR 0003](adr/0003-independent-verifier.md) | 独立验证 Agent 拥有否决权 | 已接受 |
| [ADR 0004](adr/0004-mvp-approval-and-idempotency.md) | MVP 审批状态机、幂等作用域与补偿边界 | 已接受 |

## 维护约定

- 架构、接口、领域模型与质量目标的变更，先更新[系统设计](design.md)。
- 影响多个模块或难以逆转的决策，新增 ADR，并在设计文档中链接。
- 排期、交付物与风险变化更新[实施计划](plan.md)；数据许可变化更新[数据来源与合规](data-sources.md)。
- 新增文档后同步更新本索引和根目录 `README.md` 的文档链接。

## 历史

- 2026-11-03：完成 v1.0 设计规格与首批三条 ADR。
- 2026-11-04：将原规格重组为「系统设计 / 实施计划 / 数据来源」三份文档，并新增本索引与 ADR 索引。
- 2026-11-04：MVP 需求收敛为订单异常 + 拆单/改址的 3 周可写闭环，新增 [MVP 设计规格](specs/2026-11-04-mvp-order-exception-design.md)。
- 2026-11-04：新增 [JD 对齐设计方案](specs/2026-11-04-jd-alignment-design.md)，在 MVP 后补 ERP Adapter、SKILL、Memory、RAG、RPA 和多模型，总周期约 6 周。
- 2026-11-04：使用 `code-review-and-quality` skill 重新生成[项目代码审查](reviews/2026-11-04-project-code-review.md)，记录五轴复审、结构热点与 P0/P1/P2 建议。
- 2026-11-04：核心源码补充中文 Google 风格文档字符串，并在[交付状态](delivery-status.md)记录覆盖范围与验证结果。
- 2026-11-10：新增 [跨境电商全流程需求分析与能力地图（草案）](specs/2026-11-10-cross-border-ecommerce-platform-design.md)，评估自营店与卖铲子路线、平台对比、5000 SKU 运营模型与能力地图。
- 2026-11-10：新增 [模拟演示系统需求规格](specs/2026-11-10-cross-border-simulation-design.md) 与 [实施计划](plans/2026-11-10-cross-border-simulation-implementation.md)，以 Mock 世界 + 影刀 RPA 演示 Agent 全流程自动化。
- 2026-11-10：新增 [跨境电商运营异常处理指南](operations/2026-11-10-cross-border-ecommerce-operations-exception-guide.md)，覆盖全流程、80 个异常场景、L/I/P 定级、18 个 playbook 与运营方法论。
- 2026-11-11：新增 [电商运营 Agent 统筹架构](specs/2026-11-11-agent-orchestration-design.md)，定义 Agent 分层、AI 制图、竞品比价调价、工作流 DSL 与四道门。
- 2026-11-11：新增 [归因/持久化/Skill/SOP/飞轮设计](specs/2026-11-11-agent-attribution-persistence-flywheel-design.md)、[Orchestrator Skill](skills/ecommerce-operations-orchestrator/SKILL.md) 与 [跨境运营 SOP](sop/2026-11-11-cross-border-operations-sop.md)。
- 2026-11-11：新增 [总规格 SPEC.md（审查稿）](../SPEC.md)，整合业务链路、六平面架构、Agent 协作、归因/持久化/Skill/SOP/飞轮、验收与 ADR。
- 2026-11-12：完成台前调度台 v1.2：阶段结果/详情与集成 API、MockPlatformAdapter/ControlService、Vue 3 场景目录与阶段工作台、Vue 静态托管与 Playwright 冒烟；见 [v1.2 实施计划](plans/2026-11-12-dispatch-console-v1.2.md)。
- 2026-11-12：新增首页经营可视化：近 7 日销售额、Agent 使用量/成功率、阶段结果交付；全部图表使用朱墨自绘样式并标注 Mock 数据。
- 2026-11-12：新增 [HR 项目展示 Deck](../design/opsconductor-hr-deck/README.md)，14 页、约 9 分钟，覆盖电商场景、多 Agent 编排、产品截图与工程证据。
