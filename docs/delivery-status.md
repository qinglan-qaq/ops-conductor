# MVP 交付状态

**分支** `feature/opsconductor-mvp` ｜ **日期** 2026-11-04

## 已验证范围

- 订单异常可写闭环：拆单、改址、审批、幂等、补偿、审计、trace、报告。
- MCP 工具网关、任务 API、审批控制台、执行入口。
- PostgreSQL 16（Docker 主机端口 15432）；MVP 不依赖 Redis。
- 演示使用确定性模板 Planner，不需要真实模型凭据。

## 验证证据

- `pytest`：164 passed，5 xfailed。
- Golden Tasks：23/28 完全达标；5 条 known gaps（GT-08/09/12/17/26）。
- `ruff check .`：通过。
- `mypy src`：42 个文件通过。
- `scripts/demo.sh` 可启动并通过真实 MCP 客户端完成审批与执行。

## 已知缺口

见 [KNOWN_GAPS.md](KNOWN_GAPS.md)。这些用例以 xfail 保留，不计入 28/28 全绿。

## 演示入口

- 启动：`bash scripts/demo.sh`
- 控制台：`http://127.0.0.1:8000/console/tasks?api_key=dev-operator-a`
- 演示步骤：[demo-script.md](demo-script.md)
- 关键决策：[ADR 0004](adr/0004-mvp-approval-and-idempotency.md)
