"""Mock 平台 Adapter：用确定性数据实现 typed ports。

该 Adapter 是本期唯一实现，目的是证明平台差异被限制在适配层：领域层只看到
canonical model，Vue 只看到 ``/integrations`` 的能力与健康信息。它不访问
网络、不读取凭据、不产生真实平台副作用。

同时保留 ``call`` 方法以兼容尚未 typed 化的 :class:`ToolPort`；新代码应优先
使用 ``fetch_*`` 与 ``execute``。
"""

from __future__ import annotations

from collections.abc import Mapping

from opsconductor.dispatch.domain.enums import (
    ControlStatus,
    Freshness,
    IntegrationCapability,
    IntegrationMode,
    IntegrationStatus,
    RiskLevel,
)
from opsconductor.dispatch.domain.errors import CapabilityNotSupported
from opsconductor.dispatch.domain.models import (
    AdapterManifest,
    CanonicalAdMetric,
    CanonicalInventory,
    CanonicalListing,
    CanonicalOrder,
    CanonicalSettlement,
    CanonicalShipment,
    ControlCommand,
    ControlResult,
    DataPage,
    DataProvenance,
    DataQuality,
    DataQuery,
    IntegrationHealth,
    OrderLine,
)

_CAPABILITIES: tuple[IntegrationCapability, ...] = (
    IntegrationCapability.data_orders,
    IntegrationCapability.data_inventory,
    IntegrationCapability.data_listings,
    IntegrationCapability.data_settlements,
    IntegrationCapability.data_ads,
    IntegrationCapability.data_logistics,
    IntegrationCapability.control_listing,
    IntegrationCapability.control_price,
    IntegrationCapability.control_inventory,
    IntegrationCapability.control_shipment,
    IntegrationCapability.control_refund,
)

_ADAPTER_ID = "mock-nestwell-us"
_PLATFORM = "mock"
_SHOP_ID = "nestwell-us"
_SCHEMA_VERSION = "1.0"


def _source() -> DataProvenance:
    """返回 Mock 数据来源。"""
    return DataProvenance(
        platform=_PLATFORM,
        shop_id=_SHOP_ID,
        adapter="MockPlatformAdapter",
        synced_at="10:42",
        schema_version=_SCHEMA_VERSION,
    )


def _quality() -> DataQuality:
    """返回无告警的 Mock 数据质量。"""
    return DataQuality(warnings=(), missing_fields=(), stale_after=None)


