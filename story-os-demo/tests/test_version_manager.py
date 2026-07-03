from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from system.version_manager import (
    build_versioned_paths,
    format_chapter_id,
    get_next_version_number,
    get_selected_version,
    list_versions,
    load_versions_index,
    select_version,
)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_format_chapter_id_pads_to_three_digits() -> None:
    assert format_chapter_id(1) == "001"


def test_build_versioned_paths_uses_expected_names(tmp_path: Path) -> None:
    paths = build_versioned_paths(1, "draft", 2, tmp_path)

    assert paths["json_path"].endswith("data" if False else "chapter_001_draft_v002.json")
    assert "drafts" in paths["json_path"]


def test_list_versions_scans_draft_and_edited(tmp_path: Path) -> None:
    write_json(
        tmp_path / "drafts" / "chapter_001_draft_v001.json",
        {"chapter_id": 1, "version": 1, "version_label": "draft_v001", "draft_text": "draft one"},
    )
    write_json(
        tmp_path / "edited" / "chapter_001_edited_v001.json",
        {
            "chapter_id": 1,
            "version": 1,
            "version_label": "edited_v001",
            "edited_text": "edited one",
            "source_draft_version": 1,
        },
    )

    versions = list_versions(1, tmp_path)

    assert len(versions["drafts"]) == 1
    assert len(versions["edited"]) == 1
    assert versions["drafts"][0]["version_label"] == "draft_v001"


def test_get_next_version_number_returns_next(tmp_path: Path) -> None:
    write_json(tmp_path / "drafts" / "chapter_001_draft_v001.json", {"chapter_id": 1, "draft_text": "one"})
    write_json(tmp_path / "drafts" / "chapter_001_draft_v002.json", {"chapter_id": 1, "draft_text": "two"})

    assert get_next_version_number(1, "draft", tmp_path) == 3


def test_select_and_get_selected_version(tmp_path: Path) -> None:
    write_json(
        tmp_path / "edited" / "chapter_001_edited_v001.json",
        {"chapter_id": 1, "version": 1, "version_label": "edited_v001", "edited_text": "edited"},
    )

    selected = select_version(1, "edited", 1, tmp_path)
    loaded = get_selected_version(1, tmp_path)

    assert selected["source_type"] == "edited"
    assert loaded["version"] == 1
    assert (tmp_path / "versions" / "chapter_001_versions.json").exists()


def test_load_versions_index_falls_back_to_latest_edited(tmp_path: Path) -> None:
    write_json(
        tmp_path / "drafts" / "chapter_001_draft_v001.json",
        {"chapter_id": 1, "version": 1, "draft_text": "draft"},
    )
    write_json(
        tmp_path / "edited" / "chapter_001_edited_v001.json",
        {"chapter_id": 1, "version": 1, "edited_text": "edited"},
    )

    index = load_versions_index(1, tmp_path)
    selected = get_selected_version(1, tmp_path)

    assert index["edited"]
    assert selected["source_type"] == "edited"
