"""平台控制写的应用服务：审批、幂等、dry-run 与能力门禁。

页面与 Agent 不得直接调用 :class:`~opsconductor.dispatch.domain.ports.PlatformControlPort`；
只能经本服务执行写命令。服务按以下顺序校验，任一失败都不触达 Adapter：

1. 能力必须由 Adapter manifest 声明；
2. ``L2``/``L3`` 命令必须携带已批准的 ``approval_id``；
3. 同一幂等键只允许对应同一命令体；
4. ``dry_run`` 只能预检，不得写平台。

本期不提供 HTTP 写端点；真实平台接入时再挂载 ``POST /control/commands``。
"""

from __future__ import annotations

from collections.abc import Callable

from opsconductor.dispatch.application.integrations import AdapterRegistry
from opsconductor.dispatch.domain.enums import ControlStatus, RiskLevel
from opsconductor.dispatch.domain.errors import (
    ApprovalRequired,
    CapabilityNotSupported,
    IdempotencyConflict,
)
from opsconductor.dispatch.domain.models import (
    ControlCommand,
    ControlResult,
    PlatformRef,
)

_APPROVAL_RISKS = {RiskLevel.L2, RiskLevel.L3}


class ControlService:
    """执行受审批与幂等保护的控制命令。

    Attributes:
        _approved: 审批查询函数；返回 ``True`` 才允许 L2/L3 写。
        _results: 幂等键 → ``(命令签名, 首次结果)``。
    """

    def __init__(
        self,
        registry: AdapterRegistry,
        approved: Callable[[str], bool],
    ) -> None:
        self._registry = registry
        self._approved = approved
        self._results: dict[str, tuple[str, ControlResult]] = {}

    def execute(self, command: ControlCommand) -> ControlResult:
        """校验并执行一条控制命令。

        Args:
            command: 跨平台控制写命令。

        Returns:
            Adapter 返回的控制结果；dry-run 只能返回 ``accepted``。

        Raises:
            AdapterNotFound: 平台/店铺没有注册 Adapter。
            CapabilityNotSupported: Adapter 未声明该能力，或不支持 dry-run。
            ApprovalRequired: L2/L3 缺少已批准的审批 ID。
            IdempotencyConflict: 同一幂等键被用于不同命令体。
        """
        adapter = self._registry.resolve(
            command.capability,
            PlatformRef(
                tenant_id=command.tenant_id,
                platform=command.platform,
                shop_id=command.shop_id,
            ),
        )
        manifest = adapter.manifest()
        if command.capability not in manifest.capabilities:
            raise CapabilityNotSupported(
                f"capability not supported: {command.capability.value}"
            )
        if command.risk in _APPROVAL_RISKS:
            if not command.approval_id or not self._approved(command.approval_id):
                raise ApprovalRequired(
                    f"approval required for {command.risk.value}: "
                    f"{command.capability.value}"
                )
        if command.dry_run and not manifest.supports_dry_run:
            raise CapabilityNotSupported(
                f"adapter {manifest.adapter_id} does not support dry-run"
            )

        signature = self._signature(command)
        cached = self._results.get(command.idempotency_key)
        if cached is not None:
            previous_signature, previous_result = cached
            if previous_signature != signature:
                raise IdempotencyConflict(
                    f"idempotency key reused: {command.idempotency_key}"
                )
            return previous_result

        result = adapter.execute(command)
        if not command.dry_run and result.status is ControlStatus.accepted:
            result = ControlResult(
                command_id=result.command_id,
                status=ControlStatus.succeeded,
                external_id=result.external_id,
                evidence=result.evidence,
                error=result.error,
                adapter_meta=result.adapter_meta,
                completed_at=result.completed_at,
            )
        self._results[command.idempotency_key] = (signature, result)
        return result

    @staticmethod
    def _signature(command: ControlCommand) -> str:
        """生成用于幂等冲突检测的稳定命令体签名。"""
        params = tuple(
            sorted((str(key), repr(value)) for key, value in command.params.items())
        )
        return repr(
            (
                command.command_id,
                command.tenant_id,
                command.platform,
                command.shop_id,
                command.capability.value,
                command.operation,
                command.entity_type,
                command.entity_id,
                params,
                command.expected_version,
                command.risk.value,
                command.dry_run,
                command.approval_id,
            )
        )


__all__ = ["ControlService"]
