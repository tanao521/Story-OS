from fastapi.testclient import TestClient

from web.app import app


def test_adoption_endpoints_reject_missing_candidate(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with TestClient(app) as client:
        assert client.post("/api/evaluations/improvements/missing/adoption-preview").status_code in {404, 409}
        assert client.post("/api/evaluations/improvements/missing/adopt", json={}).status_code in {404, 409, 422}
        assert client.post("/api/evaluations/improvements/missing/discard", json={}).status_code in {404, 409, 422}
