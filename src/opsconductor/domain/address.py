"""Address validity and normalization helpers shared by tools and planners.

An address is the six-field mapping in :data:`ADDRESS_FIELDS`. Validation needs
``receiver_name``, ``phone``, ``province``, ``city``, and ``district`` to be
non-empty, requires a mainland Chinese mobile number, and requires
``address_detail`` to contain non-whitespace text. Helpers never mutate the
order they receive.
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
    """Check a candidate address mapping against the persisted-order rules.

    The mapping is validated as a whole: the first five fields must be
    non-empty, ``phone`` must match the mainland Chinese mobile format
    ``1[3-9]`` followed by nine digits, and ``address_detail`` must contain
    non-whitespace text. Extra keys are ignored.

    Args:
        values: Address-like mapping; missing keys fail validation.

    Returns:
        ``True`` when every rule passes, ``False`` otherwise. Malformed values
        are reported as invalid rather than raised.
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
    """Snapshot an order's address fields as a plain mapping.

    Missing or null attributes become empty strings, so the result is always a
    six-key, JSON-serializable mapping suitable for audit ``before`` and
    ``after`` payloads.

    Args:
        order: Order whose address columns are read.

    Returns:
        A new mapping keyed by :data:`ADDRESS_FIELDS`.
    """

    return {field: getattr(order, field, "") or "" for field in ADDRESS_FIELDS}


def address_is_valid(order: SalesOrder) -> bool:
    """Return whether an order's stored address passes validation.

    Args:
        order: Order to validate.

    Returns:
        ``True`` when the order's address fields satisfy
        :func:`address_fields_are_valid`.
    """

    return address_fields_are_valid(
        {field: getattr(order, field, None) for field in ADDRESS_FIELDS}
    )


def normalized_address(order: SalesOrder) -> str:
    """Return a non-empty ``address_detail`` for display and tool payloads.

    When the stored detail is blank, a deterministic placeholder built from the
    order's city and district is returned instead of an empty string.

    Args:
        order: Order whose address detail is read.

    Returns:
        The trimmed detail, or a synthesized placeholder when it is blank.

    Note:
        The fallback is demo data, not a verified delivery address; it exists
        so planners can still produce a complete address payload.
    """

    detail = (order.address_detail or "").strip()
    if detail:
        return detail
    return f"{order.city}{order.district}世纪大道100号"
