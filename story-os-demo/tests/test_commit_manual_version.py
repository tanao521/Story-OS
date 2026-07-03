from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import commands
from system.version_manager import select_version


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def prepare_project(root: Path) -> None:
    write_json(root / "data" / "story_spec.json", {"title": "Test"})
    write_json(root / "data" / "characters.json", {"main_characters": []})
    write_json(root / "data" / "world_bible.json", {"core_rules": []})
    write_json(root / "data" / "state.json", {"current_chapter": 0, "current_stage": "waiting_for_review", "foreshadows": [], "timeline": [], "plot": {}})
    write_json(
        root / "data" / "next_chapter_plan.json",
        {
            "chapter_id": 1,
            "chapter_title": "Opening",
            "chapter_goal": "goal",
            "conflict_design": {"main_conflict": "conflict"},
            "climax_design": {"climax_event": "climax"},
            "required_context": {"characters_to_use": [], "world_rules_to_use": []},
        },
    )


def write_manual(root: Path, version: int, text: str) -> None:
    write_json(
        root / "data" / "manual" / f"chapter_001_manual_v{version:03d}.json",
        {
            "chapter_id": 1,
            "chapter_title": "Opening",
            "version": version,
            "version_label": f"manual_v{version:03d}",
            "manual_text": text,
            "source_type": "edited",
            "source_version": 1,
            "editing": {"mode": "manual", "fallback_used": False},
        },
    )


def test_commit_uses_selected_manual(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_project(tmp_path)
    write_manual(tmp_path, 1, "selected manual text")
    write_json(tmp_path / "data" / "edited" / "chapter_001_edited_v001.json", {"chapter_id": 1, "version": 1, "edited_text": "edited text"})
    select_version(1, "manual", 1, tmp_path / "data")

    result = commands.commit_chapter_command()
    chapter_text = (tmp_path / "data" / "chapters" / "chapter_001.md").read_text(encoding="utf-8")
    state = json.loads((tmp_path / "data" / "state.json").read_text(encoding="utf-8"))

    assert result["status"] == "success"
    assert result["outputs"]["source_used"] == "manual"
    assert result["outputs"]["source_version"] == 1
    assert "selected manual text" in chapter_text
    assert "edited text" not in chapter_text
    assert state["current_chapter"] == 1


def test_commit_prefers_latest_manual_without_selected(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_project(tmp_path)
    write_json(tmp_path / "data" / "edited" / "chapter_001_edited_v001.json", {"chapter_id": 1, "version": 1, "edited_text": "edited text"})
    write_manual(tmp_path, 1, "first manual")
    write_manual(tmp_path, 2, "latest manual")

    result = commands.commit_chapter_command()
    chapter_text = (tmp_path / "data" / "chapters" / "chapter_001.md").read_text(encoding="utf-8")

    assert result["outputs"]["source_used"] == "manual"
    assert result["outputs"]["source_version"] == 2
    assert "latest manual" in chapter_text
