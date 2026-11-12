"""跨境调度领域策略：风险分级、审批门禁与异常优先级。

策略是无状态纯函数对象，便于应用层复用与单元测试。风险分级规则对应
SPEC §9 与 Demo 剧本：``ads_create``、``refund_execute`` 等资金/大额动作固定
为 ``L3``，改价与履约写操作为 ``L2``，内容与对账任务为 ``L1``，其余读取类动作
为 ``L0``。
"""

from opsconductor.dispatch.domain.enums import Priority, RiskLevel

L3_ACTIONS = {"ads_create", "refund_execute", "compensate_execute"}
L2_ACTIONS = {
    "listing_update",
    "price_update",
    "split_order",
    "change_address",
    "shipment_create",
    "customs_declare",
    "rpa_supplier_portal",
}
L1_ACTIONS = {"content_brief", "asset_draft", "reconcile_task"}

PRIORITY_SLA_MINUTES = {
    Priority.P0: 15,
    Priority.P1: 30,
    Priority.P2: 240,
    Priority.P3: 1440,
}


class RiskPolicy:
    """按动作名与金额判定 L0–L3 风险等级。"""

    def classify(self, action: str, amount: int | None = None) -> RiskLevel:
        """返回动作的风险等级。

        Args:
            action: 工具或计划动作名，例如 ``ads_create``。
            amount: 可选的整数美元金额；大额广告创建视为 ``L3``。

        Returns:
            匹配的 :class:`RiskLevel`；未知动作按 ``L0`` 处理。
        """
        if action in L3_ACTIONS:
            return RiskLevel.L3
        if action == "ads_create" and amount is not None and amount > 1000:
            return RiskLevel.L3
        if action in L2_ACTIONS:
            return RiskLevel.L2
        if action in L1_ACTIONS:
            return RiskLevel.L1
        return RiskLevel.L0

    def requires_approval(self, risk: RiskLevel) -> bool:
        """返回该风险等级是否必须人工审批。

        ``L2`` 需要二次确认，``L3`` 必须人工审批；``L0``/``L1`` 自动执行。
        """
        return risk in {RiskLevel.L2, RiskLevel.L3}


class ApprovalPolicy:
    """审批门禁策略。

    当前 Demo 的审批规则与风险策略一致，保留独立类型以便后续按租户或动作
    扩展差异化门禁。
    """

    def requires_approval(self, risk: RiskLevel) -> bool:
        """返回该风险等级是否进入审批队列。"""
        return RiskPolicy().requires_approval(risk)


class PriorityPolicy:
    """按 5×5 风险矩阵（可能性 × 影响）给异常定级并给出响应 SLA。"""

    def classify(self, likelihood: int, impact: int) -> Priority:
        """按乘积阈值把 L×I 映射为 P0–P3。

        Args:
            likelihood: 可能性维度，通常为 1–5。
            impact: 影响维度，通常为 1–5。

        Returns:
            分数 ≥20 为 P0，≥12 为 P1，≥6 为 P2，其余为 P3。
        """
        score = likelihood * impact
        if score >= 20:
            return Priority.P0
        if score >= 12:
            return Priority.P1
        if score >= 6:
            return Priority.P2
        return Priority.P3

    def sla_minutes(self, priority: Priority) -> int:
        """返回优先级的响应 SLA（分钟）。

        Args:
            priority: 异常的优先级。

        Returns:
            该优先级的响应时长，P0 为 15 分钟，P3 为 1440 分钟。
        """
        return PRIORITY_SLA_MINUTES[priority]
