"""Deterministic fault injection for ERP tool calls.

Faults are held in a :class:`contextvars.ContextVar`, so a test or demo can
inject a tool-level failure for one task without leaking it into concurrent
test cases. ``inject`` is re-entrant: nested scopes merge their keys and the
previous mapping is restored on exit.

Modes:

- ``timeout``: fail before the tool call executes.
- ``upstream``: fail before the tool call with an upstream error.
- ``timeout_after_commit``: execute the tool call, then lose its response.
  ``check`` deliberately ignores this mode; clients call ``check_after`` once
  the underlying operation has completed.
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


def mode(tool_name: str) -> str | None:
    """Return the configured fault mode for ``tool_name``, if any."""

    return _active().get(tool_name)


def check(tool_name: str) -> None:
    """Raise a pre-call failure for ``tool_name``, if one is configured."""

    fault = _active().get(tool_name)
    if fault == "timeout":
        raise TimeoutError(f"{tool_name} timeout")
    if fault == "upstream":
        raise RuntimeError(f"{tool_name} upstream error")


def check_after(tool_name: str) -> None:
    """Raise a post-call failure for ``tool_name``, if one is configured."""

    if _active().get(tool_name) == "timeout_after_commit":
        raise TimeoutError(f"{tool_name} timeout after commit")
