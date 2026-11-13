"""首页经营可视化的只读聚合。

本模块只把确定性 Mock 世界整理成图表所需的数据，不接真实 BI、广告平台或
销售系统，也不参与审批和执行。页面必须明确标注 ``mock``，不得把这里的数字
当作真实经营结果。

数据口径：
    - 销售额：近 7 日每日销售额，合计与周目标用于完成率。
    - Agent 使用量：8 个领域 Agent 的演示调用次数、成功率与平均耗时。
    - 返回结果：直接由 :data:`STAGE_RESULTS` 派生，保证与阶段工作台一致。
"""

from __future__ import annotations

from dataclasses import dataclass

from opsconductor.dispatch.application.stages import STAGE_CATALOG, STAGE_RESULTS
from opsconductor.dispatch.domain.enums import StageStatus
from opsconductor.dispatch.domain.models import DispatchState

_SALES_DAYS: tuple[tuple[str, int], ...] = (
    ("11-06", 11800),
    ("11-07", 12600),
    ("11-08", 12100),
    ("11-09", 13900),
    ("11-10", 15200),
    ("11-11", 16400),
    ("11-12", 17600),
)
_TARGET_USD = 100_000

_AGENT_USAGE: dict[str, tuple[int, int, int]] = {
    "selection": (24, 96, 42_000),
    "content": (18, 94, 65_000),
    "pricing": (12, 88, 28_000),
    "ads": (9, 91, 35_000),
    "order": (21, 93, 51_000),
    "fulfillment": (16, 90, 47_000),
    "settlement": (14, 89, 39_000),
    "compliance": (10, 98, 31_000),
}


@dataclass(frozen=True)
class SalesPoint:
    """一日销售额与日目标。"""

    date: str
    amount_usd: int
    target_usd: int


@dataclass(frozen=True)
class SalesAnalytics:
    """近 7 日销售额与周目标。"""

    points: tuple[SalesPoint, ...]
    total_usd: int
    target_usd: int
    daily_target_usd: int


@dataclass(frozen=True)
class AgentUsage:
    """单个 Agent 的演示调用量、成功率与平均耗时。"""

    agent_id: str
    name: str
    runs: int
    success_rate: int
    avg_duration_ms: int


@dataclass(frozen=True)
class ResultDeliveryStage:
    """单个阶段的返回结果数量与状态。"""

    stage_id: str
    name: str
    status: StageStatus
    artifact_count: int
    evidence_count: int


@dataclass(frozen=True)
class ResultDelivery:
    """十段链路的返回结果汇总。"""

    stages: tuple[ResultDeliveryStage, ...]
    total_results: int
    artifact_count: int
    evidence_count: int
    alert_stages: int


@dataclass(frozen=True)
class AnalyticsSnapshot:
    """首页经营可视化所需的全部只读数据。"""

    source: str
    sales: SalesAnalytics
    agent_usage: tuple[AgentUsage, ...]
    results: ResultDelivery


def build_analytics(state: DispatchState) -> AnalyticsSnapshot:
    """从种子状态与阶段结果构建确定性经营分析。

    Args:
        state: 当前调度状态；只读取 Agent 名称，不修改任何实体。

    Returns:
        标注为 ``mock`` 的销售额、Agent 使用量与返回结果聚合。
    """
    points = tuple(
        SalesPoint(date, amount, round(_TARGET_USD / len(_SALES_DAYS)))
        for date, amount in _SALES_DAYS
    )
    sales = SalesAnalytics(
        points=points,
        total_usd=sum(point.amount_usd for point in points),
        target_usd=_TARGET_USD,
        daily_target_usd=round(_TARGET_USD / len(_SALES_DAYS)),
    )

    usage: list[AgentUsage] = []
    for agent_id, card in state.agents.items():
        runs, success_rate, avg_duration_ms = _AGENT_USAGE.get(
            agent_id, (0, 100, 0)
        )
        usage.append(
            AgentUsage(
                agent_id=agent_id,
                name=card.name,
                runs=runs,
                success_rate=success_rate,
                avg_duration_ms=avg_duration_ms,
            )
        )

    names = {stage.id: stage.name for stage in STAGE_CATALOG}
    stages = tuple(
        ResultDeliveryStage(
            stage_id=result.stage_id,
            name=names.get(result.stage_id, result.stage_id),
            status=result.status,
            artifact_count=len(result.artifacts),
            evidence_count=len(result.evidence),
        )
        for result in STAGE_RESULTS.values()
    )
    results = ResultDelivery(
        stages=stages,
        total_results=len(stages),
        artifact_count=sum(stage.artifact_count for stage in stages),
        evidence_count=sum(stage.evidence_count for stage in stages),
        alert_stages=sum(
            1 for stage in stages if stage.status is StageStatus.alert
        ),
    )
    return AnalyticsSnapshot(
        source="mock",
        sales=sales,
        agent_usage=tuple(usage),
        results=results,
    )


__all__ = [
    "AgentUsage",
    "AnalyticsSnapshot",
    "ResultDelivery",
    "ResultDeliveryStage",
    "SalesAnalytics",
    "SalesPoint",
    "build_analytics",
]
