from __future__ import annotations

import json
from pathlib import Path

from system.todo_manager import create_todos_from_quality_report, load_todos


def write_quality_report(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "chapter_id": 3,
                "flags": [
                    {"type": "anti_ai_style", "severity": "high", "message": "减少解释腔"},
                    {"type": "continuity", "severity": "medium", "message": "核对避难所规则"},
                    {"type": "hook_strength", "severity": "low", "message": "加强结尾钩子"},
                ],
                "suggestions": ["补一段角色选择压力"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_create_todos_from_quality_flags(tmp_path: Path) -> None:
    report_path = tmp_path / "data" / "quality_reports" / "report.json"
    write_quality_report(report_path)

    created = create_todos_from_quality_report(report_path, tmp_path / "data")

    assert any(item["title"] == "减少解释腔" for item in created)


def test_create_todos_from_quality_suggestions(tmp_path: Path) -> None:
    report_path = tmp_path / "data" / "quality_reports" / "report.json"
    write_quality_report(report_path)

    created = create_todos_from_quality_report(report_path, tmp_path / "data")

    assert any(item["title"] == "补一段角色选择压力" for item in created)


def test_anti_ai_style_maps_to_style(tmp_path: Path) -> None:
    report_path = tmp_path / "data" / "quality_reports" / "report.json"
    write_quality_report(report_path)

    created = create_todos_from_quality_report(report_path, tmp_path / "data")

    assert next(item for item in created if item["title"] == "减少解释腔")["type"] == "style"


def test_continuity_maps_to_continuity(tmp_path: Path) -> None:
    report_path = tmp_path / "data" / "quality_reports" / "report.json"
    write_quality_report(report_path)

    created = create_todos_from_quality_report(report_path, tmp_path / "data")

    assert next(item for item in created if item["title"] == "核对避难所规则")["type"] == "continuity"


def test_hook_strength_maps_to_revision(tmp_path: Path) -> None:
    report_path = tmp_path / "data" / "quality_reports" / "report.json"
    write_quality_report(report_path)

    created = create_todos_from_quality_report(report_path, tmp_path / "data")

    assert next(item for item in created if item["title"] == "加强结尾钩子")["type"] == "revision"


def test_duplicate_quality_todo_is_not_created(tmp_path: Path) -> None:
    report_path = tmp_path / "data" / "quality_reports" / "report.json"
    write_quality_report(report_path)

    first = create_todos_from_quality_report(report_path, tmp_path / "data")
    second = create_todos_from_quality_report(report_path, tmp_path / "data")
    todos = load_todos(tmp_path / "data")

    assert first
    assert second == []
    assert len(todos["items"]) == len(first)
