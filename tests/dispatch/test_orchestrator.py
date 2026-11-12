"""应用层计划工厂与 Demo 编排器的单元测试。"""

from opsconductor.dispatch.application.agents import (
    AgentRegistry,
    VerifierAgent,
    build_agents,
)
from opsconductor.dispatch.application.orchestrator import DispatchOrchestrator
from opsconductor.dispatch.application.plans import build_plan
from opsconductor.dispatch.application.seed import SEED_GOAL
from opsconductor.dispatch.domain.enums import ApprovalStatus, StepStatus


class _Tools:
    def call(self, tool, params):
        return {"tool": tool, "artifact": f"{tool}.json"}


class _Clock:
    def now_label(self):
        return "10:50"


def _orchestrator():
    return DispatchOrchestrator(AgentRegistry(build_agents(_Tools())), VerifierAgent(), _Clock())


def test_plan_has_ten_steps_and_three_approval_ids():
    plan = build_plan(SEED_GOAL)

    assert len(plan.steps) == 10
    assert plan.goal_id == SEED_GOAL.id
    assert plan.approval_ids == ["budget", "price", "refund"]
    assert [step.stage for step in plan.steps] == [
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


def test_plan_seed_statuses_match_the_dashboard():
    steps = {step.stage: step for step in build_plan(SEED_GOAL).steps}

    assert steps["selection"].status is StepStatus.succeeded
    for stage in ("content", "order", "fulfillment", "logistics", "settlement"):
        assert steps[stage].status is StepStatus.running
    for stage in ("listing", "organic", "paid", "aftersales"):
        assert steps[stage].status is StepStatus.pending


def test_demo_run_records_approvals_compensation_rpa_and_diffs():
    report = _orchestrator().run(SEED_GOAL)
    titles = [event.title for event in report.events]

    assert titles.count("审批通过") == 2
    assert titles.count("审批驳回") == 1
    assert "补偿触发" in titles
    assert any("RPA" in title for title in titles)
    assert any("对账差异" in title for title in titles)
    assert "报告生成" in titles
    assert report.verification.passed
    assert report.verification.vetoed
    assert report.summary


def test_demo_run_executes_all_steps_and_applies_scripted_decisions():
    report = _orchestrator().run(SEED_GOAL)

    assert len(report.steps) == 10
    assert all(step.status is StepStatus.succeeded for step in report.steps)
    assert all(step.artifact for step in report.steps)

    approvals = {approval.id: approval for approval in report.approvals}
    assert set(approvals) == {"budget", "price", "refund"}
    assert approvals["budget"].status is ApprovalStatus.approved
    assert approvals["price"].status is ApprovalStatus.rejected
    assert approvals["refund"].status is ApprovalStatus.approved
    assert approvals["budget"].actor == "财务小财"
    assert approvals["price"].actor == "运营小运"
