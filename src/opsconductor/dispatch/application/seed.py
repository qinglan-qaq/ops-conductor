"""Demo 种子状态：目标、审批案、十段链路、trace、异常与 Agent 卡片。

所有文案来自 ``design/cross-border-dispatch/index.html`` 的硬编码卡片与
``exceptionData``，确保后端快照与静态页面视觉一致。异常优先级由领域
:class:`PriorityPolicy` 按 L×I 计算；响应 SLA 使用页面原文。
"""

from __future__ import annotations

from collections.abc import Mapping

from opsconductor.dispatch.application.agents import (
    APPROVAL_BUDGET,
    APPROVAL_PRICE,
    APPROVAL_REFUND,
)
from opsconductor.dispatch.application.plans import build_plan
from opsconductor.dispatch.domain.enums import AgentStatus, StageStatus
from opsconductor.dispatch.domain.models import (
    AgentCard,
    ApprovalCase,
    ApprovalDraft,
    ChainStage,
    DispatchState,
    ExceptionCase,
    Goal,
    Playbook,
    PlaybookPhase,
    TraceEvent,
)
from opsconductor.dispatch.domain.policies import PriorityPolicy

SEED_GOAL = Goal(
    id="goal-demo",
    instruction="本周做到 $100k GMV，广告预算 $10k；优先处理断货与超时订单。",
)

_SEED_AGENT_STATES: dict[str, tuple[AgentStatus, str]] = {
    "selection": (AgentStatus.done, "扫描 8–12 周趋势，输出 5 个 Hero SKU。"),
    "content": (AgentStatus.running, "5 个 SKU × 3 图 + 2 条短视频脚本。"),
    "pricing": (AgentStatus.waiting, "1 条涨价建议待批，运营可驳回。"),
    "ads": (AgentStatus.waiting, "3 个 Campaign，总预算 $10,000。"),
    "order": (AgentStatus.running, "6 单异常，2 单 P0/P1，优先止损。"),
    "fulfillment": (AgentStatus.running, "1 票报关失败，触发拆单补偿。"),
    "settlement": (AgentStatus.running, "3 笔对账差异，生成财务任务。"),
    "compliance": (AgentStatus.done, "1 个 SKU 合规不达标，已剔除。"),
}


def _approval_case(draft: ApprovalDraft) -> ApprovalCase:
    """把审批草稿转换为待批的领域审批案。"""
    return ApprovalCase(
        id=draft.id,
        title=draft.title,
        action=draft.action,
        risk=draft.risk,
        owner=draft.owner,
        impact=draft.impact,
        recommended=draft.recommended,
    )


def build_approvals() -> tuple[ApprovalCase, ...]:
    """返回页面上的三件待批审批案。"""
    return tuple(
        _approval_case(draft) for draft in (APPROVAL_BUDGET, APPROVAL_PRICE, APPROVAL_REFUND)
    )


def build_chain() -> tuple[ChainStage, ...]:
    """返回十段链路的展示状态，与页面节点一一对应。"""
    return (
        ChainStage("selection", "选品", StageStatus.done, "5 SKU"),
        ChainStage("content", "内容", StageStatus.running, "5 SKU"),
        ChainStage("listing", "上架", StageStatus.waiting, "待创建"),
        ChainStage("organic", "自然流量", StageStatus.waiting, "内容日历"),
        ChainStage("paid", "付费广告", StageStatus.waiting, "3 Campaign"),
        ChainStage("order", "订单", StageStatus.alert, "6 单异常"),
        ChainStage("fulfillment", "库存履约", StageStatus.running, "补偿 1"),
        ChainStage("logistics", "物流关务", StageStatus.alert, "1 票扣关"),
        ChainStage("settlement", "收款结算", StageStatus.running, "3 笔差异"),
        ChainStage("aftersales", "售后合规", StageStatus.waiting, "政策 RAG"),
    )


def build_trace() -> list[TraceEvent]:
    """返回页面初始的七条 trace。"""
    return [
        TraceEvent("10:42", "目标接入", "结构化 intent · 店铺 / 市场 / 预算"),
        TraceEvent("10:43", "计划生成", "DAG · 风险 · 预算"),
        TraceEvent("10:45", "审批", "广告预算 L3 待批"),
        TraceEvent("11:02", "执行", "订单 Agent 处理 6 单异常"),
        TraceEvent("11:08", "验证", "Verifier 检查库存非负"),
        TraceEvent("11:12", "归因", "触点 / 动作 / 结果"),
        TraceEvent("11:15", "报告", "指标 / 证据 / trace"),
    ]


