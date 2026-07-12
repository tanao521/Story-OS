from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from system.version_manager import (
    archive_version,
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


def test_list_versions_ignores_pipeline_runs_and_invalid_version_json(tmp_path: Path) -> None:
    pipeline_dir = tmp_path / "pipeline_runs"
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    (pipeline_dir / "run_chapter_001.json").write_text("{not valid json", encoding="utf-8")
    invalid_draft = tmp_path / "drafts" / "chapter_001_draft_v001.json"
    invalid_draft.parent.mkdir(parents=True, exist_ok=True)
    invalid_draft.write_text("{not valid json", encoding="utf-8")
    write_json(
        tmp_path / "manual" / "chapter_001_manual_v001.json",
        {"chapter_id": 1, "version": 1, "manual_text": "manual", "source_type": "edited", "source_version": 1},
    )

    versions = list_versions(1, tmp_path)

    assert versions["drafts"] == []
    assert len(versions["manual"]) == 1
    assert all("pipeline_runs" not in item["json_path"] for item in versions["manual"])


def test_archive_version_moves_files_and_hides_from_list(tmp_path: Path) -> None:
    json_path = tmp_path / "drafts" / "chapter_001_draft_v001.json"
    md_path = tmp_path / "drafts" / "chapter_001_draft_v001.md"
    quality_path = tmp_path / "quality_reports" / "chapter_001_draft_v001_quality.json"
    write_json(json_path, {"chapter_id": 1, "version": 1, "version_label": "draft_v001", "draft_text": "draft one"})
    md_path.write_text("draft one", encoding="utf-8")
    write_json(quality_path, {"chapter_id": 1, "source_type": "draft", "source_version": 1})
    select_version(1, "draft", 1, tmp_path)

    result = archive_version(1, "draft", 1, tmp_path)
    versions = list_versions(1, tmp_path)

    assert versions["drafts"] == []
    assert versions["selected"] == {}
    assert result["source_type"] == "draft"
    assert not json_path.exists()
    assert (tmp_path / "archive" / "versions" / "chapter_001" / "draft_v001" / "drafts" / "chapter_001_draft_v001.json").exists()
    assert (tmp_path / "archive" / "versions" / "chapter_001" / "draft_v001" / "quality_reports" / "chapter_001_draft_v001_quality.json").exists()
    assert (tmp_path / "archive" / "versions" / "chapter_001" / "draft_v001" / "archive_meta.json").exists()
