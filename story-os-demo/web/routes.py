from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

import commands
from core.setup_wizard import create_story_project
from system.manual_editor import create_manual_version
from system.memory_health import run_memory_health_check
from system.quality_checker import load_quality_report, quality_report_paths, quality_summary_from_report
from system.review_gate import prepare_review_record, save_review_markdown, update_review_status
from system.status_dashboard import build_status_dashboard
from system.story_qa import answer_from_memory, answer_from_state, answer_from_story
from system.text_diff import build_text_diff
from system.todo_manager import create_todo, list_todos, update_todo_status
from system.version_manager import list_versions, read_version_payload
from web.schemas import AskRequest, ManualSaveRequest, ProjectCreateRequest, ReviewApproveRequest, TodoCreateRequest, VersionSelectRequest
from web.view_models import api_error, api_ok


router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


def api_response(
    ok: bool = True,
    message: str = "",
    result: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": ok,
        "message": message,
        "result": result or {},
        "warnings": warnings or [],
        "errors": errors or [],
    }
    if extra:
        payload.update(extra)
    return payload


def command_response(result: dict[str, Any]) -> dict[str, Any]:
    ok = result.get("status") != "failed"
    return api_response(
        ok=ok,
        message=str(result.get("message", "")),
        result=dict(result.get("outputs", {}) or {}),
        warnings=list(result.get("warnings", []) or []),
        errors=[] if ok else [str(result.get("message", "操作失败"))],
    )


def guarded(action: Callable[[], dict[str, Any]]) -> JSONResponse:
    try:
        payload = action()
    except Exception as exc:
        payload = api_error("操作失败", [str(exc)])
    return JSONResponse(payload)


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")


@router.get("/api/project/init-state")
def api_project_init_state() -> dict[str, Any]:
    story_spec_path = Path("data/story_spec.json")
    missing_files = []
    for item in ["data/story_spec.json", "data/state.json"]:
        if not Path(item).exists():
            missing_files.append(item)
    initialized = story_spec_path.exists()
    return api_ok(result={
        "initialized": initialized,
        "missing_files": [] if initialized else missing_files,
        "next_action": "open_dashboard" if initialized else "create_story",
    })


@router.post("/api/project/create")
def api_project_create(request: ProjectCreateRequest) -> JSONResponse:
    def action() -> dict[str, Any]:
        if not request.title.strip():
            return api_error("小说标题不能为空。", ["title is required"])
        result = create_story_project(request.model_dump(), "data")
        return api_ok("小说项目已创建。", result)

    return guarded(action)


@router.get("/api/status")
def api_status() -> dict[str, Any]:
    return build_status_dashboard(full=True)


@router.get("/api/memory-health")
def api_memory_health(full: bool = False) -> JSONResponse:
    def action() -> dict[str, Any]:
        report = run_memory_health_check(data_dir="data", full=full)
        return api_ok(result=report)

    return guarded(action)


@router.post("/api/run-chapter")
def api_run_chapter() -> JSONResponse:
    return guarded(lambda: command_response(commands.run_chapter_command(auto_commit=False)))


@router.post("/api/quality-check")
def api_quality_check() -> JSONResponse:
    return guarded(lambda: command_response(commands.quality_check_command()))


@router.get("/api/versions")
def api_versions() -> dict[str, Any]:
    result = commands.compare_drafts_command()
    outputs = result.get("outputs", {}) if result.get("status") != "failed" else {}
    return {
        "drafts": outputs.get("drafts", []),
        "edited": outputs.get("edited", []),
        "manual": outputs.get("manual", []),
        "selected": outputs.get("selected") or None,
    }


@router.get("/api/versions/content")
def api_version_content(
    source_type: str = Query(..., pattern="^(draft|edited|manual)$"),
    version: int = Query(..., ge=1),
) -> JSONResponse:
    return guarded(lambda: api_ok(result=build_version_content(source_type, version)))


@router.get("/api/versions/diff")
def api_version_diff(
    left_type: str = Query(..., pattern="^(draft|edited|manual)$"),
    left_version: int = Query(..., ge=1),
    right_type: str = Query(..., pattern="^(draft|edited|manual)$"),
    right_version: int = Query(..., ge=1),
) -> JSONResponse:
    def action() -> dict[str, Any]:
        left = build_version_content(left_type, left_version)
        right = build_version_content(right_type, right_version)
        diff = build_text_diff(left["text"], right["text"])
        return api_ok(result={
            "chapter_id": left["chapter_id"],
            "left": {"source_type": left_type, "version": left_version, "label": left["version_label"]},
            "right": {"source_type": right_type, "version": right_version, "label": right["version_label"]},
            **diff,
        })

    return guarded(action)


