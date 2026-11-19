"""Run API 冒烟测试。"""

from __future__ import annotations


def test_start_run_returns_full_run(client):
    response = client.post("/api/v1/dispatch/runs")

    assert response.status_code == 200
    run = response.json()
    assert run["id"].startswith("run-")
    assert run["status"] == "succeeded"
    assert run["mode"] == "demo"
    assert len(run["steps"]) == 10
    assert len(run["agents"]) == 8
    assert len(run["events"]) == 51
    assert len(run["gates"]) == 3
    assert len(run["handoffs"]) == 8
    assert len(run["artifacts"]) == 10
    assert run["metrics"]["approved_gates"] == 2
    assert run["metrics"]["rejected_gates"] == 1
    assert run["metrics"]["reconciliation_count"] == 3
    assert run["verification"]["passed"] is True


def test_get_run_and_latest_return_same_run(client):
    created = client.post("/api/v1/dispatch/runs").json()

    fetched = client.get(f"/api/v1/dispatch/runs/{created['id']}")
    latest = client.get("/api/v1/dispatch/runs/latest")

    assert fetched.status_code == 200
    assert latest.status_code == 200
    assert fetched.json()["id"] == created["id"]
    assert latest.json()["id"] == created["id"]


def test_list_runs_returns_newest_first(client):
    first = client.post("/api/v1/dispatch/runs").json()
    second = client.post("/api/v1/dispatch/runs").json()

    response = client.get("/api/v1/dispatch/runs?limit=2")

    assert response.status_code == 200
    runs = response.json()["runs"]
    assert [run["id"] for run in runs] == [second["id"], first["id"]]
    assert set(runs[0]) == {
        "id",
        "status",
        "goal_instruction",
        "started_at",
        "step_count",
        "gate_count",
        "summary",
    }


def test_latest_run_returns_404_without_records(client):
    response = client.get("/api/v1/dispatch/runs/latest")

    assert response.status_code == 404
    assert response.json()["detail"] == "no runs"


def test_unknown_run_returns_404(client):
    response = client.get("/api/v1/dispatch/runs/run-missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "unknown run: run-missing"


def test_list_limit_is_bounded(client):
    assert client.get("/api/v1/dispatch/runs?limit=0").status_code == 422
    assert client.get("/api/v1/dispatch/runs?limit=21").status_code == 422


def test_start_run_does_not_change_dispatch_snapshot(client):
    before = client.get("/api/v1/dispatch/snapshot").json()

    response = client.post("/api/v1/dispatch/runs")
    assert response.status_code == 200

    after = client.get("/api/v1/dispatch/snapshot").json()
    assert after == before


def test_run_payload_does_not_expose_credentials(client):
    response = client.post("/api/v1/dispatch/runs")

    body = response.text
    assert "credential_ref" not in body
    assert "TIKTOK_SHOP_US_TOKEN" not in body
