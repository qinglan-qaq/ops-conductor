"""MCP stdio server exposing tenant-scoped ERP read and write tools."""

from typing import Any
from uuid import UUID

from mcp.server.mcpserver import MCPServer

from opsconductor.db import SessionLocal
from opsconductor.tools.service import ErpToolService

server = MCPServer("opsconductor-erp")


def _optional_uuid(value: str | None) -> UUID | None:
    return UUID(value) if value else None


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


@server.tool(name="order_split")
async def order_split(
    tenant_id: str,
    order_id: str,
    shipments: list[dict[str, Any]],
    idempotency_key: str,
    dry_run: bool = False,
    actor_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Split a pending order into shipments and reserve inventory atomically."""

    async with SessionLocal() as session:
        return await ErpToolService(session).order_split(
            UUID(tenant_id),
            UUID(order_id),
            shipments,
            idempotency_key,
            dry_run=dry_run,
            actor_id=_optional_uuid(actor_id),
            task_id=_optional_uuid(task_id),
        )


@server.tool(name="shipment_cancel")
async def shipment_cancel(
    tenant_id: str,
    shipment_id: str,
    idempotency_key: str,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Compensation tool: cancel one shipment and release its reservation."""

    async with SessionLocal() as session:
        return await ErpToolService(session).shipment_cancel(
            UUID(tenant_id),
            UUID(shipment_id),
            idempotency_key,
            task_id=_optional_uuid(task_id),
        )


@server.tool(name="inventory_release")
async def inventory_release(
    tenant_id: str,
    order_id: str,
    idempotency_key: str,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Compensation tool: release every active shipment reservation for an order."""

    async with SessionLocal() as session:
        return await ErpToolService(session).inventory_release(
            UUID(tenant_id),
            UUID(order_id),
            idempotency_key,
            task_id=_optional_uuid(task_id),
        )


@server.tool(name="order_revert_split")
async def order_revert_split(
    tenant_id: str,
    order_id: str,
    idempotency_key: str,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Compensation tool: cancel shipments, release stock, restore the order."""

    async with SessionLocal() as session:
        return await ErpToolService(session).order_revert_split(
            UUID(tenant_id),
            UUID(order_id),
            idempotency_key,
            task_id=_optional_uuid(task_id),
        )


if __name__ == "__main__":
    server.run(transport="stdio")
