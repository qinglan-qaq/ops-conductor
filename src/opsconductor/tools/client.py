"""OpsConductor ERP 工具服务器的 MCP stdio 客户端。

:class:`ErpToolClient` 以子进程方式启动 ``python -m opsconductor.tools.server``，
通过 stdio 建立 MCP 会话，并在上下文退出时由 :class:`AsyncExitStack` 关闭会话与
子进程。子进程继承当前进程的完整环境变量。

Invariants:

- 每次工具调用前执行 :func:`opsconductor.tools.faults.check`；调用成功后执行
  ``check_after``，因此 ``timeout_after_commit`` 表示“写入可能已提交但响应丢失”。
- 工具返回的 ``is_error`` 结果会转换为异常；错误文本含 ``TOOL_ACCESS_DENIED``
  时转换为 403 的 :class:`ToolAccessDenied`。
- 返回载荷必须可 JSON 序列化，供上层直接持久化或渲染。
- 客户端只负责传输与故障注入，不写审计；审计由服务端工具与上层编排层负责。
"""

import json
import os
import sys
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from opsconductor.tools import faults
from opsconductor.tools.guard import TOOL_ACCESS_DENIED, ToolAccessDenied


def _error_text(result: Any) -> str:
    """提取 MCP 工具错误结果中的可读文本。

    Args:
        result: MCP 的 ``CallToolResult`` 或结构类似的对象。

    Returns:
        内容块文本以 ``" | "`` 连接；没有文本块时回退到结构化内容或对象本身的
        字符串形式。
    """

    content = getattr(result, "content", None) or []
    parts = [getattr(item, "text", str(item)) for item in content]
    if not parts:
        parts.append(str(getattr(result, "structured_content", "") or result))
    return " | ".join(parts)


class ErpToolClient:
    """以子进程方式启动 ERP MCP 服务器并调用其工具。

    Attributes:
        _stack: 持有 stdio 客户端与 MCP 会话的退出栈。
        _session: 初始化后的 MCP 客户端会话；进入上下文前为 ``None``。

    Note:
        请使用 ``async with``：进入时启动子进程并完成 MCP 初始化，退出时关闭
        会话并终止子进程。子进程环境复制自 ``os.environ``，因此它与当前进程
        使用相同的配置与凭据。
    """

    def __init__(self) -> None:
        self._stack = AsyncExitStack()
        self._session: ClientSession | None = None

    async def __aenter__(self) -> "ErpToolClient":
        """启动 MCP 服务器子进程并完成会话初始化。

        Returns:
            已初始化的客户端自身。

        Raises:
            Exception: 子进程启动或 MCP 初始化失败时原样抛出。

        Note:
            失败时先关闭退出栈再抛出，不会留下悬挂的子进程。
        """

        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "opsconductor.tools.server"],
            env=dict(os.environ),
        )
        try:
            read, write = await self._stack.enter_async_context(stdio_client(params))
            self._session = await self._stack.enter_async_context(ClientSession(read, write))
            await self._session.initialize()
        except BaseException:
            await self._stack.aclose()
            raise
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        """关闭 MCP 会话并终止子进程。"""

        await self._stack.aclose()

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """调用一个 MCP 工具并返回其 JSON 载荷。

        Args:
            name: 工具名，例如 ``order_get``。
            arguments: 工具参数字典；必须包含调用方租户的 ``tenant_id``。

        Returns:
            工具的结构化输出，或首个文本内容块解析出的 JSON 对象。

        Raises:
            ToolAccessDenied: 服务端拒绝写入且错误文本包含
                ``TOOL_ACCESS_DENIED`` 时，携带 403 状态码。
            RuntimeError: 工具返回错误、没有可用文本内容，或错误结果不是访问
                拒绝。
            TimeoutError: 故障注入配置了 ``timeout``（调用前）或
                ``timeout_after_commit``（调用后）。
            json.JSONDecodeError: 文本内容不是合法 JSON。

        Warning:
            ``timeout_after_commit`` 在工具调用成功之后抛出，此时服务端写入可能
            已经提交；调用方应把结果视为未知并按幂等键重试，而不是假定失败。

        Note:
            客户端不写审计；读工具当前也不审计。写工具的审批门禁与拒绝审计都在
            服务端完成。
        """

        assert self._session is not None
        faults.check(name)
        result = await self._session.call_tool(name, arguments)
        if result.is_error:
            detail = _error_text(result)
            if TOOL_ACCESS_DENIED in detail:
                raise ToolAccessDenied(detail, status_code=403)
            raise RuntimeError(f"MCP tool {name} failed")
        if result.structured_content is not None:
            payload = result.structured_content
        else:
            text = getattr(result.content[0], "text", None)
            if not isinstance(text, str):
                raise RuntimeError(f"MCP tool {name} returned no text content")
            payload = json.loads(text)
        faults.check_after(name)
        return payload