def _playbook(
    trigger: str,
    phases: tuple[tuple[str, tuple[str, ...]], ...],
    automation: str,
) -> Playbook:
    """由页面数据结构构造分阶段 playbook。"""
    return Playbook(
        trigger=trigger,
        phases=tuple(PlaybookPhase(label, steps) for label, steps in phases),
        automation=automation,
    )


def _exception(
    exception_id: str,
    title: str,
    likelihood: int,
    impact: int,
    sla: str,
    owner: str,
    count: str,
    playbook: Playbook,
) -> ExceptionCase:
    """按 5×5 策略给异常定级并组装领域实体。"""
    return ExceptionCase(
        id=exception_id,
        title=title,
        priority=PriorityPolicy().classify(likelihood, impact),
        likelihood=likelihood,
        impact=impact,
        sla=sla,
        owner=owner,
        count=count,
        playbook=playbook,
    )


def build_exceptions() -> tuple[ExceptionCase, ...]:
    """返回页面异常簿中的六条异常及完整 playbook。"""
    return (
        _exception(
            "ORD-01",
            "超时未发货",
            5,
            4,
            "15 分钟响应 · 1 小时止损",
            "订单 Agent",
            "2 单",
            _playbook(
                "订单临近平台发货截止，仓库未接单 / 未出库 / 库存不足。",
                (
                    (
                        "0–30 分钟",
                        (
                            "拉出所有临期订单，按剩余时间排序。",
                            "检查仓库接单、库存预占、地址校验、支付状态。",
                            "能发的优先发；不能发的拆单/换仓；地址异常的改址或联系客户。",
                        ),
                    ),
                    (
                        "1–4 小时",
                        (
                            "与仓库确认产能和截单时间；必要时切换备用仓 / 承运商。",
                            "对无法按时发货的订单，主动通知客户并给方案（等待 / 换货 / 退款）。",
                            "在平台后台做延迟发货报备（若规则允许），避免计入违规。",
                        ),
                    ),
                    (
                        "24–72 小时",
                        (
                            "复盘根因：库存、仓库、地址、支付、系统同步。",
                            "对批量问题调整安全库存 / 截单规则 / 仓库分配。",
                            "对受影响客户补偿（优惠券 / 运费 / 小礼品），记录成本。",
                        ),
                    ),
                ),
                "order_list_overdue → 分类 → 拆单/改址建议 → L2 审批 → 执行 → 报告；超时升级人工。",
            ),
        ),
        _exception(
            "INV-01",
            "库存不足 / 超卖",
            4,
            4,
            "30 分钟响应 · 4 小时止损",
            "履约 Agent",
            "1 SKU",
            _playbook(
                "可用库存 < 订单需求，或同一 SKU 被多渠道同时卖出。",
                (
                    (
                        "0–30 分钟",
                        (
                            "冻结该 SKU 的新订单 / 广告，避免继续超卖。",
                            "盘点可用、预占、在途、其他仓库存。",
                            "能调拨的调拨，能拆单的拆单，不能履约的取消并通知客户。",
                        ),
                    ),
                    (
                        "1–4 小时",
                        (
                            "与供应商确认补货交期；必要时空运 / 加急。",
                            "对已超卖订单给出方案：等待 / 换色换码 / 退款 + 补偿。",
                            "检查同步链路：平台、ERP、WMS 是否有延迟。",
                        ),
                    ),
                    (
                        "24–72 小时",
                        (
                            "复盘安全库存、同步频率、预占逻辑、促销叠加。",
                            "调整补货点和缓冲库存；对高风险 SKU 设置限购。",
                        ),
                    ),
                ),
                "inventory_get → 拆单/调拨/取消建议 → L2 审批 → 补偿；Verifier 检查库存非负。",
            ),
        ),
        _exception(
            "ORD-03",
            "地址异常 / 改址",
            4,
            3,
            "30 分钟响应 · 4 小时止损",
            "订单 Agent",
            "1 单",
            _playbook(
                "地址校验失败、客户申请改址、承运商反馈无法投递。",
                (
                    (
                        "0–30 分钟",
                        (
                            "校验地址字段：收件人、电话、省市区、邮编、门牌。",
                            "未发货允许改址；已发货联系承运商拦截 / 改派。",
                            "高风险地址（偏远、转运仓、频繁退件）人工确认。",
                        ),
                    ),
                    (
                        "1–4 小时",
                        (
                            "与客户确认新地址和时效；必要时补运费差价。",
                            "无法改派则退回 / 退款 / 重发。",
                        ),
                    ),
                    (
                        "24–72 小时",
                        (
                            "复盘地址校验规则；对高频错误地区加提示。",
                            "更新地址库 / 黑名单。",
                        ),
                    ),
                ),
                "address.validate → 改址建议 → L2 审批 → 执行 → 审计；已发货转人工。",
            ),
        ),
        _exception(
            "LOG-03",
            "海关扣关 / 查验",
            3,
            4,
            "30 分钟响应 · 4 小时止损",
            "履约 Agent",
            "1 票",
            _playbook(
                "清关状态停滞、承运商要求补资料、海关查验 / 征税。",
                (
                    (
                        "0–30 分钟",
                        (
                            "确认扣关原因：申报价值、HS 编码、品名、认证、禁限售、收件人信息。",
                            "收集资料：发票、装箱单、成分 / 材质、认证、授权书。",
                            "通知客户可能延迟，避免承诺不确定时效。",
                        ),
                    ),
                    (
                        "1–4 小时",
                        (
                            "交给报关行 / 承运商处理；能补资料立即补。",
                            "评估退运 / 销毁 / 转口成本；高货值考虑律师 / 关务顾问。",
                        ),
                    ),
                    (
                        "24–72 小时",
                        (
                            "跟踪清关；对批量问题切换口岸 / 物流商。",
                            "复盘 HS 归类和申报流程。",
                        ),
                    ),
                ),
                "customs_declare → 资料校验 → 补资料 / 换渠道建议 → L2 审批；失败转人工。",
            ),
        ),
        _exception(
            "PAY-02",
            "结算少结 / 多扣",
            4,
            3,
            "30 分钟响应 · 4 小时止损",
            "结算 Agent",
            "3 笔",
            _playbook(
                "结算单与订单 / 退款 / 费用对不上；到账少于预期。",
                (
                    (
                        "0–30 分钟",
                        (
                            "拉结算单、订单、退款、广告费、运费、平台费。",
                            "按订单 / 费用类型拆分差异；标记疑似重复扣费 / 漏结。",
                            "冻结相关 SKU 的促销（如费用异常大）。",
                        ),
                    ),
                    (
                        "1–4 小时",
                        (
                            "向平台 / PSP 提交工单，附差异明细和证据。",
                            "财务做暂估调整，避免现金流误判。",
                        ),
                    ),
                    (
                        "24–72 小时",
                        (
                            "跟踪工单；对系统性差异调整定价 / 费用模型。",
                            "更新对账规则和告警阈值。",
                        ),
                    ),
                ),
                "settlement_fetch → 差异拆分 → 工单 / 暂估 → 财务任务；差异不自动打款。",
            ),
        ),
        _exception(
            "ORD-04",
            "重复订单 / 重复扣款",
            3,
            3,
            "30 分钟响应 · 4 小时止损",
            "订单 Agent",
            "1 单",
            _playbook(
                "同一客户、同一 SKU 出现多单，或支付渠道重复扣款。",
                (
                    (
                        "0–30 分钟",
                        (
                            "按客户 / SKU / 时间窗口聚合重复单。",
                            "检查幂等键、支付流水、订单状态。",
                            "能合并的合并，需取消的取消，已扣款进入退款流程。",
                        ),
                    ),
                    (
                        "1–4 小时",
                        (
                            "通知客户并确认处理方案。",
                            "对重复扣款做冲正 / 退款，保留审计记录。",
                        ),
                    ),
                    (
                        "24–72 小时",
                        (
                            "复盘去重规则、幂等键覆盖、风控阈值。",
                            "补充 Golden Task，防止回归。",
                        ),
                    ),
                ),
                "order_dedupe → 合并 / 取消 / 退款建议 → L2 审批 → 执行 → 审计。",
            ),
        ),
    )


def build_seed_state(agent_cards: Mapping[str, AgentCard]) -> DispatchState:
    """组装调度台初始状态。

    Args:
        agent_cards: Agent 工厂注册卡片的映射；按播种状态写入状态与任务。

    Returns:
        目标、计划、三件待批、六条异常、八个卡片、十段链路与七条 trace。
    """
    cards = dict(agent_cards)
    for agent_id, (status, task) in _SEED_AGENT_STATES.items():
        card = cards.get(agent_id)
        if card is not None:
            cards[agent_id] = card.with_status(status, task)
    return DispatchState(
        goal=SEED_GOAL,
        plan=build_plan(SEED_GOAL),
        approvals={approval.id: approval for approval in build_approvals()},
        exceptions=build_exceptions(),
        agents=cards,
        chain=build_chain(),
        trace=build_trace(),
    )


__all__ = [
    "SEED_GOAL",
    "build_approvals",
    "build_chain",
    "build_exceptions",
    "build_seed_state",
    "build_trace",
]
