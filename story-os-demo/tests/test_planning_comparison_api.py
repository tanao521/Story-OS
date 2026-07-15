from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_planning_evaluation_service import _ready
from web.app import app


def _tree_hash(path: Path) -> str:
    digest = sha256()
    for item in sorted(path.rglob("*")):
        if item.is_file():
            digest.update(item.relative_to(path).as_posix().encode())
            digest.update(item.read_bytes())
    return digest.hexdigest()


def test_comparison_endpoints_are_read_only_and_enforce_target_scope(tmp_path, monkeypatch) -> None:
    _ready(tmp_path); monkeypatch.chdir(tmp_path)
    with TestClient(app) as client:
        first = client.post("/api/evaluations/planning", json={"target_type": "near_planning_window", "operation_id": "comparison-first"}).json()["result"]["evaluation"]
        second = client.post("/api/evaluations/planning", json={"target_type": "near_planning_window", "operation_id": "comparison-second"}).json()["result"]["evaluation"]
        before = _tree_hash(tmp_path / "data" / "evaluations")
        comparison = client.get(f"/api/evaluations/{second['evaluation_id']}/comparison")
        comparable = client.get(f"/api/evaluations/{second['evaluation_id']}/comparable-reports")
        proposals = client.get(f"/api/evaluations/{second['evaluation_id']}/planning-proposals")
        after = _tree_hash(tmp_path / "data" / "evaluations")
        assert comparison.status_code == comparable.status_code == proposals.status_code == 200
        assert comparison.json()["result"]["comparison"]["baseline_evaluation_id"] == first["evaluation_id"]
        assert comparable.json()["result"]["reports"][0]["evaluation_id"] == first["evaluation_id"]
        assert before == after
        volume = client.post("/api/evaluations/planning", json={"target_type": "current_volume", "scope_ref": {"volume_id": "volume_1"}, "operation_id": "comparison-volume"}).json()["result"]["evaluation"]
        mismatch = client.get(f"/api/evaluations/{second['evaluation_id']}/comparison", params={"baseline_evaluation_id": volume["evaluation_id"]})
        assert mismatch.status_code == 409
        assert "PLANNING_COMPARISON_TARGET_MISMATCH" in mismatch.json()["errors"]


def test_comparison_no_baseline_is_a_normal_response(tmp_path, monkeypatch) -> None:
    _ready(tmp_path); monkeypatch.chdir(tmp_path)
    with TestClient(app) as client:
        report = client.post("/api/evaluations/planning", json={"target_type": "near_planning_window", "operation_id": "comparison-only"}).json()["result"]["evaluation"]
        response = client.get(f"/api/evaluations/{report['evaluation_id']}/comparison")
    assert response.status_code == 200
    assert response.json()["result"]["comparison"]["comparison_status"] == "no_baseline"
