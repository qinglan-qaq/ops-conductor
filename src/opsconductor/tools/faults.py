"""ERP 工具调用的确定性故障注入。

故障保存在 :class:`contextvars.ContextVar` 中，因此测试或演示可以为单个任务注入
工具级失败，而不会泄漏到并发的测试用例。``inject`` 可重入：嵌套作用域合并各自
的键，退出时恢复之前的映射。

故障模式：

- ``timeout``：在工具调用执行前失败。
- ``upstream``：在工具调用执行前以上游错误失败。
- ``timeout_after_commit``：先执行工具调用，再丢失其响应。``check`` 会刻意忽略
  该模式；客户端在底层操作完成后调用 ``check_after``。

Invariants:

- 故障映射只对当前上下文可见，不会跨任务或并发请求泄漏。
- ``check`` 只处理调用前模式；``timeout_after_commit`` 只在 ``check_after`` 中
  生效。
"""

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager

_current: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "faults", default=None
)


def _active() -> dict[str, str]:
    """返回当前作用域内的故障映射；未注入时返回空字典。"""

    return _current.get() or {}


@contextmanager
def inject(**faults: str) -> Iterator[None]:
    """在代码块内把 ``faults`` 合并进当前故障映射。

    Args:
        **faults: 工具名到故障模式的映射；与已有键同名时覆盖旧值。

    Yields:
        ``None``。进入时设置新的上下文变量，退出时恢复原值。

    Note:
        作用域可以嵌套：内层只覆盖自己的键，退出后外层映射原样恢复，异常路径
        同样如此。
    """

    token = _current.set({**_active(), **faults})
    try:
        yield
    finally:
        _current.reset(token)


def mode(tool_name: str) -> str | None:
    """返回 ``tool_name`` 配置的故障模式；未配置时返回 ``None``。

    Args:
        tool_name: MCP 工具名。

    Returns:
        模式名，例如 ``timeout``、``upstream`` 或 ``timeout_after_commit``。
    """

    return _active().get(tool_name)


def check(tool_name: str) -> None:
    """若为 ``tool_name`` 配置了调用前故障，则抛出异常。

    Args:
        tool_name: 即将调用的 MCP 工具名。

    Raises:
        TimeoutError: 模式为 ``timeout``。
        RuntimeError: 模式为 ``upstream``。

    Note:
        ``timeout_after_commit`` 在这里被刻意忽略，因为它要求先执行真实调用。
    """

    fault = _active().get(tool_name)
    if fault == "timeout":
        raise TimeoutError(f"{tool_name} timeout")
    if fault == "upstream":
        raise RuntimeError(f"{tool_name} upstream error")


def check_after(tool_name: str) -> None:
    """若为 ``tool_name`` 配置了调用后故障，则抛出异常。

    Args:
        tool_name: 已执行完毕的 MCP 工具名。

    Raises:
        TimeoutError: 模式为 ``timeout_after_commit``。

    Warning:
        抛出时底层操作可能已经提交；调用方必须按“结果未知”处理，而不是假定
        写入失败。
    """

    if _active().get(tool_name) == "timeout_after_commit":
        raise TimeoutError(f"{tool_name} timeout after commit")
