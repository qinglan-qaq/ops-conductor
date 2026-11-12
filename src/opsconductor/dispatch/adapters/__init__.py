"""跨境调度的适配层。

适配层实现领域端口并暴露 HTTP 接口：``memory`` 提供进程内仓储，``mock_tools``
提供确定性工具调用，``serialize`` 负责 JSON 投影，``api`` / ``page`` 提供
FastAPI 路由，``container`` 组装对象图。只有本层可以依赖 FastAPI。
"""
