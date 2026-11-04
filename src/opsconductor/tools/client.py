"""MCP stdio client for the OpsConductor ERP tool server."""

import json
import os
import sys
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


class ErpToolClient:
    """Start the ERP MCP server as a subprocess and call its read tools."""

    def __init__(self) -> None:
        self._stack = AsyncExitStack()
        self._session: ClientSession | None = None

    async def __aenter__(self) -> "ErpToolClient":
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "opsconductor.tools.server"],
            env=dict(os.environ),
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._stack.aclose()

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        assert self._session is not None
        result = await self._session.call_tool(name, arguments)
        if result.is_error:
            raise RuntimeError(f"MCP tool {name} failed")
        if result.structured_content is not None:
            return result.structured_content
        return json.loads(result.content[0].text)
