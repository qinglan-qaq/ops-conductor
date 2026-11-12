"""十段运营链路的阶段目录与确定性阶段结果。

``STAGE_CATALOG`` 是侧栏、阶段详情与测试共享的静态定义；``STAGE_RESULTS``
是 Demo 世界中各子 Agent 的产出。两者顺序必须与电商运营顺序一致：
选品 → 内容 → 上架定价 → 自然流量 → 付费广告 → 订单 → 库存履约 →
物流关务 → 收款结算 → 售后合规。

阶段结果中的摘要、产物名、指标与证据来自
``docs/specs/2026-11-12-dispatch-console-enhancement-design.md`` §6.3；
金额与数量不得在实现时另行编造。控制塔只提供导航聚合，不进入阶段目录。
"""

from __future__ import annotations

from opsconductor.dispatch.domain.enums import (
    ArtifactKind,
    RiskLevel,
    StageStatus,
)
from opsconductor.dispatch.domain.models import (
    Artifact,
    DataProvenance,
    Metric,
    StageDefinition,
    StageResult,
    StageStep,
)

_PLATFORM = "mock"
_SHOP_ID = "nestwell-us"
_ADAPTER = "MockPlatformAdapter"
_SCHEMA_VERSION = "1.0"


def _provenance(synced_at: str) -> DataProvenance:
    """构造 Demo 固定来源；后续真实 Adapter 必须填入真实平台与店铺。"""
    return DataProvenance(
        platform=_PLATFORM,
        shop_id=_SHOP_ID,
        adapter=_ADAPTER,
        synced_at=synced_at,
        schema_version=_SCHEMA_VERSION,
    )


def _steps(*items: tuple[str, str]) -> tuple[StageStep, ...]:
    """把 ``(id, name)`` 序列转换为不可变步骤元组。"""
    return tuple(StageStep(step_id, name) for step_id, name in items)


