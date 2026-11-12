"""跨境调度领域策略与审批状态机的单元测试。"""

import pytest

from opsconductor.dispatch.domain.enums import ApprovalStatus, Decision, Priority, RiskLevel
from opsconductor.dispatch.domain.errors import ApprovalAlreadyDecided, InvalidGoal
from opsconductor.dispatch.domain.models import ApprovalCase, Goal
from opsconductor.dispatch.domain.policies import ApprovalPolicy, PriorityPolicy, RiskPolicy


def test_risk_policy_l3_budget_l2_price_l0_scan():
    policy = RiskPolicy()
    assert policy.classify("ads_create", amount=10_000) is RiskLevel.L3
    assert policy.classify("price_update") is RiskLevel.L2
    assert policy.classify("trend_scan") is RiskLevel.L0
    assert policy.requires_approval(RiskLevel.L2)
    assert not policy.requires_approval(RiskLevel.L1)


def test_priority_policy_5x5_and_sla():
    policy = PriorityPolicy()
    assert policy.classify(5, 4) is Priority.P0
    assert policy.classify(4, 3) is Priority.P1
    assert policy.classify(3, 2) is Priority.P2
    assert policy.classify(1, 1) is Priority.P3
    assert policy.sla_minutes(Priority.P0) == 15
    assert policy.sla_minutes(Priority.P1) == 30


def test_approval_policy_delegates_to_risk_policy():
    policy = ApprovalPolicy()
    assert policy.requires_approval(RiskLevel.L3)
    assert not policy.requires_approval(RiskLevel.L0)


def test_approval_cannot_be_decided_twice():
    approval = ApprovalCase(
        id="budget", title="广告预算", action="ads_create",
        risk=RiskLevel.L3, owner="投放 Agent", impact="影响 3 个 Campaign",
    )
    approval.decide(Decision.approve, "财务小财", "10:50")
    with pytest.raises(ApprovalAlreadyDecided):
        approval.decide(Decision.reject, "运营小运", "10:51")


def test_approval_reset_restores_pending_state():
    approval = ApprovalCase(
        id="price", title="涨价建议", action="price_update",
        risk=RiskLevel.L2, owner="定价 Agent", impact="影响 Listing 价格",
    )
    approval.decide(Decision.reject, "运营小运", "10:51")
    assert approval.status is ApprovalStatus.rejected

    approval.reset()

    assert approval.status is ApprovalStatus.pending
    assert approval.actor is None
    assert approval.decided_at is None


def test_goal_rejects_blank_instruction():
    with pytest.raises(InvalidGoal):
        Goal(id="g1", instruction="   ")
