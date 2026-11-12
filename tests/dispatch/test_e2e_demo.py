"""端到端冒烟：完整审批、Demo 编排与重置。"""


def test_full_demo_flow(client):
    initial = client.get("/api/v1/dispatch/snapshot").json()
    assert initial["kpis"]["approvals_pending"] == 3
    assert len(initial["chain"]) == 10
    assert len(initial["agents"]) == 8

    for approval_id, decision in (
        ("budget", "approve"),
        ("price", "reject"),
        ("refund", "approve"),
    ):
        response = client.post(
            f"/api/v1/dispatch/approvals/{approval_id}/decision",
            json={"decision": decision, "actor": "demo-operator"},
        )
        assert response.status_code == 200

    final = response.json()["snapshot"]
    assert final["kpis"]["approvals_pending"] == 0
    assert final["flow_note"] == "审批已清 · 进入执行"
    assert final["approvals"]["price"]["status"] == "rejected"
    assert final["approvals"]["price"]["stamp"] == "驳"
    assert final["approvals"]["budget"]["stamp"] == "准"

    report = client.post("/api/v1/dispatch/demo/run")
    assert report.status_code == 200
    payload = report.json()["report"]
    titles = [event["title"] for event in payload["events"]]
    assert len(payload["steps"]) == 10
    assert titles.count("审批通过") == 2
    assert "审批驳回" in titles
    assert "补偿触发" in titles
    assert any("RPA" in title for title in titles)
    assert any("对账差异" in title for title in titles)
    assert payload["verification"]["passed"] is True
    assert payload["verification"]["vetoed"]

    reset = client.post("/api/v1/dispatch/reset")
    assert reset.status_code == 200
    assert reset.json()["kpis"]["approvals_pending"] == 3


def test_goal_rebuilds_plan_and_pending_approvals(client):
    response = client.post(
        "/api/v1/dispatch/goals",
        json={"instruction": "本周把美国店做到 12 万美元 GMV，预算 1.2 万。"},
    )
    assert response.status_code == 200
    snapshot = response.json()
    assert snapshot["goal"]["instruction"].startswith("本周把美国店")
    assert snapshot["kpis"]["approvals_pending"] == 3
    assert len(snapshot["plan"]["steps"]) == 10


def test_unknown_exception_returns_404(client):
    assert client.get("/api/v1/dispatch/exceptions/NOPE-99").status_code == 404