STAGE_CATALOG: tuple[StageDefinition, ...] = (
    StageDefinition(
        id="selection",
        order_label="壹",
        name="选品与市场",
        owner="选品运营",
        risk=RiskLevel.L1,
        actions=("趋势扫描", "竞品分析", "评分卡", "合规 IP 校验", "SKU 组合"),
        failures=("趋势误判", "同质化", "侵权/合规", "毛利不足"),
        ai=("趋势聚类", "竞品抓取", "评分卡", "组合优化"),
        metrics=("命中率", "毛利率", "动销率"),
        steps=_steps(
            ("trend", "趋势扫描"),
            ("competitor", "竞品分析"),
            ("scorecard", "评分卡"),
            ("ip", "合规 IP"),
            ("mix", "SKU 组合"),
        ),
    ),
    StageDefinition(
        id="content",
        order_label="贰",
        name="商品与内容",
        owner="内容运营",
        risk=RiskLevel.L2,
        actions=("Brief", "AI 制图视频", "品牌合规", "Listing 文案", "效果反馈"),
        failures=("品牌不一致", "素材侵权", "平台拒审", "转化偏低"),
        ai=("AIGC 素材", "多语言文案", "合规词库", "素材评分"),
        metrics=("素材产出", "审核通过率", "CTR"),
        steps=_steps(
            ("brief", "Brief"),
            ("assets", "AI 制图视频"),
            ("brand", "品牌合规"),
            ("copy", "Listing 文案"),
            ("feedback", "效果反馈"),
        ),
    ),
    StageDefinition(
        id="listing",
        order_label="叁",
        name="上架与定价",
        owner="运营",
        risk=RiskLevel.L2,
        actions=("类目属性", "标题关键词", "价格带", "库存同步", "价格审批"),
        failures=("类目错放", "关键词违规", "价格倒挂", "库存不同步"),
        ai=("类目映射", "关键词生成", "竞品价格", "价格弹性"),
        metrics=("上架成功率", "曝光", "转化", "毛利"),
        steps=_steps(
            ("category", "类目属性"),
            ("keywords", "标题关键词"),
            ("price", "价格带"),
            ("inventory", "库存同步"),
            ("approval", "价格审批"),
        ),
    ),
    StageDefinition(
        id="organic",
        order_label="肆",
        name="自然流量",
        owner="内容增长",
        risk=RiskLevel.L2,
        actions=("内容日历", "达人联盟", "寄样", "直播排期", "效果归因"),
        failures=("内容延期", "达人违约", "样品丢失", "归因缺失"),
        ai=("选题生成", "达人匹配", "脚本草稿", "归因分析"),
        metrics=("自然曝光", "互动", "CPM", "归因覆盖率"),
        steps=_steps(
            ("calendar", "内容日历"),
            ("creators", "达人联盟"),
            ("samples", "寄样"),
            ("live", "直播排期"),
            ("attribution", "效果归因"),
        ),
    ),
    StageDefinition(
        id="paid",
        order_label="伍",
        name="付费广告",
        owner="投放",
        risk=RiskLevel.L3,
        actions=("计划", "预算", "出价", "素材轮换", "ROAS"),
        failures=("超投", "ROAS 下滑", "审核拒登", "归因错误"),
        ai=("预算分配", "出价建议", "素材轮换", "异常检测"),
        metrics=("ROAS", "ACOS", "花费", "转化"),
        steps=_steps(
            ("plan", "计划"),
            ("budget", "预算"),
            ("bid", "出价"),
            ("creative", "素材轮换"),
            ("roas", "ROAS"),
        ),
    ),
    StageDefinition(
        id="order",
        order_label="陆",
        name="订单",
        owner="订单运营",
        risk=RiskLevel.L2,
        actions=("订单同步", "库存预占", "拆单/改址", "缺货处理"),
        failures=("超卖", "超时未发", "地址异常", "重复履约"),
        ai=("异常分类", "拆单/改址方案", "补偿", "库存调拨"),
        metrics=("迟发率", "取消率", "缺陷率"),
        steps=_steps(
            ("sync", "订单同步"),
            ("classify", "异常分类"),
            ("split", "拆单 / 改址"),
            ("stockout", "缺货处理"),
            ("compensate", "补偿"),
        ),
    ),
    StageDefinition(
        id="fulfillment",
        order_label="柒",
        name="库存与履约",
        owner="履约",
        risk=RiskLevel.L2,
        actions=("预占", "拆单换仓", "补货", "盘点", "补偿"),
        failures=("库存不准", "仓库爆仓", "补货延迟", "补偿失败"),
        ai=("仓网优化", "补货预测", "调拨建议", "补偿路径"),
        metrics=("有货率", "履约时效", "库存周转", "补偿率"),
        steps=_steps(
            ("reserve", "预占"),
            ("split_warehouse", "拆单换仓"),
            ("replenish", "补货"),
            ("count", "盘点"),
            ("compensate", "补偿"),
        ),
    ),
    StageDefinition(
        id="logistics",
        order_label="捌",
        name="物流与关务",
        owner="履约",
        risk=RiskLevel.L2,
        actions=("比价", "发货", "报关", "轨迹", "理赔退件"),
        failures=("扣关", "丢件", "延误", "退件"),
        ai=("渠道选择", "报关资料校验", "轨迹预测", "理赔草稿"),
        metrics=("时效", "妥投率", "关务异常率", "物流成本"),
        steps=_steps(
            ("compare", "比价"),
            ("ship", "发货"),
            ("customs", "报关"),
            ("tracking", "轨迹"),
            ("claims", "理赔退件"),
        ),
    ),
    StageDefinition(
        id="settlement",
        order_label="玖",
        name="收款与结算",
        owner="财务",
        risk=RiskLevel.L3,
        actions=("结算单", "费用退款拒付", "对账", "差异归因", "财务任务"),
        failures=("少结", "多扣", "退款争议", "拒付"),
        ai=("差异归因", "异常费用识别", "对账规则", "工单草稿"),
        metrics=("到账准确率", "差异率", "回款周期"),
        steps=_steps(
            ("statement", "结算单"),
            ("fees", "费用退款拒付"),
            ("reconcile", "对账"),
            ("diff", "差异归因"),
            ("finance", "财务任务"),
        ),
    ),
    StageDefinition(
        id="aftersales",
        order_label="拾",
        name="售后与合规",
        owner="客服与合规",
        risk=RiskLevel.L3,
        actions=("退货退款", "纠纷", "差评", "IP 产品安全", "平台政策"),
        failures=("退款滥用", "纠纷升级", "差评扩散", "合规下架"),
        ai=("政策 RAG", "退款裁决建议", "纠纷回复", "合规扫描"),
        metrics=("退款率", "纠纷率", "DSR", "合规下架数"),
        steps=_steps(
            ("returns", "退货退款"),
            ("disputes", "纠纷"),
            ("reviews", "差评"),
            ("compliance", "IP 产品安全"),
            ("policy", "平台政策"),
        ),
    ),
)

