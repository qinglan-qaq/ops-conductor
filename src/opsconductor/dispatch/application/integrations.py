"""平台 Adapter 的注册、发现与写入归属策略。

本模块是应用层的稳定边界：上层只依赖 :class:`AdapterRegistry`、
:class:`CapabilityRouter` 与 :class:`SourceOfTruthPolicy`，不感知任何平台 SDK、
签名、分页或错误码。新增平台只需注册新的
:class:`~opsconductor.dispatch.domain.ports.PlatformAdapter`，不修改 Agent、Vue
页面或领域实体。

Invariants:
    - 同一 ``adapter_id`` 只能注册一次，重复注册直接失败。
    - 能力是唯一门禁；不得按平台名在调用方写分支。
    - 每个 canonical 实体最多一个主写方，避免平台与 ERP 双写。
"""

from __future__ import annotations

from collections.abc import Mapping

from opsconductor.dispatch.domain.enums import IntegrationCapability
from opsconductor.dispatch.domain.errors import AdapterNotFound, CapabilityNotSupported
from opsconductor.dispatch.domain.models import (
    AdapterManifest,
    IntegrationHealth,
    PlatformRef,
)
from opsconductor.dispatch.domain.ports import PlatformAdapter


class AdapterRegistry:
    """按 ``adapter_id`` 注册平台 Adapter，并按能力解析。"""

    def __init__(self) -> None:
        self._adapters: dict[str, PlatformAdapter] = {}

    def register(self, adapter: PlatformAdapter) -> None:
        """注册一个 Adapter。

        Args:
            adapter: 同时实现数据与控制端口的平台适配器。

        Raises:
            ValueError: ``adapter_id`` 已注册。
        """
        manifest = adapter.manifest()
        if manifest.adapter_id in self._adapters:
            raise ValueError(f"adapter already registered: {manifest.adapter_id}")
        self._adapters[manifest.adapter_id] = adapter

    def get(self, adapter_id: str) -> PlatformAdapter:
        """按 ID 返回 Adapter。

        Raises:
            AdapterNotFound: 未注册该 ID。
        """
        try:
            return self._adapters[adapter_id]
        except KeyError:
            raise AdapterNotFound(f"unknown adapter: {adapter_id}") from None

    def all(self) -> tuple[PlatformAdapter, ...]:
        """按注册顺序返回全部 Adapter。"""
        return tuple(self._adapters.values())

    def manifests(self) -> tuple[AdapterManifest, ...]:
        """返回全部 Adapter 的能力与限制声明。"""
        return tuple(adapter.manifest() for adapter in self._adapters.values())

    def health(self) -> tuple[IntegrationHealth, ...]:
        """返回全部 Adapter 的连接状态与数据新鲜度。"""
        return tuple(adapter.health() for adapter in self._adapters.values())

    def resolve(
        self,
        capability: IntegrationCapability,
        ref: PlatformRef | None = None,
    ) -> PlatformAdapter:
        """按能力与平台/店铺边界选择 Adapter。

        Args:
            capability: 请求的数据或控制能力。
            ref: 可选的租户/平台/店铺边界；``None`` 表示任意平台。

        Returns:
            第一个声明该能力的匹配 Adapter。

        Raises:
            AdapterNotFound: 没有匹配平台/店铺的 Adapter。
            CapabilityNotSupported: 存在匹配 Adapter，但未声明该能力。
        """
        candidates = tuple(
            adapter
            for adapter in self._adapters.values()
            if ref is None
            or (
                adapter.manifest().platform == ref.platform
                and adapter.health().shop_id == ref.shop_id
            )
        )
        if not candidates:
            raise AdapterNotFound(
                "no adapter for platform/shop: "
                f"{ref.platform if ref is not None else '*'}/"
                f"{ref.shop_id if ref is not None else '*'}"
            )
        for adapter in candidates:
            if capability in adapter.manifest().capabilities:
                return adapter
        raise CapabilityNotSupported(
            f"capability not supported: {capability.value}"
        )


class CapabilityRouter:
    """页面与 Agent 选择 Adapter 的唯一入口。"""

    def __init__(self, registry: AdapterRegistry) -> None:
        self._registry = registry

    def resolve(
        self,
        capability: IntegrationCapability,
        ref: PlatformRef | None = None,
    ) -> PlatformAdapter:
        """委托注册表按能力解析 Adapter。"""
        return self._registry.resolve(capability, ref)


class SourceOfTruthPolicy:
    """声明每个 canonical 实体的唯一主写方。

    策略只保存 ``实体 → adapter_id`` 配置，不包含平台分支。没有登记的实体
    不允许控制写，避免出现“后写覆盖”的双写冲突。
    """

    def __init__(self, writers: Mapping[str, str] | None = None) -> None:
        self._writers = dict(writers or {})

    def writer_for(self, entity_type: str) -> str:
        """返回实体的主写 Adapter ID。

        Raises:
            AdapterNotFound: 未声明主写方。
        """
        try:
            return self._writers[entity_type]
        except KeyError:
            raise AdapterNotFound(
                f"no source of truth for entity: {entity_type}"
            ) from None

    def all_writers(self) -> Mapping[str, str]:
        """返回只读的主写方配置副本。"""
        return dict(self._writers)


__all__ = ["AdapterRegistry", "CapabilityRouter", "SourceOfTruthPolicy"]
