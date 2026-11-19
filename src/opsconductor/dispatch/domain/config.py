"""平台配置与凭据值对象。

配置描述“连哪个平台、用哪个 Adapter、限额多少”；密钥只通过
``CredentialProvider`` 在适配器边界解析，不进入配置文件或 run。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from opsconductor.dispatch.domain.enums import IntegrationCapability, IntegrationMode


class CredentialStatus(str, Enum):  # noqa: UP042
    """集成页可展示的凭据状态，不包含密钥值。"""

    not_required = "not_required"
    configured = "configured"
    missing = "missing"


@dataclass(frozen=True, repr=False)
class Secret:
    """只在适配器边界短暂持有的密钥值。"""

    _value: str

    def __post_init__(self) -> None:
        if not isinstance(self._value, str) or not self._value.strip():
            raise ValueError("secret must not be blank")

    def reveal(self) -> str:
        """返回原值；调用方不得记录或序列化该值。"""
        return self._value

    def __repr__(self) -> str:
        return "Secret(***)"

    def __str__(self) -> str:
        return "***"


def _text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")


def _positive(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")


def _non_negative(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")


@dataclass(frozen=True)
class PlatformConfig:
    """一个平台/店铺的非密钥连接配置。"""

    adapter_id: str
    platform: str
    shop_id: str
    display_name: str
    mode: IntegrationMode
    enabled: bool
    capabilities: tuple[IntegrationCapability, ...]
    credential_ref: str | None
    rate_limit_per_minute: int
    timeout_ms: int
    max_attempts: int
    backoff_ms: int

    def __post_init__(self) -> None:
        for field in ("adapter_id", "platform", "shop_id", "display_name"):
            _text(getattr(self, field), field)
        if not isinstance(self.mode, IntegrationMode):
            raise ValueError("mode must be an IntegrationMode")
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be a boolean")
        if not isinstance(self.capabilities, tuple) or not self.capabilities:
            raise ValueError("capabilities must be a non-empty tuple")
        if any(not isinstance(item, IntegrationCapability) for item in self.capabilities):
            raise ValueError("capabilities must contain IntegrationCapability values")
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("capabilities must be unique")
        if self.credential_ref is not None and not isinstance(self.credential_ref, str):
            raise ValueError("credential_ref must be a string or None")
        if self.mode is IntegrationMode.mock:
            if self.credential_ref:
                raise ValueError("credential_ref must be empty for mock mode")
        elif not self.credential_ref:
            raise ValueError("credential_ref is required for live mode")
        _positive(self.rate_limit_per_minute, "rate_limit_per_minute")
        _positive(self.timeout_ms, "timeout_ms")
        if (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or self.max_attempts < 1
        ):
            raise ValueError("max_attempts must be a positive integer")
        _non_negative(self.backoff_ms, "backoff_ms")


__all__ = ["CredentialStatus", "PlatformConfig", "Secret"]
