"""Deterministic fault injection for ERP tool calls.

Faults are held in a :class:`contextvars.ContextVar`, so a test or demo can
inject a tool-level failure for one task without leaking it into concurrent
test cases. ``inject`` is re-entrant: nested scopes merge their keys and the
previous mapping is restored on exit.
"""

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager

_current: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "faults", default=None
)


def _active() -> dict[str, str]:
    return _current.get() or {}


@contextmanager
def inject(**faults: str) -> Iterator[None]:
    """Merge ``faults`` into the active fault map for the enclosed block."""

    token = _current.set({**_active(), **faults})
    try:
        yield
    finally:
        _current.reset(token)


def check(tool_name: str) -> None:
    """Raise the configured failure for ``tool_name``, if any."""

    fault = _active().get(tool_name)
    if fault == "timeout":
        raise TimeoutError(f"{tool_name} timeout")
    if fault == "upstream":
        raise RuntimeError(f"{tool_name} upstream error")
