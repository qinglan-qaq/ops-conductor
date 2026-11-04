"""MCP stdio 服务器，暴露按租户限定的 ERP 读取与写入工具。

每个工具的第一个参数都是 ``tenant_id``，调用方必须传入自己已认证的租户；服务端
用它限定所有查询与写入。工具结果必须是可 JSON 序列化的字典，由 MCP 客户端直接
返回或持久化。

Invariants:

- ``tenant_id`` 是调用方作用域：工具绝不根据订单、SKU 或发货单 ID 推断租户。
- 写工具（``order_split``、``order_change_address``）在校验通过前调用
  :func:`require_approved_write`；拒绝会转换为 MCP ``ToolError``，客户端再映射为
  403。
- 补偿工具（``order_revert_*``、``shipment_cancel``、``inventory_release``）是
  内部/绕过边界：它们不经过审批门禁，只由执行器的补偿流程调用。
- 读工具目前不写审计；写工具的审计由写服务与审批门禁负责。
"""

from typing import Any
from uuid import UUID

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from opsconductor.db import SessionLocal
from opsconductor.tools.guard import ToolAccessDenied, require_approved_write
from opsconductor.tools.service import ErpToolService

server = MCPServer("opsconductor-erp")


def _optional_uuid(value: str | None) -> UUID | None:
    """把非空字符串转换为 ``UUID``，空值返回 ``None``。

    Args:
        value: 可选的 UUID 字符串。

    Returns:
        解析后的 UUID；``None`` 或空字符串返回 ``None``。

    Raises:
        ValueError: 非空值不是合法 UUID。
    """

    return UUID(value) if value else None


@server.tool(name="order_list_overdue")
async def order_list_overdue(tenant_id: str, warehouse: str | None = None) -> dict[str, Any]:
    """列出调用方租户内逾期的订单。

    Args:
        tenant_id: 调用方租户的 UUID 字符串。
        warehouse: 可选的仓库过滤条件。

    Returns:
        ``{"orders": [...]}``；每项包含订单 ``id``、``order_no`` 与 ``status``。

    Raises:
        ValueError: ``tenant_id`` 不是合法 UUID。

    Note:
        读工具不写审计；``tenant_id`` 只限定范围，鉴权由 API 层完成。
    """

    async with SessionLocal() as session:
        orders = await ErpToolService(session).order_list_overdue(UUID(tenant_id), warehouse)
        return {"orders": orders}


@server.tool(name="order_get")
async def order_get(tenant_id: str, order_id: str) -> dict[str, Any]:
    """返回一个订单的头部、地址与订单行。

    Args:
        tenant_id: 调用方租户的 UUID 字符串。
        order_id: 目标订单的 UUID 字符串。

    Returns:
        订单字典；UUID 以字符串表示，``lines`` 为 SKU 与数量列表。

    Raises:
        ValueError: ID 不是合法 UUID，或订单不存在。

    Note:
        查询按租户过滤，其他租户的订单表现为不存在，不会泄露其存在性；读工具
        不写审计。
    """

    async with SessionLocal() as session:
        return await ErpToolService(session).order_get(UUID(tenant_id), UUID(order_id))


@server.tool(name="inventory_get")
async def inventory_get(
    tenant_id: str, sku_id: str, warehouse_id: str
) -> dict[str, Any]:
    """返回某 SKU 在某仓库的库存快照。

    Args:
        tenant_id: 调用方租户的 UUID 字符串。
        sku_id: 目标 SKU 的 UUID 字符串。
        warehouse_id: 目标仓库的 UUID 字符串。

    Returns:
        包含 ``available``、``reserved`` 与 ``version`` 的字典。

    Raises:
        ValueError: ID 不是合法 UUID，或库存行不存在。

    Note:
        库存行按租户限定；读工具不写审计。
    """

    async with SessionLocal() as session:
        return await ErpToolService(session).inventory_get(
            UUID(tenant_id), UUID(sku_id), UUID(warehouse_id)
        )


@server.tool(name="shipment_list")
async def shipment_list(tenant_id: str, order_id: str) -> dict[str, Any]:
    """列出订单的发货单摘要。

    Args:
        tenant_id: 调用方租户的 UUID 字符串。
        order_id: 目标订单的 UUID 字符串。

    Returns:
        ``{"shipments": [...]}``；每项包含发货单 ``id`` 与 ``status``。

    Raises:
        ValueError: ID 不是合法 UUID。

    Note:
        读工具不写审计；订单不存在时返回空列表。
    """

    async with SessionLocal() as session:
        shipments = await ErpToolService(session).shipment_list(
            UUID(tenant_id), UUID(order_id)
        )
        return {"shipments": shipments}


