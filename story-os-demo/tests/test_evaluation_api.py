from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from web.app import app


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_evaluation_api_aggregates_without_model_call(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "data" / "state.json", {"current_chapter": 1})
    _write(tmp_path / "data" / "next_chapter_plan.json", {"chapter_id": 1, "chapter_goal": "推进"})
    _write(tmp_path / "data" / "drafts" / "chapter_001_draft_v001.json", {"chapter_id": 1, "draft_text": "正文", "generation": {}})
    with TestClient(app) as client:
        assert client.get("/api/evaluations/overview").status_code == 200
        response = client.post("/api/evaluations", json={"target_type": "chapter_draft", "chapter_number": 1, "operation_id": "api-1"})
        assert response.status_code == 200
        payload = response.json()["result"]
        assert payload["replayed"] is False
        assert len(payload["evaluation"]["dimensions"]) == 10
        assert client.get("/api/evaluations").json()["result"]["evaluations"]
        assert client.get("/api/evaluations/profiles").json()["result"]["profiles"][0]["profile_id"] == "chapter-default-v1"
