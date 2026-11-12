"""阶段目录、阶段结果与首页聚合视图的单元测试。"""

from __future__ import annotations

import copy

import pytest

from opsconductor.dispatch.application.agents import (
    AgentRegistry,
    VerifierAgent,
    build_agents,
)
from opsconductor.dispatch.application.orchestrator import DispatchOrchestrator
from opsconductor.dispatch.application.seed import build_seed_state
from opsconductor.dispatch.application.service import DispatchService
from opsconductor.dispatch.application.stages import STAGE_CATALOG, STAGE_RESULTS
from opsconductor.dispatch.domain.enums import ApprovalStatus
from opsconductor.dispatch.domain.errors import StageNotFound


class _Tools:
    """返回确定性工具产物的测试网关。"""

    def call(self, tool, params):
        return {"tool": tool, "artifact": f"{tool}.json"}


class _Clock:
    """固定展示时刻，避免测试依赖本地时间。"""

    def now_label(self):
        return "10:50"


class _FakeRepository:
    """与仓储端口一致、返回深拷贝的测试仓储。"""

    def __init__(self, seed):
        self._seed = seed
        self._state = seed()

    def snapshot(self):
        return copy.deepcopy(self._state)

    def mutate(self, mutator):
        mutator(self._state)

    def reset(self):
        self._state = self._seed()
        return copy.deepcopy(self._state)


def _service() -> DispatchService:
    agents = build_agents(_Tools())
    orchestrator = DispatchOrchestrator(AgentRegistry(agents), VerifierAgent(), _Clock())
    repo = _FakeRepository(
        lambda: build_seed_state({a.card.id: a.card for a in agents.values()})
    )
    return DispatchService(repo, orchestrator, _Clock())


def test_stage_catalog_has_ten_stages_in_scenario_order():
    assert [stage.id for stage in STAGE_CATALOG] == [
        "selection",
        "content",
        "listing",
        "organic",
        "paid",
        "order",
        "fulfillment",
        "logistics",
        "settlement",
        "aftersales",
    ]


def test_every_stage_has_four_or_five_steps():
    assert all(4 <= len(stage.steps) <= 5 for stage in STAGE_CATALOG)


def test_stage_results_cover_every_operational_stage():
    assert set(STAGE_RESULTS) == {stage.id for stage in STAGE_CATALOG}
    assert all(result.agent_id for result in STAGE_RESULTS.values())
    assert all(
        result.provenance.adapter == "MockPlatformAdapter"
        for result in STAGE_RESULTS.values()
    )


def test_order_stage_result_uses_script_numbers():
    result = STAGE_RESULTS["order"]

    assert result.summary == "分类 6 单异常，2 单 P0/P1；拆单/改址建议已生成"
    assert [artifact.name for artifact in result.artifacts] == [
        "order-exceptions.csv",
        "split-address-plan.json",
    ]
    assert {metric.key: metric.value for metric in result.metrics} == {
        "exceptions": 6,
        "p0_p1": 2,
        "sla_minutes": 15,
    }


def test_navigation_has_ten_stages_plus_control_tower():
    navigation = _service().snapshot().navigation

    assert [item.id for item in navigation] == [
        *[stage.id for stage in STAGE_CATALOG],
        "control",
    ]
    assert navigation[-1].order_label == "—"
    assert navigation[-1].approval_count == 3
    assert navigation[-1].exception_count == 6


def test_stage_detail_filters_approvals_and_exceptions_by_stage():
    service = _service()

    order = service.get_stage_detail("order")
    paid = service.get_stage_detail("paid")
    settlement = service.get_stage_detail("settlement")

    assert [case.id for case in order.exceptions] == ["ORD-01", "ORD-03", "ORD-04"]
    assert order.approvals == ()
    assert [case.id for case in paid.approvals] == ["budget"]
    assert [case.id for case in settlement.approvals] == ["refund"]


def test_get_stage_unknown_raises_stage_not_found():
    service = _service()

    with pytest.raises(StageNotFound):
        service.get_stage_detail("unknown")
    with pytest.raises(StageNotFound):
        service.get_stage_detail("control")


def test_approval_progress_updates_after_decision():
    service = _service()

    assert service.approval_progress().decided_percent == 0
    service.decide_approval("budget", "approve", "财务小财")
    progress = service.approval_progress()

    assert (progress.total, progress.pending, progress.approved) == (3, 2, 1)
    assert progress.decided_percent == 33
    assert (progress.l2_total, progress.l3_total) == (1, 2)
    assert service.snapshot().navigation[5].approval_count == 0


def test_status_summary_counts_chain_agents_approvals_exceptions():
    summary = _service().snapshot().status_summary

    assert summary.chain == {"done": 1, "running": 3, "alert": 2, "waiting": 4}
    assert summary.agents == {"idle": 0, "running": 4, "waiting": 2, "done": 2, "error": 0}
    assert summary.approvals.pending == 3
    assert summary.exceptions == {"P0": 1, "P1": 4, "P2": 1, "P3": 0}


def test_stage_status_survives_approval_decision():
    service = _service()
    service.decide_approval("price", "reject", "运营小运")

    detail = service.get_stage_detail("listing")

    assert detail.status.value == "waiting"
    assert detail.approvals[0].status is ApprovalStatus.rejected
