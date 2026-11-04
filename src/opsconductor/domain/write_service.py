"""带幂等与补偿的订单事务写入操作。

服务拥有它开启的每个事务边界：:func:`split_order`、:func:`change_address`、
:func:`revert_address`、:func:`cancel_split`、:func:`cancel_shipment` 与
:func:`release_inventory` 在返回前提交，任何失败都会回滚。审计辅助函数只在调用方
会话上暂存并 flush 审计行，因此审计记录恰好在业务变更提交时可见。

Invariants:

- 所有读写都按 ``tenant_id`` 限定作用域。仅有 ID 从不足以证明调用方可以访问某个
  订单、发货单或库存行。
- 写入由幂等作用域加请求指纹保护。以不同请求复用键会抛出
  :class:`IdempotencyConflict`；重放完全相同的请求会原样返回已存储的响应。
- ``split_order`` 以发货单为单位且要么全部成功、要么全部失败：请求的发货明细必须
  与订单明细作为多重集完全一致，任一仓库中任一 SKU 缺货都会拒绝整次拆分。
- 补偿按订单归属：只释放属于目标订单与发货单的流水行，因此补偿一个订单永远不会
  消耗另一个订单的预留。
"""

import hashlib
import json
import uuid
from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from opsconductor.domain.address import (
    ADDRESS_FIELDS,
    address_fields_are_valid,
    order_address,
)
from opsconductor.domain.models import (
    IdempotencyKey,
    Inventory,
    InventoryLedger,
    OrderLine,
    SalesOrder,
    Shipment,
    ShipmentLine,
)
from opsconductor.observability.audit import write_audit

__all__ = [
    "IdempotencyConflict",
    "InsufficientStock",
    "InvalidState",
    "NotFound",
    "ValidationError",
    "WriteError",
    "cancel_shipment",
    "cancel_split",
    "change_address",
    "release_inventory",
    "revert_address",
    "split_order",
]

SPLIT_RESERVATION_REASON = "order_split"
SPLIT_COMPENSATION_REASON = "split_compensation"
_RESERVATION_REASONS = (SPLIT_RESERVATION_REASON, SPLIT_COMPENSATION_REASON)


class WriteError(Exception):
    """写入路径失败的基类，携带稳定的工具错误码。"""

    code = "WRITE_ERROR"


class ValidationError(WriteError):
    """请求未通过结构或业务校验（``VALIDATION_ERROR``）。"""

    code = "VALIDATION_ERROR"


class NotFound(WriteError):
    """目标行在调用方租户内不存在（``NOT_FOUND``）。"""

    code = "NOT_FOUND"


class InvalidState(WriteError):
    """资源状态不允许请求的转换（``INVALID_STATE``）。"""

    code = "INVALID_STATE"


class InsufficientStock(WriteError):
    """请求数量超过可用库存（``INSUFFICIENT_STOCK``）。"""

    code = "INSUFFICIENT_STOCK"


class IdempotencyConflict(WriteError):
    """幂等键被复用于不同请求（``CONFLICT``）。"""

    code = "CONFLICT"


def _split_scope(order_id: UUID) -> str:
    return f"order.split:{order_id}"


def _cancel_split_scope(order_id: UUID) -> str:
    return f"order.split.cancel:{order_id}"


def _shipment_cancel_scope(shipment_id: UUID) -> str:
    return f"shipment.cancel:{shipment_id}"


def _inventory_release_scope(order_id: UUID) -> str:
    return f"inventory.release:{order_id}"


def _change_address_scope(order_id: UUID) -> str:
    return f"order.change_address:{order_id}"


def _revert_address_scope(order_id: UUID) -> str:
    return f"order.change_address.revert:{order_id}"


def _request_hash(payload: Any) -> str:
    """将请求负载哈希为稳定的幂等指纹。

    Args:
        payload: 类 JSON 请求数据。哈希前会对键排序，非 JSON 值回退为
            ``str``。

    Returns:
        规范化 JSON 编码的小写 SHA-256 十六进制摘要。
    """

    encoded = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validate_idempotency_key(idempotency_key: Any) -> str:
    """校验并返回调用方提供的幂等键。

    Args:
        idempotency_key: 待校验的键。

    Returns:
        当键是长度不超过 200 的非空白字符串时原样返回。

    Raises:
        ValidationError: 键不是字符串、为空白或超过 200 个字符。
    """

    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise ValidationError("idempotency_key must be a non-empty string")
    if len(idempotency_key) > 200:
        raise ValidationError("idempotency_key must be at most 200 characters")
    return idempotency_key


def _as_uuid(value: Any, field: str) -> UUID:
    """将请求值转换为 ``UUID``。

    Args:
        value: 已有 UUID 或可被 ``UUID`` 接受的字符串。
        field: 错误消息中使用的字段名。

    Returns:
        解析后的 UUID。

    Raises:
        ValidationError: 值无法转换为 UUID。
    """

    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValidationError(f"{field} must be a UUID") from exc


def _normalize_address_object(value: Any, field: str) -> dict[str, str]:
    """要求完整的六字段地址对象并归一化其字符串。

    Args:
        value: 待校验的地址映射。
        field: 错误消息中使用的字段名。

    Returns:
        仅包含 ``ADDRESS_FIELDS`` 的新映射，每个值已去除首尾空白。

    Raises:
        ValidationError: 值不是映射、缺少字段、含未知字段或存在非字符串值。
    """

    if not isinstance(value, dict):
        raise ValidationError(f"{field} must be an address object")
    missing = [name for name in ADDRESS_FIELDS if name not in value]
    if missing:
        raise ValidationError(f"{field} is missing fields: " + ", ".join(missing))
    unknown = sorted(str(name) for name in value if name not in ADDRESS_FIELDS)
    if unknown:
        raise ValidationError(f"{field} has unknown fields: " + ", ".join(unknown))

    normalized: dict[str, str] = {}
    for name in ADDRESS_FIELDS:
        item = value[name]
        if not isinstance(item, str):
            raise ValidationError(f"{field}.{name} must be a string")
        normalized[name] = item.strip()
    return normalized


