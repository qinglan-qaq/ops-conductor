"""跨境调度领域端口。

端口用 ``typing.Protocol`` 描述应用层需要的能力，适配器负责实现。协议只约束
方法形状，不引入具体存储、HTTP 或时钟实现。
"""

from collections.abc import Callable, Mapping
from typing import Protocol, runtime_checkable

from opsconductor.dispatch.domain.models import (
    AdapterManifest,
    AgentCard,
    AgentResult,
    AgentTask,
    CanonicalAdMetric,
    CanonicalInventory,
    CanonicalListing,
    CanonicalOrder,
    CanonicalSettlement,
    CanonicalShipment,
    ControlCommand,
    ControlResult,
    DataPage,
    DataQuery,
    DispatchState,
    IntegrationHealth,
)


@runtime_checkable
class DispatchRepository(Protocol):
    """调度状态的仓储。

    读路径返回快照，写路径通过 ``mutate`` 在仓储锁内修改状态。实现必须保证
    快照与外部状态隔离，避免调用方绕过锁修改内部对象。
    """

    def snapshot(self) -> DispatchState: ...

    def mutate(self, mutator: Callable[[DispatchState], None]) -> None: ...

    def reset(self) -> DispatchState: ...


@runtime_checkable
class AgentPort(Protocol):
    """领域 Agent 的统一接口。"""

    @property
    def card(self) -> AgentCard: ...

    def handle(self, task: AgentTask) -> AgentResult: ...


@runtime_checkable
class ToolPort(Protocol):
    """工具网关端口；Demo 由 Mock 实现返回确定性结果。"""

    def call(self, tool: str, params: Mapping[str, object]) -> dict[str, object]: ...


@runtime_checkable
class ClockPort(Protocol):
    """展示用时钟端口，返回 ``HH:MM`` 标签。"""

    def now_label(self) -> str: ...


@runtime_checkable
class CommerceDataPort(Protocol):
    """电商平台数据获取端口；只读，不得产生业务副作用。"""

    def fetch_orders(self, query: DataQuery) -> DataPage[CanonicalOrder]: ...

    def fetch_inventory(self, query: DataQuery) -> DataPage[CanonicalInventory]: ...

    def fetch_listings(self, query: DataQuery) -> DataPage[CanonicalListing]: ...

    def fetch_settlements(self, query: DataQuery) -> DataPage[CanonicalSettlement]: ...

    def fetch_ads(self, query: DataQuery) -> DataPage[CanonicalAdMetric]: ...

    def fetch_logistics(self, query: DataQuery) -> DataPage[CanonicalShipment]: ...


@runtime_checkable
class PlatformControlPort(Protocol):
    """平台控制端口；所有写操作必须经过审批、幂等、dry-run 与审计。"""

    def execute(self, command: ControlCommand) -> ControlResult: ...


@runtime_checkable
class PlatformAdapter(CommerceDataPort, PlatformControlPort, Protocol):
    """一个平台/店铺适配器同时暴露数据与控制能力。"""

    def manifest(self) -> AdapterManifest: ...

    def health(self) -> IntegrationHealth: ...
