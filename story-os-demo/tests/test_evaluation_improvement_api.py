from fastapi.testclient import TestClient

from web.app import app


def test_improvement_api_exposes_only_candidate_read_endpoints(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/evaluations/missing/improvements", json={"issue_ids": ["x"]})
        assert response.status_code == 409
        assert response.json()["errors"] == ["IMPROVEMENT_SOURCE_CHANGED"]
        assert client.get("/api/evaluations/improvements/missing/diff").status_code == 404