def _normalize_new_address(new_address: Any) -> dict[str, str]:
    """将改址请求归一化为完整或部分地址映射。

    字典必须携带全部六个地址字段。裸字符串是规划器的便捷形式：它替换
    ``address_detail``，其余字段在应用变更时保留自当前订单。

    Args:
        new_address: 完整六字段地址映射或裸 ``address_detail`` 字符串。

    Returns:
        完整地址映射；字符串形式则返回仅含 ``address_detail`` 的部分映射。

    Raises:
        ValidationError: 值格式错误或字符串为空。
    """

    if isinstance(new_address, str):
        detail = new_address.strip()
        if not detail:
            raise ValidationError("new_address must not be empty")
        return {"address_detail": detail}
    return _normalize_address_object(new_address, "new_address")


def _normalize_shipments(shipments: Any) -> list[dict[str, Any]]:
    """校验请求结构并将 ID 归一化为 ``UUID`` 对象。

    Args:
        shipments: 请求的发货单，每项为含 ``warehouse_id`` 与非空 ``lines``
            的映射，``lines`` 中每项为 ``sku_id``/``qty`` 映射。

    Returns:
        归一化后的发货单列表，仓库与 SKU UUID 已解析，数量为正整数。

    Raises:
        ValidationError: 列表为空，或任一项、明细、ID、数量格式错误。
    """

    if not isinstance(shipments, list) or not shipments:
        raise ValidationError("shipments must be a non-empty list")

    normalized: list[dict[str, Any]] = []
    for index, entry in enumerate(shipments):
        if not isinstance(entry, dict):
            raise ValidationError(f"shipments[{index}] must be an object")
        warehouse_id = _as_uuid(
            entry.get("warehouse_id"), f"shipments[{index}].warehouse_id"
        )
        lines = entry.get("lines")
        if not isinstance(lines, list) or not lines:
            raise ValidationError(f"shipments[{index}].lines must be a non-empty list")

        normalized_lines: list[dict[str, Any]] = []
        for line_index, line in enumerate(lines):
            label = f"shipments[{index}].lines[{line_index}]"
            if not isinstance(line, dict):
                raise ValidationError(f"{label} must be an object")
            sku_id = _as_uuid(line.get("sku_id"), f"{label}.sku_id")
            qty = line.get("qty")
            if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
                raise ValidationError(f"{label}.qty must be a positive integer")
            normalized_lines.append({"sku_id": sku_id, "qty": qty})
        normalized.append({"warehouse_id": warehouse_id, "lines": normalized_lines})
    return normalized


def _canonical_shipments(shipments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """返回用于幂等哈希的 JSON 稳定表示。

    Args:
        shipments: 含 UUID 标识符的归一化发货单。

    Returns:
        标识符渲染为字符串的相同发货单，保留调用方的发货单与明细顺序。
    """

    return [
        {
            "warehouse_id": str(entry["warehouse_id"]),
            "lines": [
                {"sku_id": str(line["sku_id"]), "qty": line["qty"]}
                for line in entry["lines"]
            ],
        }
        for entry in shipments
    ]


async def _find_idempotency(
    session: AsyncSession, tenant_id: UUID, scope: str, key: str
) -> IdempotencyKey | None:
    """返回 tenant/scope/key 三元组对应的幂等记录（若存在）。

    Args:
        session: 调用方会话。
        tenant_id: 拥有该记录的租户；其他租户的同名键互不相关。
        scope: 操作作用域字符串。
        key: 调用方提供的幂等键。

    Returns:
        匹配的记录；键未被使用时返回 ``None``。
    """

    return await session.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.tenant_id == tenant_id,
            IdempotencyKey.scope == scope,
            IdempotencyKey.key == key,
        )
    )


async def _replay(
    session: AsyncSession,
    tenant_id: UUID,
    scope: str,
    key: str,
    fingerprint: str,
) -> dict[str, Any] | None:
    """返回已存储的响应；键未被使用时返回 ``None``。

    Args:
        session: 调用方会话；查询不会提交。
        tenant_id: 拥有幂等记录的租户。
        scope: 记录的操作作用域。
        key: 调用方提供的幂等键。
        fingerprint: 当前请求负载的哈希。

    Returns:
        当键用于完全相同的请求时返回已存储的响应映射，否则返回 ``None``。

    Raises:
        IdempotencyConflict: 键曾用于不同请求，或记录存在但没有已存储的响应。
    """

    record = await _find_idempotency(session, tenant_id, scope, key)
    if record is None:
        return None
    if record.request_hash != fingerprint:
        raise IdempotencyConflict(
            f"idempotency key {key!r} was used with a different request"
        )
    if record.response is None:
        raise IdempotencyConflict(f"idempotency key {key!r} is still in progress")
    return record.response


async def _commit_or_replay(
    session: AsyncSession,
    tenant_id: UUID,
    scope: str,
    key: str,
    fingerprint: str,
) -> dict[str, Any] | None:
    """提交；若键冲突，则返回并发已提交的响应。

    幂等行最后才暂存，因此使用相同键的竞争请求会在提交时而非 flush 时触发唯一
    约束。

    Args:
        session: 持有待提交写入的会话。
        tenant_id: 拥有幂等记录的租户。
        scope: 记录的操作作用域。
        key: 调用方提供的幂等键。
        fingerprint: 当前请求负载的哈希。

    Returns:
        若另一请求先提交了相同键，返回胜出的响应；否则本请求正常提交后返回
        ``None``。

    Raises:
        IdempotencyConflict: 冲突记录的指纹不同。
        IntegrityError: 完整性约束冲突与本次幂等键无关。
    """

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        replay = await _replay(session, tenant_id, scope, key, fingerprint)
        if replay is None:
            raise
        return replay
    return None


