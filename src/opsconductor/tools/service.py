"""ERP 工具服务：提供租户限定的读取与事务写入委托。

:class:`ErpToolService` 把数据库仓储结果转换为可 JSON 序列化的普通字典，供 MCP
工具直接返回。写操作只委托给 :mod:`opsconductor.domain.write_service`，后者拥有
事务边界并在返回前提交；本服务从不提交或回滚。

Invariants:

- 每个查询都携带 ``tenant_id``；仅凭订单、SKU 或发货单 ID 不足以访问一行数据。
- 读取方法返回的载荷只含字符串化 UUID 与原始标量，可直接 JSON 序列化。
- 写方法不做审批校验；审批门禁由 MCP 服务端在调用本服务之前执行。
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from opsconductor.domain import repositories, write_service
from opsconductor.domain.address import address_is_valid

__all__ = ["ErpToolService", "address_is_valid"]


class ErpToolService:
    """以 JSON 可序列化载荷暴露 ERP 读取，并委托事务写入。

    Attributes:
        session: 调用方拥有的异步会话；写方法的事务由写服务管理。

    Note:
        本服务从不提交。读方法只查询；写方法把整个事务交给
        :mod:`opsconductor.domain.write_service`。审批门禁不在这里执行，而是由
        MCP 服务端在调用写方法之前完成。
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def order_list_overdue(
        self, tenant_id: UUID, warehouse: str | None = None
    ) -> list[dict[str, Any]]:
        """列出租户内逾期的订单摘要。

        Args:
            tenant_id: 调用方租户。
            warehouse: 可选的仓库过滤条件。

        Returns:
            每项包含 ``id``、``order_no`` 与 ``status`` 的列表。
        """

        orders = await repositories.list_overdue_orders(self.session, tenant_id, warehouse)
        return [
            {"id": str(order.id), "order_no": order.order_no, "status": order.status}
            for order in orders
        ]

    async def order_get(self, tenant_id: UUID, order_id: UUID) -> dict[str, Any]:
        """返回订单头与订单行。

        Args:
            tenant_id: 调用方租户。
            order_id: 目标订单。

        Returns:
            包含地址、状态、版本与 ``lines`` 的订单字典；UUID 以字符串表示。

        Raises:
            ValueError: 订单不存在或不属于该租户。
        """

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
        """返回某 SKU 在某仓库的库存快照。

        Args:
            tenant_id: 调用方租户。
            sku_id: 目标 SKU。
            warehouse_id: 目标仓库。

        Returns:
            包含 ``available``、``reserved`` 与 ``version`` 的字典。

        Raises:
            ValueError: 库存行不存在或不属于该租户。
        """

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
        """列出订单的发货单摘要。

        Args:
            tenant_id: 调用方租户。
            order_id: 目标订单。

        Returns:
            每项包含 ``id`` 与 ``status`` 的列表；没有发货单时为空列表。
        """

        shipments = await repositories.list_shipments(self.session, tenant_id, order_id)
        return [
            {"id": str(shipment.id), "status": shipment.status} for shipment in shipments
        ]

    async def order_get_state(self, tenant_id: UUID, order_id: UUID) -> dict[str, Any]:
        """返回订单的状态与版本，不读取订单行。

        Args:
            tenant_id: 调用方租户。
            order_id: 目标订单。

        Returns:
            ``order_id``、``status`` 与 ``version``。

        Raises:
            ValueError: 订单不存在或不属于该租户。
        """

        order = await repositories.get_order(self.session, tenant_id, order_id)
        if order is None:
            raise ValueError("order not found")
        return {"order_id": str(order_id), "status": order.status, "version": order.version}

    async def address_validate(self, order_id: UUID, tenant_id: UUID) -> dict[str, Any]:
        """校验订单已存储的地址字段。

        Args:
            order_id: 目标订单。
            tenant_id: 调用方租户。

        Returns:
            ``valid`` 与 ``order_id``；``valid`` 表示六个地址字段是否满足地址
            校验规则。

        Raises:
            ValueError: 订单不存在或不属于该租户。

        Note:
            参数顺序是 ``order_id`` 在前，与其他读取方法相反；调用方应按位置或
            关键字传参以避免混淆。校验只读取已存储字段，不会修复订单。
        """

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
        """把订单拆分为多个发货单并预留库存。

        写服务负责提交；``dry_run`` 只校验并返回计划，不产生持久化副作用。

        Args:
            tenant_id: 调用方租户。
            order_id: 待拆分的订单。
            shipments: 发货明细列表；其多重集必须与订单行完全一致。
            idempotency_key: 幂等键；相同请求重放返回已存储的响应。
            dry_run: 为 ``True`` 时只做校验，不写入。
            actor_id: 操作者，用于审计。
            task_id: 触发写入的任务，用于审计。

        Returns:
            写服务返回的可序列化结果。

        Raises:
            write_service.WriteError: 结构或业务校验失败、目标行不在租户内、
                库存不足或幂等键冲突。
        """

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

    async def order_change_address(
        self,
        tenant_id: UUID,
        order_id: UUID,
        address: dict[str, str] | str,
        idempotency_key: str,
        dry_run: bool = False,
        actor_id: UUID | None = None,
        task_id: UUID | None = None,
    ) -> dict[str, Any]:
        """修改待处理订单的地址。

        写服务负责提交；``address`` 既可以是包含六个字段的完整地址对象，也可以
        是仅含 ``address_detail`` 的裸字符串，字符串形式会保留订单的其他地址
        字段。

        Args:
            tenant_id: 调用方租户。
            order_id: 待改址的订单。
            address: 完整地址对象或裸 ``address_detail`` 字符串。
            idempotency_key: 幂等键；相同请求重放返回已存储的响应。
            dry_run: 为 ``True`` 时只做校验，不写入。
            actor_id: 操作者，用于审计。
            task_id: 触发写入的任务，用于审计。

        Returns:
            写服务返回的可序列化结果。

        Raises:
            write_service.WriteError: 地址或状态校验失败、订单不在租户内或幂等
                键冲突。
        """

        return await write_service.change_address(
            self.session,
            tenant_id,
            order_id,
            address,
            idempotency_key,
            dry_run=dry_run,
            actor_id=actor_id,
            task_id=task_id,
        )

    async def order_revert_address(
        self,
        tenant_id: UUID,
        order_id: UUID,
        before_address: dict[str, str],
        idempotency_key: str,
        task_id: UUID | None = None,
    ) -> dict[str, Any]:
        """恢复上一次改址返回的地址快照。

        Args:
            tenant_id: 调用方租户。
            order_id: 目标订单。
            before_address: 之前 ``order_change_address`` 返回的六字段快照。
            idempotency_key: 幂等键；相同请求重放返回已存储的响应。
            task_id: 关联任务，用于审计。

        Returns:
            写服务返回的可序列化结果。

        Raises:
            write_service.WriteError: 快照无效、订单状态不允许或幂等键冲突。

        Warning:
            这是补偿路径的一部分，绕过审批门禁，仅供执行器内部调用。
        """

        return await write_service.revert_address(
            self.session,
            tenant_id,
            order_id,
            before_address,
            idempotency_key,
            task_id=task_id,
        )

    async def order_revert_split(
        self,
        tenant_id: UUID,
        order_id: UUID,
        idempotency_key: str,
        task_id: UUID | None = None,
    ) -> dict[str, Any]:
        """通过取消发货单并恢复订单来补偿一次拆分。

        Args:
            tenant_id: 调用方租户。
            order_id: 目标订单。
            idempotency_key: 幂等键；相同请求重放返回已存储的响应。
            task_id: 关联任务，用于审计。

        Returns:
            写服务返回的可序列化结果。

        Raises:
            write_service.WriteError: 订单状态不允许或幂等键冲突。

        Warning:
            这是补偿路径的一部分，绕过审批门禁，仅供执行器内部调用。
        """

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
        """取消一个发货单并释放其预留库存。

        Args:
            tenant_id: 调用方租户。
            shipment_id: 目标发货单。
            idempotency_key: 幂等键；相同请求重放返回已存储的响应。
            task_id: 关联任务，用于审计。

        Returns:
            写服务返回的可序列化结果。

        Raises:
            write_service.WriteError: 发货单不在租户内、状态不允许或幂等键冲突。

        Warning:
            这是补偿路径的一部分，绕过审批门禁，仅供执行器内部调用。
        """

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
        """释放订单所有活动发货单的预留库存。

        Args:
            tenant_id: 调用方租户。
            order_id: 目标订单。
            idempotency_key: 幂等键；相同请求重放返回已存储的响应。
            task_id: 关联任务，用于审计。

        Returns:
            写服务返回的可序列化结果。

        Raises:
            write_service.WriteError: 订单状态不允许或幂等键冲突。

        Warning:
            这是补偿路径的一部分，绕过审批门禁，仅供执行器内部调用。
        """

        return await write_service.release_inventory(
            self.session, tenant_id, order_id, idempotency_key, task_id=task_id
        )
