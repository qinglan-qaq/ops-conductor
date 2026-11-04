"""Central risk grading for planned task nodes."""

from opsconductor.config import Settings, get_settings
from opsconductor.domain.enums import RiskLevel
from opsconductor.schemas import Plan


class RiskPolicy:
    """Single source of truth for node risk levels and approval requirements.

    Split operations are L2 by default and escalate to L3 when one task plans a
    batch at or above ``settings.l3_batch_threshold``. Address changes are
    always L2, and every non-write action is L0 and needs no approval.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @staticmethod
    def split_count(plan: Plan) -> int:
        """Return how many split operations this plan contains."""

        return sum(1 for node in plan.nodes if node.action == "split_order")

    def assign(self, plan: Plan, split_count: int | None = None) -> RiskLevel:
        """Return the risk level that applies to split nodes in this plan."""

        count = self.split_count(plan) if split_count is None else split_count
        if count >= self.settings.l3_batch_threshold:
            return RiskLevel.L3
        return RiskLevel.L2

    def apply(self, plan: Plan) -> RiskLevel:
        """Assign risk and approval flags to every node in place.

        Returns the risk level applied to split nodes, which is L3 when the
        batch threshold is reached.
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
