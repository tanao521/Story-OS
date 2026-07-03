from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from system.version_manager import build_versioned_paths, get_next_version_number, get_selected_version, list_versions, select_version


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_manual_paths_and_next_version(tmp_path: Path) -> None:
    write_json(tmp_path / "manual" / "chapter_001_manual_v001.json", {"chapter_id": 1, "manual_text": "x"})

    paths = build_versioned_paths(1, "manual", 2, tmp_path)

    assert "manual" in paths["json_path"]
    assert paths["json_path"].endswith("chapter_001_manual_v002.json")
    assert get_next_version_number(1, "manual", tmp_path) == 2


def test_list_select_and_fallback_manual(tmp_path: Path) -> None:
    write_json(
        tmp_path / "drafts" / "chapter_001_draft_v001.json",
        {"chapter_id": 1, "version": 1, "version_label": "draft_v001", "draft_text": "draft"},
    )
    write_json(
        tmp_path / "edited" / "chapter_001_edited_v001.json",
        {"chapter_id": 1, "version": 1, "version_label": "edited_v001", "edited_text": "edited"},
    )
    write_json(
        tmp_path / "manual" / "chapter_001_manual_v001.json",
        {
            "chapter_id": 1,
            "version": 1,
            "version_label": "manual_v001",
            "manual_text": "manual text",
            "source_type": "edited",
            "source_version": 1,
            "editing": {"mode": "manual"},
        },
    )

    versions = list_versions(1, tmp_path)
    selected = select_version(1, "manual", 1, tmp_path)
    loaded = get_selected_version(1, tmp_path)

    assert len(versions["manual"]) == 1
    assert selected["source_type"] == "manual"
    assert loaded["version_label"] == "manual_v001"


def test_get_selected_version_prefers_latest_manual_without_selected(tmp_path: Path) -> None:
    write_json(tmp_path / "edited" / "chapter_001_edited_v001.json", {"chapter_id": 1, "version": 1, "edited_text": "edited"})
    write_json(tmp_path / "manual" / "chapter_001_manual_v002.json", {"chapter_id": 1, "version": 2, "manual_text": "manual"})

    selected = get_selected_version(1, tmp_path)

    assert selected["source_type"] == "manual"
    assert selected["version"] == 2
