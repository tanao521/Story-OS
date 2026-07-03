from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from system import pipeline_runner


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


def patch_pre_review_success(monkeypatch: Any) -> None:
    monkeypatch.setattr(pipeline_runner.commands, "build_context_command", make_success_step("build-context"))
    monkeypatch.setattr(pipeline_runner.commands, "plan_next_command", make_success_step("plan-next"))
    monkeypatch.setattr(pipeline_runner.commands, "write_draft_command", make_success_step("write-draft"))
    monkeypatch.setattr(pipeline_runner.commands, "edit_draft_command", make_success_step("edit-draft"))


def patch_review_record(monkeypatch: Any) -> None:
    def fake_prepare(data_dir: str = "data") -> dict[str, Any]:
        review_dir = Path(data_dir) / "reviews"
        review_dir.mkdir(parents=True, exist_ok=True)
        review_path = review_dir / "chapter_001_review.json"
        review_path.write_text('{"status": "pending"}', encoding="utf-8")
        return {
            "record": {"chapter_id": 1, "status": "pending"},
            "target": {"chapter_id": 1},
            "json_path": review_path.as_posix(),
            "markdown_path": (review_dir / "chapter_001_review.md").as_posix(),
        }

    monkeypatch.setattr(pipeline_runner, "prepare_review_record", fake_prepare)


def patch_commit_success(monkeypatch: Any, chapter_after: int = 1) -> None:
    def commit() -> dict[str, Any]:
        write_state(chapter_after)
        return {"name": "commit-chapter", "status": "success", "message": "commit ok", "outputs": {}, "warnings": []}

    monkeypatch.setattr(pipeline_runner.commands, "commit_chapter_command", commit)
    monkeypatch.setattr(pipeline_runner.commands, "sync_obsidian_command", make_success_step("sync-obsidian"))
    monkeypatch.setattr(pipeline_runner.commands, "index_vault_command", make_success_step("index-vault"))


def test_run_chapter_default_does_not_commit(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_state(0)
    patch_pre_review_success(monkeypatch)
    patch_review_record(monkeypatch)

    called = {"commit": False}

    def commit() -> dict[str, Any]:
        called["commit"] = True
        return {"name": "commit-chapter", "status": "success", "message": "", "outputs": {}, "warnings": []}

    monkeypatch.setattr(pipeline_runner.commands, "commit_chapter_command", commit)

    report = pipeline_runner.run_single_chapter_pipeline(auto_commit=False)

    assert report["status"] == "waiting_for_review"
    assert called["commit"] is False
    assert report["final_state"]["current_chapter_after"] == 0
    assert Path(report["review"]["path"]).exists()


def test_auto_commit_true_but_config_disallows_still_waits(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_state(0)
    patch_pre_review_success(monkeypatch)
    patch_review_record(monkeypatch)
    monkeypatch.setattr(
        pipeline_runner,
        "load_local_config",
        lambda: {"review_gate": {"enabled": True, "allow_auto_commit": False}},
    )

    report = pipeline_runner.run_single_chapter_pipeline(auto_commit=True)

    assert report["status"] == "waiting_for_review"
    assert report["final_state"]["current_chapter_after"] == 0


def test_auto_commit_true_and_config_allows_commit(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_state(0)
    patch_pre_review_success(monkeypatch)
    patch_review_record(monkeypatch)
    patch_commit_success(monkeypatch, chapter_after=1)
    monkeypatch.setattr(
        pipeline_runner,
        "load_local_config",
        lambda: {"review_gate": {"enabled": True, "allow_auto_commit": True}},
    )

    report = pipeline_runner.run_single_chapter_pipeline(auto_commit=True)

    assert report["status"] == "success"
    assert report["final_state"]["current_chapter_after"] == 1
    assert [step["name"] for step in report["steps"]][-1] == "index-vault"


def test_auto_commit_cannot_advance_more_than_one(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_state(0)
    patch_pre_review_success(monkeypatch)
    patch_review_record(monkeypatch)
    patch_commit_success(monkeypatch, chapter_after=2)
    monkeypatch.setattr(
        pipeline_runner,
        "load_local_config",
        lambda: {"review_gate": {"enabled": True, "allow_auto_commit": True}},
    )

    report = pipeline_runner.run_single_chapter_pipeline(auto_commit=True)

    assert report["status"] == "failed"
    assert any("current_chapter 推进异常" in error for error in report["errors"])