async def _lock_order(
    session: AsyncSession, tenant_id: UUID, order_id: UUID
) -> SalesOrder | None:
    """在事务期间锁定单个订单行。

    Args:
        session: 持有锁的事务所在会话。
        tenant_id: 必须拥有该订单的租户。
        order_id: 待锁定的订单。

    Returns:
        已锁定的订单；在该租户内不存在时返回 ``None``。
    """

    return await session.scalar(
        select(SalesOrder)
        .where(SalesOrder.tenant_id == tenant_id, SalesOrder.id == order_id)
        .with_for_update()
    )


async def _lock_inventory(
    session: AsyncSession, tenant_id: UUID, sku_id: UUID, warehouse_id: UUID
) -> Inventory | None:
    """在事务期间锁定单个库存行。

    Args:
        session: 持有锁的事务所在会话。
        tenant_id: 必须拥有该库存行的租户。
        sku_id: 锁定库存的 SKU。
        warehouse_id: 持有库存的仓库。

    Returns:
        已锁定的库存行；该租户与库位组合没有记录时返回 ``None``。
    """

    return await session.scalar(
        select(Inventory)
        .where(
            Inventory.tenant_id == tenant_id,
            Inventory.sku_id == sku_id,
            Inventory.warehouse_id == warehouse_id,
        )
        .with_for_update()
    )


async def _validate_shipment_coverage(
    session: AsyncSession,
    tenant_id: UUID,
    order_id: UUID,
    shipments: list[dict[str, Any]],
) -> None:
    """要求发货明细与订单明细作为多重集完全一致。

    每个订单 SKU 必须被足量发货，且不得出现订单之外的 SKU。该校验在锁定库存或
    暂存任何行之前执行，因此少发或外来 SKU 永远不会把订单推进到 ``split``。

    Args:
        session: 用于租户限定明细查询的会话。
        tenant_id: 拥有该订单的租户。
        order_id: 正在拆分的订单。
        shipments: 来自请求的归一化发货单。

    Raises:
        ValidationError: 任一 SKU 的发货数量与订单数量不同。
    """

    order_lines = list(
        (
            await session.scalars(
                select(OrderLine).where(
                    OrderLine.tenant_id == tenant_id,
                    OrderLine.order_id == order_id,
                )
            )
        ).all()
    )
    expected: dict[UUID, int] = defaultdict(int)
    for line in order_lines:
        expected[line.sku_id] += line.qty

    shipped: dict[UUID, int] = defaultdict(int)
    for entry in shipments:
        for line in entry["lines"]:
            shipped[line["sku_id"]] += line["qty"]

    if dict(shipped) == dict(expected):
        return

    missing = {
        sku_id: expected[sku_id] - shipped.get(sku_id, 0)
        for sku_id in expected
        if shipped.get(sku_id, 0) < expected[sku_id]
    }
    extra = {
        sku_id: shipped[sku_id] - expected.get(sku_id, 0)
        for sku_id in shipped
        if shipped[sku_id] > expected.get(sku_id, 0)
    }
    details: list[str] = []
    if missing:
        details.append(
            "missing "
            + ", ".join(
                f"SKU {sku_id} qty {qty}"
                for sku_id, qty in sorted(missing.items(), key=lambda item: str(item[0]))
            )
        )
    if extra:
        details.append(
            "unexpected "
            + ", ".join(
                f"SKU {sku_id} qty {qty}"
                for sku_id, qty in sorted(extra.items(), key=lambda item: str(item[0]))
            )
        )
    raise ValidationError(
        f"shipments do not match order {order_id} lines: " + "; ".join(details)
    )


async def _plan_inventory(
    session: AsyncSession,
    tenant_id: UUID,
    shipments: list[dict[str, Any]],
) -> tuple[dict[tuple[UUID, UUID], Inventory], list[dict[str, Any]]]:
    """锁定所有受影响的库存行，并证明整体需求可被满足。

    库存检查前先按 SKU/仓库聚合需求，因此跨发货单的重复明细无法各自通过而总需求
    却会失败。行按确定的 SKU/仓库顺序加锁，避免并发拆分之间发生死锁。

    Args:
        session: 持有锁的事务所在会话。
        tenant_id: 拥有库存行的租户。
        shipments: 待检查需求的归一化发货单。

    Returns:
        以 ``(warehouse_id, sku_id)`` 为键的已锁定库存行，以及逐行描述需求与当前
        库存的 JSON 可序列化影响列表。

    Raises:
        InsufficientStock: 任一 SKU 缺少库存行，或可用库存低于聚合需求。
    """

    demand: dict[tuple[UUID, UUID], int] = defaultdict(int)
    for entry in shipments:
        for line in entry["lines"]:
            demand[(entry["warehouse_id"], line["sku_id"])] += line["qty"]

    inventory_rows: dict[tuple[UUID, UUID], Inventory] = {}
    impact: list[dict[str, Any]] = []
    for warehouse_id, sku_id in sorted(demand, key=lambda item: (str(item[0]), str(item[1]))):
        qty = demand[(warehouse_id, sku_id)]
        inventory = await _lock_inventory(session, tenant_id, sku_id, warehouse_id)
        if inventory is None:
            raise InsufficientStock(
                f"insufficient stock for SKU {sku_id} in warehouse {warehouse_id}: "
                f"no inventory row (required {qty})"
            )
        if inventory.available < qty:
            raise InsufficientStock(
                f"insufficient stock for SKU {sku_id} in warehouse {warehouse_id}: "
                f"required {qty}, available {inventory.available}"
            )
        inventory_rows[(warehouse_id, sku_id)] = inventory
        impact.append(
            {
                "sku_id": str(sku_id),
                "warehouse_id": str(warehouse_id),
                "qty": qty,
                "available": inventory.available,
                "reserved": inventory.reserved,
                "version": inventory.version,
            }
        )
    return inventory_rows, impact


