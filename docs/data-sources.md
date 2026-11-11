# 数据来源与合规

> 演示数据只使用公开、开源或合成数据，不包含真实个人信息。

**状态** 资料调研完成，部分许可待逐项核实 ｜ **关联文档**：[系统设计](design.md) ｜ [实施计划](plan.md)

## 1. 总原则

- 订单与订单行优先使用公开数据集；原始数据不入库、不入仓。
- 客户、地址、电话等个人信息一律用 Faker `zh_CN` 合成，禁止使用真实 PII。
- 公开规则页面只提炼条款结构，**改写为合成 SOP**，不复制原文、不重新分发原文。
- 非商业许可数据集只用于本地演示并署名，不用于商业用途。
- 所有数据通过脚本生成或下载；仓库只保留 schema、种子脚本和小样本。
- 每个数据集在接入前必须完成许可核实，并在 `README` 或本文档记录归属与限制。

## 2. 订单与交易数据

| 资料 | 地址 | 许可 | 用途 |
|---|---|---|---|
| Olist Brazilian E-Commerce | kaggle.com/datasets/olistbr/brazilian-ecommerce | CC BY-NC-SA 4.0（以页面为准） | 订单、订单行、客户、商品、评价、支付，字段最完整 |
| UCI Online Retail II | archive.ics.uci.edu/dataset/502/online+retail+ii | CC BY 4.0（已核实） | 106 万行订单行，适合做销量与退货分析 |
| DataCo Smart Supply Chain | Kaggle 搜索 DataCo | 需核实 | 延迟交付、供应风险字段 |
| M5 Forecasting | Kaggle 竞赛页 | 需核实 | 销量预测与补货（可选，非核心） |
| Taobao User Behavior | 天池数据集 | 仅限研究，禁止商用 | 行为序列（可选，非核心） |

## 3. 商品目录

| 资料 | 地址 | 许可 | 用途 |
|---|---|---|---|
| Amazon Reviews 2023 元数据 | McAuley Lab 项目页 | 需核实，通常限研究 | 商品标题、类目、参数 |
| Open Food Facts | openfoodfacts.org | 数据 ODbL，图片 CC BY-SA | 商品参数与条码 |
| Google Product Taxonomy | google.com/basepages/producttype/taxonomy-with-ids.zh-CN.txt | 需核实 | 类目体系参考 |
| Akeneo 示例数据 | akeneo.com | 需核实 | PIM 字段设计参考 |

## 4. 中文客服与知识库

| 资料 | 地址 | 许可 | 用途 |
|---|---|---|---|
| InfiniFlow Ecommerce-Customer-Service-Workflow | huggingface.co/datasets/InfiniFlow/Ecommerce-Customer-Service-Workflow | Apache-2.0 | 中文商品说明与客服知识，首选 RAG 语料 |
| JDDC / JDDC 2.0 | arxiv.org/abs/1911.09969、arxiv.org/abs/2109.12913 | 需申请，官方入口已失效 | 客服对话（可选） |
| EcomGPT / EcomInstruct | GitHub Alibaba-NLP | 需核实 | 电商指令数据（可选） |
| Bitext 客服数据集 | HuggingFace | 需核实 | 意图分类与多语言客服 |
| CLINC150 | GitHub clinc-oos | 需核实 | 意图路由评测 |

## 5. 可选 ERP 参考实现

| 项目 | 许可 | 说明 |
|---|---|---|
| ERPNext | GPLv3 | 流程与单据设计参考；不建议直接改造，多租户成本高 |
| Odoo Community | LGPLv3 | 流程文档参考 |
| Medusa / Saleor | MIT / BSD-3 | 订单与商品模型参考 |

这些项目仅作为领域建模参考，不引入其代码。

## 6. 公开规则页面

淘宝/天猫规则中心、京东商家规则中心、拼多多商家规则、抖音电商规则中心、Shopify Help Center、Amazon Seller Central Policies。

用法：提炼条款结构，改写为合成 SOP 文档；不复制、不批量抓取、不重新分发原文。

## 7. 聚水潭公开资料

- 开放平台文档：open.jushuitan.com（接口规则、常见问题、商品映射等）。
- 开放平台门户：openweb.jushuitan.com。

用途仅限对齐 API 形态与术语（签名、订单查询、商品映射等）；不申请真实商家授权，不调用生产接口。

## 8. 灌数与仓库策略

- 提供 `scripts/` 下的下载与生成脚本，以及 schema 与种子数据。
- 原始数据和完整数据集不进入 Git，仓库只保留可公开的小样本。
- 每个数据文件附带来源、许可、生成时间与字段映射说明。
- 演示环境使用固定随机种子，保证可重复构建。
- 涉及个人信息时只使用 Faker 生成值；如引入公开数据集中的客户字段，先做脱敏或替换。
