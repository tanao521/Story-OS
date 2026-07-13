from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

import commands
from core.project_context import ProjectContext, bind_project_context, get_project_context
from system.data_store import DataStore
from system.obsidian_sync import load_local_config
from system.review_gate import prepare_review_record

StepFunction = Callable[[], dict[str, Any]]
ProgressCallback = Callable[[dict[str, Any]], None]
CancelCheck = Callable[[], bool]

STEP_LABELS = {
    "build-context": "Build writing context", "plan-next": "Plan next chapter",
    "write-draft": "Write draft", "prepare-review": "Prepare review",
    "edit-draft": "Edit draft", "commit-chapter": "Commit chapter",
    "sync-obsidian": "Sync Obsidian", "index-vault": "Update vector index",
}


def run_single_chapter_pipeline(
    auto_commit: bool = False,
    require_model: bool = False,
    *,
    context: ProjectContext | None = None,
    progress_callback: ProgressCallback | None = None,
    cancellation_token: CancelCheck | None = None,
) -> dict[str, Any]:
    """Run the existing chapter workflow, optionally reporting safe step events."""
    context = context or get_project_context()
    cancelled = cancellation_token or (lambda: False)
    with bind_project_context(context):
        return _run_pipeline(auto_commit, require_model, context, progress_callback, cancelled)


def _run_pipeline(auto_commit: bool, require_model: bool, context: ProjectContext,
                  progress: ProgressCallback | None, cancelled: CancelCheck) -> dict[str, Any]:
    current_before = _read_current_chapter(context, default=0)
    report: dict[str, Any] = {
        "pipeline_version": "1.5", "status": "success", "chapter_id": current_before + 1,
        "steps": [], "final_state": {"current_chapter_before": current_before, "current_chapter_after": current_before},
        "review": {}, "warnings": [], "errors": [],
    }
    write_draft = (lambda: commands.write_draft_command(require_model=True)) if require_model else commands.write_draft_command
    required = [("build-context", commands.build_context_command), ("plan-next", commands.plan_next_command), ("write-draft", write_draft)]
    for name, function in required:
        if _cancelled(report, context, name, progress, cancelled):
            return report
        _emit(progress, name, "running")
        step = _run_step(name, function)
        _append_step(report, step)
        _emit(progress, name, "failed" if step["status"] == "failed" else "completed", step)
        if step["status"] == "failed":
            _fail(report, context, name, step["message"])
            save_pipeline_report(report, context)
            return report
        if _cancelled(report, context, name, progress, cancelled):
            return report

    if _review_gate_enabled():
        if not auto_commit or not _auto_commit_allowed():
            if auto_commit and not _auto_commit_allowed():
                report["warnings"].append("Automatic chapter commit is disabled; draft remains pending review.")
            _emit(progress, "prepare-review", "running")
            _wait_for_review(report, context)
            review_step = {"name": "prepare-review", "status": "success", "message": "Draft is ready for human review.", "outputs": report["review"], "warnings": []}
            _append_step(report, review_step)
            _emit(progress, "prepare-review", "completed", review_step)
            save_pipeline_report(report, context)
            return report

    for name, function, optional in [
        ("edit-draft", commands.edit_draft_command, True),
        ("commit-chapter", commands.commit_chapter_command, False),
        ("sync-obsidian", commands.sync_obsidian_command, True),
        ("index-vault", commands.index_vault_command, True),
    ]:
        if _cancelled(report, context, name, progress, cancelled):
            return report
        _emit(progress, name, "running")
        step = _run_step(name, function)
        _append_step(report, step)
        _emit(progress, name, "failed" if step["status"] == "failed" else "completed", step)
        if step["status"] == "failed" and not optional:
            _fail(report, context, name, step["message"])
            save_pipeline_report(report, context)
            return report
        if step["status"] == "failed":
            report["warnings"].append(f"{name} 失败: {step['message']}")
        if name == "commit-chapter":
            committed_chapter = _read_current_chapter(context, default=current_before)
            report["final_state"]["current_chapter_after"] = committed_chapter
            if committed_chapter != current_before + 1:
                report["status"] = "failed"
                report["errors"].append("current_chapter 推进异常")
                save_pipeline_report(report, context)
                return report

    report["final_state"]["current_chapter_after"] = _read_current_chapter(context, default=current_before)
    report["status"] = "success_with_warnings" if report["warnings"] else "success"
    save_pipeline_report(report, context)
    return report


