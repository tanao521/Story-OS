from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import config
import commands


class FakePath:
    def __init__(self, key: str) -> None:
        self.key = key

    def exists(self) -> bool:
        return True

    def __fspath__(self) -> str:
        return self.key

    def __str__(self) -> str:
        return self.key

    def as_posix(self) -> str:
        return self.key

    def __repr__(self) -> str:
        return f"FakePath({self.key!r})"


def prepare_project(store: dict[str, Any]) -> None:
    store["story_spec.json"] = {"title": "Test", "genre": "test"}
    store["story_blueprint.json"] = {"title": "Test"}
    store["characters.json"] = {"main_characters": []}
    store["world_bible.json"] = {"core_rules": []}
    store["state.json"] = {"current_chapter": 0, "current_stage": "next_chapter_planned"}
    store["next_chapter_plan.json"] = {
        "chapter_id": 1,
        "chapter_title": "Opening",
        "estimated_word_count": 1200,
        "chapter_goal": "start",
        "conflict_design": {"main_conflict": "conflict"},
        "pacing_design": {"ending_hook": "hook"},
        "scene_plan": [],
        "required_context": {"characters_to_use": [], "world_rules_to_use": []},
    }


def configure_memory_workspace(monkeypatch: Any, store: dict[str, Any]) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", "ollama_cloud", raising=False)
    monkeypatch.setattr(config, "OLLAMA_CLOUD_BASE_URL", "https://ollama.com/api", raising=False)
    monkeypatch.setattr(config, "OLLAMA_CLOUD_MODEL", "deepseek-v4-pro:cloud", raising=False)
    monkeypatch.setattr(config, "OLLAMA_CLOUD_API_KEY", "test-key", raising=False)

    paths = {
        "story_spec": FakePath("story_spec.json"),
        "state": FakePath("state.json"),
        "blueprint": FakePath("story_blueprint.json"),
        "characters": FakePath("characters.json"),
        "world_bible": FakePath("world_bible.json"),
        "next_chapter_plan": FakePath("next_chapter_plan.json"),
        "memory_index": FakePath("memory_index.json"),
        "current_context": FakePath("current_context.json"),
        "edited_dir": FakePath("edited_dir"),
    }

    monkeypatch.setattr(commands, "_paths", lambda project_root=None: paths)
    monkeypatch.setattr(commands, "_missing_write_draft_inputs", lambda paths: "")

    monkeypatch.setattr(commands, "draft_paths", lambda chapter_id: (FakePath(f"chapter_{chapter_id:03d}_draft.json"), FakePath(f"chapter_{chapter_id:03d}_draft.md")))
    monkeypatch.setattr(commands, "edited_paths", lambda chapter_id: (FakePath(f"chapter_{chapter_id:03d}_edited.json"), FakePath(f"chapter_{chapter_id:03d}_edited.md")))

    version_counters = {"draft": 0, "edited": 0}

    def fake_get_next_version_number(chapter_id: int, version_type: str) -> int:
        version_counters[version_type] += 1
        return version_counters[version_type]

    monkeypatch.setattr(commands, "get_next_version_number", fake_get_next_version_number)
    monkeypatch.setattr(
        commands,
        "build_versioned_paths",
        lambda chapter_id, version_type, version: {
            "json_path": FakePath(f"chapter_{chapter_id:03d}_{version_type}_v{version:03d}.json"),
            "markdown_path": FakePath(f"chapter_{chapter_id:03d}_{version_type}_v{version:03d}.md"),
        },
    )

    versions_index: dict[int, dict[str, list[dict[str, Any]]]] = {}

    def fake_load_versions_index(chapter_id: int) -> dict[str, Any]:
        return versions_index.setdefault(chapter_id, {"selected": {}, "drafts": [], "edited": [], "manual": []})

    def fake_save_versions_index(chapter_id: int, payload: dict[str, Any]) -> None:
        versions_index[chapter_id] = payload

    monkeypatch.setattr(commands, "load_versions_index", fake_load_versions_index)
    monkeypatch.setattr(commands, "save_versions_index", fake_save_versions_index)

    def fake_load_json(path: Any) -> dict[str, Any]:
        key = str(path)
        if key.endswith("story_spec.json"):
            return store["story_spec.json"]
        if key.endswith("story_blueprint.json"):
            return store["story_blueprint.json"]
        if key.endswith("characters.json"):
            return store["characters.json"]
        if key.endswith("world_bible.json"):
            return store["world_bible.json"]
        if key.endswith("state.json"):
            return store["state.json"]
        if key.endswith("next_chapter_plan.json"):
            return store["next_chapter_plan.json"]
        if key.endswith("current_context.json"):
            return store.setdefault("current_context.json", {})
        if key.endswith("draft_v001.json") or key.endswith("draft_v002.json") or key.endswith("draft.json"):
            return store[key]
        if key.endswith("edited_v001.json") or key.endswith("edited_v002.json") or key.endswith("edited.json"):
            return store[key]
        raise KeyError(key)

    def fake_save_json(path: Any, data: dict[str, Any]) -> None:
        def normalize(value: Any) -> Any:
            if isinstance(value, FakePath):
                return value.as_posix()
            if isinstance(value, dict):
                return {key: normalize(item) for key, item in value.items()}
            if isinstance(value, list):
                return [normalize(item) for item in value]
            return value

        store[str(path)] = normalize(data)

    def fake_save_markdown(path: Any, text: str) -> None:
        store[str(path)] = text

    monkeypatch.setattr(commands, "load_json", fake_load_json)
    monkeypatch.setattr(commands, "save_json", fake_save_json)
    monkeypatch.setattr(commands, "save_markdown", fake_save_markdown)

    def fake_resolve_draft_for_edit(chapter_id: int, draft_version: int | None):
        version = draft_version or 1
        return (
            {
                "json_path": FakePath(f"chapter_{chapter_id:03d}_draft_v{version:03d}.json"),
                "source_type": "draft",
            },
            "",
        )

    monkeypatch.setattr(commands, "_resolve_draft_for_edit", fake_resolve_draft_for_edit)