@router.get("/api/quality-report")
def api_quality_report(
    source_type: str = Query(..., pattern="^(draft|edited|manual)$"),
    version: int = Query(..., ge=1),
) -> JSONResponse:
    return guarded(lambda: api_ok(*quality_report_response(source_type, version)))


@router.post("/api/versions/select")
def api_select_version(request: VersionSelectRequest) -> JSONResponse:
    def action() -> dict[str, Any]:
        select_spec = f"{request.source_type}:{request.version}"
        return command_response(commands.compare_drafts_command(select_spec=select_spec))

    return guarded(action)


@router.post("/api/manual/save")
def api_manual_save(request: ManualSaveRequest) -> JSONResponse:
    def action() -> dict[str, Any]:
        try:
            result = create_manual_version(
                request.chapter_id,
                request.source_type,
                request.source_version,
                request.text,
                "data",
            )
        except ValueError as exc:
            return api_error("正文无效，未保存。", [part.strip() for part in str(exc).split(";") if part.strip()])
        payload = {
            "chapter_id": result["chapter_id"],
            "source_type": "manual",
            "version": result["version"],
            "version_label": result["version_label"],
            "json_path": result["json_path"],
            "markdown_path": result["markdown_path"],
            "selected": True,
        }
        return api_ok("人工修改版已保存。", payload)

    return guarded(action)


@router.post("/api/review/approve")
def api_review_approve(request: ReviewApproveRequest) -> JSONResponse:
    return guarded(lambda: approve_review(force=request.force))


@router.post("/api/review/reject")
def api_review_reject() -> JSONResponse:
    return guarded(lambda: update_review("rejected", "reject", "当前版本已拒绝，章节未提交。"))


@router.post("/api/review/later")
def api_review_later() -> JSONResponse:
    return guarded(lambda: update_review("pending", "later", "已保留为稍后审核。"))


@router.get("/api/todos")
def api_todos() -> list[dict[str, Any]]:
    return list_todos(status="open")


@router.post("/api/todos")
def api_create_todo(request: TodoCreateRequest) -> JSONResponse:
    def action() -> dict[str, Any]:
        item = create_todo(
            request.title,
            todo_type=request.type,
            priority=request.priority,
            chapter_id=request.chapter_id,
        )
        return api_ok("Todo 已添加。", {"todo": item})

    return guarded(action)


@router.post("/api/todos/{todo_id}/done")
def api_todo_done(todo_id: int) -> JSONResponse:
    return guarded(lambda: todo_status_response(todo_id, "done", "Todo 已完成。"))


@router.post("/api/todos/{todo_id}/reopen")
def api_todo_reopen(todo_id: int) -> JSONResponse:
    return guarded(lambda: todo_status_response(todo_id, "open", "Todo 已重新打开。"))


@router.post("/api/todos/{todo_id}/cancel")
def api_todo_cancel(todo_id: int) -> JSONResponse:
    return guarded(lambda: todo_status_response(todo_id, "cancelled", "Todo 已取消。"))


@router.post("/api/ask")
def api_ask(request: AskRequest) -> JSONResponse:
    def action() -> dict[str, Any]:
        if request.mode == "state":
            result = answer_from_state(request.question)
        elif request.mode == "memory":
            result = answer_from_memory(request.question, use_vector=request.use_vector)
        else:
            result = answer_from_story(
                request.question,
                use_llm=request.use_llm,
                use_vector=request.use_vector,
            )
        return api_ok("问答完成。", {"qa": result}, list(result.get("warnings", []) or []))

    return guarded(action)


@router.post("/api/sync-obsidian")
def api_sync_obsidian() -> JSONResponse:
    return guarded(lambda: command_response(commands.sync_obsidian_command()))


@router.post("/api/index-vault")
def api_index_vault() -> JSONResponse:
    return guarded(lambda: command_response(commands.index_vault_command()))


def build_version_content(source_type: str, version: int) -> dict[str, Any]:
    chapter_id = current_target_chapter()
    versions = list_versions(chapter_id, "data")
    match = find_version_info(versions, source_type, version)
    if not match:
        raise FileNotFoundError(f"{source_type}:{version} 不存在")
    payload = read_version_payload(match)
    field = "draft_text" if source_type == "draft" else ("manual_text" if source_type == "manual" else "edited_text")
    text = str(payload.get(field) or payload.get("text", ""))
    process = payload.get("generation", {}) if source_type == "draft" else payload.get("editing", {})
    if not isinstance(process, dict):
        process = {}
    quality = quality_summary(chapter_id, source_type, version)
    return {
        "chapter_id": chapter_id,
        "source_type": source_type,
        "version": version,
        "version_label": str(match.get("version_label", f"{source_type}_v{version:03d}")),
        "title": str(payload.get("chapter_title", "")),
        "text": text,
        "word_count": int(payload.get("actual_word_count", len(text)) or len(text)),
        "json_path": str(match.get("json_path", "")),
        "markdown_path": str(match.get("markdown_path", "")),
        "generation": {
            "mode": str(process.get("mode", "")),
            "model": str(process.get("model", "")),
            "fallback_used": bool(process.get("fallback_used", False)),
        },
        "quality": quality,
    }