async def _shipment_lines(
    session: AsyncSession, tenant_id: UUID, shipment_id: UUID
) -> list[ShipmentLine]:
    return list(
        (
            await session.scalars(
                select(ShipmentLine).where(
                    ShipmentLine.tenant_id == tenant_id,
                    ShipmentLine.shipment_id == shipment_id,
                )
            )
        ).all()
    )


async def _release_shipment_stock(
    session: AsyncSession,
    tenant_id: UUID,
    shipment: Shipment,
    task_id: UUID | None,
) -> list[dict[str, Any]]:
    """将单个发货单的预留释放回可用库存。

    只释放归属该订单与该发货单的流水行。归属的净预留仍必须等于发货明细，否则释放
    失败关闭，而不是消耗可能属于其他订单的聚合 ``inventory.reserved``。正是这种
    按订单归属保证了补偿不会释放其他订单的库存。

    Args:
        session: 持有事务的会话；由调用方提交。
        tenant_id: 拥有该发货单与流水行的租户。
        shipment: 待释放预留的发货单。
        task_id: 记入补偿流水行的任务（若有）。

    Returns:
        每条已释放明细对应一个 ``sku_id``/``warehouse_id``/``qty`` 映射。

    Raises:
        InvalidState: 发货单没有明细或没有预留流水、流水引用其他仓库、净预留与
            发货明细不匹配，或库存行缺失/预留不足。
    """

    lines = await _shipment_lines(session, tenant_id, shipment.id)
    if not lines:
        raise InvalidState(f"shipment {shipment.id} has no lines")

    demand: dict[UUID, int] = defaultdict(int)
    for line in lines:
        demand[line.sku_id] += line.qty

    ledger_rows = list(
        (
            await session.scalars(
                select(InventoryLedger).where(
                    InventoryLedger.tenant_id == tenant_id,
                    InventoryLedger.order_id == shipment.order_id,
                    InventoryLedger.shipment_id == shipment.id,
                    InventoryLedger.reason.in_(_RESERVATION_REASONS),
                )
            )
        ).all()
    )
    if not ledger_rows:
        raise InvalidState(
            f"no reservation ledger for shipment {shipment.id}; refusing to "
            "release aggregate inventory"
        )

    balance: dict[UUID, int] = defaultdict(int)
    for row in ledger_rows:
        if row.warehouse_id != shipment.warehouse_id:
            raise InvalidState(
                f"reservation ledger for shipment {shipment.id} references "
                f"warehouse {row.warehouse_id}, expected {shipment.warehouse_id}"
            )
        balance[row.sku_id] += row.delta_reserved

    if set(balance) != set(demand) or any(
        balance[sku_id] != qty for sku_id, qty in demand.items()
    ):
        raise InvalidState(
            f"reservation ledger for shipment {shipment.id} does not match "
            "shipment lines"
        )

    inventory_rows: dict[UUID, Inventory] = {}
    for sku_id in sorted(demand, key=str):
        inventory = await _lock_inventory(
            session, tenant_id, sku_id, shipment.warehouse_id
        )
        if inventory is None:
            raise InvalidState(
                f"inventory row missing for SKU {sku_id} in warehouse "
                f"{shipment.warehouse_id}"
            )
        if inventory.reserved < demand[sku_id]:
            raise InvalidState(
                f"reserved inventory for SKU {sku_id} in warehouse "
                f"{shipment.warehouse_id} is {inventory.reserved}, below shipment "
                f"reservation {demand[sku_id]}"
            )
        inventory_rows[sku_id] = inventory

    released: list[dict[str, Any]] = []
    for line in lines:
        inventory = inventory_rows[line.sku_id]
        inventory.available += line.qty
        inventory.reserved -= line.qty
        inventory.version += 1
        session.add(
            InventoryLedger(
                tenant_id=tenant_id,
                order_id=shipment.order_id,
                shipment_id=shipment.id,
                sku_id=line.sku_id,
                warehouse_id=shipment.warehouse_id,
                delta_available=line.qty,
                delta_reserved=-line.qty,
                reason=SPLIT_COMPENSATION_REASON,
                task_id=task_id,
            )
        )
        released.append(
            {
                "sku_id": str(line.sku_id),
                "warehouse_id": str(shipment.warehouse_id),
                "qty": line.qty,
            }
        )
    return released


async def _lock_order_shipments(
    session: AsyncSession, tenant_id: UUID, order_id: UUID
) -> list[Shipment]:
    """按创建顺序锁定某个订单的全部发货单。

    Args:
        session: 持有锁的事务所在会话。
        tenant_id: 拥有这些发货单的租户。
        order_id: 需要锁定发货单的订单。

    Returns:
        已锁定的发货单，按 ``created_at`` 再按 ``id`` 排序。
    """

    return list(
        (
            await session.scalars(
                select(Shipment)
                .where(
                    Shipment.tenant_id == tenant_id,
                    Shipment.order_id == order_id,
                )
                .order_by(Shipment.created_at, Shipment.id)
                .with_for_update()
            )
        ).all()
    )


