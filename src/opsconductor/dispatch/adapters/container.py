"""依赖组装：构建调度 Demo 的进程内对象图。

启动时按 ``MockToolGateway → build_agents → AgentRegistry →
InMemoryDispatchRepository → DispatchOrchestrator → DispatchService`` 的顺序组装，
并把服务保存为模块级单例供 FastAPI 依赖使用。测试通过 ``reset_service`` 重建
对象图，避免审批裁决等写操作在用例之间泄漏。
"""

from __future__ import annotations

from datetime import datetime

from opsconductor.dispatch.adapters.memory import InMemoryDispatchRepository
from opsconductor.dispatch.adapters.mock_tools import MockToolGateway
from opsconductor.dispatch.application.agents import (
    AgentRegistry,
    VerifierAgent,
    build_agents,
)
from opsconductor.dispatch.application.orchestrator import DispatchOrchestrator
from opsconductor.dispatch.application.seed import build_seed_state
from opsconductor.dispatch.application.service import DispatchService


class SystemClock:
    """返回本地时间 ``HH:MM`` 展示标签的时钟适配器。"""

    def now_label(self) -> str:
        """返回当前本地时刻，格式为 ``HH:MM``。"""
        return datetime.now().strftime("%H:%M")


def _build_service() -> DispatchService:
    """按固定顺序组装一次完整的 Demo 服务。"""
    tools = MockToolGateway()
    agents = build_agents(tools)
    registry = AgentRegistry(agents)
    repo = InMemoryDispatchRepository(
        lambda: build_seed_state(
            {agent.card.id: agent.card for agent in agents.values()}
        )
    )
    orchestrator = DispatchOrchestrator(registry, VerifierAgent(), SystemClock())
    return DispatchService(repo, orchestrator, SystemClock())


_service = _build_service()


def get_service() -> DispatchService:
    """FastAPI 依赖：返回当前进程内服务单例。"""
    return _service


def reset_service() -> DispatchService:
    """重建服务图并替换单例，返回新服务。

    Returns:
        使用全新种子状态构建的 :class:`DispatchService`。
    """
    global _service
    _service = _build_service()
    return _service


__all__ = ["SystemClock", "get_service", "reset_service"]
