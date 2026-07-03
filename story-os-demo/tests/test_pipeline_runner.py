from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from system import pipeline_runner


STEP_NAMES = [
    "build-context",
    "plan-next",
    "write-draft",
    "edit-draft",
    "commit-chapter",
    "sync-obsidian",
    "index-vault",
]


def write_state(current_chapter: int) -> None:
    path = Path("data/state.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"current_chapter": current_chapter, "current_stage": "test"}, ensure_ascii=False),
        encoding="utf-8",
    )


def make_success_step(name: str) -> Any:
    def step() -> dict[str, Any]:
        return {"name": name, "status": "success", "message": f"{name} ok", "outputs": {}, "warnings": []}

    return step


def patch_success_pipeline(monkeypatch: Any) -> None:
    monkeypatch.setattr(pipeline_runner.commands, "build_context_command", make_success_step("build-context"))
    monkeypatch.setattr(pipeline_runner.commands, "plan_next_command", make_success_step("plan-next"))
    monkeypatch.setattr(pipeline_runner.commands, "write_draft_command", make_success_step("write-draft"))
    monkeypatch.setattr(pipeline_runner.commands, "edit_draft_command", make_success_step("edit-draft"))

    def commit() -> dict[str, Any]:
        write_state(1)
        return {"name": "commit-chapter", "status": "success", "message": "commit ok", "outputs": {}, "warnings": []}

    monkeypatch.setattr(pipeline_runner.commands, "commit_chapter_command", commit)
    monkeypatch.setattr(pipeline_runner.commands, "sync_obsidian_command", make_success_step("sync-obsidian"))
    monkeypatch.setattr(pipeline_runner.commands, "index_vault_command", make_success_step("index-vault"))


def test_run_single_chapter_pipeline_returns_dict(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_state(0)
    patch_success_pipeline(monkeypatch)

    monkeypatch.setattr(
        pipeline_runner,
        "load_local_config",
        lambda: {"review_gate": {"enabled": True, "allow_auto_commit": True}},
    )
    report = pipeline_runner.run_single_chapter_pipeline(auto_commit=True)

    assert isinstance(report, dict)


def test_success_status_and_steps(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_state(0)
    patch_success_pipeline(monkeypatch)

    monkeypatch.setattr(
        pipeline_runner,
        "load_local_config",
        lambda: {"review_gate": {"enabled": True, "allow_auto_commit": True}},
    )
    report = pipeline_runner.run_single_chapter_pipeline(auto_commit=True)

    assert report["status"] in {"success", "success_with_warnings"}
    assert [step["name"] for step in report["steps"]] == STEP_NAMES
    assert report["final_state"]["current_chapter_after"] == report["final_state"]["current_chapter_before"] + 1


def test_plan_next_failure_stops_pipeline(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_state(0)
    monkeypatch.setattr(pipeline_runner.commands, "build_context_command", make_success_step("build-context"))
    monkeypatch.setattr(
        pipeline_runner.commands,
        "plan_next_command",
        lambda: {"name": "plan-next", "status": "failed", "message": "缺少 story_blueprint.json", "outputs": {}, "warnings": []},
    )

    monkeypatch.setattr(
        pipeline_runner,
        "load_local_config",
        lambda: {"review_gate": {"enabled": True, "allow_auto_commit": True}},
    )
    report = pipeline_runner.run_single_chapter_pipeline(auto_commit=True)

    assert report["status"] == "failed"
    assert [step["name"] for step in report["steps"]] == ["build-context", "plan-next"]
    assert "plan-next failed" in report["errors"][0]


def test_edit_draft_failure_continues_to_commit_draft(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_state(0)
    patch_success_pipeline(monkeypatch)
    monkeypatch.setattr(
        pipeline_runner.commands,
        "edit_draft_command",
        lambda: {"name": "edit-draft", "status": "failed", "message": "edit boom", "outputs": {}, "warnings": []},
    )

    monkeypatch.setattr(
        pipeline_runner,
        "load_local_config",
        lambda: {"review_gate": {"enabled": True, "allow_auto_commit": True}},
    )
    report = pipeline_runner.run_single_chapter_pipeline(auto_commit=True)

    assert report["status"] == "success_with_warnings"
    assert any("edit-draft 失败" in warning for warning in report["warnings"])
    assert "commit-chapter" in [step["name"] for step in report["steps"]]


def test_sync_failure_becomes_success_with_warnings(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_state(0)
    patch_success_pipeline(monkeypatch)
    monkeypatch.setattr(
        pipeline_runner.commands,
        "sync_obsidian_command",
        lambda: {"name": "sync-obsidian", "status": "failed", "message": "sync boom", "outputs": {}, "warnings": []},
    )

    monkeypatch.setattr(
        pipeline_runner,
        "load_local_config",
        lambda: {"review_gate": {"enabled": True, "allow_auto_commit": True}},
    )
    report = pipeline_runner.run_single_chapter_pipeline(auto_commit=True)

    assert report["status"] == "success_with_warnings"
    assert any("sync-obsidian 失败" in warning for warning in report["warnings"])


def test_save_pipeline_report_generates_json_and_markdown(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.chdir(tmp_path)
    report = {
        "pipeline_version": "1.4",
        "status": "success",
        "chapter_id": 1,
        "steps": [],
        "final_state": {"current_chapter_before": 0, "current_chapter_after": 1},
        "warnings": [],
        "errors": [],
    }

    json_path, markdown_path = pipeline_runner.save_pipeline_report(report)

    assert Path(json_path).exists()
    assert Path(markdown_path).exists()


def test_pipeline_fails_if_chapter_advances_more_than_one(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_state(0)
    patch_success_pipeline(monkeypatch)

    def bad_commit() -> dict[str, Any]:
        write_state(2)
        return {"name": "commit-chapter", "status": "success", "message": "commit ok", "outputs": {}, "warnings": []}

    monkeypatch.setattr(pipeline_runner.commands, "commit_chapter_command", bad_commit)

    monkeypatch.setattr(
        pipeline_runner,
        "load_local_config",
        lambda: {"review_gate": {"enabled": True, "allow_auto_commit": True}},
    )
    report = pipeline_runner.run_single_chapter_pipeline(auto_commit=True)

    assert report["status"] == "failed"
    assert any("current_chapter 推进异常" in error for error in report["errors"])