async def change_address(
    session: AsyncSession,
    tenant_id: UUID,
    order_id: UUID,
    new_address: dict[str, str] | str,
    idempotency_key: str,
    dry_run: bool = False,
    actor_id: UUID | None = None,
    task_id: UUID | None = None,
) -> dict[str, Any]:
    """在订单被拆分或发货前修改其地址。

    ``new_address`` 要么是含全部六个字段的完整地址对象，要么是裸
    ``address_detail`` 字符串（规划器产出的形式）；字符串形式保留订单的其他
    地址字段。合并后的候选地址在写入任何内容之前完成校验。``dry_run`` 返回投影
    的前后地址而不暂存行。成功写入在返回前提交；服务拥有事务边界。

    写入按 ``(tenant, order, key)`` 作用域幂等。重复相同请求返回已存储的响应；
    将键复用于不同请求会抛出 :class:`IdempotencyConflict`。

    Args:
        session: 调用方的暂存会话；服务提交或回滚该事务。
        tenant_id: 必须拥有该订单的租户。
        order_id: 需要改址的订单。
        new_address: 完整六字段地址映射，或裸 ``address_detail`` 字符串。
        idempotency_key: 用于重放与冲突检查的调用方幂等键。
        dry_run: 只返回投影地址，不持久化任何内容。
        actor_id: 记入审计行的操作者（若已知）。
        task_id: 记入审计行的任务（若在任务内执行）。

    Returns:
        实际写入时返回订单 ID、订单号、状态 ``updated``、``before``/``after``
        地址以及递增后的版本号。重放时返回为该键存储的响应。``dry_run`` 时返回
        带 ``dry_run`` 标记且无持久化变更的映射。

    Raises:
        ValidationError: 键、地址结构或合并后的地址无效。
        NotFound: 该订单在此租户内不存在。
        InvalidState: 订单不是 ``pending_shipment``，或已存在发货单。
        IdempotencyConflict: 键被复用于不同请求。
    """

    idempotency_key = _validate_idempotency_key(idempotency_key)
    normalized = _normalize_new_address(new_address)
    scope = _change_address_scope(order_id)
    fingerprint = _request_hash(
        {"order_id": str(order_id), "new_address": normalized}
    )

    replay = await _replay(session, tenant_id, scope, idempotency_key, fingerprint)
    if replay is not None:
        return replay

    try:
        order = await _lock_order(session, tenant_id, order_id)
        if order is None:
            raise NotFound(f"order {order_id} not found for this tenant")
        if order.status != "pending_shipment":
            replay = await _replay(
                session, tenant_id, scope, idempotency_key, fingerprint
            )
            if replay is not None:
                await session.rollback()
                return replay
            raise InvalidState(
                f"order {order_id} is {order.status!r}, expected 'pending_shipment'"
            )
        existing_shipment = await session.scalar(
            select(Shipment.id)
            .where(Shipment.tenant_id == tenant_id, Shipment.order_id == order_id)
            .limit(1)
        )
        if existing_shipment is not None:
            raise InvalidState(f"order {order_id} already has shipments")

        before = order_address(order)
        after = {**before, **normalized}
        if not address_fields_are_valid(after):
            raise ValidationError(
                f"invalid address for order {order_id}: receiver_name, phone, "
                "province, city, district, and address_detail must be valid"
            )

        if dry_run:
            result = {
                "dry_run": True,
                "order_id": str(order_id),
                "order_no": order.order_no,
                "before": before,
                "after": after,
            }
            await session.rollback()
            return result

        for field in ADDRESS_FIELDS:
            setattr(order, field, after[field])
        order.version += 1
        response = {
            "order_id": str(order_id),
            "order_no": order.order_no,
            "status": "updated",
            "before": before,
            "after": after,
            "version": order.version,
        }
        await write_audit(
            session,
            tenant_id=tenant_id,
            task_id=task_id,
            actor_id=actor_id,
            action="order.change_address",
            entity_type="sales_order",
            entity_id=str(order_id),
            before=before,
            after=after,
            evidence={"version": order.version},
        )
        # Stage the idempotency row last: its unique constraint must surface at
        # the final commit so _commit_or_replay can replay the winning response.
        session.add(
            IdempotencyKey(
                tenant_id=tenant_id,
                scope=scope,
                key=idempotency_key,
                request_hash=fingerprint,
                response=response,
                status="completed",
            )
        )
        replayed = await _commit_or_replay(
            session, tenant_id, scope, idempotency_key, fingerprint
        )
        return replayed if replayed is not None else response
    except BaseException:
        await session.rollback()
        raise


async def revert_address(
    session: AsyncSession,
    tenant_id: UUID,
    order_id: UUID,
    before_address: dict[str, str],
    idempotency_key: str,
    task_id: UUID | None = None,
) -> dict[str, Any]:
    """通过恢复给定快照补偿一次改址。

    ``before_address`` 是原 ``change_address`` 调用返回的完整六字段 ``before``
    映射。恢复后的地址不会重新校验，因为原地址本身可能就是无效的（例如空的
    ``address_detail``）。写入按键幂等，并在返回前提交。

    Args:
        session: 调用方的暂存会话；服务提交或回滚该事务。
        tenant_id: 必须拥有该订单的租户。
        order_id: 需要恢复地址的订单。
        before_address: 原变更前捕获的完整六字段快照。
        idempotency_key: 用于重放与冲突检查的调用方幂等键。
        task_id: 记入审计行的任务（若在任务内执行）。

    Returns:
        订单 ID、订单号、状态 ``reverted``、当前与恢复后的地址以及递增后的版本
        号；重放时返回已存储的响应。

    Raises:
        ValidationError: 键或快照结构无效。
        NotFound: 该订单在此租户内不存在。
        IdempotencyConflict: 键被复用于不同请求。
    """

    idempotency_key = _validate_idempotency_key(idempotency_key)
    target = _normalize_address_object(before_address, "before_address")
    scope = _revert_address_scope(order_id)
    fingerprint = _request_hash(
        {"order_id": str(order_id), "before_address": target}
    )

    replay = await _replay(session, tenant_id, scope, idempotency_key, fingerprint)
    if replay is not None:
        return replay

    try:
        order = await _lock_order(session, tenant_id, order_id)
        if order is None:
            raise NotFound(f"order {order_id} not found for this tenant")

        current = order_address(order)
        for field in ADDRESS_FIELDS:
            setattr(order, field, target[field])
        order.version += 1
        response = {
            "order_id": str(order_id),
            "order_no": order.order_no,
            "status": "reverted",
            "before": current,
            "after": target,
            "version": order.version,
        }
        await write_audit(
            session,
            tenant_id=tenant_id,
            task_id=task_id,
            actor_id=None,
            action="order.change_address.revert",
            entity_type="sales_order",
            entity_id=str(order_id),
            before=current,
            after=target,
            evidence={"version": order.version},
        )
        # Stage the idempotency row last so a concurrent duplicate key fails at
        # commit and is replayed by _commit_or_replay instead of during a flush.
        session.add(
            IdempotencyKey(
                tenant_id=tenant_id,
                scope=scope,
                key=idempotency_key,
                request_hash=fingerprint,
                response=response,
                status="completed",
            )
        )
        replayed = await _commit_or_replay(
            session, tenant_id, scope, idempotency_key, fingerprint
        )
        return replayed if replayed is not None else response
    except BaseException:
        await session.rollback()
        raise