STAGE_RESULTS: dict[str, StageResult] = {
    "selection": StageResult(
        stage_id="selection",
        agent_id="selection",
        status=StageStatus.done,
        summary="扫描 8–12 周趋势，输出 5 个 Hero SKU；NW-102 毛利 6.8% 被 Verifier 否决并替换",
        artifacts=(
            Artifact(
                "trend-report.json",
                ArtifactKind.json,
                "mock://dispatch/selection/trend-report.json",
                "趋势与竞品扫描报告",
            ),
            Artifact(
                "selection-scorecard.csv",
                ArtifactKind.csv,
                "mock://dispatch/selection/selection-scorecard.csv",
                "5 个 Hero SKU 评分卡",
            ),
        ),
        metrics=(Metric("hero_skus", 5), Metric("vetoed", 1)),
        evidence=("选品评分卡", "Verifier 否决记录"),
        provenance=_provenance("10:20"),
        at="11:02",
    ),
    "content": StageResult(
        stage_id="content",
        agent_id="content",
        status=StageStatus.running,
        summary="产出 5 份 Brief、15 张商品图与 10 条短视频脚本草稿",
        artifacts=(
            Artifact(
                "brief-NW-101.md",
                ArtifactKind.markdown,
                "mock://dispatch/content/brief-NW-101.md",
                "NW-101 内容 Brief",
            ),
            Artifact(
                "hero-NW-101-01.png",
                ArtifactKind.image,
                "mock://dispatch/content/hero-NW-101-01.png",
                "首图第一版",
            ),
            Artifact(
                "reel-NW-101-01.mp4",
                ArtifactKind.video,
                "mock://dispatch/content/reel-NW-101-01.mp4",
                "短视频脚本预览",
            ),
        ),
        metrics=(
            Metric("briefs", 5),
            Metric("images", 15),
            Metric("videos", 10),
        ),
        evidence=("品牌规范", "合规词库（Mock）"),
        provenance=_provenance("10:30"),
        at="11:04",
    ),
    "listing": StageResult(
        stage_id="listing",
        agent_id="pricing",
        status=StageStatus.waiting,
        summary="生成 5 个 Listing 草稿与 1 条涨价建议，等待 L2 审批",
        artifacts=(
            Artifact(
                "listing-draft.json",
                ArtifactKind.json,
                "mock://dispatch/listing/listing-draft.json",
                "5 个 Listing 草稿",
            ),
            Artifact(
                "price-band.csv",
                ArtifactKind.csv,
                "mock://dispatch/listing/price-band.csv",
                "价格带与竞品对照",
            ),
        ),
        metrics=(Metric("listings", 5), Metric("price_changes", 1)),
        evidence=("平台类目模板", "价格带规则"),
        provenance=_provenance("10:36"),
        at="11:06",
    ),
    "organic": StageResult(
        stage_id="organic",
        agent_id="content",
        status=StageStatus.waiting,
        summary="内容日历与达人寄样排期已生成，等待发布",
        artifacts=(
            Artifact(
                "content-calendar.csv",
                ArtifactKind.csv,
                "mock://dispatch/organic/content-calendar.csv",
                "15 条内容排期",
            ),
            Artifact(
                "creator-samples.md",
                ArtifactKind.markdown,
                "mock://dispatch/organic/creator-samples.md",
                "8 位达人寄样清单",
            ),
        ),
        metrics=(Metric("planned_posts", 15), Metric("creators", 8)),
        evidence=("内容日历", "达人清单（Mock）"),
        provenance=_provenance("10:38"),
        at="11:08",
    ),
    "paid": StageResult(
        stage_id="paid",
        agent_id="ads",
        status=StageStatus.waiting,
        summary="生成 3 个 Campaign、总预算 $10,000、ROAS 护栏 2.5，等待 L3 审批",
        artifacts=(
            Artifact(
                "campaign-plan.csv",
                ArtifactKind.csv,
                "mock://dispatch/paid/campaign-plan.csv",
                "3 个 Campaign 计划",
            ),
            Artifact(
                "budget-guard.json",
                ArtifactKind.json,
                "mock://dispatch/paid/budget-guard.json",
                "预算与 ROAS 护栏",
            ),
        ),
        metrics=(
            Metric("campaigns", 3),
            Metric("budget", 10000),
            Metric("roas", "2.5"),
        ),
        evidence=("投放剧本", "预算护栏"),
        provenance=_provenance("10:40"),
        at="11:10",
    ),
    "order": StageResult(
        stage_id="order",
        agent_id="order",
        status=StageStatus.alert,
        summary="分类 6 单异常，2 单 P0/P1；拆单/改址建议已生成",
        artifacts=(
            Artifact(
                "order-exceptions.csv",
                ArtifactKind.csv,
                "mock://dispatch/order/order-exceptions.csv",
                "6 单异常明细",
            ),
            Artifact(
                "split-address-plan.json",
                ArtifactKind.json,
                "mock://dispatch/order/split-address-plan.json",
                "拆单/改址建议",
            ),
        ),
        metrics=(
            Metric("exceptions", 6),
            Metric("p0_p1", 2),
            Metric("sla_minutes", 15),
        ),
        evidence=("异常目录 ORD-01/03/04", "5×5 定级"),
        provenance=_provenance("10:42"),
        at="11:12",
    ),
    "fulfillment": StageResult(
        stage_id="fulfillment",
        agent_id="fulfillment",
        status=StageStatus.running,
        summary="完成空运/海运/海外仓比价，1 票报关失败触发拆单补偿",
        artifacts=(
            Artifact(
                "shipment-plan.json",
                ArtifactKind.json,
                "mock://dispatch/fulfillment/shipment-plan.json",
                "仓配与运力比价",
            ),
            Artifact(
                "compensation-log.md",
                ArtifactKind.markdown,
                "mock://dispatch/fulfillment/compensation-log.md",
                "拆单补偿记录",
            ),
        ),
        metrics=(Metric("compensations", 1), Metric("reservations_released", 6)),
        evidence=("拆单补偿剧本", "库存预占记录"),
        provenance=_provenance("10:45"),
        at="11:14",
    ),
    "logistics": StageResult(
        stage_id="logistics",
        agent_id="fulfillment",
        status=StageStatus.alert,
        summary="1 票扣关，补资料/换口岸建议已生成，轨迹监控中",
        artifacts=(
            Artifact(
                "customs-declaration.pdf",
                ArtifactKind.pdf,
                "mock://dispatch/logistics/customs-declaration.pdf",
                "报关资料与补件清单",
            ),
            Artifact(
                "tracking-events.json",
                ArtifactKind.json,
                "mock://dispatch/logistics/tracking-events.json",
                "轨迹事件",
            ),
        ),
        metrics=(Metric("customs_failures", 1), Metric("sla_minutes", 30)),
        evidence=("异常目录 LOG-03", "报关资料清单"),
        provenance=_provenance("10:48"),
        at="11:16",
    ),
    "settlement": StageResult(
        stage_id="settlement",
        agent_id="settlement",
        status=StageStatus.running,
        summary="3 笔对账差异，已生成财务任务；退款等待 L3 审批",
        artifacts=(
            Artifact(
                "settlement-diff.csv",
                ArtifactKind.csv,
                "mock://dispatch/settlement/settlement-diff.csv",
                "3 笔对账差异",
            ),
            Artifact(
                "finance-tasks.md",
                ArtifactKind.markdown,
                "mock://dispatch/settlement/finance-tasks.md",
                "财务跟进任务",
            ),
        ),
        metrics=(Metric("diffs", 3), Metric("pending_approvals", 1)),
        evidence=("PAY-02 playbook", "对账规则"),
        provenance=_provenance("10:52"),
        at="11:18",
    ),
    "aftersales": StageResult(
        stage_id="aftersales",
        agent_id="compliance",
        status=StageStatus.waiting,
        summary="1 个 SKU 合规不达标被剔除，售后政策 RAG 待命",
        artifacts=(
            Artifact(
                "compliance-report.md",
                ArtifactKind.markdown,
                "mock://dispatch/aftersales/compliance-report.md",
                "合规扫描与政策引用",
            ),
        ),
        metrics=(Metric("vetoed_skus", 1),),
        evidence=("AFS 异常目录", "政策 RAG（Mock）"),
        provenance=_provenance("10:55"),
        at="11:20",
    ),
}

CONTROL_STAGE = StageDefinition(
    id="control",
    order_label="—",
    name="全局控制塔",
    owner="运营负责人",
    risk=RiskLevel.L3,
    actions=("指标", "告警", "审批", "trace 审计", "复盘飞轮"),
    failures=("指标失真", "告警风暴", "审计缺口", "复盘不闭环"),
    ai=("异常检测", "归因分析", "复盘摘要"),
    metrics=("GMV", "毛利", "异常率", "审批时效"),
    steps=_steps(
        ("metrics", "指标"),
        ("alerts", "告警"),
        ("approvals", "审批"),
        ("trace", "trace 审计"),
        ("retro", "复盘飞轮"),
    ),
)


__all__ = ["CONTROL_STAGE", "STAGE_CATALOG", "STAGE_RESULTS"]