@server.tool(name="order_get_state")
async def order_get_state(tenant_id: str, order_id: str) -> dict[str, Any]:
    """返回订单的状态与版本。

    Args:
        tenant_id: 调用方租户的 UUID 字符串。
        order_id: 目标订单的 UUID 字符串。

    Returns:
        ``order_id``、``status`` 与 ``version``。

    Raises:
        ValueError: ID 不是合法 UUID，或订单不存在。

    Note:
        读工具不写审计；该工具不读取订单行。
    """

    async with SessionLocal() as session:
        return await ErpToolService(session).order_get_state(
            UUID(tenant_id), UUID(order_id)
        )


@server.tool(name="address_validate")
async def address_validate(tenant_id: str, order_id: str) -> dict[str, Any]:
    """校验订单已存储的地址字段。

    Args:
        tenant_id: 调用方租户的 UUID 字符串。
        order_id: 目标订单的 UUID 字符串。

    Returns:
        ``valid`` 与 ``order_id``；``valid`` 表示六个地址字段是否完整合法。

    Raises:
        ValueError: ID 不是合法 UUID，或订单不存在。

    Note:
        只读取并校验已存储字段，不修复订单；读工具不写审计。
    """

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
    """把待处理订单拆分为发货单并原子预留库存。

    Args:
        tenant_id: 调用方租户的 UUID 字符串。
        order_id: 待拆分订单的 UUID 字符串。
        shipments: 发货明细列表；其多重集必须与订单行完全一致。
        idempotency_key: 幂等键；相同请求重放返回已存储的响应。
        dry_run: 为 ``True`` 时只校验并返回计划，不写入。
        actor_id: 操作者 UUID 字符串，用于审计。
        task_id: 拥有已审批计划节点的任务 UUID 字符串；写工具必填。

    Returns:
        写服务返回的可序列化载荷。

    Raises:
        ToolError: 审批门禁拒绝时，消息以 ``TOOL_ACCESS_DENIED`` 开头。
        write_service.WriteError: 校验失败、库存不足或幂等冲突等服务层错误。
        ValueError: ID 不是合法 UUID。

    Note:
        门禁要求 ``task_id``、订单与 ``split_order`` 动作三者都匹配已批准的
        审批；``dry_run`` 同样需要审批，因为门禁在写入前统一执行。
    """

    async with SessionLocal() as session:
        tenant_uuid = UUID(tenant_id)
        order_uuid = UUID(order_id)
        try:
            await require_approved_write(
                session,
                tenant_id=tenant_uuid,
                task_id=_optional_uuid(task_id),
                order_id=order_uuid,
                tool="order_split",
                actor_id=_optional_uuid(actor_id),
            )
        except ToolAccessDenied as exc:
            raise ToolError(str(exc)) from exc
        return await ErpToolService(session).order_split(
            tenant_uuid,
            order_uuid,
            shipments,
            idempotency_key,
            dry_run=dry_run,
            actor_id=_optional_uuid(actor_id),
            task_id=_optional_uuid(task_id),
        )


