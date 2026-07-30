from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from core.project_context import get_project_context
from system.chapter_assembly_evidence_service import ChapterAssemblyEvidenceScope, ChapterAssemblyEvidenceService
from web.app import app


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _project(root: Path) -> None:
    _write(root / "data" / "next_chapter_plan.json", {"chapter_id": 1})
    _write(root / "data" / "state.json", {"current_chapter": 0})
    _write(root / "data" / "manual" / "chapter_001_manual_v001.json", {
        "chapter_id": 1, "version": 1, "version_label": "manual_v001", "manual_text": "精确审核版本。",
    })
    _write(root / "data" / "branches" / "main" / "registry.json", {
        "project_id": root.name, "timeline_id": "main", "active_branch_id": "main", "revision": "1",
    })


def _generate(root: Path) -> None:
    context = get_project_context(root)
    ChapterAssemblyEvidenceService(context).generate(ChapterAssemblyEvidenceScope(
        project_id=root.name, timeline_id="main", branch_id="main", chapter_id=1, source_version_id="manual_v001",
    ))


def test_review_evidence_endpoint_returns_only_current_version_evidence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _project(tmp_path); _generate(tmp_path); monkeypatch.chdir(tmp_path)
    response = TestClient(app).get("/api/review/assembly-evidence?source_type=manual&version=1")
    result = response.json()["result"]
    assert result["status"] == "CURRENT"
    assert result["evidence"]["source_version_id"] == "manual_v001"
    assert "manual_text" not in response.text


def test_review_evidence_endpoint_reports_stale_without_regenerating(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _project(tmp_path); _generate(tmp_path); monkeypatch.chdir(tmp_path)
    _write(tmp_path / "data" / "manual" / "chapter_001_manual_v001.json", {
        "chapter_id": 1, "version": 1, "version_label": "manual_v001", "manual_text": "内容已修改。",
    })
    response = TestClient(app).get("/api/review/assembly-evidence?source_type=manual&version=1")
    assert response.json()["result"]["status"] == "STALE"
    assert len(list((tmp_path / "data" / "chapter_assembly_evidence").rglob("*.json"))) == 1


def test_review_evidence_frontend_is_advisory_only():
    template = (Path(__file__).parents[1] / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    script = (Path(__file__).parents[1] / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "review-assembly-evidence" in template
    assert "仅供人工审核参考；不会自动通过、拒绝、提交或改写正文。" in template
    assert "/api/review/assembly-evidence" in script
    assert "apiPost(\"/api/review/approve\"" not in script[script.index("async function loadReviewAssemblyEvidence"):script.index("async function selectVersion")]
