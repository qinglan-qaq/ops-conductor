"""应用层 DispatchService 门面的单元测试。

适配器是后续任务，这里使用测试内的假仓储（快照 / 修改 / 重置 + 深拷贝）
验证门面行为；真实内存仓储由 Task 3/5 覆盖。
"""

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
from opsconductor.dispatch.domain.enums import ApprovalStatus, Decision
from opsconductor.dispatch.domain.errors import (
    ApprovalAlreadyDecided,
    ApprovalNotFound,
    ExceptionNotFound,
    InvalidGoal,
)


class _Tools:
    def call(self, tool, params):
        return {"tool": tool, "artifact": f"{tool}.json"}


class _Clock:
    def now_label(self):
        return "10:50"


class _FakeRepository:
    """测试内仓储：与端口契约一致，快照返回深拷贝。"""

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


def _service():
    agents = build_agents(_Tools())
    orchestrator = DispatchOrchestrator(AgentRegistry(agents), VerifierAgent(), _Clock())
    repo = _FakeRepository(lambda: build_seed_state({a.card.id: a.card for a in agents.values()}))
    return DispatchService(repo, orchestrator, _Clock())


def test_snapshot_starts_with_three_pending_approvals_and_six_exceptions():
    snapshot = _service().snapshot()

    assert snapshot.kpis.approvals_pending == 3
    assert snapshot.kpis.gmv_target == 100_000
    assert snapshot.kpis.exceptions == 6
    assert snapshot.kpis.compensations == 1
    assert len(snapshot.approvals) == 3
    assert len(snapshot.exceptions) == 6
    assert len(snapshot.agents) == 8
    assert len(snapshot.chain) == 10
    assert len(snapshot.trace) == 7
    assert snapshot.flow_note == "审批进行中 · 3 件待批"


def test_approve_reject_updates_state_and_trace():
    service = _service()

    service.decide_approval("budget", "approve", "财务小财")
    snapshot = service.snapshot()

    assert snapshot.kpis.approvals_pending == 2
    assert snapshot.approvals["budget"].status is ApprovalStatus.approved
    assert snapshot.approvals["budget"].actor == "财务小财"
    assert snapshot.flow_note == "审批进行中 · 2 件待批"
    assert any(event.title == "审批通过" for event in snapshot.trace)
    assert len(snapshot.trace) == 8


def test_reject_records_rejected_status_and_trace():
    service = _service()

    snapshot = service.decide_approval("price", "reject", "运营小运")

    approval = snapshot.approvals["price"]
    assert approval.status is ApprovalStatus.rejected
    assert approval.decided_at == "10:50"
    assert snapshot.trace[-1].title == "审批驳回"


def test_approval_cannot_be_decided_twice_and_unknown_raises():
    service = _service()
    service.decide_approval("budget", "approve", "财务小财")

    with pytest.raises(ApprovalAlreadyDecided):
        service.decide_approval("budget", "reject", "运营小运")
    with pytest.raises(ApprovalNotFound):
        service.decide_approval("missing", "approve", "财务小财")


def test_flow_note_turns_to_execution_when_approvals_are_clear():
    service = _service()
    service.decide_approval("budget", "approve", "财务小财")
    service.decide_approval("price", "reject", "运营小运")
    snapshot = service.decide_approval("refund", "approve", "财务小财")

    assert snapshot.kpis.approvals_pending == 0
    assert snapshot.flow_note == "审批已清 · 进入执行"


def test_reset_approvals_restores_pending_and_appends_trace():
    service = _service()
    service.decide_approval("budget", "approve", "财务小财")
    service.decide_approval("price", "reject", "运营小运")

    snapshot = service.reset_approvals()

    assert snapshot.kpis.approvals_pending == 3
    assert all(a.status is ApprovalStatus.pending for a in snapshot.approvals.values())
    assert all(a.actor is None and a.decided_at is None for a in snapshot.approvals.values())
    assert snapshot.trace[-1].title == "审批案重置"


def test_create_goal_rebuilds_plan_and_resets_demo_state():
    service = _service()
    service.decide_approval("budget", "approve", "财务小财")

    snapshot = service.create_goal("把 GMV 做到 $120k，优先稳住退款率。")

    assert snapshot.goal.id == "goal-demo"
    assert snapshot.goal.instruction == "把 GMV 做到 $120k，优先稳住退款率。"
    assert snapshot.plan.goal_id == "goal-demo"
    assert snapshot.kpis.approvals_pending == 3
    assert len(snapshot.trace) == 8
    assert snapshot.trace[-1].title == "计划生成"
    assert snapshot.flow_note == "审批进行中 · 3 件待批"


def test_create_goal_rejects_blank_instruction():
    with pytest.raises(InvalidGoal):
        _service().create_goal("   ")


def test_run_demo_returns_orchestrator_report():
    report = _service().run_demo()

    assert len(report.steps) == 10
    assert len(report.approvals) == 3
    assert {a.id for a in report.approvals} == {"budget", "price", "refund"}
    assert all(a.status is not ApprovalStatus.pending for a in report.approvals)
    assert report.verification.passed


def test_get_exception_returns_playbook_and_unknown_raises():
    service = _service()

    exception = service.get_exception("ORD-01")

    assert exception.id == "ORD-01"
    assert exception.priority.value == "P0"
    assert len(exception.playbook.phases) == 3
    with pytest.raises(ExceptionNotFound):
        service.get_exception("NOPE-99")


def test_reset_restores_full_seed_snapshot():
    service = _service()
    service.decide_approval("budget", "approve", "财务小财")
    service.create_goal("任意新目标")

    snapshot = service.reset()

    assert snapshot.goal.id == "goal-demo"
    assert snapshot.goal.instruction.startswith("本周做到 $100k GMV")
    assert snapshot.kpis.approvals_pending == 3
    assert len(snapshot.trace) == 7
    assert snapshot.trace[0].title == "目标接入"
    assert all(a.status is ApprovalStatus.pending for a in snapshot.approvals.values())


def test_decision_strings_use_domain_enum():
    snapshot = _service().decide_approval("refund", Decision.approve.value, "财务小财")

    assert snapshot.approvals["refund"].status is ApprovalStatus.approved