def quality_report_response(source_type: str, version: int) -> tuple[str, dict[str, Any], list[str] | None]:
    chapter_id = current_target_chapter()
    report = load_quality_report(chapter_id, source_type, version, "data")
    json_path, markdown_path = quality_report_paths(chapter_id, source_type, version, "data")
    if not report:
        return "当前版本尚未生成质量报告。", {"exists": False}, None
    result = {
        "exists": True,
        "overall_score": report.get("overall_score", 0),
        "scores": report.get("scores", {}),
        "flags": report.get("flags", []),
        "suggestions": report.get("suggestions", []),
        "reader_simulation": report.get("reader_simulation", {}),
        "checks": report.get("checks", {}),
        "json_path": json_path.as_posix(),
        "markdown_path": markdown_path.as_posix(),
    }
    return "", result, None


def quality_summary(chapter_id: int, source_type: str, version: int) -> dict[str, Any]:
    report = load_quality_report(chapter_id, source_type, version, "data")
    json_path, markdown_path = quality_report_paths(chapter_id, source_type, version, "data")
    if not report:
        return {
            "exists": False,
            "score": None,
            "risk_level": "unknown",
            "report_path": "",
            "flags": [],
            "suggestions": [],
        }
    score = report.get("overall_score")
    return {
        "exists": True,
        "score": score,
        "risk_level": risk_level(score),
        "report_path": markdown_path.as_posix(),
        "json_path": json_path.as_posix(),
        "flags": report.get("flags", []),
        "suggestions": report.get("suggestions", []),
        "summary": quality_summary_from_report(report),
    }


def current_target_chapter() -> int:
    plan_path = Path("data/next_chapter_plan.json")
    if plan_path.exists():
        try:
            return int(json.loads(plan_path.read_text(encoding="utf-8")).get("chapter_id", 1) or 1)
        except json.JSONDecodeError:
            return 1
    state_path = Path("data/state.json")
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            return int(state.get("current_chapter", 0) or 0) + 1
        except json.JSONDecodeError:
            return 1
    return 1


def find_version_info(versions: dict[str, Any], source_type: str, version: int) -> dict[str, Any]:
    key = "drafts" if source_type == "draft" else source_type
    for item in versions.get(key, []):
        if int(item.get("version", 0) or 0) == version and Path(str(item.get("json_path", ""))).exists():
            return item
    return {}


def risk_level(score: Any) -> str:
    if score is None:
        return "unknown"
    value = float(score)
    if value >= 0.8:
        return "low"
    if value >= 0.65:
        return "medium"
    return "high"


def approve_review(force: bool = False) -> dict[str, Any]:
    prepared = prepare_review_record("data")
    target = prepared["target"]
    quality_summary_data = commands.quality_summary_for_target(target)
    score = float(quality_summary_data.get("overall_score", 1.0) or 1.0) if quality_summary_data else 1.0
    if score < 0.65 and not force:
        return api_response(
            False,
            "当前版本质量评分较低，是否仍然提交？",
            {"quality": quality_summary_data},
            extra={"need_confirm": True},
        )

    record = update_review_status(int(target["chapter_id"]), "approved", decision="approve")
    save_review_markdown(record, target, "data")
    commit_result = commands.commit_chapter_command()
    response = command_response(commit_result)
    response["message"] = "审核通过，章节已提交。" if response["ok"] else response["message"]
    if not response["ok"]:
        return response

    for followup in [commands.sync_obsidian_command, commands.index_vault_command]:
        followup_result = followup()
        if followup_result.get("status") == "failed":
            response["warnings"].append(str(followup_result.get("message", "")))
    return response


def update_review(status: str, decision: str, message: str) -> dict[str, Any]:
    prepared = prepare_review_record("data")
    target = prepared["target"]
    record = update_review_status(int(target["chapter_id"]), status, decision=decision)
    save_review_markdown(record, target, "data")
    return api_ok(message, {"review": record})


def todo_status_response(todo_id: int, status: str, message: str) -> dict[str, Any]:
    item = update_todo_status(todo_id, status)
    return api_ok(message, {"todo": item})
