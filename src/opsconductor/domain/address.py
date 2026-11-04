"""工具与 planner 共用的地址校验与归一化辅助函数。

地址是 :data:`ADDRESS_FIELDS` 中的六字段映射。校验要求 ``receiver_name``、
``phone``、``province``、``city`` 与 ``district`` 非空，要求手机号为
中国大陆手机号，并要求 ``address_detail`` 包含非空白文本。这些辅助函数
从不修改传入的订单。
"""

import re
from collections.abc import Mapping
from typing import Any

from opsconductor.domain.models import SalesOrder

ADDRESS_FIELDS: tuple[str, ...] = (
    "receiver_name",
    "phone",
    "province",
    "city",
    "district",
    "address_detail",
)


def address_fields_are_valid(values: Mapping[str, Any]) -> bool:
    """按照持久化订单的规则校验候选地址映射。

    校验以整体为单位进行：前五个字段必须非空，``phone`` 必须匹配中国大陆手机
    号格式（``1[3-9]`` 后跟九位数字），``address_detail`` 必须包含非空白文本。
    多余的键会被忽略。

    Args:
        values: 类似地址的映射；缺少键会导致校验失败。

    Returns:
        所有规则都通过时返回 ``True``，否则返回 ``False``。格式错误的值会被
        判定为无效，而不是抛出异常。
    """

    for field in ("receiver_name", "phone", "province", "city", "district"):
        if not values.get(field):
            return False
    phone = values.get("phone")
    if not isinstance(phone, str) or not re.fullmatch(r"1[3-9]\d{9}", phone):
        return False
    detail = values.get("address_detail")
    return isinstance(detail, str) and bool(detail.strip())


def order_address(order: SalesOrder) -> dict[str, str]:
    """将订单的地址字段快照为普通映射。

    缺失或为 null 的属性会变为空字符串，因此结果始终是包含六个键、可 JSON
    序列化的映射，适用于审计的 ``before`` 与 ``after`` 载荷。

    Args:
        order: 读取其地址列的订单。

    Returns:
        以 :data:`ADDRESS_FIELDS` 为键的新映射。
    """

    return {field: getattr(order, field, "") or "" for field in ADDRESS_FIELDS}


def address_is_valid(order: SalesOrder) -> bool:
    """返回订单已存储的地址是否通过校验。

    Args:
        order: 待校验的订单。

    Returns:
        订单的地址字段满足 :func:`address_fields_are_valid` 时返回 ``True``。
    """

    return address_fields_are_valid(
        {field: getattr(order, field, None) for field in ADDRESS_FIELDS}
    )


def normalized_address(order: SalesOrder) -> str:
    """返回非空的 ``address_detail``，供展示与工具载荷使用。

    当存储的详细地址为空时，返回基于订单城市与区县构造的确定性占位符，而不是
    空字符串。

    Args:
        order: 读取其地址详情的订单。

    Returns:
        去除首尾空白后的详情；若为空则返回合成的占位符。

    Note:
        该回退值是演示数据，并非经过核验的收货地址；它的存在只是为了让
        planner 仍能生成完整的地址载荷。
    """

    detail = (order.address_detail or "").strip()
    if detail:
        return detail
    return f"{order.city}{order.district}世纪大道100号"
