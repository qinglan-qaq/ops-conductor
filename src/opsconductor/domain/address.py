"""Address validity and normalization helpers shared by tools and planners."""

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
    """Validate an address mapping with the rules used for persisted orders."""

    for field in ("receiver_name", "phone", "province", "city", "district"):
        if not values.get(field):
            return False
    phone = values.get("phone")
    if not isinstance(phone, str) or not re.fullmatch(r"1[3-9]\d{9}", phone):
        return False
    detail = values.get("address_detail")
    return isinstance(detail, str) and bool(detail.strip())


def order_address(order: SalesOrder) -> dict[str, str]:
    """Return the order's address fields as a JSON-serializable mapping."""

    return {field: getattr(order, field, "") or "" for field in ADDRESS_FIELDS}


def address_is_valid(order: SalesOrder) -> bool:
    return address_fields_are_valid(
        {field: getattr(order, field, None) for field in ADDRESS_FIELDS}
    )


def normalized_address(order: SalesOrder) -> str:
    """Return a deliverable address detail, filling a default when it is blank."""

    detail = (order.address_detail or "").strip()
    if detail:
        return detail
    return f"{order.city}{order.district}世纪大道100号"
