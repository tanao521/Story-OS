from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from web.app import app


client = TestClient(app)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_quality_report_exists(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    write_json(tmp_path / "data" / "next_chapter_plan.json", {"chapter_id": 1})
    write_json(tmp_path / "data" / "quality_reports" / "chapter_001_edited_v001_quality.json", {
        "chapter_id": 1,
        "source_type": "edited",
        "source_version": 1,
        "overall_score": 0.82,
        "scores": {"continuity": 0.85},
        "flags": [{"type": "anti_ai_style"}],
        "suggestions": ["减少解释。"],
        "reader_simulation": {},
        "checks": {},
    })

    response = client.get("/api/quality-report?source_type=edited&version=1")
    data = response.json()

    assert data["result"]["exists"] is True
    assert response.headers["X-StoryOS-Compatibility"] == "compatibility"
    assert response.headers["X-StoryOS-Canonical-Endpoint"] == "/api/evaluations"
    assert data["result"]["scores"]["continuity"] == 0.85
    assert data["result"]["flags"]
    assert data["result"]["suggestions"]


def test_quality_report_missing(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    write_json(tmp_path / "data" / "next_chapter_plan.json", {"chapter_id": 1})

    data = client.get("/api/quality-report?source_type=edited&version=1").json()

    assert data["ok"] is True
    assert data["result"]["exists"] is False


def test_quality_report_does_not_call_deepseek(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    write_json(tmp_path / "data" / "next_chapter_plan.json", {"chapter_id": 1})

    data = client.get("/api/quality-report?source_type=edited&version=1").json()

    assert data["ok"] is True


def test_quality_report_does_not_leak_api_key(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    write_json(tmp_path / "data" / "next_chapter_plan.json", {"chapter_id": 1})

    response = client.get("/api/quality-report?source_type=edited&version=1")

    assert "API Key" not in response.text
    assert "DEEPSEEK_API_KEY" not in response.text
