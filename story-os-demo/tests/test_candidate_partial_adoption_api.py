from fastapi.testclient import TestClient

from web.app import app
from tests.test_candidate_partial_adoption_service import _adopt_payload, _partial_candidate


def test_partial_adoption_endpoints_reject_missing_candidate(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with TestClient(app) as client:
        preview = client.post("/api/evaluations/improvements/missing/partial-adoption-preview", json={"selected_patch_ids": ["patch_a"]})
        adopt = client.post("/api/evaluations/improvements/missing/partial-adopt", json={"operation_id": "partial-api"})
    assert preview.status_code == 404 and adopt.status_code == 404


def test_partial_adoption_api_returns_preview_and_creates_work_version(tmp_path, monkeypatch) -> None:
    service, request, _, _ = _partial_candidate(tmp_path)
    monkeypatch.chdir(tmp_path)
    with TestClient(app) as client:
        response = client.post(f"/api/evaluations/improvements/{request['improvement_id']}/partial-adoption-preview", json={"candidate_id": request["candidate"]["candidate_id"], "selected_patch_ids": ["patch_alpha"]})
        assert response.status_code == 200
        preview = response.json()["result"]["preview"]
        assert response.json()["result"]["selected_patch_count"] == 1
        completed = client.post(f"/api/evaluations/improvements/{request['improvement_id']}/partial-adopt", json=_adopt_payload(preview, operation_id="partial-api-1"))
    assert completed.status_code == 200
    result = completed.json()["result"]
    assert result["candidate_status"] == "partially_adopted" and result["canon_changed"] is False
