# 运筹 OpsConductor

> 从一句话到一次可审计的 ERP 操作。

[![CI](https://github.com/qinglan-qaq/ops-conductor/actions/workflows/ci.yml/badge.svg)](https://github.com/qinglan-qaq/ops-conductor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

运筹（OpsConductor）是一个面向电商 SaaS ERP 的多 Agent 运营系统。它把「处理今天华东仓超时未发货的订单」这类模糊指令，翻译成可拆解、可审批、可回滚、可审计的 ERP 操作。

项目当前已交付 **MVP 订单异常可写闭环**：拆单 / 改址走通「计划 → 审批 → dry-run → 执行 → 验证 → 补偿 → 审计与 trace」。28 条 Golden Tasks 中 **23 条完全满足，5 条（GT-08/09/12/17/26）以 xfail 显式记录**，不宣称 28/28 全绿，详见 [Known Gaps](docs/KNOWN_GAPS.md)。当前完整测试基线为 164 passed + 5 xfailed。MVP 后进入 3 周 JD 对齐阶段，补齐 ERP Adapter、SKILL、Memory、RAG、RPA 与多模型，详见 [JD 对齐设计方案](docs/specs/2026-11-04-jd-alignment-design.md)。平台级目标、六平面架构与 Agent 归因/数据飞轮设计见 [总规格 SPEC.md](SPEC.md)；跨境电商全流程模拟与 Agent 统筹设计见 [文档索引](docs/README.md)。

## 核心场景

1. **订单异常处理**：超时未发货、库存不足、地址异常，生成拆单/换仓/改址/取消方案并执行。
2. **售后退款闭环**：检索售后政策，判定退款资格与金额，审批后执行退款并回写工单。
3. **多仓库存调拨**：识别缺货仓与积压仓，生成调拨建议，审批后执行并校验库存一致性。

## 架构

```mermaid
flowchart TB
    subgraph L1["接入层"]
        A["Web 控制台 / 飞书 webhook"]
    end

    subgraph L2["编排层"]
        R["意图路由"]
        P["Planner · 任务 DAG"]
        D["DAG 执行器"]
        H["人工审批"]
    end

    subgraph L3["执行层"]
        AG["领域 Agent"]
        MCP["MCP 工具网关"]
        V["验证 Agent · 可否决"]
    end

    subgraph L4["汇总层"]
        S["冲突消解 / 质量门禁 / 报告"]
    end

    subgraph SUP["支撑层"]
        RAG["RAG 混合检索"]
        MEM["记忆"]
        OBS["可观测"]
        EVAL["评估"]
    end

    A --> R --> P --> D
    D --> AG
    AG --> MCP
    D --> V
    V --> S
    MCP --> S
    RAG --> AG
    MEM --> P
    OBS --> L2
    EVAL --> L2
```

设计原则：

- **LLM 负责规划与异常判断，确定性运行时负责执行与超时控制。**
- 验证 Agent 独立于生成 Agent，并拥有阻塞性否决权。
- 写操作按风险分级审批，幂等、补偿、审计三件套齐全。
- 审批由持久化的任务/审批状态机承担（**不是 LangGraph interrupt**），执行器只读取已批准的 `Approval` 行。
- API 优先，浏览器自动化只作为无 API 旧系统的兜底。

完整设计见 [系统设计](docs/design.md)。

## 技术栈

- Python 3.11+、FastAPI、SQLAlchemy、Alembic
- PostgreSQL 16 + pgvector（MVP 必需；Docker 主机端口 15432）
- Redis（后续阶段使用，MVP 不依赖）
- LangGraph、MCP Python SDK
- BGE-M3 + bge-reranker-v2-m3、BM25 + 向量混合检索（后续阶段）
- Playwright（RPA 兜底）、Langfuse / OpenTelemetry（后续阶段）
- Docker Compose、pytest、ruff、mypy

## 快速开始

环境要求：Anaconda / Miniconda、Docker Desktop（Compose v2）。MVP 只依赖 PostgreSQL 16；Redis 不在启动链路中。

### 一键启动（推荐）

```bash
bash scripts/demo.sh
```

脚本只启动 Docker 中的 PostgreSQL（主机端口 **15432**）、执行 Alembic 迁移、写入幂等种子数据，然后启动 uvicorn。可重复执行。脚本假定 conda 环境 `opsconductor` 已存在（首次使用按下面「手动启动」第 2 步创建，或通过 `OPSCONDUCTOR_CONDA_ENV` 指定）。

### 手动启动

```bash
# 1. 启动 PostgreSQL 16（Docker 映射 15432；不要启动 Redis）
docker compose up -d postgres

# 2. 创建并激活 conda 环境（含项目与开发依赖）
conda create -n opsconductor python=3.11 -y
conda activate opsconductor
pip install -e ".[dev]"

# 3. 指向 Docker PostgreSQL。应用默认仍是 5432（原生 PostgreSQL 12），必须覆盖
export OPSCONDUCTOR_DATABASE_URL=postgresql+psycopg://ops:ops@localhost:15432/opsconductor
export OPSCONDUCTOR_STUB_LLM=true

# 4. 迁移与种子（均可重复执行）
alembic upgrade head
python -m opsconductor.domain.seed

# 5. 启动 API
uvicorn opsconductor.api.main:app --reload
```

验证：

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok","version":"0.1.0","env":"development"}
```

接口文档：http://127.0.0.1:8000/docs
控制台：http://127.0.0.1:8000/console/tasks?api_key=dev-operator-a

## 演示账号与主流程

| 身份 | API Key | 用途 |
|---|---|---|
| tenant-a operator | `dev-operator-a` | 创建任务、执行任务 |
| tenant-a approver | `dev-approver-a` | 审批 L2/L3 |
| tenant-b operator | `dev-operator-b` | 跨租户拒绝演示 |

主流程（完整 3 分钟脚本见 [docs/demo-script.md](docs/demo-script.md)）：

```bash
BASE=http://127.0.0.1:8000

# 0. Git Bash 下用文件传中文 JSON，避免终端编码破坏请求体
cat > /tmp/ops-task.json <<'JSON'
{"instruction":"处理今天华东仓超时未发货的订单","warehouse":"east","cutoff":"2026-11-04T00:00:00Z"}
JSON

# 1. 创建任务：operator 身份 + Idempotency-Key
curl -sS -X POST "$BASE/api/v1/tasks" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-operator-a" \
  -H "Idempotency-Key: demo-1" \
  --data-binary @/tmp/ops-task.json

# 2. 查看计划（等待审批）
curl -sS "$BASE/api/v1/tasks/<TASK_ID>" -H "X-API-Key: dev-operator-a"

# 3. 审批：approver 身份（也可在控制台提交审批表单）
curl -sS -X POST "$BASE/api/v1/tasks/<TASK_ID>/approve" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-approver-a" \
  -d '{"comment":"demo approval"}'

# 4. 执行：读取已批准的 Approval 行 → dry-run → 写入 → 验证 → 补偿/报告
curl -sS -X POST "$BASE/api/v1/tasks/<TASK_ID>/execute" \
  -H "X-API-Key: dev-operator-a"

# 5. 查看最终状态与 trace
curl -sS "$BASE/api/v1/tasks/<TASK_ID>" -H "X-API-Key: dev-operator-a"
```

> 审批是数据库中的任务/审批状态机，不使用 LangGraph interrupt。执行前必须已有 `approved` 的 Approval 行；待审批或过期审批返回 `awaiting_approval` 且不调用任何工具，拒绝的节点会被跳过。重复执行不会重复写入。

## 验证与测试

```bash
pytest -q          # 需要 Docker PostgreSQL 15432；测试库为 opsconductor_test
ruff check .
mypy src
```

当前基线：**164 passed + 5 xfailed**。5 个 xfail 是 GT-08/09/12/17/26，原因见 [docs/KNOWN_GAPS.md](docs/KNOWN_GAPS.md)。

失败注入演示（真实执行器、真实写服务和注入故障；不在 3 分钟主流程内）：

```bash
pytest -q \
  "tests/eval/test_golden_tasks.py::test_golden_task[GT-13]" \
  "tests/eval/test_golden_tasks.py::test_golden_task[GT-25]"
```

- 真实模型冒烟：`python scripts/smoke_live.py`，需要 `OPSCONDUCTOR_LLM_API_KEY` 与 `OPSCONDUCTOR_LLM_BASE_URL`；未配置时打印 `SKIPPED`。该脚本不在确定性测试套件内，本次收尾未运行真实模型。
- Windows 下若 `mypy src` 因 user site-packages 中的同名 `psutil` 命名空间包崩溃，可用 `python -s -m mypy src` 绕过。

## 目录结构

```
src/opsconductor/
├── api/           # HTTP 接口、审批控制台、执行入口
├── orchestrator/  # Planner、审批状态机、LangGraph 执行器、验证、幂等
├── tools/         # MCP 服务端/客户端、写审批守卫、故障注入
├── domain/        # ERP 模型、种子数据、拆单/改址/补偿写服务
├── observability/ # 审计与 trace
├── schemas.py     # 任务/计划 API Schema
├── config.py      # 环境变量配置
├── db.py          # 数据库引擎与会话
├── agents/        # 后续阶段占位
├── rag/           # 后续阶段占位
└── memory/        # 后续阶段占位
```

## 路线图

| 阶段 | 状态 | 内容 |
|---|---|---|
| MVP：订单异常 | 已交付 | 计划、审批状态机、dry-run、拆单/改址、验证、按订单补偿、审计与 trace、控制台；28 条 Golden Tasks（23 满足 + 5 known gaps） |
| JD 对齐（3 周） | 待开始 | ERP Adapter、SKILL、Memory、RAG、RPA、多模型 |

## 文档

- [总规格 SPEC.md](SPEC.md) — 平台目标、端到端链路、六平面架构、归因/持久化/Skill/SOP/飞轮、验收与开放问题（审查稿）
- [文档索引](docs/README.md)
- [跨境电商台前调度 Demo](design/cross-border-dispatch/README.md) — 朱墨批阅台页面 + 可运行 FastAPI 后端
- [系统设计](docs/design.md)
- [MVP 设计规格](docs/specs/2026-11-04-mvp-order-exception-design.md)
- [3 分钟演示脚本](docs/demo-script.md)
- [Known Gaps](docs/KNOWN_GAPS.md)
- [JD 对齐设计方案](docs/specs/2026-11-04-jd-alignment-design.md)
- [跨境电商全流程需求分析与能力地图（草案）](docs/specs/2026-11-10-cross-border-ecommerce-platform-design.md)
- [跨境电商全流程模拟演示系统 · 需求规格](docs/specs/2026-11-10-cross-border-simulation-design.md)
- [跨境电商全流程模拟演示系统 · 实施计划](docs/plans/2026-11-10-cross-border-simulation-implementation.md)
- [电商运营 Agent 统筹架构](docs/specs/2026-11-11-agent-orchestration-design.md)
- [Agent 归因、持久化、Skill/SOP 与数据飞轮设计](docs/specs/2026-11-11-agent-attribution-persistence-flywheel-design.md)
- [电商运营 Orchestrator Skill](docs/skills/ecommerce-operations-orchestrator/SKILL.md)
- [跨境运营 SOP](docs/sop/2026-11-11-cross-border-operations-sop.md)
- [跨境电商运营异常处理指南](docs/operations/2026-11-10-cross-border-ecommerce-operations-exception-guide.md)
- [MVP 实施计划](docs/plans/2026-11-04-mvp-order-exception-implementation.md)
- [JD 对齐实施计划](docs/plans/2026-11-04-jd-alignment-implementation.md)
- [实施计划](docs/plan.md)
- [数据来源与合规](docs/data-sources.md)
- [ADR 0001：记录架构决策](docs/adr/0001-record-architecture-decisions.md)
- [ADR 0002：LLM 规划 + 确定性执行](docs/adr/0002-plan-execute-deterministic-runtime.md)
- [ADR 0003：独立验证 Agent](docs/adr/0003-independent-verifier.md)
- [ADR 0004：MVP 审批状态机、幂等作用域与补偿边界](docs/adr/0004-mvp-approval-and-idempotency.md)

## 许可证

[MIT](LICENSE)
