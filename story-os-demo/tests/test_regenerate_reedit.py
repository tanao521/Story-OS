from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import commands


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def prepare_project(root: Path) -> None:
    write_json(root / "data" / "story_spec.json", {"title": "Test", "genre": "末世"})
    write_json(root / "data" / "story_blueprint.json", {"title": "Test"})
    write_json(root / "data" / "characters.json", {"main_characters": []})
    write_json(root / "data" / "world_bible.json", {"core_rules": []})
    write_json(root / "data" / "state.json", {"current_chapter": 0, "current_stage": "next_chapter_planned"})
    write_json(
        root / "data" / "next_chapter_plan.json",
        {
            "chapter_id": 1,
            "chapter_title": "Opening",
            "estimated_word_count": 1200,
            "chapter_goal": "start",
            "conflict_design": {"main_conflict": "conflict"},
            "pacing_design": {"ending_hook": "hook"},
            "scene_plan": [],
            "required_context": {"characters_to_use": [], "world_rules_to_use": []},
        },
    )


def fake_write(*args: Any, **kwargs: Any) -> dict[str, Any]:
    fake_write.counter += 1
    return {
        "chapter_id": 1,
        "chapter_title": "Opening",
        "status": "draft",
        "estimated_word_count": 1200,
        "actual_word_count": 700 + fake_write.counter,
        "draft_text": f"draft text version {fake_write.counter} " * 80,
        "generation": {"mode": "mock", "model": "mock", "fallback_used": False, "warnings": []},
        "self_check": {"warnings": []},
    }


fake_write.counter = 0


def fake_edit(draft: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
    fake_edit.counter += 1
    return {
        "chapter_id": 1,
        "chapter_title": "Opening",
        "status": "edited",
        "actual_word_count": 800 + fake_edit.counter,
        "edited_text": f"edited from draft {draft.get('version')} pass {fake_edit.counter} " * 70,
        "editing": {"mode": "local_rule", "model": "local_rule", "fallback_used": True, "warnings": []},
        "checks": {"warnings": []},
        "source_draft_path": draft.get("source_draft_path", ""),
    }


fake_edit.counter = 0


def test_regenerate_draft_creates_new_versions_without_advancing_chapter(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_project(tmp_path)
    fake_write.counter = 0
    monkeypatch.setattr(commands, "write_chapter_draft", fake_write)

    first = commands.write_draft_command()
    second = commands.regenerate_draft_command()
    state = json.loads((tmp_path / "data" / "state.json").read_text(encoding="utf-8"))

    assert first["outputs"]["version"] == 1
    assert second["outputs"]["version"] == 2
    assert (tmp_path / "data" / "drafts" / "chapter_001_draft_v001.json").exists()
    assert (tmp_path / "data" / "drafts" / "chapter_001_draft_v002.json").exists()
    assert (tmp_path / "data" / "drafts" / "chapter_001_draft.json").exists()
    assert state["current_chapter"] == 0


def test_reedit_draft_can_use_specific_draft_version(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_project(tmp_path)
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
    assert (tmp_path / "data" / "edited" / "chapter_001_edited_v001.json").exists()
    assert (tmp_path / "data" / "edited" / "chapter_001_edited_v002.json").exists()
