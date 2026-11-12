"""跨境调度领域模型的单元测试。"""

import pytest

from opsconductor.dispatch.domain.enums import AgentStatus, RiskLevel, StageStatus, StepStatus
from opsconductor.dispatch.domain.errors import InvalidTransition
from opsconductor.dispatch.domain.models import (
    AgentCard,
    CanonicalOrder,
    DataProvenance,
    Metric,
    OrderLine,
    PlanStep,
    StageDefinition,
    StageResult,
    StageStep,
)


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


def _provenance() -> DataProvenance:
    """返回测试用 canonical 数据来源。"""
    return DataProvenance(
        platform="mock",
        shop_id="nestwell-us",
        adapter="MockPlatformAdapter",
        synced_at="10:42",
        schema_version="1.0",
    )


def test_stage_result_rejects_duplicate_metrics():
    with pytest.raises(ValueError, match="metric keys must be unique"):
        StageResult(
            stage_id="order",
            agent_id="order",
            status=StageStatus.alert,
            summary="分类 6 单异常",
            artifacts=(),
            evidence=(),
            metrics=(Metric("exceptions", 6), Metric("exceptions", 7)),
            provenance=_provenance(),
            at="11:02",
        )


def test_stage_result_rejects_blank_summary():
    with pytest.raises(ValueError, match="summary must not be blank"):
        StageResult(
            stage_id="order",
            agent_id="order",
            status=StageStatus.alert,
            summary="   ",
            artifacts=(),
            metrics=(),
            evidence=(),
            provenance=_provenance(),
            at="11:02",
        )


def test_stage_definition_keeps_steps_in_declared_order():
    definition = StageDefinition(
        id="order",
        order_label="陆",
        name="订单",
        owner="订单运营",
        risk=RiskLevel.L2,
        actions=("订单同步", "拆单/改址"),
        failures=("超卖", "超时未发"),
        ai=("异常分类",),
        metrics=("迟发率",),
        steps=(StageStep("sync", "订单同步"), StageStep("split", "拆单 / 改址")),
    )

    assert [step.id for step in definition.steps] == ["sync", "split"]


def test_canonical_order_preserves_external_id_and_raw_ref():
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

    assert order.external_id == "NW-1001"
    assert order.raw_ref == "mock://orders/NW-1001"
    assert order.lines[0].sku == "NW-101"
