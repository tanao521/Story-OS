from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import commands
import main
import web.routes as routes
from system.quality_checker import build_quality_report, save_quality_report
from system.review_gate import find_current_review_target
from system.version_manager import select_version


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def prepare_project(root: Path, text: str | None = None) -> None:
    chapter_text = text or (
        "林声找到避难所入口。\n\n"
        "“先别动。”他说。\n\n"
        "门后传来第二个人的呼吸声。"
    )
    write_json(root / "data" / "story_spec.json", {"title": "Test"})
    write_json(root / "data" / "characters.json", {"main_characters": []})
    write_json(root / "data" / "world_bible.json", {"continuity_rules": []})
    write_json(
        root / "data" / "state.json",
        {"current_chapter": 0, "current_stage": "waiting_for_review", "foreshadows": [], "timeline": [], "plot": {}},
    )
    write_json(
        root / "data" / "next_chapter_plan.json",
        {
            "chapter_id": 1,
            "chapter_title": "Opening",
            "chapter_goal": "找到避难所入口",
            "pacing_design": {"ending_hook": "门后传来第二个人的呼吸声"},
            "required_context": {"characters_to_use": [{"name": "林声"}], "world_rules_to_use": []},
        },
    )
    write_json(
        root / "data" / "edited" / "chapter_001_edited_v001.json",
        {
            "chapter_id": 1,
            "chapter_title": "Opening",
            "version": 1,
            "version_label": "edited_v001",
            "edited_text": chapter_text,
            "actual_word_count": len(chapter_text),
            "editing": {"mode": "local_rule", "fallback_used": True},
        },
    )
    select_version(1, "edited", 1, root / "data")


def save_report(root: Path, score_text: str | None = None) -> dict[str, Any]:
    source = json.loads((root / "data" / "edited" / "chapter_001_edited_v001.json").read_text(encoding="utf-8"))
    plan = json.loads((root / "data" / "next_chapter_plan.json").read_text(encoding="utf-8"))
    report = build_quality_report(
        source,
        "edited",
        1,
        "data/edited/chapter_001_edited_v001.json",
        plan,
        {},
        {},
        {},
        {},
    )
    if score_text == "low":
        report["overall_score"] = 0.58
    save_quality_report(report, root / "data")
    return report


def test_review_target_can_read_existing_quality_report(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_project(tmp_path)
    save_report(tmp_path)
    target = find_current_review_target(tmp_path / "data")

    summary = commands.quality_summary_for_target(target, tmp_path / "data")

    assert summary["overall_score"] > 0


def test_compare_drafts_includes_quality_score(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_project(tmp_path)
    report = save_report(tmp_path)

    result = commands.compare_drafts_command()

    assert result["outputs"]["edited"][0]["quality_score"] == report["overall_score"]


def test_low_score_approve_prompts_before_commit(monkeypatch: Any, tmp_path: Path, capsys: Any) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_project(tmp_path)
    save_report(tmp_path, "low")
    answers = iter(["approve", "no", "later"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    main.run_review_draft_command()

    output = capsys.readouterr().out
    state = json.loads((tmp_path / "data" / "state.json").read_text(encoding="utf-8"))
    assert "质量评分较低" in output
    assert state["current_chapter"] == 0


def test_missing_quality_report_does_not_crash(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_project(tmp_path)
    target = find_current_review_target(tmp_path / "data")

    assert commands.quality_summary_for_target(target, tmp_path / "data") == {}


def test_quality_check_does_not_call_deepseek(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_project(tmp_path)

    result = commands.quality_check_command()

    assert result["status"] == "success"
    assert result["outputs"]["report"]["overall_score"] >= 0


def test_quality_check_supports_committed_chapter(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_project(tmp_path)
    committed = tmp_path / "data" / "chapters" / "chapter_001.md"
    committed.parent.mkdir(parents=True, exist_ok=True)
    committed.write_text("# Opening\n\nCommitted chapter text.", encoding="utf-8")

    result = commands.quality_check_command(committed_chapter=1, allow_refinement=False)

    report = result["outputs"]["report"]
    assert result["status"] == "success"
    assert report["source_type"] == "committed"
    assert report["source_version"] == 1
    assert Path(report["json_path"]).exists()


def test_committed_quality_report_is_read_by_its_own_chapter_id(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_project(tmp_path)
    committed = tmp_path / "data" / "chapters" / "chapter_001.md"
    committed.parent.mkdir(parents=True, exist_ok=True)
    committed.write_text("# Opening\n\nCommitted chapter text.", encoding="utf-8")
    plan_path = tmp_path / "data" / "next_chapter_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["chapter_id"] = 2
    write_json(plan_path, plan)

    result = commands.quality_check_command(committed_chapter=1, allow_refinement=False)
    _, response, _ = routes.quality_report_response("committed", 1)

    assert result["status"] == "success"
    assert response["exists"] is True