async def split_order(
    session: AsyncSession,
    tenant_id: UUID,
    order_id: UUID,
    shipments: list[dict[str, Any]],
    idempotency_key: str,
    dry_run: bool = False,
    actor_id: UUID | None = None,
    task_id: UUID | None = None,
) -> dict[str, Any]:
    """将待发货订单拆分为多个发货单，并原子地预留全部库存。

    发货单是拆分的单位：其明细必须与订单明细作为多重集一致，请求要么全部成功、
    要么全部失败。任一处缺货都会拒绝整个订单；不会写入部分发货单集合。
    ``dry_run`` 锁定并校验相同的行，但只返回影响而不暂存任何写入。成功调用在
    返回前提交。

    写入按 ``(tenant, order, key)`` 作用域幂等。重复相同的发货单会返回原始响应
    与发货单 ID。

    Args:
        session: 调用方的暂存会话；服务提交或回滚该事务。
        tenant_id: 必须拥有该订单与库存的租户。
        order_id: 正在拆分的订单。
        shipments: 带仓库 ID 与明细数量的请求发货单。
        idempotency_key: 用于重放与冲突检查的调用方幂等键。
        dry_run: 只校验并返回库存影响，不写入。
        actor_id: 记入审计行的操作者（若已知）。
        task_id: 记入流水与审计行的任务（若有）。

    Returns:
        实际写入时返回订单 ID、订单号、状态 ``split``、发货单数量与新发货单 ID。
        重放时返回已存储的响应。``dry_run`` 时返回发货单数量与逐行影响，无持久化
        变更。

    Raises:
        ValidationError: 键、发货单或订单明细覆盖无效。
        NotFound: 该订单在此租户内不存在。
        InvalidState: 订单不是 ``pending_shipment``，或已存在发货单。
        InsufficientStock: 任一 SKU 的库存不足以满足聚合需求。
        IdempotencyConflict: 键被复用于不同请求。

    Note:
        库存行按确定的 SKU/仓库顺序加锁，幂等行最后暂存，因此并发重复拆分在提交
        时解决。
    """

    idempotency_key = _validate_idempotency_key(idempotency_key)
    normalized = _normalize_shipments(shipments)
    scope = _split_scope(order_id)
    fingerprint = _request_hash(
        {"order_id": str(order_id), "shipments": _canonical_shipments(normalized)}
    )

    replay = await _replay(session, tenant_id, scope, idempotency_key, fingerprint)
    if replay is not None:
        return replay

    try:
        order = await _lock_order(session, tenant_id, order_id)
        if order is None:
            raise NotFound(f"order {order_id} not found for this tenant")
        if order.status != "pending_shipment":
            replay = await _replay(
                session, tenant_id, scope, idempotency_key, fingerprint
            )
            if replay is not None:
                await session.rollback()
                return replay
            raise InvalidState(
                f"order {order_id} is {order.status!r}, expected 'pending_shipment'"
            )
        existing_shipment = await session.scalar(
            select(Shipment.id)
            .where(Shipment.tenant_id == tenant_id, Shipment.order_id == order_id)
            .limit(1)
        )
        if existing_shipment is not None:
            raise InvalidState(f"order {order_id} already has shipments")

        await _validate_shipment_coverage(
            session, tenant_id, order_id, normalized
        )
        inventory_rows, impact = await _plan_inventory(
            session, tenant_id, normalized
        )

        if dry_run:
            result = {
                "dry_run": True,
                "order_id": str(order_id),
                "order_no": order.order_no,
                "shipments": len(normalized),
                "impact": impact,
            }
            await session.rollback()
            return result

        shipment_ids: list[uuid.UUID] = []
        for entry in normalized:
            shipment_id = uuid.uuid4()
            shipment_ids.append(shipment_id)
            session.add(
                Shipment(
                    id=shipment_id,
                    tenant_id=tenant_id,
                    order_id=order_id,
                    warehouse_id=entry["warehouse_id"],
                    status="created",
                )
            )
            for line in entry["lines"]:
                session.add(
                    ShipmentLine(
                        tenant_id=tenant_id,
                        shipment_id=shipment_id,
                        sku_id=line["sku_id"],
                        qty=line["qty"],
                    )
                )
        # Ledger rows reference shipments by FK; flush the parents first because
        # the models declare plain columns rather than ORM relationships.
        await session.flush()

        for entry, shipment_id in zip(normalized, shipment_ids, strict=True):
            for line in entry["lines"]:
                inventory = inventory_rows[
                    (entry["warehouse_id"], line["sku_id"])
                ]
                inventory.available -= line["qty"]
                inventory.reserved += line["qty"]
                inventory.version += 1
                session.add(
                    InventoryLedger(
                        tenant_id=tenant_id,
                        order_id=order_id,
                        shipment_id=shipment_id,
                        sku_id=line["sku_id"],
                        warehouse_id=entry["warehouse_id"],
                        delta_available=-line["qty"],
                        delta_reserved=line["qty"],
                        reason=SPLIT_RESERVATION_REASON,
                        task_id=task_id,
                    )
                )

        order.status = "split"
        order.version += 1
        response = {
            "order_id": str(order_id),
            "order_no": order.order_no,
            "status": "split",
            "shipments": len(normalized),
            "shipment_ids": [str(shipment_id) for shipment_id in shipment_ids],
        }
        await write_audit(
            session,
            tenant_id=tenant_id,
            task_id=task_id,
            actor_id=actor_id,
            action="order.split",
            entity_type="sales_order",
            entity_id=str(order_id),
            before={"status": "pending_shipment"},
            after={"status": "split"},
            evidence={
                "impact": impact,
                "shipment_ids": response["shipment_ids"],
            },
        )
        # Stage the idempotency row last so a concurrent duplicate key fails at
        # commit and is replayed by _commit_or_replay instead of during a flush.
        session.add(
            IdempotencyKey(
                tenant_id=tenant_id,
                scope=scope,
                key=idempotency_key,
                request_hash=fingerprint,
                response=response,
                status="completed",
            )
        )
        replayed = await _commit_or_replay(
            session, tenant_id, scope, idempotency_key, fingerprint
        )
        return replayed if replayed is not None else response
    except BaseException:
        await session.rollback()
        raise


