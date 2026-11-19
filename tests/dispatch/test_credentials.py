"""凭据读取与 Secret 隐藏测试。"""

from __future__ import annotations

from opsconductor.dispatch.adapters.credentials import EnvCredentialProvider
from opsconductor.dispatch.domain.config import CredentialStatus, Secret


def test_secret_hides_value_in_repr_and_str() -> None:
    secret = Secret("super-secret-value")

    assert secret.reveal() == "super-secret-value"
    assert "super-secret-value" not in repr(secret)
    assert "super-secret-value" not in str(secret)
    assert str(secret) == "***"


def test_secret_rejects_blank_value() -> None:
    try:
        Secret("   ")
    except ValueError as exc:
        assert "secret" in str(exc)
    else:
        raise AssertionError("Secret accepted a blank value")


def test_env_provider_reads_and_hides_value(monkeypatch) -> None:
    monkeypatch.setenv("TEST_PLATFORM_TOKEN", "sentinel-token")
    provider = EnvCredentialProvider()

    assert provider.has("TEST_PLATFORM_TOKEN") is True
    secret = provider.get("TEST_PLATFORM_TOKEN")
    assert secret is not None
    assert secret.reveal() == "sentinel-token"
    assert "sentinel-token" not in repr(secret)


def test_env_provider_treats_missing_and_empty_as_absent(monkeypatch) -> None:
    monkeypatch.delenv("TEST_PLATFORM_TOKEN", raising=False)
    monkeypatch.setenv("EMPTY_PLATFORM_TOKEN", "")
    provider = EnvCredentialProvider()

    assert provider.has("TEST_PLATFORM_TOKEN") is False
    assert provider.get("TEST_PLATFORM_TOKEN") is None
    assert provider.has("EMPTY_PLATFORM_TOKEN") is False
    assert provider.get("EMPTY_PLATFORM_TOKEN") is None


def test_credential_status_values_are_stable() -> None:
    assert CredentialStatus.not_required.value == "not_required"
    assert CredentialStatus.configured.value == "configured"
    assert CredentialStatus.missing.value == "missing"
