from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from web.app import app


def test_revision_api_creates_candidates_and_diff(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    chapter = tmp_path / "data" / "chapters" / "chapter_001.md"
    chapter.parent.mkdir(parents=True)
    chapter.write_text("# Chapter 1\n\nOriginal event.", encoding="utf-8")
    with TestClient(app) as client:
        created = client.post("/api/revisions", json={"chapter_id": 1, "reason": "Correct event"}).json()
        assert created["ok"]
        revision_id = created["result"]["revision"]["revision_id"]
        candidate = client.post(f"/api/revisions/{revision_id}/candidates", json={"content": "# Chapter 1\n\nCorrected event."}).json()
        assert candidate["ok"]
        compared = client.get(f"/api/revisions/{revision_id}/diff").json()
        assert compared["ok"] and "unified_diff" in compared["result"]["diff"]
        reviewed = client.post(f"/api/revisions/{revision_id}/review", json={"decision": "approve"}).json()
        assert reviewed["ok"] and reviewed["result"]["revision"]["status"] == "approved"
        versions = client.get("/api/chapters/1/canon-versions").json()
        assert versions["ok"] and versions["result"]["versions"]
