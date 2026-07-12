from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from web.app import app


client = TestClient(app)


def test_project_assets_get_lists_editable_story_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "story_spec.json").write_text(json.dumps({"title": "测试小说"}, ensure_ascii=False), encoding="utf-8")

    response = client.get("/api/project-assets")
    payload = response.json()

    assert response.status_code == 200
    assert payload["ok"] is True
    asset_ids = {asset["id"] for asset in payload["result"]["assets"]}
    assert {"story_spec", "story_blueprint", "characters", "world_bible", "world_rules", "project_md"} <= asset_ids
    story_spec = next(asset for asset in payload["result"]["assets"] if asset["id"] == "story_spec")
    assert story_spec["exists"] is True
    assert "测试小说" in story_spec["content"]


def test_project_asset_post_updates_json_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()

    response = client.post("/api/project-assets/characters", json={"content": '{"main_characters":[{"name":"林声"}]}'})
    saved = json.loads((tmp_path / "data" / "characters.json").read_text(encoding="utf-8"))

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert saved["main_characters"][0]["name"] == "林声"


def test_project_asset_post_rejects_invalid_json_without_overwrite(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    path = data_dir / "story_blueprint.json"
    path.write_text(json.dumps({"title": "原始蓝图"}, ensure_ascii=False), encoding="utf-8")

    response = client.post("/api/project-assets/story_blueprint", json={"content": '{bad json}'})
    saved = json.loads(path.read_text(encoding="utf-8"))

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert saved["title"] == "原始蓝图"


def test_project_asset_post_updates_project_markdown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()

    response = client.post("/api/project-assets/project_md", json={"content": "# 手动设定\n\n新的项目说明"})
    saved = (tmp_path / "data" / "project.md").read_text(encoding="utf-8")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert "新的项目说明" in saved
