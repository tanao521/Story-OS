from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import commands
from system.obsidian_sync import load_local_config
from system.review_gate import prepare_review_record


StepFunction = Callable[[], dict[str, Any]]


def run_single_chapter_pipeline(auto_commit: bool = False, require_model: bool = False) -> dict[str, Any]:
    current_chapter_before = _read_current_chapter(default=0)
    chapter_id = current_chapter_before + 1
    report: dict[str, Any] = {
        "pipeline_version": "1.4",
        "status": "success",
        "chapter_id": chapter_id,
        "steps": [],
        "final_state": {
            "current_chapter_before": current_chapter_before,
            "current_chapter_after": current_chapter_before,
        },
        "review": {},
        "warnings": [],
        "errors": [],
    }

    write_draft_step: StepFunction = (
        (lambda: commands.write_draft_command(require_model=True))
        if require_model
        else commands.write_draft_command
    )
    required_steps: list[tuple[str, StepFunction]] = [
        ("build-context", commands.build_context_command),
        ("plan-next", commands.plan_next_command),
        ("write-draft", write_draft_step),
    ]
    for name, function in required_steps:
        step = _run_step(name, function)
        _append_step(report, step)
        if step["status"] == "failed":
            _fail(report, name, step["message"])
            save_pipeline_report(report)
            return report

    if _review_gate_enabled():
        if not auto_commit:
            _wait_for_review(report)
            save_pipeline_report(report)
            return report
        if not _auto_commit_allowed():
            report["warnings"].append(
                "当前配置禁止自动提交。请先在配置中设置 review_gate.allow_auto_commit=true。"
            )
            _wait_for_review(report)
            save_pipeline_report(report)
            return report

    edit_step = _run_step("edit-draft", commands.edit_draft_command)
    _append_step(report, edit_step)
    if edit_step["status"] == "failed":
        warning = "edit-draft (AI润色) 失败，将使用原始草稿提交。"
        report["warnings"].append(f"{warning} {edit_step['message']}".strip())

    commit_step = _run_step("commit-chapter", commands.commit_chapter_command)
    _append_step(report, commit_step)
    if commit_step["status"] == "failed":
        _fail(report, "commit-chapter", commit_step["message"])
        save_pipeline_report(report)
        return report

    current_chapter_after_commit = _read_current_chapter(default=current_chapter_before)
    report["final_state"]["current_chapter_after"] = current_chapter_after_commit
    if current_chapter_after_commit != current_chapter_before + 1:
        report["errors"].append("current_chapter 推进异常。")
        report["status"] = "failed"
        save_pipeline_report(report)
        return report

    optional_steps: list[tuple[str, StepFunction]] = [
        ("sync-obsidian", commands.sync_obsidian_command),
        ("index-vault", commands.index_vault_command),
    ]
    for name, function in optional_steps:
        step = _run_step(name, function)
        _append_step(report, step)
        if step["status"] == "failed":
            report["warnings"].append(f"{name} 失败：{step['message']}")

    if report["warnings"] and not report["errors"]:
        report["status"] = "success_with_warnings"
    elif report["errors"]:
        report["status"] = "failed"
    else:
        report["status"] = "success"

    save_pipeline_report(report)
    return report


