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


def prepare_diff_versions(root: Path) -> None:
    write_json(root / "data" / "next_chapter_plan.json", {"chapter_id": 1})
    write_json(root / "data" / "drafts" / "chapter_001_draft_v001.json", {
        "chapter_id": 1,
        "version": 1,
        "version_label": "draft_v001",
        "draft_text": "相同段落。\n\n旧句子。",
    })
    write_json(root / "data" / "edited" / "chapter_001_edited_v001.json", {
        "chapter_id": 1,
        "version": 1,
        "version_label": "edited_v001",
        "edited_text": "相同段落。\n\n新句子。",
    })


def test_diff_api_returns_ok(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_diff_versions(tmp_path)

    response = client.get("/api/versions/diff?left_type=draft&left_version=1&right_type=edited&right_version=1")

    assert response.json()["ok"] is True


def test_diff_api_returns_html_and_summary(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_diff_versions(tmp_path)

    data = client.get("/api/versions/diff?left_type=draft&left_version=1&right_type=edited&right_version=1").json()

    assert "diff_html" in data["result"]
    assert "summary" in data["result"]


def test_diff_api_missing_version_returns_error(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    write_json(tmp_path / "data" / "next_chapter_plan.json", {"chapter_id": 1})

    data = client.get("/api/versions/diff?left_type=draft&left_version=1&right_type=edited&right_version=1").json()

    assert data["ok"] is False


def test_diff_api_does_not_call_external_services(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_diff_versions(tmp_path)

    response = client.get("/api/versions/diff?left_type=draft&left_version=1&right_type=edited&right_version=1")

    assert response.status_code == 200
