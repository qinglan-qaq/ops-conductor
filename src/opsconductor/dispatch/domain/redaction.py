"""工具参数与结果的递归脱敏。

密钥不进入 Agent，也不进入 Run；本模块作为最后的 defensible 边界，把可能
被工具透传的敏感键替换为 ``***``。
"""

from __future__ import annotations

import re
from collections.abc import Mapping

_SENSITIVE_KEY = re.compile(
    r"api[_-]?key|token|secret|password|authorization|credential",
    re.IGNORECASE,
)


def _redact_value(value: object) -> object:
    if isinstance(value, Mapping):
        return redact_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_redact_value(item) for item in value]
    return value


def redact_mapping(mapping: Mapping[str, object]) -> dict[str, object]:
    """返回一份敏感键已脱敏的普通字典。

    Args:
        mapping: 工具参数或结果；键会被转换为字符串。

    Returns:
        新的 ``dict``，敏感键的值为 ``"***"``，嵌套 Mapping/List/Tuple 递归处理。
    """
    redacted: dict[str, object] = {}
    for key, value in mapping.items():
        text_key = str(key)
        if _SENSITIVE_KEY.search(text_key):
            redacted[text_key] = "***"
        else:
            redacted[text_key] = _redact_value(value)
    return redacted


__all__ = ["redact_mapping"]