def save_pipeline_report(report: dict[str, Any]) -> tuple[str, str]:
    chapter_id = int(report.get("chapter_id", 1) or 1)
    directory = Path("data/pipeline_runs")
    directory.mkdir(parents=True, exist_ok=True)
    run_id = str(report.get("run_id") or datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    report["run_id"] = run_id
    stem = f"run_chapter_{chapter_id:03d}_{_safe_filename_part(run_id)}"
    json_path = directory / f"{stem}.json"
    markdown_path = directory / f"{stem}.md"
    report["report_paths"] = {
        "json_path": json_path.as_posix(),
        "markdown_path": markdown_path.as_posix(),
    }
    _write_text_atomic(json_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    _write_text_atomic(markdown_path, render_pipeline_report_markdown(report))
    return json_path.as_posix(), markdown_path.as_posix()


def _safe_filename_part(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)
    return cleaned or datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _write_text_atomic(path: Path, content: str) -> None:
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(path)


def render_pipeline_report_markdown(report: dict[str, Any]) -> str:
    final_state = report.get("final_state", {})
    review = report.get("review", {})
    steps = report.get("steps", [])
    step_rows = "\n".join(
        f"| {step.get('name', '')} | {step.get('status', '')} | {step.get('message', '')} |"
        for step in steps
    )
    return f"""# 单章流水线报告：第{report.get("chapter_id", "")}章

## 状态

- pipeline version: {report.get("pipeline_version", "")}
- status: {report.get("status", "")}
- chapter_id: {report.get("chapter_id", "")}
- current_chapter_before: {final_state.get("current_chapter_before", "")}
- current_chapter_after: {final_state.get("current_chapter_after", "")}

## 审核

- status: {review.get("status", "")}
- path: {review.get("path", "")}

## 步骤

| 步骤 | 状态 | 信息 |
|---|---|---|
{step_rows}

## Warnings

{_render_list(report.get("warnings", []))}

## Errors

{_render_list(report.get("errors", []))}
"""


def _wait_for_review(report: dict[str, Any]) -> None:
    prepared = prepare_review_record("data")
    record = prepared["record"]
    report["status"] = "waiting_for_review"
    report["review"] = {
        "status": record.get("status", "pending"),
        "path": prepared["json_path"],
        "markdown_path": prepared["markdown_path"],
        "chapter_id": record.get("chapter_id", report.get("chapter_id")),
    }
    report["final_state"]["current_chapter_after"] = _read_current_chapter(
        default=report["final_state"]["current_chapter_before"]
    )
    _update_state_waiting_for_review(report)


def _update_state_waiting_for_review(report: dict[str, Any]) -> None:
    state_path = Path("data/state.json")
    if not state_path.exists():
        return
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["current_stage"] = "waiting_for_review"
    state["review"] = {
        "chapter_id": report["review"].get("chapter_id", report.get("chapter_id")),
        "status": "pending",
        "path": report["review"].get("path", ""),
    }
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _review_gate_enabled() -> bool:
    review_gate = load_local_config().get("review_gate", {})
    if not isinstance(review_gate, dict):
        return True
    return bool(review_gate.get("enabled", True))


def _auto_commit_allowed() -> bool:
    review_gate = load_local_config().get("review_gate", {})
    if not isinstance(review_gate, dict):
        return False
    return bool(review_gate.get("allow_auto_commit", False))


def _run_step(name: str, function: StepFunction) -> dict[str, Any]:
    try:
        result = function()
    except Exception as exc:
        return {
            "name": name,
            "status": "failed",
            "message": _error_summary(exc),
            "outputs": {},
            "warnings": [],
        }
    return {
        "name": result.get("name", name),
        "status": result.get("status", "success"),
        "message": result.get("message", ""),
        "outputs": result.get("outputs", {}),
        "warnings": result.get("warnings", []),
    }


def _append_step(report: dict[str, Any], step: dict[str, Any]) -> None:
    report["steps"].append(step)
    warnings = step.get("warnings", [])
    if isinstance(warnings, list):
        report["warnings"].extend(str(item) for item in warnings)


def _fail(report: dict[str, Any], step_name: str, message: str) -> None:
    report["status"] = "failed"
    report["errors"].append(f"{step_name} failed: {message}")
    report["final_state"]["current_chapter_after"] = _read_current_chapter(
        default=report["final_state"]["current_chapter_before"]
    )


def _read_current_chapter(default: int = 0) -> int:
    state_path = Path("data/state.json")
    if not state_path.exists():
        return default
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default
    return int(state.get("current_chapter", default) or default)


def _render_list(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return "无"
    return "\n".join(f"- {item}" for item in items)


def _error_summary(error: Exception) -> str:
    message = str(error).strip()
    return message[:300] if message else error.__class__.__name__
