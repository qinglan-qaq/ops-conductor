# 文档索引

运筹 OpsConductor 的设计、实施与合规文档。推荐阅读顺序：

1. [系统设计](design.md) — 系统架构、领域模型、Agent 编排、工具契约、安全、RAG、测试策略。
2. [MVP 设计规格](specs/2026-11-04-mvp-order-exception-design.md) — 订单异常可写闭环的范围、28 条评测与三周切片。
3. [JD 对齐设计方案](specs/2026-11-04-jd-alignment-design.md) — 对照岗位要求的 3 周能力补齐、ERP Adapter、SKILL、Memory、RAG、RPA 与多模型。
4. [实施计划](plan.md) — 6 周排期、交付物、投递节奏与风险。
5. [数据来源与合规](data-sources.md) — 公开数据、许可状态、灌数与仓库策略。
6. [架构决策记录](adr/README.md) — 关键架构取舍及其理由。

## 文档清单

| 文档 | 内容 | 状态 |
|---|---|---|
| [系统设计](design.md) | 主设计文档，技术决策与接口契约 | 已确认，随实现迭代 |
| [MVP 设计规格](specs/2026-11-04-mvp-order-exception-design.md) | 订单异常可写闭环的详细需求与验收 | 已确认，待实施 |
| [JD 对齐设计方案](specs/2026-11-04-jd-alignment-design.md) | 对照岗位要求的 3 周能力补齐与商业边界 | 已确认，待实施 |
| [实施计划](plan.md) | 6 周排期、交付物、投递节奏与风险管理 | 进行中 |
| [MVP 实施计划](plans/2026-11-04-mvp-order-exception-implementation.md) | 订单异常 3 周任务级 TDD 计划 | 待执行 |
| [JD 对齐实施计划](plans/2026-11-04-jd-alignment-implementation.md) | ERP Adapter、SKILL、Memory、RAG、RPA、多模型任务级计划 | 待执行 |
| [项目代码审查](reviews/2026-11-04-project-code-review.md) | 两轴审查、结构图、P0/P1/P2 建议与已知缺口 | 已完成 |
| [数据来源与合规](data-sources.md) | 数据集、许可、灌数策略 | 部分许可待核实 |
| [ADR 0001](adr/0001-record-architecture-decisions.md) | 使用 ADR 记录架构决策 | 已接受 |
| [ADR 0002](adr/0002-plan-execute-deterministic-runtime.md) | LLM 规划 + 确定性运行时执行 | 已接受 |
| [ADR 0003](adr/0003-independent-verifier.md) | 独立验证 Agent 拥有否决权 | 已接受 |

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
- 2026-11-04：新增 [项目代码审查](reviews/2026-11-04-project-code-review.md)，记录两轴审查、结构热点与 P0/P1/P2 建议。
- 2026-11-04：核心源码补充中文 Google 风格文档字符串，并在[交付状态](delivery-status.md)记录覆盖范围与验证结果。
