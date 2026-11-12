"""跨境调度领域模型的单元测试。"""

import pytest

from opsconductor.dispatch.domain.enums import AgentStatus, RiskLevel, StepStatus
from opsconductor.dispatch.domain.errors import InvalidTransition
from opsconductor.dispatch.domain.models import AgentCard, PlanStep


def _step() -> PlanStep:
    return PlanStep(
        id="step-1", stage="order", name="订单异常", capability="order_triage",
        risk=RiskLevel.L2,
    )


def test_plan_step_transitions_and_rejects_double_finish():
    step = PlanStep(
        id="step-1", stage="order", name="订单异常", capability="order_triage",
        risk=RiskLevel.L2,
    )
    step.start()
    assert step.status is StepStatus.running
    step.finish("orders.json")
    assert step.status is StepStatus.succeeded
    assert step.artifact == "orders.json"

    with pytest.raises(InvalidTransition):
        step.finish("again.json")


def test_plan_step_cannot_finish_before_start():
    step = _step()

    with pytest.raises(InvalidTransition):
        step.finish("orders.json")

    assert step.status is StepStatus.pending
    assert step.artifact is None


def test_plan_step_fail_records_reason_and_rejects_restart():
    step = _step()
    step.start()
    step.fail("tool timeout")

    assert step.status is StepStatus.failed
    assert step.error == "tool timeout"

    with pytest.raises(InvalidTransition):
        step.start()


def test_agent_card_with_status_returns_updated_copy():
    card = AgentCard(
        id="selection", name="选品 Agent", role="趋势 · 评分 · SKU 组合",
        capabilities=("trend_scan",), risk=RiskLevel.L1,
    )

    updated = card.with_status(AgentStatus.done, "5 SKU")

    assert updated.status is AgentStatus.done
    assert updated.current_task == "5 SKU"
    assert updated.id == card.id
    assert card.status is AgentStatus.idle
    assert card.current_task == ""
