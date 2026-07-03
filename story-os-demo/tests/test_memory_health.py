from __future__ import annotations

import json
from pathlib import Path

from system.memory_health import (
    check_chapter_files,
    check_project_initialization,
    check_quality_reports,
    check_state_consistency,
    check_summary_files,
    check_todos,
    check_vector_index,
    check_version_integrity,
    render_memory_health_markdown,
    run_memory_health_check,
    save_memory_health_report,
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_missing_story_spec_returns_error(tmp_path: Path) -> None:
    write_json(tmp_path / "state.json", {"current_chapter": 0})
    result = check_project_initialization(tmp_path)
    assert any(issue["id"] == "missing_story_spec" and issue["level"] == "error" for issue in result["issues"])


def test_missing_state_returns_error(tmp_path: Path) -> None:
    write_json(tmp_path / "story_spec.json", {"title": "Test"})
    result = check_project_initialization(tmp_path)
    assert any(issue["id"] == "missing_state" and issue["level"] == "error" for issue in result["issues"])


def test_current_chapter_and_chapter_count_mismatch_returns_error(tmp_path: Path) -> None:
    write_json(tmp_path / "state.json", {"current_chapter": 2})
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "chapter_001.md").write_text("一" * 250, encoding="utf-8")
    result = check_state_consistency(tmp_path)
    assert any(issue["level"] == "error" for issue in result["issues"])


def test_missing_summary_returns_warning(tmp_path: Path) -> None:
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "chapter_001.md").write_text("一" * 250, encoding="utf-8")
    result = check_summary_files(tmp_path)
    assert any(issue["id"] == "missing_summary" and issue["level"] == "warning" for issue in result["issues"])


def test_selected_points_to_missing_version_returns_error(tmp_path: Path) -> None:
    write_json(
        tmp_path / "versions" / "chapter_001_versions.json",
        {
            "chapter_id": 1,
            "selected": {
                "source_type": "manual",
                "version": 1,
                "json_path": str(tmp_path / "manual" / "missing.json"),
            },
        },
    )
    result = check_version_integrity(tmp_path)
    assert any(issue["id"] == "selected_version_missing" and issue["level"] == "error" for issue in result["issues"])


def test_manual_missing_manual_text_returns_warning(tmp_path: Path) -> None:
    manual_path = tmp_path / "manual" / "chapter_001_manual_v001.json"
    write_json(manual_path, {"chapter_id": 1, "version": 1})
    write_json(
        tmp_path / "versions" / "chapter_001_versions.json",
        {"chapter_id": 1, "manual": [{"source_type": "manual", "version": 1, "json_path": str(manual_path)}]},
    )
    result = check_version_integrity(tmp_path)
    assert any(issue["id"] == "manual_missing_text" and issue["level"] == "warning" for issue in result["issues"])


def test_missing_quality_report_returns_warning_or_info(tmp_path: Path) -> None:
    write_json(
        tmp_path / "versions" / "chapter_001_versions.json",
        {
            "chapter_id": 1,
            "selected": {
                "source_type": "draft",
                "version": 1,
                "json_path": str(tmp_path / "drafts" / "chapter_001_draft_v001.json"),
            },
        },
    )
    result = check_quality_reports(tmp_path)
    assert any(issue["category"] == "quality" and issue["level"] in {"warning", "info"} for issue in result["issues"])


def test_too_many_todos_returns_warning(tmp_path: Path) -> None:
    write_json(tmp_path / "todos" / "todos.json", {"todos": [{"status": "open", "priority": "medium"} for _ in range(21)]})
    result = check_todos(tmp_path)
    assert any(issue["id"] == "too_many_open_todos" and issue["level"] == "warning" for issue in result["issues"])


def test_missing_memory_index_returns_info(tmp_path: Path) -> None:
    result = check_vector_index(tmp_path)
    assert any(issue["id"] == "memory_index_missing" and issue["level"] == "info" for issue in result["issues"])


def test_render_memory_health_markdown_contains_title(tmp_path: Path) -> None:
    report = run_memory_health_check(tmp_path)
    assert "Story OS Memory Health Report" in render_memory_health_markdown(report)


def test_save_memory_health_report_generates_latest_json_and_md(tmp_path: Path) -> None:
    report = run_memory_health_check(tmp_path)
    paths = save_memory_health_report(report, tmp_path)
    assert Path(paths["json_path"]).exists()
    assert Path(paths["markdown_path"]).exists()


def test_chapter_files_detects_number_gap(tmp_path: Path) -> None:
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "chapter_001.md").write_text("一" * 250, encoding="utf-8")
    (chapters / "chapter_003.md").write_text("三" * 250, encoding="utf-8")
    result = check_chapter_files(tmp_path)
    assert any(issue["id"] == "chapter_number_gap" for issue in result["issues"])