class MockPlatformAdapter:
    """NestWell Home US 的 Mock 平台适配器。"""

    def __init__(self) -> None:
        self._manifest = AdapterManifest(
            adapter_id=_ADAPTER_ID,
            platform=_PLATFORM,
            version="1.0",
            capabilities=_CAPABILITIES,
            default_risk=RiskLevel.L2,
            rate_limit_per_minute=60,
            supports_dry_run=True,
            supports_idempotency=True,
            display_name="NestWell Home US",
        )
        self._health = IntegrationHealth(
            platform=_PLATFORM,
            shop_id=_SHOP_ID,
            status=IntegrationStatus.mock,
            mode=IntegrationMode.mock,
            capabilities=_CAPABILITIES,
            last_sync_at="10:42",
            freshness=Freshness.fresh,
            warnings=(),
        )

    def manifest(self) -> AdapterManifest:
        """返回 Adapter 能力与限制声明。"""
        return self._manifest

    def health(self) -> IntegrationHealth:
        """返回 Mock 连接状态、最近同步与新鲜度。"""
        return self._health

    def _require(self, capability: IntegrationCapability) -> None:
        """确认 Adapter 声明了请求能力。"""
        if capability not in self._manifest.capabilities:
            raise CapabilityNotSupported(
                f"capability not supported: {capability.value}"
            )

    def fetch_orders(self, query: DataQuery) -> DataPage[CanonicalOrder]:
        """返回一页 canonical 订单。"""
        self._require(IntegrationCapability.data_orders)
        order = CanonicalOrder(
            external_id="NW-1001",
            status="paid",
            currency="USD",
            total_usd=89,
            lines=(OrderLine(sku="NW-101", quantity=1, amount_usd=89),),
            shipping_address="San Francisco, CA",
            updated_at="2026-11-12T10:42:00Z",
            raw_ref="mock://orders/NW-1001",
        )
        return DataPage(
            items=(order,),
            next_cursor=None,
            fetched_at="10:42",
            source=_source(),
            quality=_quality(),
        )

    def fetch_inventory(self, query: DataQuery) -> DataPage[CanonicalInventory]:
        """返回一页 canonical 库存。"""
        self._require(IntegrationCapability.data_inventory)
        inventory = CanonicalInventory(
            sku="NW-101",
            warehouse="US-WEST",
            available=42,
            reserved=6,
            in_transit=20,
            version=3,
            raw_ref="mock://inventory/NW-101",
        )
        return DataPage(
            items=(inventory,),
            next_cursor=None,
            fetched_at="10:42",
            source=_source(),
            quality=_quality(),
        )

    def fetch_listings(self, query: DataQuery) -> DataPage[CanonicalListing]:
        """返回一页 canonical Listing。"""
        self._require(IntegrationCapability.data_listings)
        listing = CanonicalListing(
            external_id="NW-101-LST",
            sku="NW-101",
            title="NestWell Linen Throw",
            price_usd=59,
            currency="USD",
            status="active",
            version=5,
            raw_ref="mock://listings/NW-101-LST",
        )
        return DataPage(
            items=(listing,),
            next_cursor=None,
            fetched_at="10:42",
            source=_source(),
            quality=_quality(),
        )

    def fetch_settlements(self, query: DataQuery) -> DataPage[CanonicalSettlement]:
        """返回一页 canonical 结算单。"""
        self._require(IntegrationCapability.data_settlements)
        settlement = CanonicalSettlement(
            external_id="SETTLE-2026-11-W2",
            period="2026-11-05/2026-11-11",
            gross_usd=12000,
            fees_usd=1800,
            refunds_usd=400,
            net_usd=9800,
            currency="USD",
            raw_ref="mock://settlements/SETTLE-2026-11-W2",
        )
        return DataPage(
            items=(settlement,),
            next_cursor=None,
            fetched_at="10:42",
            source=_source(),
            quality=_quality(),
        )

    def fetch_ads(self, query: DataQuery) -> DataPage[CanonicalAdMetric]:
        """返回一页 canonical 广告指标。"""
        self._require(IntegrationCapability.data_ads)
        metric = CanonicalAdMetric(
            campaign_id="CMP-001",
            spend_usd=3200,
            impressions=120000,
            clicks=2400,
            conversions=96,
            roas=2.7,
            source="mock://ads/CMP-001",
        )
        return DataPage(
            items=(metric,),
            next_cursor=None,
            fetched_at="10:42",
            source=_source(),
            quality=_quality(),
        )

    def fetch_logistics(self, query: DataQuery) -> DataPage[CanonicalShipment]:
        """返回一页 canonical 物流轨迹。"""
        self._require(IntegrationCapability.data_logistics)
        shipment = CanonicalShipment(
            external_id="SHP-9001",
            order_external_id="NW-1001",
            carrier="UPS",
            tracking_no="1Z-MOCK-9001",
            status="in_transit",
            events=("label_created", "picked_up", "in_transit"),
            raw_ref="mock://shipments/SHP-9001",
        )
        return DataPage(
            items=(shipment,),
            next_cursor=None,
            fetched_at="10:42",
            source=_source(),
            quality=_quality(),
        )

    def execute(self, command: ControlCommand) -> ControlResult:
        """返回确定性的控制结果；不产生真实平台副作用。

        Raises:
            CapabilityNotSupported: 命令能力未在 manifest 中声明。
        """
        self._require(command.capability)
        status = (
            ControlStatus.accepted if command.dry_run else ControlStatus.succeeded
        )
        external_id = (
            None
            if command.dry_run
            else f"mock://control/{command.entity_type}/"
            f"{command.entity_id or command.command_id}"
        )
        return ControlResult(
            command_id=command.command_id,
            status=status,
            external_id=external_id,
            evidence=(
                f"adapter={_ADAPTER_ID}",
                f"operation={command.operation}",
                f"dry_run={command.dry_run}",
            ),
            error=None,
            adapter_meta={
                "platform": command.platform,
                "shop_id": command.shop_id,
                "idempotency_key": command.idempotency_key,
                "approval_id": command.approval_id,
            },
            completed_at="10:42",
        )

    def call(self, tool: str, params: Mapping[str, object]) -> dict[str, object]:
        """兼容过渡期 ``ToolPort``：返回确定性工具产物。"""
        del params
        return {"tool": tool, "artifact": f"{tool}.json"}


__all__ = ["MockPlatformAdapter"]
