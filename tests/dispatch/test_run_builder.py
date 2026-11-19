"""RunBuilder 与编排器兼容性测试。"""

from __future__ import annotations

from opsconductor.dispatch.application.agents import (
    AgentRegistry,
    VerifierAgent,
    build_agents,
)
from opsconductor.dispatch.application.orchestrator import DispatchOrchestrator
from opsconductor.dispatch.application.seed import SEED_GOAL
from opsconductor.dispatch.domain.enums import ApprovalStatus, Decision
from opsconductor.dispatch.domain.runs import RunEventKind, RunStatus, RunStepStatus


class _Tools:
    def call(self, tool, params):
        return {"tool": tool, "artifact": f"{tool}.json", "status": "ok"}


class _Clock:
    def now_label(self):
        return "10:50"


def _orchestrator() -> DispatchOrchestrator:
    return DispatchOrchestrator(
        AgentRegistry(build_agents(_Tools())), VerifierAgent(), _Clock()
    )


def _run():
    return _orchestrator().run_agent(SEED_GOAL, run_id="run-test")


def test_run_records_full_execution_fact() -> None:
    run = _run()

    assert run.id == "run-test"
    assert run.status is RunStatus.succeeded
    assert len(run.steps) == 10
    assert len(run.agents) == 8
    assert len(run.handoffs) == 8
    assert len(run.gates) == 3
    assert len(run.artifacts) == 10
    assert len(run.events) == 51
    assert all(step.status is RunStepStatus.succeeded for step in run.steps)
    assert all(step.tool_calls for step in run.steps)
    assert all(len(step.tool_calls) == 1 for step in run.steps)
    assert run.metrics.step_count == 10
    assert run.metrics.succeeded_steps == 10
    assert run.metrics.agent_count == 8
    assert run.metrics.handoff_count == 8
    assert run.metrics.gate_count == 3
    assert run.metrics.approved_gates == 2
    assert run.metrics.rejected_gates == 1
    assert run.metrics.artifact_count == 10
    assert run.metrics.compensation_count == 1
    assert run.metrics.reconciliation_count == 3
    assert run.metrics.duration_ms >= 0


def test_event_titles_and_order_match_the_script() -> None:
    titles = [event.title for event in _run().events]

    assert titles[0] == "运行开始"
    assert titles.count("Agent 启动") == 10
    assert titles.count("工具调用") == 10
    assert titles.count("Agent 完成") == 10
    assert titles.count("Agent 交接") == 8
    assert titles.count("审批待决") == 3
    assert titles.count("审批通过") == 2
    assert titles.count("审批驳回") == 1
    assert titles.count("Verifier 通过") == 1
    assert titles.count("补偿触发") == 1
    assert titles.count("RPA 执行") == 1
    assert titles.count("对账差异") == 1
    assert titles.count("报告生成") == 1
    assert titles.count("运行完成") == 1
    assert titles[-1] == "运行完成"


def test_handoff_sequence_and_event_linkage() -> None:
    run = _run()

    assert [(handoff.from_agent_id, handoff.to_agent_id) for handoff in run.handoffs] == [
        ("selection", "content"),
        ("content", "pricing"),
        ("pricing", "content"),
        ("content", "ads"),
        ("ads", "order"),
        ("order", "fulfillment"),
        ("fulfillment", "settlement"),
        ("settlement", "compliance"),
    ]
    handoff_events = {
        event.seq: event for event in run.events if event.kind is RunEventKind.handoff
    }
    for handoff in run.handoffs:
        event = handoff_events[handoff.event_seq]
        assert event.step_id == handoff.to_step_id
        assert event.agent_id == handoff.to_agent_id
        assert handoff.artifact


def test_gates_follow_the_demo_script() -> None:
    run = _run()
    gates = {gate.id: gate for gate in run.gates}

    assert set(gates) == {"budget", "price", "refund"}
    assert gates["budget"].status is ApprovalStatus.approved
    assert gates["budget"].decision is Decision.approve
    assert gates["budget"].stage == "paid"
    assert gates["price"].status is ApprovalStatus.rejected
    assert gates["price"].decision is Decision.reject
    assert gates["price"].stage == "listing"
    assert gates["refund"].status is ApprovalStatus.approved
    assert gates["refund"].stage == "settlement"
    assert gates["budget"].step_id == "step-5"
    assert gates["price"].step_id == "step-3"
    assert gates["refund"].step_id == "step-9"


def test_run_is_deterministic_in_content() -> None:
    first = _run()
    second = _run()

    assert [step.id for step in first.steps] == [step.id for step in second.steps]
    assert [event.kind for event in first.events] == [event.kind for event in second.events]
    assert [event.title for event in first.events] == [event.title for event in second.events]
    assert first.handoffs == second.handoffs
    assert first.gates == second.gates


def test_run_report_remains_compatible() -> None:
    report = _orchestrator().run(SEED_GOAL)
    titles = [event.title for event in report.events]

    assert len(report.events) == 28
    assert len(report.steps) == 10
    assert len(report.approvals) == 3
    assert titles.count("审批通过") == 2
    assert titles.count("审批驳回") == 1
    assert "补偿触发" in titles
    assert any("RPA" in title for title in titles)
    assert any("对账差异" in title for title in titles)
    assert "报告生成" in titles
    assert report.verification.passed
    assert report.verification.vetoed
    assert report.summary
