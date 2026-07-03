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
    write_json(
        root / "data" / "state.json",
        {"current_chapter": 0, "current_stage": "waiting_for_review", "foreshadows": [], "timeline": [], "plot": {}},
    )
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


def test_commit_uses_selected_draft_version(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_project(tmp_path)
    write_json(
        tmp_path / "data" / "drafts" / "chapter_001_draft_v001.json",
        {
            "chapter_id": 1,
            "chapter_title": "Opening",
            "version": 1,
            "version_label": "draft_v001",
            "draft_text": "selected draft text",
        },
    )
    write_json(
        tmp_path / "data" / "edited" / "chapter_001_edited_v001.json",
        {
            "chapter_id": 1,
            "chapter_title": "Opening",
            "version": 1,
            "version_label": "edited_v001",
            "edited_text": "newer edited text",
            "source_draft_version": 1,
        },
    )
    select_version(1, "draft", 1, tmp_path / "data")

    result = commands.commit_chapter_command()
    chapter_text = (tmp_path / "data" / "chapters" / "chapter_001.md").read_text(encoding="utf-8")

    assert result["status"] == "success"
    assert result["outputs"]["source_used"] == "draft"
    assert result["outputs"]["source_version"] == 1
    assert result["outputs"]["source_path"].endswith("chapter_001_draft_v001.json")
    assert "selected draft text" in chapter_text
    assert "newer edited text" not in chapter_text


def test_commit_falls_back_when_selected_version_missing(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_project(tmp_path)
    write_json(
        tmp_path / "data" / "versions" / "chapter_001_versions.json",
        {
            "chapter_id": 1,
            "drafts": [],
            "edited": [],
            "selected": {"source_type": "draft", "version": 99, "json_path": "missing.json"},
        },
    )
    write_json(
        tmp_path / "data" / "edited" / "chapter_001_edited_v001.json",
        {
            "chapter_id": 1,
            "chapter_title": "Opening",
            "version": 1,
            "version_label": "edited_v001",
            "edited_text": "fallback edited text",
            "source_draft_version": 1,
        },
    )

    result = commands.commit_chapter_command()

    assert result["status"] == "success"
    assert result["outputs"]["source_used"] == "edited"
    assert result["outputs"]["source_version"] == 1
    assert result["warnings"]
