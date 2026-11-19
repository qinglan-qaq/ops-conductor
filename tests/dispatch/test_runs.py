"""Run 领域值对象与聚合不变量测试。"""

from __future__ import annotations

import pytest

from opsconductor.dispatch.domain.enums import (
    ApprovalStatus,
    ArtifactKind,
    Decision,
    RiskLevel,
)
from opsconductor.dispatch.domain.models import Goal, VerificationResult
from opsconductor.dispatch.domain.runs import (
    AgentRun,
    RunAgent,
    RunArtifact,
    RunEvent,
    RunEventKind,
    RunGate,
    RunHandoff,
    RunMetrics,
    RunMode,
    RunStatus,
    RunStep,
    RunStepStatus,
    RunToolCall,
)


def _tool_call(**overrides: object) -> RunToolCall:
    values = {
        "tool": "trend_scan",
        "params": {"capability": "trend_scan"},
        "result": {"status": "ok"},
        "status": "ok",
        "duration_ms": 1,
    }
    values.update(overrides)
    return RunToolCall(**values)


def _step(**overrides: object) -> RunStep:
    values = {
        "index": 1,
        "id": "step-1",
        "stage": "selection",
        "name": "市场与选品",
        "agent_id": "selection",
        "capability": "trend_scan",
        "risk": RiskLevel.L1,
        "status": RunStepStatus.succeeded,
        "summary": "完成选品",
        "artifact": "trend_scan.json",
        "tool_calls": (_tool_call(),),
        "approval_id": None,
        "duration_ms": 1,
        "error": None,
    }
    values.update(overrides)
    return RunStep(**values)


def _agent(**overrides: object) -> RunAgent:
    values = {
        "id": "selection",
        "name": "选品 Agent",
        "role": "趋势",
        "risk": RiskLevel.L1,
        "capabilities": ("trend_scan",),
        "step_ids": ("step-1",),
    }
    values.update(overrides)
    return RunAgent(**values)


def _event(seq: int = 1, **overrides: object) -> RunEvent:
    values = {
        "seq": seq,
        "kind": RunEventKind.agent_started,
        "at": "10:43",
        "step_id": "step-1",
        "agent_id": "selection",
        "gate_id": None,
        "title": "Agent 启动",
        "detail": "选品 Agent · 市场与选品",
    }
    values.update(overrides)
    return RunEvent(**values)


def _gate(**overrides: object) -> RunGate:
    values = {
        "id": "budget",
        "step_id": "step-1",
        "stage": "selection",
        "title": "预算",
        "action": "ads_create",
        "risk": RiskLevel.L3,
        "owner": "财务",
        "impact": "$10,000",
        "recommended": Decision.approve,
        "status": ApprovalStatus.approved,
        "decision": Decision.approve,
        "actor": "财务小财",
        "decided_at": "10:44",
    }
    values.update(overrides)
    return RunGate(**values)


def _artifact(**overrides: object) -> RunArtifact:
    values = {
        "name": "trend_scan.json",
        "kind": ArtifactKind.json,
        "uri": "mock://trend_scan.json",
        "step_id": "step-1",
        "agent_id": "selection",
        "description": "选品 Agent · 市场与选品",
    }
    values.update(overrides)
    return RunArtifact(**values)


def _metrics(**overrides: object) -> RunMetrics:
    values = {
        "step_count": 1,
        "succeeded_steps": 1,
        "failed_steps": 0,
        "agent_count": 1,
        "handoff_count": 0,
        "gate_count": 1,
        "approved_gates": 1,
        "rejected_gates": 0,
        "artifact_count": 1,
        "compensation_count": 0,
        "reconciliation_count": 0,
        "duration_ms": 1,
    }
    values.update(overrides)
    return RunMetrics(**values)


def _run(**overrides: object) -> AgentRun:
    values = {
        "id": "run-test",
        "goal": Goal(id="goal-demo", instruction="测试目标"),
        "plan_id": "plan-demo",
        "status": RunStatus.succeeded,
        "mode": RunMode.demo,
        "started_at": "10:43",
        "finished_at": "10:44",
        "summary": "1 步完成",
        "steps": (_step(),),
        "agents": (_agent(),),
        "events": (_event(),),
        "gates": (_gate(),),
        "handoffs": (),
        "artifacts": (_artifact(),),
        "verification": VerificationResult(passed=True, checks=("trace",), vetoed=()),
        "metrics": _metrics(),
    }
    values.update(overrides)
    return AgentRun(**values)


