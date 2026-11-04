import pytest

from opsconductor.schemas import Plan, PlanNode, validate_plan


def test_plan_rejects_cycle():
    plan = Plan(
        task_id="00000000-0000-0000-0000-000000000001",
        nodes=[
            PlanNode(node_id="a", action="verify", depends_on=["b"]),
            PlanNode(node_id="b", action="verify", depends_on=["a"]),
        ],
    )
    with pytest.raises(ValueError, match="cycle"):
        validate_plan(plan)


def test_plan_accepts_linear_nodes():
    plan = Plan(
        task_id="00000000-0000-0000-0000-000000000001",
        nodes=[
            PlanNode(node_id="a", action="verify"),
            PlanNode(node_id="b", action="verify", depends_on=["a"]),
        ],
    )
    validate_plan(plan)


def test_plan_rejects_duplicate_node_ids():
    plan = Plan(
        task_id="00000000-0000-0000-0000-000000000001",
        nodes=[
            PlanNode(node_id="a", action="verify"),
            PlanNode(node_id="a", action="report"),
        ],
    )
    with pytest.raises(ValueError, match="duplicate node_id"):
        validate_plan(plan)


def test_plan_rejects_unknown_dependency():
    plan = Plan(
        task_id="00000000-0000-0000-0000-000000000001",
        nodes=[PlanNode(node_id="a", action="verify", depends_on=["missing"])],
    )
    with pytest.raises(ValueError, match="unknown dependency"):
        validate_plan(plan)
