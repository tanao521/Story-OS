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


def prepare_versions(root: Path) -> None:
    write_json(root / "data" / "next_chapter_plan.json", {"chapter_id": 1})
    write_json(root / "data" / "drafts" / "chapter_001_draft_v001.json", {
        "chapter_id": 1,
        "chapter_title": "草稿章",
        "version": 1,
        "version_label": "draft_v001",
        "draft_text": "草稿正文",
        "generation": {"mode": "local_model", "model": "qwen", "fallback_used": False},
    })
    write_json(root / "data" / "edited" / "chapter_001_edited_v001.json", {
        "chapter_id": 1,
        "chapter_title": "编辑章",
        "version": 1,
        "version_label": "edited_v001",
        "edited_text": "编辑正文",
        "editing": {"mode": "deepseek", "model": "deepseek-chat", "fallback_used": False},
    })


def test_version_content_returns_draft_text(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_versions(tmp_path)

    response = client.get("/api/versions/content?source_type=draft&version=1")

    assert response.json()["result"]["text"] == "草稿正文"


def test_version_content_returns_edited_text(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_versions(tmp_path)

    response = client.get("/api/versions/content?source_type=edited&version=1")

    assert response.json()["result"]["text"] == "编辑正文"


def test_version_content_missing_file_returns_error(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    write_json(tmp_path / "data" / "next_chapter_plan.json", {"chapter_id": 1})

    response = client.get("/api/versions/content?source_type=draft&version=1")
    data = response.json()

    assert data["ok"] is False
    assert "Traceback" not in response.text


def test_version_content_includes_quality_summary(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_versions(tmp_path)
    write_json(tmp_path / "data" / "quality_reports" / "chapter_001_edited_v001_quality.json", {
        "chapter_id": 1,
        "source_type": "edited",
        "source_version": 1,
        "overall_score": 0.82,
        "scores": {},
        "flags": [],
        "suggestions": [],
    })

    response = client.get("/api/versions/content?source_type=edited&version=1")

    assert response.json()["result"]["quality"]["exists"] is True
    assert response.json()["result"]["quality"]["score"] == 0.82