@pytest.mark.parametrize(
    ("field", "value"),
    [("tool", ""), ("status", ""), ("duration_ms", -1)],
)
def test_tool_call_rejects_invalid_fields(field: str, value: object) -> None:
    with pytest.raises(ValueError, match=field):
        _tool_call(**{field: value})


def test_step_rejects_negative_duration() -> None:
    with pytest.raises(ValueError, match="duration_ms"):
        _step(duration_ms=-1)


def test_step_rejects_blank_id() -> None:
    with pytest.raises(ValueError, match="id"):
        _step(id="   ")


def test_agent_rejects_duplicate_capabilities() -> None:
    with pytest.raises(ValueError, match="capabilities"):
        _agent(capabilities=("trend_scan", "trend_scan"))


def test_event_rejects_missing_association_for_agent_started() -> None:
    with pytest.raises(ValueError, match="step_id"):
        _event(step_id=None)


def test_handoff_event_uses_receiving_agent_and_step() -> None:
    event = _event(
        kind=RunEventKind.handoff,
        step_id="step-2",
        agent_id="content",
        title="Agent 交接",
        detail="选品 → 内容",
    )

    assert event.step_id == "step-2"
    assert event.agent_id == "content"


def test_gate_rejects_inconsistent_decision() -> None:
    with pytest.raises(ValueError, match="decision"):
        _gate(status=ApprovalStatus.approved, decision=Decision.reject)


def test_gate_rejects_pending_with_actor() -> None:
    with pytest.raises(ValueError, match="actor"):
        _gate(status=ApprovalStatus.pending, decision=None, actor="某人", decided_at="10:44")


def test_metrics_reject_impossible_counts() -> None:
    with pytest.raises(ValueError, match="succeeded_steps"):
        _metrics(step_count=1, succeeded_steps=2)


def test_run_rejects_non_contiguous_event_seq() -> None:
    with pytest.raises(ValueError, match="seq"):
        _run(events=(_event(seq=2),))


def test_run_rejects_handoff_between_non_adjacent_steps() -> None:
    steps = (
        _step(),
        _step(
            index=2,
            id="step-2",
            stage="content",
            name="商品与内容",
            agent_id="content",
            capability="content_brief",
            summary="完成内容",
            artifact="content_brief.json",
            tool_calls=(_tool_call(tool="content_brief"),),
        ),
        _step(
            index=3,
            id="step-3",
            stage="listing",
            name="上架与定价",
            agent_id="pricing",
            capability="listing_update",
            summary="完成定价",
            artifact="listing_update.json",
            tool_calls=(_tool_call(tool="listing_update"),),
        ),
    )
    agents = (
        _agent(),
        _agent(
            id="content",
            name="内容 Agent",
            role="内容",
            capabilities=("content_brief",),
            step_ids=("step-2",),
        ),
        _agent(
            id="pricing",
            name="定价 Agent",
            role="定价",
            risk=RiskLevel.L2,
            capabilities=("listing_update",),
            step_ids=("step-3",),
        ),
    )
    events = (
        _event(seq=1),
        _event(seq=2, step_id="step-2", agent_id="content"),
        _event(seq=3, step_id="step-3", agent_id="pricing"),
    )
    artifacts = (
        _artifact(),
        _artifact(
            name="content_brief.json",
            uri="mock://content_brief.json",
            step_id="step-2",
            agent_id="content",
            description="内容 Agent · 商品与内容",
        ),
        _artifact(
            name="listing_update.json",
            uri="mock://listing_update.json",
            step_id="step-3",
            agent_id="pricing",
            description="定价 Agent · 上架与定价",
        ),
    )
    handoff = RunHandoff(
        event_seq=1,
        from_agent_id="selection",
        to_agent_id="pricing",
        from_step_id="step-1",
        to_step_id="step-3",
        artifact="trend_scan.json",
        note="跳步交接",
    )

    with pytest.raises(ValueError, match="adjacent"):
        _run(
            steps=steps,
            agents=agents,
            events=events,
            gates=(),
            artifacts=artifacts,
            handoffs=(handoff,),
            metrics=_metrics(
                step_count=3,
                succeeded_steps=3,
                agent_count=3,
                handoff_count=1,
                gate_count=0,
                approved_gates=0,
                artifact_count=3,
            ),
        )


def test_run_rejects_artifact_with_mismatched_step() -> None:
    with pytest.raises(ValueError, match="artifact"):
        _run(artifacts=(_artifact(step_id="step-9"),))


def test_run_rejects_metrics_that_do_not_match_entities() -> None:
    with pytest.raises(ValueError, match="metrics"):
        _run(metrics=_metrics(agent_count=2))
