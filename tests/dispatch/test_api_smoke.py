"""Dispatch HTTP API 冒烟测试：快照契约、审批裁决、异常与页面服务。"""

import json

SNAPSHOT = "/api/v1/dispatch/snapshot"
DECIDE_BUDGET = "/api/v1/dispatch/approvals/budget/decision"

GOAL_FIELDS = {
    "id",
    "instruction",
    "store",
    "market",
    "target_gmv",
    "budget",
    "roas_target",
}
KPI_FIELDS = {"gmv_target", "exceptions", "approvals_pending", "compensations"}
PLAN_FIELDS = {"id", "goal_id", "approval_ids", "risk", "created_at", "steps"}
STEP_FIELDS = {"id", "stage", "name", "capability", "risk", "status", "artifact"}
CHAIN_FIELDS = {"id", "name", "status", "meta"}
AGENT_FIELDS = {
    "id",
    "name",
    "role",
    "capabilities",
    "risk",
    "status",
    "status_label",
    "current_task",
}
APPROVAL_FIELDS = {
    "id",
    "title",
    "action",
    "risk",
    "owner",
    "impact",
    "recommended",
    "status",
    "stamp",
    "actor",
    "decided_at",
}
EXCEPTION_FIELDS = {
    "id",
    "title",
    "priority",
    "li",
    "sla",
    "owner",
    "count",
    "playbook",
}
TRACE_FIELDS = {"at", "title", "detail"}


def test_snapshot_has_demo_contract(client):
    response = client.get(SNAPSHOT)

    assert response.status_code == 200
    data = response.json()
    assert data["kpis"]["approvals_pending"] == 3
    assert data["kpis"]["gmv_target"] == 100_000
    assert data["kpis"]["exceptions"] == 6
    assert data["kpis"]["compensations"] == 1
    assert data["flow_note"] == "审批进行中 · 3 件待批"
    assert len(data["exceptions"]) == 6
    assert len(data["trace"]) == 7
    assert len(data["chain"]) == 10
    assert len(data["agents"]) == 8
    assert len(data["plan"]["steps"]) == 10
    assert data["plan"]["approval_ids"] == ["budget", "price", "refund"]
    assert data["plan"]["risk"] == "L3"


def test_snapshot_payload_is_plain_json_and_matches_frontend_shape(client):
    data = client.get(SNAPSHOT).json()

    assert json.loads(json.dumps(data)) == data
    assert set(data) == {
        "goal",
        "kpis",
        "flow_note",
        "plan",
        "chain",
        "agents",
        "approvals",
        "exceptions",
        "trace",
    }
    assert set(data["goal"]) == GOAL_FIELDS
    assert set(data["kpis"]) == KPI_FIELDS
    assert set(data["plan"]) == PLAN_FIELDS
    assert set(data["plan"]["steps"][0]) == STEP_FIELDS
    assert set(data["chain"][0]) == CHAIN_FIELDS
    assert set(data["agents"][0]) == AGENT_FIELDS
    assert set(data["approvals"]) == {"budget", "price", "refund"}
    assert set(data["approvals"]["budget"]) == APPROVAL_FIELDS
    assert set(data["exceptions"][0]) == EXCEPTION_FIELDS
    assert set(data["exceptions"][0]["playbook"]) == {"trigger", "phases", "automation"}
    assert set(data["exceptions"][0]["playbook"]["phases"][0]) == {"label", "steps"}
    assert set(data["trace"][0]) == TRACE_FIELDS


def test_snapshot_agent_labels_keep_presentation_overrides(client):
    agents = {agent["id"]: agent for agent in client.get(SNAPSHOT).json()["agents"]}

    assert agents["selection"]["status"] == "done"
    assert agents["selection"]["status_label"] == "已完成"
    assert agents["content"]["status_label"] == "进行中"
    assert agents["pricing"]["status_label"] == "待批"
    assert agents["ads"]["status_label"] == "待批"
    assert agents["order"]["status_label"] == "处理中"
    assert agents["fulfillment"]["status_label"] == "补偿中"
    assert agents["settlement"]["status_label"] == "对账中"
    assert agents["compliance"]["status_label"] == "已完成"


def test_snapshot_pending_approvals_carry_no_stamp(client):
    approvals = client.get(SNAPSHOT).json()["approvals"]

    budget = approvals["budget"]
    assert budget["recommended"] == "approve"
    assert budget["status"] == "pending"
    assert budget["stamp"] is None
    assert budget["actor"] is None
    assert budget["decided_at"] is None
    assert approvals["price"]["recommended"] == "reject"
    assert approvals["refund"]["recommended"] == "approve"


