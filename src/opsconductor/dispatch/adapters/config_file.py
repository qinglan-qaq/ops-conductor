"""从 TOML 读取平台配置并校验。

配置文件只包含非密钥字段；``credential_ref`` 是环境变量/密钥管理中的变量名，
不是密钥值。未知字段、重复平台/店铺、未实现的 live 启用都会在启动时失败。
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from opsconductor.dispatch.domain.config import PlatformConfig
from opsconductor.dispatch.domain.enums import IntegrationCapability, IntegrationMode
from opsconductor.dispatch.domain.errors import InvalidConfig

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[4] / "config" / "platforms.toml"

_ALLOWED_KEYS = {
    "adapter_id",
    "platform",
    "shop_id",
    "display_name",
    "mode",
    "enabled",
    "capabilities",
    "credential_ref",
    "rate_limit_per_minute",
    "timeout_ms",
    "max_attempts",
    "backoff_ms",
}
_REQUIRED_KEYS = _ALLOWED_KEYS - {"credential_ref"}


def _require(raw: Mapping[str, Any], key: str, index: int) -> Any:
    if key not in raw:
        raise InvalidConfig(f"platforms[{index}]: missing field {key}")
    return raw[key]


def _string(raw: Mapping[str, Any], key: str, index: int) -> str:
    value = _require(raw, key, index)
    if not isinstance(value, str):
        raise InvalidConfig(f"platforms[{index}]: {key} must be a string")
    return value


def _integer(raw: Mapping[str, Any], key: str, index: int) -> int:
    value = _require(raw, key, index)
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidConfig(f"platforms[{index}]: {key} must be an integer")
    return value


def _load_one(raw: Mapping[str, Any], index: int) -> PlatformConfig:
    unknown = sorted(set(raw) - _ALLOWED_KEYS)
    if unknown:
        raise InvalidConfig(f"platforms[{index}]: unknown field(s): {unknown}")
    missing = sorted(_REQUIRED_KEYS - set(raw))
    if missing:
        raise InvalidConfig(f"platforms[{index}]: missing field(s): {missing}")

    mode_text = _string(raw, "mode", index)
    try:
        mode = IntegrationMode(mode_text)
    except ValueError as exc:
        raise InvalidConfig(
            f"platforms[{index}]: mode must be mock or live"
        ) from exc

    capabilities_raw = _require(raw, "capabilities", index)
    if not isinstance(capabilities_raw, list):
        raise InvalidConfig(f"platforms[{index}]: capabilities must be a list")
    capabilities: list[IntegrationCapability] = []
    for value in capabilities_raw:
        if not isinstance(value, str):
            raise InvalidConfig(
                f"platforms[{index}]: capabilities must contain strings"
            )
        try:
            capabilities.append(IntegrationCapability(value))
        except ValueError as exc:
            raise InvalidConfig(
                f"platforms[{index}]: unknown capability: {value}"
            ) from exc

    enabled = _require(raw, "enabled", index)
    if not isinstance(enabled, bool):
        raise InvalidConfig(f"platforms[{index}]: enabled must be a boolean")

    credential_ref = raw.get("credential_ref", None)
    if credential_ref is not None and not isinstance(credential_ref, str):
        raise InvalidConfig(f"platforms[{index}]: credential_ref must be a string")
    if credential_ref == "":
        credential_ref = None

    try:
        config = PlatformConfig(
            adapter_id=_string(raw, "adapter_id", index),
            platform=_string(raw, "platform", index),
            shop_id=_string(raw, "shop_id", index),
            display_name=_string(raw, "display_name", index),
            mode=mode,
            enabled=enabled,
            capabilities=tuple(capabilities),
            credential_ref=credential_ref,
            rate_limit_per_minute=_integer(raw, "rate_limit_per_minute", index),
            timeout_ms=_integer(raw, "timeout_ms", index),
            max_attempts=_integer(raw, "max_attempts", index),
            backoff_ms=_integer(raw, "backoff_ms", index),
        )
    except ValueError as exc:
        raise InvalidConfig(f"platforms[{index}]: {exc}") from exc

    if config.mode is IntegrationMode.live and config.enabled:
        raise InvalidConfig(
            f"live adapters are not implemented: {config.adapter_id}"
        )
    return config


def load_platform_configs(path: str | Path | None = None) -> tuple[PlatformConfig, ...]:
    """读取并校验平台配置。

    Args:
        path: TOML 路径；缺省为仓库根目录的 ``config/platforms.toml``。

    Returns:
        按文件顺序排列的 :class:`PlatformConfig` 元组。

    Raises:
        InvalidConfig: 文件不可读、TOML 非法、字段缺失/未知、重复或 live 启用。
    """
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise InvalidConfig(f"cannot read platform config: {config_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise InvalidConfig(f"invalid TOML in {config_path}: {exc}") from exc

    raw_platforms = data.get("platforms")
    if raw_platforms is None:
        raw_platforms = []
    if not isinstance(raw_platforms, list):
        raise InvalidConfig("platforms must be a list of tables")

    configs: list[PlatformConfig] = []
    seen_adapters: set[str] = set()
    seen_shops: set[tuple[str, str]] = set()
    for index, raw in enumerate(raw_platforms):
        if not isinstance(raw, Mapping):
            raise InvalidConfig(f"platforms[{index}] must be a table")
        config = _load_one(raw, index)
        if config.adapter_id in seen_adapters:
            raise InvalidConfig(f"duplicate adapter_id: {config.adapter_id}")
        if (config.platform, config.shop_id) in seen_shops:
            raise InvalidConfig(
                f"duplicate platform/shop: {config.platform}/{config.shop_id}"
            )
        seen_adapters.add(config.adapter_id)
        seen_shops.add((config.platform, config.shop_id))
        configs.append(config)
    return tuple(configs)


__all__ = ["DEFAULT_CONFIG_PATH", "load_platform_configs"]
