"""固定十段链路的计划模板与 :func:`build_plan` 工厂。

Demo 计划不依赖外部规划模型：模板按「选品 → 内容 → 上架 → 自然流量 →
付费广告 → 订单 → 履约 → 物流关务 → 结算 → 售后合规」排列，风险等级由
:class:`~opsconductor.dispatch.domain.policies.RiskPolicy` 按能力名判定。

模板中的状态是调度台的播种展示状态（``succeeded``/``running``/``pending``）；
编排器执行时会据此重建一份从 ``pending`` 开始的可变计划，避免计划快照与执行
记录互相污染。模板末列在计划未执行前作为展示用产物摘要写入 ``artifact``，
执行完成后由真实工具产物覆盖。
"""

from __future__ import annotations

from typing import NamedTuple

from opsconductor.dispatch.domain.enums import StepStatus
from opsconductor.dispatch.domain.models import Goal, Plan, PlanStep
from opsconductor.dispatch.domain.policies import RiskPolicy

APPROVAL_IDS = ["budget", "price", "refund"]


class PlanStepTemplate(NamedTuple):
    """计划模板的一行；``meta`` 仅用于播种展示。"""

    stage: str
    name: str
    capability: str
    status: StepStatus
    meta: str


PLAN_TEMPLATE: tuple[PlanStepTemplate, ...] = (
    PlanStepTemplate("selection", "市场与选品", "trend_scan", StepStatus.succeeded, "5 SKU"),
    PlanStepTemplate("content", "商品与内容", "content_brief", StepStatus.running, "5 SKU"),
    PlanStepTemplate("listing", "上架与定价", "listing_update", StepStatus.pending, "待创建"),
    PlanStepTemplate("organic", "自然流量", "content_plan", StepStatus.pending, "内容日历"),
    PlanStepTemplate("paid", "付费广告", "ads_create", StepStatus.pending, "3 Campaign"),
    PlanStepTemplate("order", "订单", "order_triage", StepStatus.running, "6 单异常"),
    PlanStepTemplate(
        "fulfillment", "库存与履约", "shipment_create", StepStatus.running, "补偿 1"
    ),
    PlanStepTemplate("logistics", "物流与关务", "customs_declare", StepStatus.running, "1 票扣关"),
    PlanStepTemplate(
        "settlement", "收款与结算", "settlement_fetch", StepStatus.running, "3 笔差异"
    ),
    PlanStepTemplate(
        "aftersales", "售后与合规", "compliance_check", StepStatus.pending, "政策 RAG"
    ),
)


def build_plan(goal: Goal) -> Plan:
    """根据目标生成固定的十段计划。

    Args:
        goal: 已结构化的运营目标；仅使用其 ``id``。

    Returns:
        含 10 个 :class:`PlanStep`、按剧本顺序排列的审批 ID 与生成时刻的计划。
    """
    risk_policy = RiskPolicy()
    steps = [
        PlanStep(
            id=f"step-{index}",
            stage=template.stage,
            name=template.name,
            capability=template.capability,
            risk=risk_policy.classify(template.capability),
            status=template.status,
            artifact=template.meta if template.status is not StepStatus.pending else None,
        )
        for index, template in enumerate(PLAN_TEMPLATE, start=1)
    ]
    return Plan(
        id="plan-demo",
        goal_id=goal.id,
        steps=steps,
        approval_ids=list(APPROVAL_IDS),
        created_at="10:43",
    )


__all__ = ["APPROVAL_IDS", "PLAN_TEMPLATE", "PlanStepTemplate", "build_plan"]
