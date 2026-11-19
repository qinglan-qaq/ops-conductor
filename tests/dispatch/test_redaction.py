"""工具参数/结果脱敏测试。"""

from __future__ import annotations

import json

from opsconductor.dispatch.domain.redaction import redact_mapping

_SENTINEL = "SENTINEL-DO-NOT-LEAK"


def test_redacts_sensitive_keys_recursively() -> None:
    payload = redact_mapping(
        {
            "api_key": _SENTINEL,
            "nested": {
                "Token": _SENTINEL,
                "password": _SENTINEL,
                "authorization": _SENTINEL,
                "credential": _SENTINEL,
                "safe": 1,
            },
            "items": [{"secret": _SENTINEL}, "plain"],
        }
    )

    assert payload["api_key"] == "***"
    assert payload["nested"]["Token"] == "***"
    assert payload["nested"]["password"] == "***"
    assert payload["nested"]["authorization"] == "***"
    assert payload["nested"]["credential"] == "***"
    assert payload["nested"]["safe"] == 1
    assert payload["items"][0]["secret"] == "***"
    assert payload["items"][1] == "plain"
    assert _SENTINEL not in json.dumps(payload)


def test_keeps_non_sensitive_values() -> None:
    payload = redact_mapping({"capability": "trend_scan", "count": 2, "ok": True, "none": None})

    assert payload == {"capability": "trend_scan", "count": 2, "ok": True, "none": None}


def test_handles_tuple_values() -> None:
    payload = redact_mapping({"items": ({"token": _SENTINEL}, 1)})

    assert payload["items"] == [{"token": "***"}, 1]
