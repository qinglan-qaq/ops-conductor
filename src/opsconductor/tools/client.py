"""MCP stdio client for the OpsConductor ERP tool server."""

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
    content = getattr(result, "content", None) or []
    parts = [getattr(item, "text", str(item)) for item in content]
    if not parts:
        parts.append(str(getattr(result, "structured_content", "") or result))
    return " | ".join(parts)


class ErpToolClient:
    """Start the ERP MCP server as a subprocess and call its tools."""

    def __init__(self) -> None:
        self._stack = AsyncExitStack()
        self._session: ClientSession | None = None

    async def __aenter__(self) -> "ErpToolClient":
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
        await self._stack.aclose()

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
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
            payload = json.loads(result.content[0].text)
        faults.check_after(name)
        return payload
