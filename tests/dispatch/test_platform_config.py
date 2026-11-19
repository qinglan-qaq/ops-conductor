"""平台配置加载与校验测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from opsconductor.dispatch.adapters.config_file import load_platform_configs
from opsconductor.dispatch.domain.config import PlatformConfig
from opsconductor.dispatch.domain.enums import IntegrationCapability, IntegrationMode
from opsconductor.dispatch.domain.errors import InvalidConfig

_MOCK = """
[[platforms]]
adapter_id = "mock-nestwell-us"
platform = "mock"
shop_id = "nestwell-us"
display_name = "NestWell Home US"
mode = "mock"
enabled = true
capabilities = ["data.orders", "data.inventory", "control.refund"]
credential_ref = ""
rate_limit_per_minute = 60
timeout_ms = 5000
max_attempts = 3
backoff_ms = 500
"""


def _load(tmp_path: Path, text: str) -> tuple[PlatformConfig, ...]:
    path = tmp_path / "platforms.toml"
    path.write_text(text, encoding="utf-8")
    return load_platform_configs(path)


def test_loads_valid_mock_config(tmp_path: Path) -> None:
    configs = _load(tmp_path, _MOCK)

    assert len(configs) == 1
    config = configs[0]
    assert config.adapter_id == "mock-nestwell-us"
    assert config.mode is IntegrationMode.mock
    assert config.enabled is True
    assert IntegrationCapability.data_orders in config.capabilities
    assert config.credential_ref is None
    assert config.rate_limit_per_minute == 60


def test_loads_disabled_live_config_with_credential_ref(tmp_path: Path) -> None:
    text = _MOCK + """
[[platforms]]
adapter_id = "tiktok-us-live"
platform = "tiktok"
shop_id = "nestwell-us"
display_name = "TikTok Shop US"
mode = "live"
enabled = false
capabilities = ["data.orders", "control.refund"]
credential_ref = "TIKTOK_SHOP_US_TOKEN"
rate_limit_per_minute = 60
timeout_ms = 5000
max_attempts = 3
backoff_ms = 500
"""

    configs = _load(tmp_path, text)

    assert len(configs) == 2
    assert configs[1].mode is IntegrationMode.live
    assert configs[1].credential_ref == "TIKTOK_SHOP_US_TOKEN"


def test_rejects_duplicate_platform_and_shop(tmp_path: Path) -> None:
    text = _MOCK + _MOCK.replace('adapter_id = "mock-nestwell-us"', 'adapter_id = "mock-2"')

    with pytest.raises(InvalidConfig, match="duplicate platform/shop"):
        _load(tmp_path, text)


def test_rejects_duplicate_adapter_id(tmp_path: Path) -> None:
    text = _MOCK + _MOCK.replace('shop_id = "nestwell-us"', 'shop_id = "other-us"')

    with pytest.raises(InvalidConfig, match="duplicate adapter_id"):
        _load(tmp_path, text)


def test_rejects_live_enabled(tmp_path: Path) -> None:
    text = _MOCK + """
[[platforms]]
adapter_id = "tiktok-us-live"
platform = "tiktok"
shop_id = "nestwell-us"
display_name = "TikTok Shop US"
mode = "live"
enabled = true
capabilities = ["data.orders"]
credential_ref = "TIKTOK_SHOP_US_TOKEN"
rate_limit_per_minute = 60
timeout_ms = 5000
max_attempts = 3
backoff_ms = 500
"""

    with pytest.raises(InvalidConfig, match="live adapters are not implemented"):
        _load(tmp_path, text)


def test_rejects_live_without_credential_ref(tmp_path: Path) -> None:
    text = _MOCK.replace('mode = "mock"', 'mode = "live"').replace(
        'credential_ref = ""', 'credential_ref = ""'
    )

    with pytest.raises(InvalidConfig, match="credential_ref"):
        _load(tmp_path, text)


def test_rejects_mock_with_credential_ref(tmp_path: Path) -> None:
    text = _MOCK.replace('credential_ref = ""', 'credential_ref = "MOCK_TOKEN"')

    with pytest.raises(InvalidConfig, match="credential_ref"):
        _load(tmp_path, text)


def test_rejects_unknown_fields_including_secrets(tmp_path: Path) -> None:
    text = _MOCK.replace('display_name = "NestWell Home US"', 'api_key = "SENTINEL"')

    with pytest.raises(InvalidConfig, match="unknown field"):
        _load(tmp_path, text)


def test_rejects_invalid_capability(tmp_path: Path) -> None:
    text = _MOCK.replace('"data.orders"', '"data.unknown"')

    with pytest.raises(InvalidConfig, match="capability"):
        _load(tmp_path, text)


def test_rejects_non_positive_rate_limit(tmp_path: Path) -> None:
    text = _MOCK.replace("rate_limit_per_minute = 60", "rate_limit_per_minute = 0")

    with pytest.raises(InvalidConfig, match="rate_limit_per_minute"):
        _load(tmp_path, text)


def test_platform_config_rejects_empty_capabilities() -> None:
    with pytest.raises(ValueError, match="capabilities"):
        PlatformConfig(
            adapter_id="a",
            platform="mock",
            shop_id="s",
            display_name="d",
            mode=IntegrationMode.mock,
            enabled=True,
            capabilities=(),
            credential_ref=None,
            rate_limit_per_minute=1,
            timeout_ms=1,
            max_attempts=1,
            backoff_ms=0,
        )
