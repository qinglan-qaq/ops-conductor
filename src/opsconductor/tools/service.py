"""ERP tool service exposing tenant-scoped reads and transactional writes."""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from opsconductor.domain import repositories, write_service
from opsconductor.domain.address import address_is_valid

__all__ = ["ErpToolService", "address_is_valid"]


class ErpToolService:
    """Expose ERP reads as JSON-serializable payloads for MCP tools."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def order_list_overdue(
        self, tenant_id: UUID, warehouse: str | None = None
    ) -> list[dict[str, Any]]:
        orders = await repositories.list_overdue_orders(self.session, tenant_id, warehouse)
        return [
            {"id": str(order.id), "order_no": order.order_no, "status": order.status}
            for order in orders
        ]

    async def order_get(self, tenant_id: UUID, order_id: UUID) -> dict[str, Any]:
        order = await repositories.get_order(self.session, tenant_id, order_id)
        if order is None:
            raise ValueError("order not found")
        lines = await repositories.list_order_lines(self.session, tenant_id, order_id)
        return {
            "id": str(order.id),
            "order_no": order.order_no,
            "status": order.status,
            "warehouse_id": str(order.warehouse_id) if order.warehouse_id else None,
            "receiver_name": order.receiver_name,
            "phone": order.phone,
            "province": order.province,
            "city": order.city,
            "district": order.district,
            "address_detail": order.address_detail,
            "version": order.version,
            "lines": [{"sku_id": str(line.sku_id), "qty": line.qty} for line in lines],
        }

    async def inventory_get(
        self, tenant_id: UUID, sku_id: UUID, warehouse_id: UUID
    ) -> dict[str, Any]:
        inventory = await repositories.get_inventory(
            self.session, tenant_id, sku_id, warehouse_id
        )
        if inventory is None:
            raise ValueError("inventory not found")
        return {
            "sku_id": str(inventory.sku_id),
            "warehouse_id": str(inventory.warehouse_id),
            "available": inventory.available,
            "reserved": inventory.reserved,
            "version": inventory.version,
        }

    async def shipment_list(self, tenant_id: UUID, order_id: UUID) -> list[dict[str, Any]]:
        shipments = await repositories.list_shipments(self.session, tenant_id, order_id)
        return [
            {"id": str(shipment.id), "status": shipment.status} for shipment in shipments
        ]

    async def order_get_state(self, tenant_id: UUID, order_id: UUID) -> dict[str, Any]:
        order = await repositories.get_order(self.session, tenant_id, order_id)
        if order is None:
            raise ValueError("order not found")
        return {"order_id": str(order_id), "status": order.status, "version": order.version}

    async def address_validate(self, order_id: UUID, tenant_id: UUID) -> dict[str, Any]:
        order = await repositories.get_order(self.session, tenant_id, order_id)
        if order is None:
            raise ValueError("order not found")
        return {"valid": address_is_valid(order), "order_id": str(order_id)}

    async def order_split(
        self,
        tenant_id: UUID,
        order_id: UUID,
        shipments: list[dict[str, Any]],
        idempotency_key: str,
        dry_run: bool = False,
        actor_id: UUID | None = None,
        task_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Split an order into shipments; the write service owns the commit."""

        return await write_service.split_order(
            self.session,
            tenant_id,
            order_id,
            shipments,
            idempotency_key,
            dry_run=dry_run,
            actor_id=actor_id,
            task_id=task_id,
        )

    async def order_revert_split(
        self,
        tenant_id: UUID,
        order_id: UUID,
        idempotency_key: str,
        task_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Compensate a split by cancelling shipments and restoring the order."""

        return await write_service.cancel_split(
            self.session, tenant_id, order_id, idempotency_key, task_id=task_id
        )

    async def shipment_cancel(
        self,
        tenant_id: UUID,
        shipment_id: UUID,
        idempotency_key: str,
        task_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Cancel one shipment and release its reserved inventory."""

        return await write_service.cancel_shipment(
            self.session, tenant_id, shipment_id, idempotency_key, task_id=task_id
        )

    async def inventory_release(
        self,
        tenant_id: UUID,
        order_id: UUID,
        idempotency_key: str,
        task_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Release reserved inventory for every active shipment of an order."""

        return await write_service.release_inventory(
            self.session, tenant_id, order_id, idempotency_key, task_id=task_id
        )
