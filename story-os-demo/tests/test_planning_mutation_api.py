from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from web.app import app


def test_save_next_chapter_route_uses_guarded_planning_mutation(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data/state.json").write_text('{"current_chapter":1,"world":{"keep":true}}', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/planning/next-chapter", json={"chapter_id": 2, "chapter_goal": "continue"})
    assert response.status_code == 200 and response.json()["ok"] is True
    state = (tmp_path / "data/state.json").read_text(encoding="utf-8")
    assert '"world"' in state and (tmp_path / "data/next_chapter_plan.md").exists()
    assert (tmp_path / "data/planning_control/mutation_audit.json").exists()
