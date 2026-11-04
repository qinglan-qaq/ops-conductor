"""Address validity and normalization helpers shared by tools and planners."""

import re

from opsconductor.domain.models import SalesOrder


def address_is_valid(order: SalesOrder) -> bool:
    if not all([order.receiver_name, order.phone, order.province, order.city, order.district]):
        return False
    if not re.fullmatch(r"1[3-9]\d{9}", order.phone):
        return False
    return bool(order.address_detail.strip())


def normalized_address(order: SalesOrder) -> str:
    """Return a deliverable address detail, filling a default when it is blank."""

    detail = (order.address_detail or "").strip()
    if detail:
        return detail
    return f"{order.city}{order.district}世纪大道100号"
