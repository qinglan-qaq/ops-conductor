"""为计划任务节点集中评定风险等级。

:class:`RiskPolicy` 是节点风险等级与审批标记的唯一来源。评级只从计划本身推导，
绝不来自任务指令：拆分节点的数量决定拆分是 L2 还是 L3。

Invariants:

- ``split_order`` 节点默认是 L2；当计划包含至少
  ``settings.l3_batch_threshold`` 个拆分时升级为 L3。
- ``change_address`` 节点始终是 L2 且需要审批。
- 其他动作（读取与校验）都是 L0，无需审批。
- 当且仅当某个节点最终为 L3 时，``Plan.requires_l3`` 为真。
"""

from opsconductor.config import Settings, get_settings
from opsconductor.domain.enums import RiskLevel
from opsconductor.schemas import Plan


class RiskPolicy:
    """节点风险等级与审批要求的唯一来源。

    拆分操作默认 L2，当单个任务计划达到或超过 ``settings.l3_batch_threshold``
    的批量时升级为 L3。改址始终是 L2，所有非写入动作都是 L0 且无需审批。

    Attributes:
        settings: 提供 L3 批量阈值的配置。
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @staticmethod
    def split_count(plan: Plan) -> int:
        """返回该计划包含多少个拆分操作。

        Args:
            plan: 统计其节点的计划。

        Returns:
            ``split_order`` 节点的数量。
        """

        return sum(1 for node in plan.nodes if node.action == "split_order")

    def assign(self, plan: Plan, split_count: int | None = None) -> RiskLevel:
        """返回适用于该计划拆分节点的风险等级。

        Args:
            plan: 参与评级的计划；未提供 ``split_count`` 时用于统计拆分数量。
            split_count: 预先算好的拆分数量，避免再次扫描。

        Returns:
            拆分数量达到配置的批量阈值时为 ``RiskLevel.L3``，否则为
            ``RiskLevel.L2``。
        """

        count = self.split_count(plan) if split_count is None else split_count
        if count >= self.settings.l3_batch_threshold:
            return RiskLevel.L3
        return RiskLevel.L2

    def apply(self, plan: Plan) -> RiskLevel:
        """就地为一计划中的每个节点设置风险与审批标记。

        Args:
            plan: 参与评级并被就地修改的计划。

        Returns:
            分配给拆分节点的风险等级：达到批量阈值时为 L3，否则为 L2。
        """

        split_risk = self.assign(plan)
        for node in plan.nodes:
            if node.action == "split_order":
                node.risk = split_risk
                node.requires_approval = True
            elif node.action == "change_address":
                node.risk = RiskLevel.L2
                node.requires_approval = True
            else:
                node.risk = RiskLevel.L0
                node.requires_approval = False
        plan.requires_l3 = any(node.risk == RiskLevel.L3 for node in plan.nodes)
        return split_risk
