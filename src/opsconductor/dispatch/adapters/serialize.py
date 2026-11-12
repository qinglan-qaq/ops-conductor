"""把调度领域对象投影为前端约定的纯 JSON 结构。

本模块只做只读投影：所有枚举通过 ``.value`` 输出，元组转换为列表，金额保持
整数美元，时间保持 ``HH:MM`` 展示标签。返回值只含 ``dict`` / ``list`` / ``str`` /
``int`` / ``float`` / ``bool`` / ``None``，可直接交给 FastAPI 序列化。

Invariants:

- ``snapshot`` 契约与 ``design/cross-border-dispatch/index.html`` 的渲染字段一一
  对应；字段改名属于破坏性变更。
- Agent 的 ``status_label`` 默认由领域状态映射；``order`` / ``fulfillment`` /
  ``settlement`` 三个 Agent 为贴合页面文案做展示覆盖。
- 审批 ``stamp`` 只在已裁决时出现：``approved`` → ``准``，``rejected`` → ``驳``，
  待批为 ``None``。
"""

from __future__ import annotations

from typing import Any

from opsconductor.dispatch.application.orchestrator import DemoRunReport
from opsconductor.dispatch.application.service import DispatchSnapshot, KpiSnapshot
from opsconductor.dispatch.domain.enums import AgentStatus, ApprovalStatus
from opsconductor.dispatch.domain.models import (
    AgentCard,
    ApprovalCase,
    ChainStage,
    ExceptionCase,
    Goal,
    Plan,
    PlanStep,
    Playbook,
    TraceEvent,
    VerificationResult,
)

AGENT_STATUS_LABELS: dict[AgentStatus, str] = {
    AgentStatus.done: "已完成",
    AgentStatus.running: "进行中",
    AgentStatus.waiting: "待批",
    AgentStatus.error: "异常",
    AgentStatus.idle: "空闲",
}

_AGENT_LABEL_OVERRIDES: dict[str, str] = {
    "order": "处理中",
    "fulfillment": "补偿中",
    "settlement": "对账中",
}

_APPROVAL_STAMPS: dict[ApprovalStatus, str] = {
    ApprovalStatus.approved: "准",
    ApprovalStatus.rejected: "驳",
}


def goal_payload(goal: Goal) -> dict[str, Any]:
    """序列化目标及其结构化约束。"""
    return {
        "id": goal.id,
        "instruction": goal.instruction,
        "store": goal.store,
        "market": goal.market,
        "target_gmv": goal.target_gmv,
        "budget": goal.budget,
        "roas_target": goal.roas_target,
    }


def kpi_payload(kpis: KpiSnapshot) -> dict[str, Any]:
    """序列化调度台四个关键指标。"""
    return {
        "gmv_target": kpis.gmv_target,
        "exceptions": kpis.exceptions,
        "approvals_pending": kpis.approvals_pending,
        "compensations": kpis.compensations,
    }


def step_payload(step: PlanStep) -> dict[str, Any]:
    """序列化计划节点；``artifact`` 未产出时为 ``None``。"""
    return {
        "id": step.id,
        "stage": step.stage,
        "name": step.name,
        "capability": step.capability,
        "risk": step.risk.value,
        "status": step.status.value,
        "artifact": step.artifact,
    }


def plan_payload(plan: Plan) -> dict[str, Any]:
    """序列化计划头与十段节点。"""
    return {
        "id": plan.id,
        "goal_id": plan.goal_id,
        "approval_ids": list(plan.approval_ids),
        "risk": plan.risk.value,
        "created_at": plan.created_at,
        "steps": [step_payload(step) for step in plan.steps],
    }


def chain_payload(stage: ChainStage) -> dict[str, Any]:
    """序列化十段价值链节点。"""
    return {
        "id": stage.id,
        "name": stage.name,
        "status": stage.status.value,
        "meta": stage.meta,
    }


def agent_status_label(card: AgentCard) -> str:
    """返回 Agent 的展示标签，优先使用按 ID 的页面覆盖。"""
    override = _AGENT_LABEL_OVERRIDES.get(card.id)
    if override is not None:
        return override
    return AGENT_STATUS_LABELS[card.status]


