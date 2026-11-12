"""跨境调度应用层。

应用层只依赖领域模型、领域策略与领域端口：``plans`` 固化十段链路模板，
``agents`` 提供八个规则型领域 Agent 与独立 Verifier，``orchestrator`` 串起
计划、执行与审批，``seed`` 提供 Demo 种子状态，``service`` 作为对适配层暴露
的门面。本层不导入 FastAPI、SQLAlchemy 或任何具体适配器。
"""