async def cancel_split(
    session: AsyncSession,
    tenant_id: UUID,
    order_id: UUID,
    idempotency_key: str,
    task_id: UUID | None = None,
) -> dict[str, Any]:
    """补偿拆分：取消发货单、释放库存并恢复订单。

    只有仍处于 ``created`` 状态的发货单会被取消；已取消的发货单会跳过，确保其
    预留不会被重复释放。订单回到 ``pending_shipment``，调用在返回前提交。补偿按
    发货单与订单归属，因此永远不会释放其他订单的库存。

    Args:
        session: 调用方的暂存会话；服务提交或回滚该事务。
        tenant_id: 必须拥有该订单与发货单的租户。
        order_id: 正在补偿的已拆分订单。
        idempotency_key: 用于重放与冲突检查的调用方幂等键。
        task_id: 记入释放流水与审计行的任务（若有）。

    Returns:
        订单 ID、订单号、状态 ``compensated`` 与取消的发货单数量；重放时返回
        已存储的响应。

    Raises:
        ValidationError: 幂等键无效。
        NotFound: 该订单在此租户内不存在。
        InvalidState: 订单不是 ``split``，或某个发货单的预留无法安全归属并释放。
        IdempotencyConflict: 键被复用于不同请求。
    """

    idempotency_key = _validate_idempotency_key(idempotency_key)
    scope = _cancel_split_scope(order_id)
    fingerprint = _request_hash({"order_id": str(order_id)})

    replay = await _replay(session, tenant_id, scope, idempotency_key, fingerprint)
    if replay is not None:
        return replay

    try:
        order = await _lock_order(session, tenant_id, order_id)
        if order is None:
            raise NotFound(f"order {order_id} not found for this tenant")
        if order.status != "split":
            replay = await _replay(
                session, tenant_id, scope, idempotency_key, fingerprint
            )
            if replay is not None:
                await session.rollback()
                return replay
            raise InvalidState(
                f"order {order_id} is {order.status!r}, expected 'split'"
            )

        shipments = await _lock_order_shipments(session, tenant_id, order_id)
        cancelled = 0
        released: list[dict[str, Any]] = []
        for shipment in shipments:
            if shipment.status != "created":
                continue
            released.extend(
                await _release_shipment_stock(session, tenant_id, shipment, task_id)
            )
            shipment.status = "cancelled"
            cancelled += 1

        order.status = "pending_shipment"
        order.version += 1
        response = {
            "order_id": str(order_id),
            "order_no": order.order_no,
            "status": "compensated",
            "shipments_cancelled": cancelled,
        }
        await write_audit(
            session,
            tenant_id=tenant_id,
            task_id=task_id,
            actor_id=None,
            action="order.split.cancel",
            entity_type="sales_order",
            entity_id=str(order_id),
            before={"status": "split"},
            after={"status": "pending_shipment"},
            evidence={"shipments": cancelled, "released": released},
        )
        # Stage the idempotency row last so a concurrent duplicate key fails at
        # commit and is replayed by _commit_or_replay instead of during a flush.
        session.add(
            IdempotencyKey(
                tenant_id=tenant_id,
                scope=scope,
                key=idempotency_key,
                request_hash=fingerprint,
                response=response,
                status="completed",
            )
        )
        replayed = await _commit_or_replay(
            session, tenant_id, scope, idempotency_key, fingerprint
        )
        return replayed if replayed is not None else response
    except BaseException:
        await session.rollback()
        raise


