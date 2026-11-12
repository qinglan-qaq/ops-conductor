"""平台集成边界：Adapter Registry、Mock Adapter 与控制写门禁。"""

from __future__ import annotations

from dataclasses import replace

import pytest

from opsconductor.dispatch.adapters.integration.mock_platform import MockPlatformAdapter
from opsconductor.dispatch.application.control_service import ControlService
from opsconductor.dispatch.application.integrations import (
    AdapterRegistry,
    CapabilityRouter,
    SourceOfTruthPolicy,
)
from opsconductor.dispatch.domain.enums import (
    ControlStatus,
    IntegrationCapability,
    RiskLevel,
)
from opsconductor.dispatch.domain.errors import (
    AdapterNotFound,
    ApprovalRequired,
    CapabilityNotSupported,
    IdempotencyConflict,
)
from opsconductor.dispatch.domain.models import ControlCommand, DataQuery, PlatformRef


def _registry() -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register(MockPlatformAdapter())
    return registry


def _query() -> DataQuery:
    return DataQuery(
        query_id="q-1",
        tenant_id="tenant-demo",
        platform="mock",
        shop_id="nestwell-us",
        resource="orders",
        filters={},
        cursor=None,
        page_size=10,
        since=None,
        until=None,
    )


def _command(**overrides: object) -> ControlCommand:
    command = ControlCommand(
        command_id="cmd-1",
        tenant_id="tenant-demo",
        platform="mock",
        shop_id="nestwell-us",
        capability=IntegrationCapability.control_price,
        operation="price_update",
        entity_type="listing",
        entity_id="NW-101-LST",
        params={"price_usd": 59},
        expected_version=5,
        risk=RiskLevel.L3,
        dry_run=True,
        idempotency_key="idem-1",
        approval_id="price",
        requested_by="pricing-agent",
        requested_at="2026-11-12T10:42:00Z",
    )
    return replace(command, **overrides)


def test_adapter_registry_rejects_duplicate_id():
    registry = _registry()

    with pytest.raises(ValueError, match="already registered"):
        registry.register(MockPlatformAdapter())


def test_capability_router_resolves_by_platform_and_shop():
    adapter = CapabilityRouter(_registry()).resolve(
        IntegrationCapability.data_orders,
        PlatformRef(tenant_id="tenant-demo", platform="mock", shop_id="nestwell-us"),
    )

    assert isinstance(adapter, MockPlatformAdapter)


def test_canonical_mapping_preserves_external_id_and_provenance():
    page = _registry().get("mock-nestwell-us").fetch_orders(_query())

    assert page.items[0].external_id == "NW-1001"
    assert page.items[0].raw_ref == "mock://orders/NW-1001"
    assert page.source.adapter == "MockPlatformAdapter"
    assert page.source.shop_id == "nestwell-us"
    assert page.quality.warnings == ()


def test_control_service_requires_approval_for_l3():
    service = ControlService(_registry(), approved=lambda _: True)

    with pytest.raises(ApprovalRequired):
        service.execute(_command(approval_id=None))


def test_control_service_rejects_unapproved_approval_id():
    service = ControlService(_registry(), approved=lambda _: False)

    with pytest.raises(ApprovalRequired):
        service.execute(_command(approval_id="budget"))


def test_dry_run_returns_accepted_without_external_id():
    service = ControlService(_registry(), approved=lambda _: True)

    result = service.execute(_command(dry_run=True))

    assert result.status is ControlStatus.accepted
    assert result.external_id is None
    assert result.error is None
    assert "dry_run=True" in result.evidence


def test_idempotency_returns_first_result_and_rejects_changed_body():
    service = ControlService(_registry(), approved=lambda _: True)
    command = _command(dry_run=False)

    first = service.execute(command)
    second = service.execute(command)

    assert first is second
    assert first.status is ControlStatus.succeeded
    assert first.external_id == "mock://control/listing/NW-101-LST"

    with pytest.raises(IdempotencyConflict):
        service.execute(replace(command, operation="price_rollback"))


def test_unsupported_capability_is_rejected():
    service = ControlService(_registry(), approved=lambda _: True)

    with pytest.raises(CapabilityNotSupported):
        service.execute(
            _command(capability=IntegrationCapability.control_purchase)
        )


def test_source_of_truth_requires_declared_writer():
    policy = SourceOfTruthPolicy({"inventory": "mock-nestwell-us"})

    assert policy.writer_for("inventory") == "mock-nestwell-us"
    with pytest.raises(AdapterNotFound, match="no source of truth"):
        policy.writer_for("settlement")