def agent_payload(card: AgentCard) -> dict[str, Any]:
    """序列化 Agent 卡片；能力元组转换为列表。"""
    return {
        "id": card.id,
        "name": card.name,
        "role": card.role,
        "capabilities": list(card.capabilities),
        "risk": card.risk.value,
        "status": card.status.value,
        "status_label": agent_status_label(card),
        "current_task": card.current_task,
    }


def approval_payload(approval: ApprovalCase) -> dict[str, Any]:
    """序列化审批案及裁决印章。

    ``stamp`` 为 ``准`` / ``驳``，待批时为 ``None``；``recommended`` 是剧本建议，
    不随实际裁决变化。
    """
    return {
        "id": approval.id,
        "title": approval.title,
        "action": approval.action,
        "risk": approval.risk.value,
        "owner": approval.owner,
        "impact": approval.impact,
        "recommended": (
            approval.recommended.value if approval.recommended is not None else None
        ),
        "status": approval.status.value,
        "stamp": _APPROVAL_STAMPS.get(approval.status),
        "actor": approval.actor,
        "decided_at": approval.decided_at,
    }


def playbook_payload(playbook: Playbook) -> dict[str, Any]:
    """序列化异常处置手册的分阶段步骤。"""
    return {
        "trigger": playbook.trigger,
        "phases": [
            {"label": phase.label, "steps": list(phase.steps)}
            for phase in playbook.phases
        ],
        "automation": playbook.automation,
    }


def exception_payload(exception: ExceptionCase) -> dict[str, Any]:
    """序列化异常用例，含 5×5 坐标与完整 playbook。"""
    return {
        "id": exception.id,
        "title": exception.title,
        "priority": exception.priority.value,
        "li": exception.li,
        "sla": exception.sla,
        "owner": exception.owner,
        "count": exception.count,
        "playbook": playbook_payload(exception.playbook),
    }


def trace_payload(event: TraceEvent) -> dict[str, Any]:
    """序列化一条 trace 事件。"""
    return {"at": event.at, "title": event.title, "detail": event.detail}


def verification_payload(result: VerificationResult) -> dict[str, Any]:
    """序列化独立 Verifier 的检查结论。"""
    return {
        "passed": result.passed,
        "checks": list(result.checks),
        "vetoed": list(result.vetoed),
    }


def snapshot_payload(snapshot: DispatchSnapshot) -> dict[str, Any]:
    """序列化前端一次性渲染所需的完整快照。"""
    return {
        "goal": goal_payload(snapshot.goal),
        "kpis": kpi_payload(snapshot.kpis),
        "flow_note": snapshot.flow_note,
        "plan": plan_payload(snapshot.plan),
        "chain": [chain_payload(stage) for stage in snapshot.chain],
        "agents": [agent_payload(card) for card in snapshot.agents.values()],
        "approvals": {
            approval_id: approval_payload(approval)
            for approval_id, approval in snapshot.approvals.items()
        },
        "exceptions": [exception_payload(case) for case in snapshot.exceptions],
        "trace": [trace_payload(event) for event in snapshot.trace],
    }


def report_payload(report: DemoRunReport) -> dict[str, Any]:
    """序列化一次 Demo 编排报告，供前端回放步骤与事件。"""
    return {
        "summary": report.summary,
        "verification": verification_payload(report.verification),
        "steps": [step_payload(step) for step in report.steps],
        "events": [trace_payload(event) for event in report.events],
        "approvals": [approval_payload(approval) for approval in report.approvals],
    }


__all__ = [
    "AGENT_STATUS_LABELS",
    "agent_payload",
    "agent_status_label",
    "approval_payload",
    "chain_payload",
    "exception_payload",
    "goal_payload",
    "kpi_payload",
    "plan_payload",
    "playbook_payload",
    "report_payload",
    "snapshot_payload",
    "step_payload",
    "trace_payload",
    "verification_payload",
]