def fake_write(*args: Any, **kwargs: Any) -> dict[str, Any]:
    fake_write.counter += 1
    return {
        "chapter_id": 1,
        "chapter_title": "Opening",
        "status": "draft",
        "estimated_word_count": 1200,
        "actual_word_count": 3500 + fake_write.counter,
        "draft_text": f"draft text version {fake_write.counter} " * 180,
        "generation": {"mode": "ollama_cloud", "model": "deepseek-v4-pro:cloud", "fallback_used": False, "warnings": []},
        "self_check": {"warnings": []},
    }


fake_write.counter = 0


def fake_edit(draft: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
    fake_edit.counter += 1
    return {
        "chapter_id": 1,
        "chapter_title": "Opening",
        "status": "edited",
        "actual_word_count": 3600 + fake_edit.counter,
        "edited_text": f"edited from draft {draft.get('version')} pass {fake_edit.counter} " * 170,
        "editing": {"mode": "local_rule", "model": "local_rule", "fallback_used": True, "warnings": []},
        "checks": {"warnings": []},
        "source_draft_path": draft.get("source_draft_path", ""),
    }


fake_edit.counter = 0


def test_regenerate_draft_creates_new_versions_without_advancing_chapter(monkeypatch: Any) -> None:
    store: dict[str, Any] = {}
    prepare_project(store)
    configure_memory_workspace(monkeypatch, store)
    fake_write.counter = 0
    monkeypatch.setattr(commands, "write_chapter_draft", fake_write)

    first = commands.write_draft_command()
    second = commands.regenerate_draft_command()
    state = store["state.json"]

    assert first["outputs"]["version"] == 1
    assert second["outputs"]["version"] == 2
    assert "chapter_001_draft_v001.json" in store
    assert "chapter_001_draft_v002.json" in store
    assert "chapter_001_draft.json" in store
    assert state["current_chapter"] == 0


def test_reedit_draft_can_use_specific_draft_version(monkeypatch: Any) -> None:
    store: dict[str, Any] = {}
    prepare_project(store)
    configure_memory_workspace(monkeypatch, store)
    fake_write.counter = 0
    fake_edit.counter = 0
    monkeypatch.setattr(commands, "write_chapter_draft", fake_write)
    monkeypatch.setattr(commands, "edit_draft", fake_edit)
    commands.write_draft_command()
    commands.regenerate_draft_command()

    first_edit = commands.edit_draft_command(draft_version=1)
    second_edit = commands.reedit_draft_command(draft_version=2)

    assert first_edit["outputs"]["source_draft_version"] == 1
    assert second_edit["outputs"]["source_draft_version"] == 2
    assert first_edit["outputs"]["version"] == 1
    assert second_edit["outputs"]["version"] == 2
    assert "chapter_001_edited_v001.json" in store
    assert "chapter_001_edited_v002.json" in store


def test_write_draft_require_model_rejects_unconfigured_mock(monkeypatch: Any) -> None:
    store: dict[str, Any] = {}
    prepare_project(store)
    configure_memory_workspace(monkeypatch, store)

    result = commands.write_draft_command(require_model=True)

    assert result["status"] == "failed"
    assert "Ollama Cloud" in result["message"] or "LLM_PROVIDER" in result["message"]
    assert "chapter_001_draft_v001.json" not in store