def test_approval_decision_and_duplicate_409(client):
    response = client.post(
        DECIDE_BUDGET,
        json={"decision": "approve", "actor": "财务小财"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["snapshot"]["kpis"]["approvals_pending"] == 2
    approval = data["approval"]
    assert approval["id"] == "budget"
    assert approval["status"] == "approved"
    assert approval["stamp"] == "准"
    assert approval["actor"] == "财务小财"
    assert approval["decided_at"]

    duplicate = client.post(
        DECIDE_BUDGET,
        json={"decision": "reject", "actor": "运营小运"},
    )
    assert duplicate.status_code == 409
    current = client.get(SNAPSHOT).json()
    assert current["approvals"]["budget"]["status"] == "approved"
    assert current["kpis"]["approvals_pending"] == 2


def test_approval_decision_defaults_actor(client):
    response = client.post(DECIDE_BUDGET, json={"decision": "approve"})

    assert response.status_code == 200
    assert response.json()["approval"]["actor"] == "demo-operator"


def test_unknown_approval_returns_404(client):
    response = client.post(
        "/api/v1/dispatch/approvals/missing/decision",
        json={"decision": "approve"},
    )

    assert response.status_code == 404


def test_exception_playbook_has_three_phases(client):
    response = client.get("/api/v1/dispatch/exceptions/ORD-01")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "ORD-01"
    assert data["priority"] == "P0"
    assert data["li"] == "L5 / I4"
    assert data["playbook"]["trigger"]
    assert data["playbook"]["automation"]
    assert len(data["playbook"]["phases"]) == 3
    assert set(data["playbook"]["phases"][0]) == {"label", "steps"}


def test_unknown_exception_returns_404(client):
    response = client.get("/api/v1/dispatch/exceptions/NOPE-99")

    assert response.status_code == 404


def test_dispatch_page_is_served(client):
    response = client.get("/dispatch")

    assert response.status_code == 200
    assert "运筹跨境" in response.text


def test_root_redirects_to_dispatch_page(client):
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/dispatch"


def test_goal_creation_returns_rebuilt_snapshot(client):
    response = client.post(
        "/api/v1/dispatch/goals",
        json={"instruction": "本周做到 $80k GMV，优先稳住退款率。"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["goal"]["instruction"] == "本周做到 $80k GMV，优先稳住退款率。"
    assert data["kpis"]["approvals_pending"] == 3
    assert data["trace"][-1]["title"] == "计划生成"


def test_blank_goal_returns_422(client):
    whitespace = client.post("/api/v1/dispatch/goals", json={"instruction": "   "})
    empty = client.post("/api/v1/dispatch/goals", json={"instruction": ""})

    assert whitespace.status_code == 422
    assert empty.status_code == 422


def test_approvals_reset_restores_pending(client):
    client.post(DECIDE_BUDGET, json={"decision": "approve"})

    response = client.post("/api/v1/dispatch/approvals/reset")

    assert response.status_code == 200
    data = response.json()
    assert data["kpis"]["approvals_pending"] == 3
    assert all(item["status"] == "pending" for item in data["approvals"].values())
    assert data["trace"][-1]["title"] == "审批案重置"


def test_reset_restores_seed(client):
    client.post(DECIDE_BUDGET, json={"decision": "approve"})
    client.post(
        "/api/v1/dispatch/goals",
        json={"instruction": "任意新目标"},
    )

    response = client.post("/api/v1/dispatch/reset")

    assert response.status_code == 200
    data = response.json()
    assert data["goal"]["id"] == "goal-demo"
    assert data["goal"]["instruction"].startswith("本周做到 $100k GMV")
    assert data["kpis"]["approvals_pending"] == 3
    assert len(data["trace"]) == 7
    assert data["trace"][0]["title"] == "目标接入"


def test_demo_run_returns_report_and_snapshot(client):
    response = client.post("/api/v1/dispatch/demo/run")

    assert response.status_code == 200
    data = response.json()
    report = data["report"]
    assert set(report) == {"summary", "verification", "steps", "events", "approvals"}
    assert report["summary"]
    assert len(report["steps"]) == 10
    assert set(report["steps"][0]) == STEP_FIELDS
    assert set(report["events"][0]) == TRACE_FIELDS
    assert set(report["approvals"][0]) == APPROVAL_FIELDS
    assert report["verification"]["passed"] is True
    assert report["verification"]["checks"] == [
        "margin",
        "inventory",
        "budget",
        "compliance",
        "trace",
    ]
    assert report["verification"]["vetoed"]

    titles = [event["title"] for event in report["events"]]
    assert titles.count("审批通过") == 2
    assert titles.count("审批驳回") == 1
    assert "补偿触发" in titles
    assert any("RPA" in title for title in titles)
    assert any("对账差异" in title for title in titles)

    approvals = {item["id"]: item for item in report["approvals"]}
    assert approvals["budget"]["status"] == "approved"
    assert approvals["price"]["status"] == "rejected"
    assert approvals["price"]["stamp"] == "驳"
    assert approvals["refund"]["stamp"] == "准"

    assert data["snapshot"]["kpis"]["approvals_pending"] == 3
