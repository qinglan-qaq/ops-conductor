"""经营分析只读视图：销售额、Agent 使用量与结果交付。"""

from __future__ import annotations

from opsconductor.dispatch.adapters.container import reset_service
from opsconductor.dispatch.application.stages import STAGE_RESULTS


def test_analytics_covers_sales_agents_and_stage_results():
    reset_service()
    analytics = reset_service().snapshot().analytics

    assert len(analytics.sales.points) == 7
    assert sum(point.amount_usd for point in analytics.sales.points) == 99_600
    assert analytics.sales.target_usd == 100_000
    assert len(analytics.agent_usage) == 8
    assert {usage.agent_id for usage in analytics.agent_usage} == {
        "selection",
        "content",
        "pricing",
        "ads",
        "order",
        "fulfillment",
        "settlement",
        "compliance",
    }

    assert analytics.results.total_results == 10
    assert analytics.results.artifact_count == 20
    assert analytics.results.evidence_count == 20
    assert analytics.results.alert_stages == 2
    assert len(analytics.results.stages) == 10


def test_analytics_results_match_stage_result_artifacts():
    analytics = reset_service().snapshot().analytics

    expected_artifacts = sum(
        len(result.artifacts) for result in STAGE_RESULTS.values()
    )
    expected_evidence = sum(
        len(result.evidence) for result in STAGE_RESULTS.values()
    )

    assert analytics.results.artifact_count == expected_artifacts
    assert analytics.results.evidence_count == expected_evidence
