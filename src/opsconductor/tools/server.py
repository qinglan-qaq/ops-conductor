"""MCP stdio server exposing tenant-scoped read-only ERP tools."""

from typing import Any
from uuid import UUID

from mcp.server.mcpserver import MCPServer

from opsconductor.db import SessionLocal
from opsconductor.tools.service import ErpToolService

server = MCPServer("opsconductor-erp")


@server.tool(name="order_list_overdue")
async def order_list_overdue(tenant_id: str, warehouse: str | None = None) -> dict[str, Any]:
    async with SessionLocal() as session:
        orders = await ErpToolService(session).order_list_overdue(UUID(tenant_id), warehouse)
        return {"orders": orders}


@server.tool(name="order_get")
async def order_get(tenant_id: str, order_id: str) -> dict[str, Any]:
    async with SessionLocal() as session:
        return await ErpToolService(session).order_get(UUID(tenant_id), UUID(order_id))


@server.tool(name="inventory_get")
async def inventory_get(
    tenant_id: str, sku_id: str, warehouse_id: str
) -> dict[str, Any]:
    async with SessionLocal() as session:
        return await ErpToolService(session).inventory_get(
            UUID(tenant_id), UUID(sku_id), UUID(warehouse_id)
        )


@server.tool(name="shipment_list")
async def shipment_list(tenant_id: str, order_id: str) -> dict[str, Any]:
    async with SessionLocal() as session:
        shipments = await ErpToolService(session).shipment_list(
            UUID(tenant_id), UUID(order_id)
        )
        return {"shipments": shipments}


@server.tool(name="order_get_state")
async def order_get_state(tenant_id: str, order_id: str) -> dict[str, Any]:
    async with SessionLocal() as session:
        return await ErpToolService(session).order_get_state(
            UUID(tenant_id), UUID(order_id)
        )


@server.tool(name="address_validate")
async def address_validate(tenant_id: str, order_id: str) -> dict[str, Any]:
    async with SessionLocal() as session:
        return await ErpToolService(session).address_validate(UUID(order_id), UUID(tenant_id))


if __name__ == "__main__":
    server.run(transport="stdio")