async def cancel_shipment(
    session: AsyncSession,
    tenant_id: UUID,
    shipment_id: UUID,
    idempotency_key: str,
    task_id: UUID | None = None,
    actor_id: UUID | None = None,
) -> dict[str, Any]:
    """取消单个发货单并将其预留释放回可用库存。

    发货单必须处于 ``created`` 状态。取消已取消的发货单是空操作：返回
    ``already_cancelled: True`` 并回滚而不写入。释放只消耗归属该发货单订单与
    发货单的流水行，因此同级发货单与其他订单保留各自的预留。调用在返回前提交。

    Args:
        session: 调用方的暂存会话；服务提交或回滚该事务。
        tenant_id: 必须拥有该发货单的租户。
        shipment_id: 待取消的发货单。
        idempotency_key: 用于重放与冲突检查的调用方幂等键。
        task_id: 记入释放流水与审计行的任务（若有）。
        actor_id: 记入审计行的操作者（若已知）。

    Returns:
        发货单与订单 ID、状态 ``cancelled``、``already_cancelled`` 标记与已释放
        明细；重放时返回已存储的响应。

    Raises:
        ValidationError: 幂等键无效。
        NotFound: 该发货单在此租户内不存在。
        InvalidState: 发货单不是 ``created``/``cancelled``，或其预留无法安全归属
            并释放。
        IdempotencyConflict: 键被复用于不同请求。
    """

    idempotency_key = _validate_idempotency_key(idempotency_key)
    scope = _shipment_cancel_scope(shipment_id)
    fingerprint = _request_hash({"shipment_id": str(shipment_id)})

    replay = await _replay(session, tenant_id, scope, idempotency_key, fingerprint)
    if replay is not None:
        return replay

    try:
        shipment = await session.scalar(
            select(Shipment)
            .where(
                Shipment.tenant_id == tenant_id,
                Shipment.id == shipment_id,
            )
            .with_for_update()
        )
        if shipment is None:
            raise NotFound(f"shipment {shipment_id} not found for this tenant")

        if shipment.status == "cancelled":
            result = {
                "shipment_id": str(shipment.id),
                "order_id": str(shipment.order_id),
                "status": "cancelled",
                "already_cancelled": True,
            }
            await session.rollback()
            return result
        if shipment.status != "created":
            raise InvalidState(
                f"shipment {shipment_id} is {shipment.status!r}, expected 'created'"
            )

        released = await _release_shipment_stock(
            session, tenant_id, shipment, task_id
        )
        shipment.status = "cancelled"
        response = {
            "shipment_id": str(shipment.id),
            "order_id": str(shipment.order_id),
            "status": "cancelled",
            "already_cancelled": False,
            "released": released,
        }
        await write_audit(
            session,
            tenant_id=tenant_id,
            task_id=task_id,
            actor_id=actor_id,
            action="shipment.cancel",
            entity_type="shipment",
            entity_id=str(shipment.id),
            before={"status": "created"},
            after={"status": "cancelled"},
            evidence={"released": released},
        )
        # Stage the idempotency row last so a concurrent duplicate key fails at
        # commit and is replayed by _commit_or_replay instead of during a flush.
        session.add(
            IdempotencyKey(
                tenant_id=tenant_id,
                scope=scope,
                key=idempotency_key,
                request_hash=fingerprint,
                response=response,
                status="completed",
            )
        )
        replayed = await _commit_or_replay(
            session, tenant_id, scope, idempotency_key, fingerprint
        )
        return replayed if replayed is not None else response
    except BaseException:
        await session.rollback()
        raise


async def release_inventory(
    session: AsyncSession,
    tenant_id: UUID,
    order_id: UUID,
    idempotency_key: str,
    task_id: UUID | None = None,
    actor_id: UUID | None = None,
) -> dict[str, Any]:
    """释放每个有效发货单的预留，同时让订单保持已拆分状态。

    这是拆分补偿中的库存部分；``cancel_split`` 会连同订单状态回滚一起执行它。
    已取消的发货单会跳过，因此预留绝不会被重复释放。

    Args:
        session: 调用方的暂存会话；服务提交或回滚该事务。
        tenant_id: 必须拥有该订单与发货单的租户。
        order_id: 需要释放预留的已拆分订单。
        idempotency_key: 用于重放与冲突检查的调用方幂等键。
        task_id: 记入释放流水与审计行的任务（若有）。
        actor_id: 记入审计行的操作者（若已知）。

    Returns:
        订单 ID、订单号、状态 ``released``、取消的发货单数量与已释放明细；重放
        时返回已存储的响应。

    Raises:
        ValidationError: 幂等键无效。
        NotFound: 该订单在此租户内不存在。
        InvalidState: 订单不是 ``split``，或某个发货单的预留无法安全归属并释放。
        IdempotencyConflict: 键被复用于不同请求。

    Note:
        此操作让订单保持 ``split`` 状态；只有预留与发货单状态发生变化。
    """

    idempotency_key = _validate_idempotency_key(idempotency_key)
    scope = _inventory_release_scope(order_id)
    fingerprint = _request_hash({"order_id": str(order_id)})

    replay = await _replay(session, tenant_id, scope, idempotency_key, fingerprint)
    if replay is not None:
        return replay

    try:
        order = await _lock_order(session, tenant_id, order_id)
        if order is None:
            raise NotFound(f"order {order_id} not found for this tenant")
        if order.status != "split":
            replay = await _replay(
                session, tenant_id, scope, idempotency_key, fingerprint
            )
            if replay is not None:
                await session.rollback()
                return replay
            raise InvalidState(
                f"order {order_id} is {order.status!r}, expected 'split'"
            )

        shipments = await _lock_order_shipments(session, tenant_id, order_id)
        cancelled = 0
        released: list[dict[str, Any]] = []
        for shipment in shipments:
            if shipment.status != "created":
                continue
            released.extend(
                await _release_shipment_stock(session, tenant_id, shipment, task_id)
            )
            shipment.status = "cancelled"
            cancelled += 1

        response = {
            "order_id": str(order_id),
            "order_no": order.order_no,
            "status": "released",
            "shipments_cancelled": cancelled,
            "released": released,
        }
        await write_audit(
            session,
            tenant_id=tenant_id,
            task_id=task_id,
            actor_id=actor_id,
            action="inventory.release",
            entity_type="sales_order",
            entity_id=str(order_id),
            before={"status": "split"},
            after={"status": "split"},
            evidence={"shipments": cancelled, "released": released},
        )
        # Stage the idempotency row last so a concurrent duplicate key fails at
        # commit and is replayed by _commit_or_replay instead of during a flush.
        session.add(
            IdempotencyKey(
                tenant_id=tenant_id,
                scope=scope,
                key=idempotency_key,
                request_hash=fingerprint,
                response=response,
                status="completed",
            )
        )
        replayed = await _commit_or_replay(
            session, tenant_id, scope, idempotency_key, fingerprint
        )
        return replayed if replayed is not None else response
    except BaseException:
        await session.rollback()
        raise
