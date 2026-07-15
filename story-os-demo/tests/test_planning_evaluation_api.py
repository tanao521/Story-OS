from fastapi.testclient import TestClient

from web.app import app
from tests.test_planning_evaluation_service import _ready


def test_planning_evaluation_api_and_overview(tmp_path, monkeypatch) -> None:
    _ready(tmp_path); monkeypatch.chdir(tmp_path)
    with TestClient(app) as client:
        overview = client.get("/api/evaluations/planning/overview")
        assert overview.status_code == 200 and any(item["target_type"] == "near_planning_window" for item in overview.json()["result"]["available_scopes"])
        created = client.post("/api/evaluations/planning", json={"target_type": "near_planning_window", "operation_id": "api-planning"})
        assert created.status_code == 200
        report = created.json()["result"]["evaluation"]
        assert client.get(f"/api/evaluations/{report['evaluation_id']}").status_code == 200
        assert client.get("/api/evaluations", params={"target_type": "near_planning_window"}).json()["result"]["evaluations"]
