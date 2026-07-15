from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from core.setup_wizard import build_story_spec_from_answers
from web.app import app


client = TestClient(app)


def test_build_story_spec_from_answers_requires_title() -> None:
    try:
        build_story_spec_from_answers({"title": ""})
    except ValueError as exc:
        assert str(exc) == "title is required"
    else:
        raise AssertionError("expected ValueError")


def test_build_story_spec_from_answers_normalizes_lists() -> None:
    spec = build_story_spec_from_answers({
        "title": "Test",
        "genre": "其他",
        "custom_genre": "异能",
        "length_type": "短篇",
        "focus": "生存,秘密\n关系",
        "avoid": ["降智", ""],
    })

    assert spec["genre"] == "异能"
    assert spec["target_word_count"] == 8000
    assert spec["focus"] == ["生存", "秘密", "关系"]
    assert spec["avoid"] == ["降智"]


def test_project_init_state_not_initialized(monkeypatch: Any) -> None:
    class FakePath:
        def __init__(self, value: str) -> None:
            self.value = value

        def exists(self) -> bool:
            return False

    monkeypatch.setattr("web.routes.Path", FakePath)

    data = client.get("/api/project/init-state").json()

    assert data["ok"] is True
    assert data["result"]["initialized"] is False
    assert data["result"]["next_action"] == "create_story"


def test_project_create_rejects_empty_title() -> None:
    data = client.post("/api/project/create", json={"title": ""}).json()

    assert data["ok"] is False
    assert data["errors"] == ["title is required"]


def test_project_create_uses_core_create_function(monkeypatch: Any) -> None:
    called: dict[str, Any] = {}

    def fake_create_story_project(raw_answers: dict[str, Any], data_dir: str = "data") -> dict[str, str]:
        called["raw_answers"] = raw_answers
        called["data_dir"] = data_dir
        return {
            "story_spec_path": "data/story_spec.json",
            "state_path": "data/state.json",
            "project_path": "data/project.md",
        }

    monkeypatch.setattr("web.routes.create_story_project", fake_create_story_project)
    monkeypatch.setattr(
        "web.routes.commands.initialize_planning_command",
        lambda use_deepseek=False: {"status": "success", "outputs": {}, "warnings": []},
    )

    data = client.post("/api/project/create", json={
        "title": "测试小说",
        "genre": "末世",
        "length_type": "长篇",
    }).json()

    assert data["ok"] is True
    assert data["result"]["story_spec_path"] == "data/story_spec.json"
    assert called["data_dir"] == "data"
    assert called["raw_answers"]["title"] == "测试小说"