def save_pipeline_report(report: dict[str, Any], context: ProjectContext | None = None) -> tuple[str, str]:
    context = context or get_project_context()
    run_id = str(report.get("run_id") or datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    report["run_id"] = run_id
    chapter_id = int(report.get("chapter_id", 1) or 1)
    stem = f"run_chapter_{chapter_id:03d}_{_safe_filename_part(run_id)}"
    json_path = context.pipeline_runs_dir / f"{stem}.json"
    markdown_path = context.pipeline_runs_dir / f"{stem}.md"
    report["report_paths"] = {"json_path": context.relative_path(json_path), "markdown_path": context.relative_path(markdown_path)}
    store = DataStore(context)
    store.write_json(json_path, report, backup=False)
    store.write_markdown(markdown_path, render_pipeline_report_markdown(report), backup=False)
    return json_path.as_posix(), markdown_path.as_posix()


def render_pipeline_report_markdown(report: dict[str, Any]) -> str:
    rows = "\n".join(f"| {item.get('name', '')} | {item.get('status', '')} | {item.get('message', '')} |" for item in report.get("steps", []))
    return f"""# Chapter pipeline report: {report.get('chapter_id', '')}

- status: {report.get('status', '')}
- chapter_id: {report.get('chapter_id', '')}

| step | status | message |
|---|---|---|
{rows}

## Warnings
{_render_list(report.get('warnings', []))}

## Errors
{_render_list(report.get('errors', []))}
"""


def _cancelled(report: dict[str, Any], context: ProjectContext, name: str,
               progress: ProgressCallback | None, cancelled: CancelCheck) -> bool:
    if not cancelled():
        return False
    step = {"name": name, "status": "cancelled", "message": "Cancelled at a safe point.", "outputs": {}, "warnings": []}
    _append_step(report, step)
    _emit(progress, name, "cancelled", step)
    report["status"] = "cancelled"
    report["final_state"]["current_chapter_after"] = _read_current_chapter(context, default=report["final_state"]["current_chapter_before"])
    save_pipeline_report(report, context)
    return True


def _wait_for_review(report: dict[str, Any], context: ProjectContext) -> None:
    prepared = prepare_review_record(str(context.data_dir))
    record = prepared["record"]
    report["status"] = "waiting_for_review"
    report["review"] = {"status": record.get("status", "pending"), "path": prepared["json_path"], "markdown_path": prepared["markdown_path"], "chapter_id": record.get("chapter_id", report.get("chapter_id"))}
    report["final_state"]["current_chapter_after"] = _read_current_chapter(context, default=report["final_state"]["current_chapter_before"])
    state = DataStore(context).read_json(context.data_dir / "state.json", default={}, expected_type=dict)
    if state:
        state["current_stage"] = "waiting_for_review"
        state["review"] = {"chapter_id": report["review"].get("chapter_id"), "status": "pending", "path": report["review"].get("path", "")}
        DataStore(context).write_json(context.data_dir / "state.json", state, backup=True)


def _review_gate_enabled() -> bool:
    value = load_local_config().get("review_gate", {})
    return bool(value.get("enabled", True)) if isinstance(value, dict) else True


def _auto_commit_allowed() -> bool:
    value = load_local_config().get("review_gate", {})
    return bool(value.get("allow_auto_commit", False)) if isinstance(value, dict) else False


def _run_step(name: str, function: StepFunction) -> dict[str, Any]:
    try:
        result = function()
    except Exception as exc:
        return {"name": name, "status": "failed", "message": _error_summary(exc), "outputs": {}, "warnings": []}
    status = "failed" if result.get("status") == "failed" else "success"
    return {"name": result.get("name", name), "status": status, "message": result.get("message", ""), "outputs": result.get("outputs", {}), "warnings": result.get("warnings", [])}


def _append_step(report: dict[str, Any], step: dict[str, Any]) -> None:
    report["steps"].append(step)
    report["warnings"].extend(str(item) for item in step.get("warnings", []) if item)


def _emit(callback: ProgressCallback | None, name: str, status: str, step: dict[str, Any] | None = None) -> None:
    if callback is None:
        return
    event = {"event": "step", "name": name, "label": STEP_LABELS.get(name, name), "status": status}
    if step:
        event.update({key: step.get(key) for key in ("message", "outputs", "warnings")})
    callback(event)


def _fail(report: dict[str, Any], context: ProjectContext, name: str, message: str) -> None:
    report["status"] = "failed"
    report["errors"].append(f"{name} failed: {message}")
    report["final_state"]["current_chapter_after"] = _read_current_chapter(context, default=report["final_state"]["current_chapter_before"])


def _read_current_chapter(context: ProjectContext, default: int = 0) -> int:
    state = DataStore(context).read_json(context.data_dir / "state.json", default={}, expected_type=dict)
    try:
        return int(state.get("current_chapter", default) or default)
    except (AttributeError, TypeError, ValueError):
        return default


def _safe_filename_part(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value) or "run"


def _render_list(items: Any) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- none"


def _error_summary(error: Exception) -> str:
    return (str(error).strip() or error.__class__.__name__)[:300]
