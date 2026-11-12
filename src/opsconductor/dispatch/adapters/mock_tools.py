"""确定性的 Mock 工具网关。

Demo 不启动 MCP 子进程，也不访问外部网络；``MockToolGateway`` 按工具名返回固定
产物文件名，供 Agent 与编排器记录 artifact。
"""

from __future__ import annotations

from collections.abc import Mapping


class MockToolGateway:
    """实现 :class:`~opsconductor.dispatch.domain.ports.ToolPort` 的离线网关。"""

    def call(self, tool: str, params: Mapping[str, object]) -> dict[str, object]:
        """返回固定形状的工具结果。

        Args:
            tool: 工具名，例如 ``ads_create``。
            params: 调用参数；Demo 忽略，仅用于保持端口签名。

        Returns:
            ``{"tool": ..., "artifact": "{tool}.json", "status": "ok"}``。
        """
        del params
        return {"tool": tool, "artifact": f"{tool}.json", "status": "ok"}


__all__ = ["MockToolGateway"]
