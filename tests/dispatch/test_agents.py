"""应用层 Agent 注册表与独立 Verifier 的单元测试。"""

import pytest

from opsconductor.dispatch.application.agents import (
    AgentRegistry,
    VerifierAgent,
    build_agents,
)
from opsconductor.dispatch.domain.enums import AgentStatus, Decision, RiskLevel
from opsconductor.dispatch.domain.models import AgentTask


class _Tools:
    def call(self, tool, params):
        return {"tool": tool, "artifact": f"{tool}.json", "status": "ok"}


def _task(capability: str, stage: str = "demo") -> AgentTask:
    return AgentTask(step_id=f"step-{capability}", stage=stage, capability=capability)


def test_builds_eight_agents_and_selects_by_capability():
    agents = build_agents(_Tools())
    registry = AgentRegistry(agents)

    assert len(registry.all()) == 8
    assert registry.select("trend_scan").card.id == "selection"
    assert registry.select("ads_create").card.risk is RiskLevel.L3
    assert all(a.card.status is AgentStatus.idle for a in registry.all())
    assert registry.get("settlement").card.id == "settlement"


def test_agent_capabilities_cover_the_ten_step_plan():
    registry = AgentRegistry(build_agents(_Tools()))

    expected = {
        "trend_scan": "selection",
        "content_brief": "content",
        "content_plan": "content",
        "price_update": "pricing",
        "listing_update": "pricing",
        "ads_create": "ads",
        "order_triage": "order",
        "shipment_create": "fulfillment",
        "customs_declare": "fulfillment",
        "settlement_fetch": "settlement",
        "compliance_check": "compliance",
    }
    assert {capability: registry.select(capability).card.id for capability in expected} == expected
    with pytest.raises(LookupError):
        registry.select("unknown_capability")


def test_handle_calls_tool_and_returns_artifact_summary_and_metadata():
    agents = build_agents(_Tools())

    result = agents["selection"].handle(_task("trend_scan", "selection"))

    assert result.agent_id == "selection"
    assert result.stage == "selection"
    assert result.artifact == "trend_scan.json"
    assert result.summary
    assert result.risk is RiskLevel.L1
    assert result.metadata == {"margin": 6.8}
    assert result.approval is None


def test_approval_drafts_match_the_demo_script():
    agents = build_agents(_Tools())

    budget = agents["ads"].handle(_task("ads_create", "paid")).approval
    price = agents["pricing"].handle(_task("listing_update", "listing")).approval
    refund = agents["settlement"].handle(_task("settlement_fetch", "settlement")).approval

    assert budget is not None
    assert (budget.id, budget.action, budget.risk, budget.recommended) == (
        "budget",
        "ads_create",
        RiskLevel.L3,
        Decision.approve,
    )
    assert price is not None
    assert (price.id, price.action, price.risk, price.recommended) == (
        "price",
        "price_update",
        RiskLevel.L2,
        Decision.reject,
    )
    assert refund is not None
    assert (refund.id, refund.action, refund.risk, refund.recommended) == (
        "refund",
        "refund_execute",
        RiskLevel.L3,
        Decision.approve,
    )


def test_handle_metadata_for_demo_agents():
    agents = build_agents(_Tools())

    assert agents["ads"].handle(_task("ads_create")).metadata == {"budget": 10000}
    assert agents["settlement"].handle(_task("settlement_fetch")).metadata == {"diff_count": 3}
    assert agents["fulfillment"].handle(_task("shipment_create")).metadata == {
        "customs_failed": True
    }
    assert agents["order"].handle(_task("order_triage")).metadata == {"inventory": 0}


def test_verifier_passes_but_vetoes_low_margin_selection():
    agents = build_agents(_Tools())
    results = [
        agents["selection"].handle(_task("trend_scan", "selection")),
        agents["order"].handle(_task("order_triage", "order")),
        agents["ads"].handle(_task("ads_create", "paid")),
        agents["compliance"].handle(_task("compliance_check", "aftersales")),
    ]

    verification = VerifierAgent().verify(results)

    assert verification.passed
    assert verification.checks == ("margin", "inventory", "budget", "compliance", "trace")
    assert verification.vetoed == ("SKU NW-102 margin 6.8% < 15%",)