@server.tool(name="order_change_address")
async def order_change_address(
    tenant_id: str,
    order_id: str,
    address: dict[str, Any] | str,
    idempotency_key: str,
    dry_run: bool = False,
    actor_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """在发货前修改待处理订单的地址。

    Args:
        tenant_id: 调用方租户的 UUID 字符串。
        order_id: 待改址订单的 UUID 字符串。
        address: 包含六个地址字段的完整对象，或仅含 ``address_detail`` 的裸
            字符串；字符串形式会保留订单的其他地址字段。
        idempotency_key: 幂等键；相同请求重放返回已存储的响应。
        dry_run: 为 ``True`` 时只校验并返回计划，不写入。
        actor_id: 操作者 UUID 字符串，用于审计。
        task_id: 拥有已审批计划节点的任务 UUID 字符串；写工具必填。

    Returns:
        写服务返回的可序列化载荷。

    Raises:
        ToolError: 审批门禁拒绝时，消息以 ``TOOL_ACCESS_DENIED`` 开头。
        write_service.WriteError: 地址或状态校验失败、订单不在租户内或幂等冲突。
        ValueError: ID 不是合法 UUID。

    Note:
        与 ``order_split`` 相同，门禁要求 ``task_id``、订单与 ``change_address``
        动作匹配已批准的审批，``dry_run`` 也不例外。
    """

    async with SessionLocal() as session:
        tenant_uuid = UUID(tenant_id)
        order_uuid = UUID(order_id)
        try:
            await require_approved_write(
                session,
                tenant_id=tenant_uuid,
                task_id=_optional_uuid(task_id),
                order_id=order_uuid,
                tool="order_change_address",
                actor_id=_optional_uuid(actor_id),
            )
        except ToolAccessDenied as exc:
            raise ToolError(str(exc)) from exc
        return await ErpToolService(session).order_change_address(
            tenant_uuid,
            order_uuid,
            address,
            idempotency_key,
            dry_run=dry_run,
            actor_id=_optional_uuid(actor_id),
            task_id=_optional_uuid(task_id),
        )


@server.tool(name="order_revert_address")
async def order_revert_address(
    tenant_id: str,
    order_id: str,
    before_address: dict[str, Any],
    idempotency_key: str,
    task_id: str | None = None,
) -> dict[str, Any]:
    """补偿工具：恢复改址操作返回的地址快照。

    Args:
        tenant_id: 调用方租户的 UUID 字符串。
        order_id: 目标订单的 UUID 字符串。
        before_address: 之前 ``order_change_address`` 返回的六字段快照。
        idempotency_key: 幂等键；相同请求重放返回已存储的响应。
        task_id: 关联任务 UUID 字符串，用于审计。

    Returns:
        写服务返回的可序列化载荷。

    Raises:
        write_service.WriteError: 快照无效、订单状态不允许或幂等冲突。
        ValueError: ID 不是合法 UUID。

    Warning:
        这是内部/绕过边界：它不经过审批门禁，仅供执行器补偿流程调用；外部调用
        方不应直接使用。
    """

    async with SessionLocal() as session:
        return await ErpToolService(session).order_revert_address(
            UUID(tenant_id),
            UUID(order_id),
            before_address,
            idempotency_key,
            task_id=_optional_uuid(task_id),
        )


@server.tool(name="shipment_cancel")
async def shipment_cancel(
    tenant_id: str,
    shipment_id: str,
    idempotency_key: str,
    task_id: str | None = None,
) -> dict[str, Any]:
    """补偿工具：取消一个发货单并释放其预留库存。

    Args:
        tenant_id: 调用方租户的 UUID 字符串。
        shipment_id: 目标发货单的 UUID 字符串。
        idempotency_key: 幂等键；相同请求重放返回已存储的响应。
        task_id: 关联任务 UUID 字符串，用于审计。

    Returns:
        写服务返回的可序列化载荷。

    Raises:
        write_service.WriteError: 发货单不在租户内、状态不允许或幂等冲突。
        ValueError: ID 不是合法 UUID。

    Warning:
        这是内部/绕过边界：它不经过审批门禁，仅供执行器补偿流程调用；外部调用
        方不应直接使用。
    """

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
    """补偿工具：释放订单所有活动发货单的预留库存。

    Args:
        tenant_id: 调用方租户的 UUID 字符串。
        order_id: 目标订单的 UUID 字符串。
        idempotency_key: 幂等键；相同请求重放返回已存储的响应。
        task_id: 关联任务 UUID 字符串，用于审计。

    Returns:
        写服务返回的可序列化载荷。

    Raises:
        write_service.WriteError: 订单状态不允许或幂等冲突。
        ValueError: ID 不是合法 UUID。

    Warning:
        这是内部/绕过边界：它不经过审批门禁，仅供执行器补偿流程调用；外部调用
        方不应直接使用。
    """

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
    """补偿工具：取消发货单、释放库存并恢复订单。

    Args:
        tenant_id: 调用方租户的 UUID 字符串。
        order_id: 目标订单的 UUID 字符串。
        idempotency_key: 幂等键；相同请求重放返回已存储的响应。
        task_id: 关联任务 UUID 字符串，用于审计。

    Returns:
        写服务返回的可序列化载荷。

    Raises:
        write_service.WriteError: 订单状态不允许或幂等冲突。
        ValueError: ID 不是合法 UUID。

    Warning:
        这是内部/绕过边界：它不经过审批门禁，仅供执行器补偿流程调用；外部调用
        方不应直接使用。
    """

    async with SessionLocal() as session:
        return await ErpToolService(session).order_revert_split(
            UUID(tenant_id),
            UUID(order_id),
            idempotency_key,
            task_id=_optional_uuid(task_id),
        )


if __name__ == "__main__":
    server.run(transport="stdio")
