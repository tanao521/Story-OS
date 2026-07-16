from __future__ import annotations

import json
from pathlib import Path

from core.project_context import get_project_context
from evaluation_engine.legacy_adapter import LegacyEvaluationAdapter
from system.continuity_checker import continuity_content_hash
from fastapi.testclient import TestClient
from web.app import app


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_legacy_quality_and_continuity_views_are_readonly(tmp_path: Path) -> None:
    _write(tmp_path / "data/quality_reports/chapter_001_draft_v001_quality.json", {"overall_score": 0.8, "scores": {"continuity": 0.9}, "flags": [], "suggestions": [], "reader_simulation": {}, "checks": {}})
    _write(tmp_path / "data/continuity_reports/chapter_001_draft_v001_continuity.json", {"content_hash": "a", "previous_content_hash": "b", "score": 0.8, "verdict": "pass"})
    adapter = LegacyEvaluationAdapter(get_project_context(tmp_path))
    assert adapter.quality_view(chapter_id=1, source_type="draft", source_version=1)["source_format"] == "legacy"
    continuity = adapter.continuity_view(chapter_id=1, source_type="draft", source_version=1, content_hash="a", previous_content_hash="b")
    assert continuity["read_only"] is True and continuity["exists"] is True
    assert not (tmp_path / "data/evaluations/index.json").exists()


def test_legacy_adapter_is_project_isolated(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    second.mkdir()
    _write(first / "data/quality_reports/chapter_001_draft_v001_quality.json", {"overall_score": 0.7})
    assert LegacyEvaluationAdapter(get_project_context(first)).quality_view(chapter_id=1, source_type="draft", source_version=1)["exists"] is True
    assert LegacyEvaluationAdapter(get_project_context(second)).quality_view(chapter_id=1, source_type="draft", source_version=1)["exists"] is False


def test_legacy_continuity_api_uses_readonly_adapter(tmp_path: Path, monkeypatch) -> None:
    current, previous = "current chapter", "previous chapter"
    _write(tmp_path / "data/continuity_reports/chapter_002_draft_v001_continuity.json", {"content_hash": continuity_content_hash(current), "previous_content_hash": continuity_content_hash(previous), "score": 0.8, "verdict": "pass"})
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("web.routes.build_version_content", lambda *_: {"chapter_id": 2, "text": current})
    monkeypatch.setattr("web.routes._continuity_source_hashes", lambda *_: (continuity_content_hash(current), continuity_content_hash(previous)))
    with TestClient(app) as client:
        response = client.get("/api/continuity-report?source_type=draft&version=1")
    assert response.json()["result"]["source_format"] == "legacy"
    assert not (tmp_path / "data/evaluations/index.json").exists()
