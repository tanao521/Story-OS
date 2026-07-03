from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import main
from system.quality_checker import build_quality_report, save_quality_report
from system.status_dashboard import (
    build_status_dashboard,
    collect_foreshadow_status,
    collect_next_chapter_state,
    collect_progress_info,
    collect_project_info,
    collect_quality_status,
    load_json_if_exists,
    render_status_text,
    save_status_report,
    suggest_next_actions,
)
from system.version_manager import select_version


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def prepare_base_project(root: Path) -> None:
    write_json(root / "data" / "story_spec.json", {
        "title": "Test Novel",
        "genre": "末世",
        "length_type": "长篇",
        "target_word_count": 300000,
    })
    write_json(root / "data" / "story_blueprint.json", {"title": "Test Novel"})
    write_json(root / "data" / "characters.json", {"main_characters": []})
    write_json(root / "data" / "world_bible.json", {"continuity_rules": []})
    write_json(root / "data" / "state.json", {
        "current_chapter": 0,
        "current_stage": "waiting_for_review",
        "foreshadows": [
            {"id": "fs_001", "content": "门后的声音", "status": "open"},
            {"id": "fs_002", "content": "旧钥匙", "status": "resolved"},
        ],
    })
    write_json(root / "data" / "next_chapter_plan.json", {
        "chapter_id": 1,
        "chapter_title": "Opening",
        "chapter_goal": "找到入口",
        "pacing_design": {"ending_hook": "门后有声音"},
        "required_context": {"characters_to_use": [], "world_rules_to_use": []},
    })


def add_versions_and_review(root: Path) -> None:
    write_json(root / "data" / "drafts" / "chapter_001_draft_v001.json", {
        "chapter_id": 1,
        "chapter_title": "Opening",
        "version": 1,
        "version_label": "draft_v001",
        "draft_text": "找到入口。\n\n“先听。”\n\n门后有声音。",
        "actual_word_count": 30,
        "generation": {"mode": "mock", "fallback_used": False},
    })
    write_json(root / "data" / "edited" / "chapter_001_edited_v001.json", {
        "chapter_id": 1,
        "chapter_title": "Opening",
        "version": 1,
        "version_label": "edited_v001",
        "edited_text": "找到入口。\n\n“先听。”\n\n门后有声音。",
        "actual_word_count": 30,
        "editing": {"mode": "local_rule", "fallback_used": True},
    })
    select_version(1, "edited", 1, root / "data")
    write_json(root / "data" / "reviews" / "chapter_001_review.json", {
        "chapter_id": 1,
        "status": "pending",
    })


def add_quality_report(root: Path) -> None:
    source = json.loads((root / "data" / "edited" / "chapter_001_edited_v001.json").read_text(encoding="utf-8"))
    plan = json.loads((root / "data" / "next_chapter_plan.json").read_text(encoding="utf-8"))
    report = build_quality_report(source, "edited", 1, "data/edited/chapter_001_edited_v001.json", plan, {}, {}, {}, {})
    report["overall_score"] = 0.82
    save_quality_report(report, root / "data")


def test_load_json_if_exists_returns_default_for_missing(tmp_path: Path) -> None:
    assert load_json_if_exists(tmp_path / "missing.json", {"x": 1}) == {"x": 1}


def test_load_json_if_exists_handles_broken_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{bad", encoding="utf-8")

    assert load_json_if_exists(path, {"safe": True}) == {"safe": True}


def test_collect_project_info_reads_story_spec(tmp_path: Path) -> None:
    prepare_base_project(tmp_path)

    assert collect_project_info(tmp_path / "data")["title"] == "Test Novel"


def test_collect_progress_info_reads_current_chapter(tmp_path: Path) -> None:
    prepare_base_project(tmp_path)

    assert collect_progress_info(tmp_path / "data")["current_chapter"] == 0


def test_collect_next_chapter_state_recognizes_plan_versions_review(tmp_path: Path) -> None:
    prepare_base_project(tmp_path)
    add_versions_and_review(tmp_path)

    state = collect_next_chapter_state(tmp_path / "data")

    assert state["plan_exists"] is True
    assert state["draft_versions_count"] == 1
    assert state["edited_versions_count"] == 1
    assert state["review_status"] == "pending"


def test_collect_quality_status_recognizes_risk_level(tmp_path: Path) -> None:
    prepare_base_project(tmp_path)
    add_versions_and_review(tmp_path)
    add_quality_report(tmp_path)

    quality = collect_quality_status(tmp_path / "data")

    assert quality["risk_level"] == "low"
    assert quality["latest_score"] == 0.82


def test_collect_foreshadow_status_counts_open_and_resolved(tmp_path: Path) -> None:
    prepare_base_project(tmp_path)

    foreshadows = collect_foreshadow_status(tmp_path / "data")

    assert foreshadows["open_count"] == 1
    assert foreshadows["resolved_count"] == 1


def test_suggest_next_actions_recommends_setup_without_story_spec() -> None:
    status = {"health": {"missing_files": ["data/story_spec.json"]}}

    assert suggest_next_actions(status)[0]["command"] == "python main.py setup"


def test_suggest_next_actions_recommends_write_draft_when_plan_exists_without_draft(tmp_path: Path) -> None:
    prepare_base_project(tmp_path)
    status = build_status_dashboard(tmp_path / "data")

    assert status["next_actions"][0]["command"] == "python main.py write-draft"


def test_suggest_next_actions_recommends_review_for_pending_edited(tmp_path: Path) -> None:
    prepare_base_project(tmp_path)
    add_versions_and_review(tmp_path)
    add_quality_report(tmp_path)
    status = build_status_dashboard(tmp_path / "data")

    assert status["next_actions"][0]["command"] == "python main.py review-draft"


def test_build_status_dashboard_returns_version(tmp_path: Path) -> None:
    prepare_base_project(tmp_path)

    assert build_status_dashboard(tmp_path / "data")["dashboard_version"] == "2.0"


def test_render_status_text_contains_title(tmp_path: Path) -> None:
    prepare_base_project(tmp_path)
    status = build_status_dashboard(tmp_path / "data")

    assert "Story OS 状态面板" in render_status_text(status)


def test_save_status_report_writes_json_and_markdown(tmp_path: Path) -> None:
    prepare_base_project(tmp_path)
    status = build_status_dashboard(tmp_path / "data")

    json_path, markdown_path = save_status_report(status, tmp_path / "data")

    assert Path(json_path).exists()
    assert Path(markdown_path).exists()


def test_status_json_output_has_no_extra_text(monkeypatch: Any, tmp_path: Path, capsys: Any) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_base_project(tmp_path)
    monkeypatch.setattr(sys, "argv", ["main.py", "status", "--json"])

    main.main()
    output = capsys.readouterr().out

    parsed = json.loads(output)
    assert parsed["dashboard_version"] == "2.0"
