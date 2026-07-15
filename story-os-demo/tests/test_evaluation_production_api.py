from fastapi.testclient import TestClient

from tests.test_planning_evaluation_service import _ready
from web.app import app


def test_usage_maintenance_and_export_endpoints(tmp_path, monkeypatch) -> None:
    service = _ready(tmp_path); monkeypatch.chdir(tmp_path)
    report, _ = service.generate({"target_type": "near_planning_window", "operation_id": "api-export"})
    with TestClient(app) as client:
        assert client.get("/api/evaluations/usage/summary").status_code == 200
        assert client.get("/api/evaluations/usage/events", params={"limit": 1}).status_code == 200
        assert client.get("/api/evaluations/maintenance/preview").status_code == 200
        exported = client.get(f"/api/evaluations/{report['evaluation_id']}/export", params={"format": "markdown"})
        assert exported.status_code == 200 and "D:/" not in exported.text
        assert client.get(f"/api/evaluations/{report['evaluation_id']}/export", params={"format": "xml"}).status_code == 422
