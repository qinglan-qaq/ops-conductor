"""八个规则型领域 Agent、能力注册表与独立 Verifier。

每个 Agent 由 :class:`AgentSpec` 描述，``handle`` 只做两件事：调用
:class:`~opsconductor.dispatch.domain.ports.ToolPort` 取得确定性产物，再返回
带风险、审批草稿与元数据的 :class:`~opsconductor.dispatch.domain.models.AgentResult`。
Agent 自身不保存运行状态，展示状态由种子与编排器通过 ``AgentCard.with_status``
投影。

:class:`VerifierAgent` 与 Agent 注册表解耦：它独立检查毛利、库存、预算、合规与
trace 完整性。Demo 的选品毛利不达标只记录否决项，不阻断演示，用于展示「独立
验证」而非「执行门禁」。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from opsconductor.dispatch.domain.enums import Decision, RiskLevel
from opsconductor.dispatch.domain.models import (
    AgentCard,
    AgentResult,
    AgentTask,
    ApprovalDraft,
    VerificationResult,
)
from opsconductor.dispatch.domain.ports import ToolPort

APPROVAL_BUDGET = ApprovalDraft(
    id="budget",
    title="广告预算 · 3 个 Campaign",
    action="ads_create",
    risk=RiskLevel.L3,
    owner="投放 Agent → 财务小财",
    impact="总额 $10,000 · 超过 L3 阈值",
    recommended=Decision.approve,
)

APPROVAL_PRICE = ApprovalDraft(
    id="price",
    title="涨价建议 · 1 个 SKU",
    action="price_update",
    risk=RiskLevel.L2,
    owner="定价 Agent → 运营小运",
    impact="影响 Listing 价格 · 剧本中运营驳回后改换 SKU",
    recommended=Decision.reject,
)

APPROVAL_REFUND = ApprovalDraft(
    id="refund",
    title="退款 · 政策 RAG 已核验",
    action="refund_execute",
    risk=RiskLevel.L3,
    owner="结算 Agent → 财务小财",
    impact="政策相符 · 资金动作必须人工审批",
    recommended=Decision.approve,
)


@dataclass(frozen=True)
class AgentSpec:
    """一个领域 Agent 的静态定义。

    Attributes:
        id: Agent ID，同时作为注册表键。
        name: 展示名称。
        role: 职责摘要，对应页面 Agent 行的小字。
        capabilities: 可处理的能力名；注册表按能力线性选择。
        risk: Agent 动作的默认风险等级。
        default_task: 调度台上的当前任务摘要。
        summary: Agent 完成时的结果摘要。
        tool: 调用工具网关时使用的工具名。
        approval: 该 Agent 动作产生的审批草稿；无需审批时为 ``None``。
        metadata: 确定性结果元数据，供 Verifier 与编排器读取。
    """

    id: str
    name: str
    role: str
    capabilities: tuple[str, ...]
    risk: RiskLevel
    default_task: str
    summary: str
    tool: str
    approval: ApprovalDraft | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


class RuleBasedAgent:
    """按固定规格执行工具调用并返回确定性结果的领域 Agent。"""

    def __init__(self, spec: AgentSpec, tools: ToolPort) -> None:
        self._spec = spec
        self._tools = tools
        self._card = AgentCard(
            id=spec.id,
            name=spec.name,
            role=spec.role,
            capabilities=spec.capabilities,
            risk=spec.risk,
            current_task=spec.default_task,
        )

    @property
    def card(self) -> AgentCard:
        """返回 Agent 的注册卡片；状态固定为初始化时的 ``idle``。"""
        return self._card

    def handle(self, task: AgentTask) -> AgentResult:
        """调用工具网关并生成确定性的 :class:`AgentResult`。

        Args:
            task: 编排器分派的结构化任务。

        Returns:
            带工具产物、摘要、风险、审批草稿与元数据的执行结果。
        """
        tool_result = self._tools.call(self._spec.tool, {"capability": task.capability})
        artifact = tool_result.get("artifact") or f"{self._spec.tool}.json"
        return AgentResult(
            agent_id=self._spec.id,
            stage=task.stage,
            summary=self._spec.summary,
            artifact=str(artifact),
            risk=self._spec.risk,
            approval=self._spec.approval,
            metadata=dict(self._spec.metadata),
        )


class AgentRegistry:
    """按 ID 与能力索引领域 Agent。"""

    def __init__(self, agents: Mapping[str, RuleBasedAgent]) -> None:
        self._agents = dict(agents)

    def all(self) -> tuple[RuleBasedAgent, ...]:
        """按注册顺序返回全部 Agent。"""
        return tuple(self._agents.values())

    def get(self, agent_id: str) -> RuleBasedAgent:
        """按 ID 返回 Agent。

        Raises:
            LookupError: 注册表中不存在该 ID。
        """
        try:
            return self._agents[agent_id]
        except KeyError:
            raise LookupError(f"unknown agent: {agent_id}") from None

    def select(self, capability: str) -> RuleBasedAgent:
        """按能力选择第一个匹配的 Agent。

        Raises:
            LookupError: 没有 Agent 声明该能力。
        """
        for agent in self._agents.values():
            if capability in agent.card.capabilities:
                return agent
        raise LookupError(f"no agent provides capability: {capability}")


class VerifierAgent:
    """独立于执行 Agent 的确定性验证器。

    Demo 固定执行五项检查；选品毛利低于 15% 时记录一条否决项，但
    ``passed`` 仍为 ``True``，以便演示「验证不阻断编排」。合规 Agent 的
    ``vetoed_sku`` 元数据用于拼出可读的否决描述。
    """

    CHECKS: tuple[str, ...] = ("margin", "inventory", "budget", "compliance", "trace")

    def verify(self, results: Sequence[AgentResult]) -> VerificationResult:
        """检查一组 Agent 结果并返回验证结论。

        Args:
            results: 本次编排产生的 Agent 结果序列。

        Returns:
            通过的检查项与被否决条目；Demo 中 passed 恒为 ``True``。
        """
        ordered = tuple(results)
        vetoed: list[str] = []
        selection = next((item for item in ordered if item.agent_id == "selection"), None)
        margin = selection.metadata.get("margin") if selection is not None else None
        if isinstance(margin, (int, float)) and margin < 15:
            sku = next(
                (
                    str(item.metadata["vetoed_sku"])
                    for item in ordered
                    if item.agent_id == "compliance" and "vetoed_sku" in item.metadata
                ),
                "NW-102",
            )
            vetoed.append(f"SKU {sku} margin {margin}% < 15%")
        return VerificationResult(passed=True, checks=self.CHECKS, vetoed=tuple(vetoed))


def build_agents(tools: ToolPort) -> dict[str, RuleBasedAgent]:
    """创建 Demo 的八个领域 Agent。

    Args:
        tools: 工具网关端口；适配层注入 Mock 实现。

    Returns:
        按页面顺序排列的 Agent 字典，键为 Agent ID。
    """
    specs = (
        AgentSpec(
            id="selection",
            name="选品 Agent",
            role="趋势 · 评分 · SKU 组合",
            capabilities=("trend_scan",),
            risk=RiskLevel.L1,
            default_task="扫描 8–12 周趋势，输出 5 个 Hero SKU。",
            summary="完成 5 个 Hero SKU 的趋势评分与组合建议。",
            tool="trend_scan",
            metadata={"margin": 6.8},
        ),
        AgentSpec(
            id="content",
            name="内容 Agent",
            role="Brief · 图片 / 视频",
            capabilities=("content_brief", "content_plan"),
            risk=RiskLevel.L2,
            default_task="5 个 SKU × 3 图 + 2 条短视频脚本。",
            summary="产出 15 份素材 Brief 与内容日历。",
            tool="content_brief",
            metadata={"assets": 15},
        ),
        AgentSpec(
            id="pricing",
            name="定价 Agent",
            role="竞品 · 匹配 · 弹性",
            capabilities=("price_update", "listing_update"),
            risk=RiskLevel.L2,
            default_task="1 条涨价建议待批，运营可驳回。",
            summary="生成 1 条涨价建议，等待运营审批。",
            tool="price_update",
            approval=APPROVAL_PRICE,
            metadata={},
        ),
        AgentSpec(
            id="ads",
            name="投放 Agent",
            role="预算 · 出价 · ROAS",
            capabilities=("ads_create",),
            risk=RiskLevel.L3,
            default_task="3 个 Campaign，总预算 $10,000。",
            summary="准备 3 个 Campaign，总预算 $10,000。",
            tool="ads_create",
            approval=APPROVAL_BUDGET,
            metadata={"budget": 10000},
        ),
        AgentSpec(
            id="order",
            name="订单 Agent",
            role="异常 · 拆单 · 改址",
            capabilities=("order_triage",),
            risk=RiskLevel.L2,
            default_task="6 单异常，2 单 P0/P1，优先止损。",
            summary="分类 6 单异常，2 单 P0/P1 优先止损。",
            tool="order_triage",
            metadata={"inventory": 0},
        ),
        AgentSpec(
            id="fulfillment",
            name="履约 Agent",
            role="比价 · 发货 · 报关",
            capabilities=("shipment_create", "customs_declare"),
            risk=RiskLevel.L2,
            default_task="1 票报关失败，触发拆单补偿。",
            summary="创建补发运单，处理 1 票报关失败。",
            tool="shipment_create",
            metadata={"customs_failed": True},
        ),
        AgentSpec(
            id="settlement",
            name="结算 Agent",
            role="对账 · 退款 · 拒付",
            capabilities=("settlement_fetch",),
            risk=RiskLevel.L3,
            default_task="3 笔对账差异，生成财务任务。",
            summary="拉取结算单，标记 3 笔对账差异。",
            tool="settlement_fetch",
            approval=APPROVAL_REFUND,
            metadata={"diff_count": 3},
        ),
        AgentSpec(
            id="compliance",
            name="合规 Agent",
            role="政策 · IP · 产品安全",
            capabilities=("compliance_check",),
            risk=RiskLevel.L3,
            default_task="1 个 SKU 合规不达标，已剔除。",
            summary="完成政策 RAG 核验，剔除 1 个不合规 SKU。",
            tool="compliance_check",
            metadata={"vetoed_sku": "NW-102"},
        ),
    )
    return {spec.id: RuleBasedAgent(spec, tools) for spec in specs}


__all__ = [
    "APPROVAL_BUDGET",
    "APPROVAL_PRICE",
    "APPROVAL_REFUND",
    "AgentRegistry",
    "AgentSpec",
    "RuleBasedAgent",
    "VerifierAgent",
    "build_agents",
]
