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

from opsconductor.dispatch.application.integrations import AdapterRegistry
from opsconductor.dispatch.application.orchestrator import DemoRunReport
from opsconductor.dispatch.application.service import (
    ApprovalProgress,
    DispatchSnapshot,
    KpiSnapshot,
    StageDetail,
    StageNavigation,
    StatusSummary,
)
from opsconductor.dispatch.domain.enums import AgentStatus, ApprovalStatus
from opsconductor.dispatch.domain.models import (
    AgentCard,
    ApprovalCase,
    Artifact,
    ChainStage,
    ExceptionCase,
    Goal,
    IntegrationHealth,
    Metric,
    Plan,
    PlanStep,
    Playbook,
    StageDefinition,
    StageResult,
    StageStep,
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
        "stage_id": approval.stage_id,
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
        "stage_id": exception.stage_id,
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


def artifact_payload(artifact: Artifact) -> dict[str, Any]:
    """序列化阶段产物引用。"""
    return {
        "name": artifact.name,
        "kind": artifact.kind.value,
        "uri": artifact.uri,
        "description": artifact.description,
    }


def metric_payload(metric: Metric) -> dict[str, Any]:
    """序列化单个指标；小数指标保持字符串。"""
    return {"key": metric.key, "value": metric.value}


def stage_result_payload(result: StageResult) -> dict[str, Any]:
    """序列化子 Agent 的阶段产出；``metrics`` 转为 JSON 对象。"""
    return {
        "stage_id": result.stage_id,
        "agent_id": result.agent_id,
        "status": result.status.value,
        "summary": result.summary,
        "artifacts": [artifact_payload(item) for item in result.artifacts],
        "metrics": {metric.key: metric.value for metric in result.metrics},
        "evidence": list(result.evidence),
        "source": {
            "platform": result.provenance.platform,
            "shop_id": result.provenance.shop_id,
            "adapter": result.provenance.adapter,
            "synced_at": result.provenance.synced_at,
            "schema_version": result.provenance.schema_version,
        },
        "at": result.at,
    }


def stage_step_payload(step: StageStep) -> dict[str, Any]:
    """序列化阶段子流程。"""
    return {"id": step.id, "name": step.name}


def stage_definition_payload(definition: StageDefinition) -> dict[str, Any]:
    """序列化阶段静态定义。"""
    return {
        "id": definition.id,
        "order_label": definition.order_label,
        "name": definition.name,
        "owner": definition.owner,
        "risk": definition.risk.value,
        "actions": list(definition.actions),
        "failures": list(definition.failures),
        "ai": list(definition.ai),
        "metrics": list(definition.metrics),
        "steps": [stage_step_payload(step) for step in definition.steps],
    }


def stage_navigation_payload(navigation: StageNavigation) -> dict[str, Any]:
    """序列化侧边栏场景目录。"""
    return {
        "id": navigation.id,
        "order_label": navigation.order_label,
        "name": navigation.name,
        "status": navigation.status.value,
        "meta": navigation.meta,
        "approval_count": navigation.approval_count,
        "exception_count": navigation.exception_count,
        "steps": [stage_step_payload(step) for step in navigation.steps],
    }


def approval_progress_payload(progress: ApprovalProgress) -> dict[str, Any]:
    """序列化首页审批进度。"""
    return {
        "total": progress.total,
        "pending": progress.pending,
        "approved": progress.approved,
        "rejected": progress.rejected,
        "decided_percent": progress.decided_percent,
        "l2_total": progress.l2_total,
        "l3_total": progress.l3_total,
    }


def status_summary_payload(summary: StatusSummary) -> dict[str, Any]:
    """序列化链路、Agent、审批与异常分布。"""
    return {
        "chain": dict(summary.chain),
        "agents": dict(summary.agents),
        "approvals": approval_progress_payload(summary.approvals),
        "exceptions": dict(summary.exceptions),
    }


def stage_detail_payload(detail: StageDetail) -> dict[str, Any]:
    """序列化阶段工作台定义、结果与上下文。"""
    definition = stage_definition_payload(detail.definition)
    return {
        **definition,
        "status": detail.status.value,
        "meta": detail.meta,
        "result": (
            stage_result_payload(detail.result)
            if detail.result is not None
            else None
        ),
        "approvals": [approval_payload(item) for item in detail.approvals],
        "exceptions": [exception_payload(item) for item in detail.exceptions],
    }


def integration_health_payload(
    platform: str,
    shop_id: str,
    name: str,
    health: IntegrationHealth,
) -> dict[str, Any]:
    """序列化单个平台/店铺的集成健康。"""
    return {
        "platform": platform,
        "shop_id": shop_id,
        "name": name,
        "status": health.status.value,
        "mode": health.mode.value,
        "capabilities": [capability.value for capability in health.capabilities],
        "last_sync_at": health.last_sync_at,
        "freshness": health.freshness.value,
        "warnings": list(health.warnings),
    }


def integrations_payload(registry: AdapterRegistry) -> dict[str, Any]:
    """序列化 Adapter Registry 的只读集成健康视图。"""
    platforms = []
    default_platform = ""
    for index, adapter in enumerate(registry.all()):
        health = adapter.health()
        manifest = adapter.manifest()
        if index == 0:
            default_platform = f"{health.platform}-{health.shop_id}"
        platforms.append(
            integration_health_payload(
                health.platform,
                health.shop_id,
                manifest.display_name,
                health,
            )
        )
    return {
        "default_platform": default_platform,
        "platforms": platforms,
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
        "navigation": [
            stage_navigation_payload(navigation) for navigation in snapshot.navigation
        ],
        "status_summary": status_summary_payload(snapshot.status_summary),
        "approval_progress": approval_progress_payload(snapshot.approval_progress),
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
    "approval_progress_payload",
    "artifact_payload",
    "chain_payload",
    "exception_payload",
    "goal_payload",
    "integration_health_payload",
    "integrations_payload",
    "kpi_payload",
    "metric_payload",
    "plan_payload",
    "playbook_payload",
    "report_payload",
    "snapshot_payload",
    "stage_definition_payload",
    "stage_detail_payload",
    "stage_navigation_payload",
    "stage_result_payload",
    "stage_step_payload",
    "status_summary_payload",
    "step_payload",
    "trace_payload",
    "verification_payload",
]
