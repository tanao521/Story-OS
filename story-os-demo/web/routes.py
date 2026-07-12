from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

import commands
from core.setup_wizard import create_story_project
from system.chapter_archive import ChapterArchiveError, archive_chapter
from system.manual_editor import create_manual_version
from system.llm_health import build_llm_health_report
from system.memory_health import run_memory_health_check
from system.quality_checker import load_quality_report, quality_report_paths, quality_summary_from_report
from system.review_gate import prepare_review_record, save_review_markdown, update_review_status
from system.status_dashboard import build_status_dashboard
from system.story_qa import answer_from_memory, answer_from_state, answer_from_story
from system.text_diff import build_text_diff
from system.todo_manager import create_todo, list_todos, update_todo_status
from system.version_manager import VersionArchiveError, archive_version, list_versions, read_version_payload
from web.schemas import AskRequest, ManualSaveRequest, ProjectCreateRequest, ReviewApproveRequest, TodoCreateRequest, VersionArchiveRequest, VersionSelectRequest
from web.view_models import api_error, api_ok


router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

PROJECT_ASSETS: dict[str, dict[str, str]] = {
    "story_spec": {"label": "项目设定", "path": "data/story_spec.json", "format": "json"},
    "story_blueprint": {"label": "故事蓝图", "path": "data/story_blueprint.json", "format": "json"},
    "characters": {"label": "角色档案", "path": "data/characters.json", "format": "json"},
    "world_bible": {"label": "世界观圣经", "path": "data/world_bible.json", "format": "json"},
    "world_rules": {"label": "世界规则", "path": "data/world_rules.json", "format": "json"},
    "project_md": {"label": "项目说明", "path": "data/project.md", "format": "markdown"},
}


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




@router.get("/api/project-assets")
def api_project_assets() -> JSONResponse:
    def action() -> dict[str, Any]:
        return api_ok(result={"assets": [_read_project_asset(asset_id) for asset_id in PROJECT_ASSETS]})

    return guarded(action)


@router.post("/api/project-assets/{asset_id}")
async def api_save_project_asset(asset_id: str, request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    def action() -> dict[str, Any]:
        if asset_id not in PROJECT_ASSETS:
            return api_error("未知项目档案。", ["unknown project asset"])
        if not isinstance(payload, dict) or not isinstance(payload.get("content"), str):
            return api_error("项目档案内容无效。", ["content must be a string"])
        asset = PROJECT_ASSETS[asset_id]
        path = Path(asset["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        content = payload["content"]
        if asset["format"] == "json":
            try:
                parsed = json.loads(content or "{}")
            except json.JSONDecodeError as exc:
                return api_error("JSON 格式无效，未保存。", [f"line {exc.lineno}, column {exc.colno}: {exc.msg}"])
            path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        else:
            path.write_text(content, encoding="utf-8")
        return api_ok("项目档案已保存。", {"asset": _read_project_asset(asset_id)})

    return guarded(action)

@router.get("/api/writing-constraints")
def api_writing_constraints() -> JSONResponse:
    def action() -> dict[str, Any]:
        story_spec = _load_json_safe(Path("data/story_spec.json"), {})
        constraints = _normalize_writing_constraints(story_spec)
        return api_ok(result=constraints)

    return guarded(action)


@router.post("/api/writing-constraints")
async def api_save_writing_constraints(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    def action() -> dict[str, Any]:
        if not isinstance(payload, dict):
            return api_error("写作约束格式无效。", ["payload must be an object"])
        story_spec_path = Path("data/story_spec.json")
        story_spec = _load_json_safe(story_spec_path, {})
        if not isinstance(story_spec, dict) or not story_spec:
            return api_error("尚未创建小说项目。", ["data/story_spec.json not found"])
        constraints = _normalize_writing_constraints({"writing_constraints": payload, **payload})
        story_spec["writing_constraints"] = constraints
        story_spec["anti_ai_style_rules"] = constraints.get("ai_style_limits", [])
        story_spec_path.write_text(json.dumps(story_spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return api_ok("写作约束已保存。", constraints)

    return guarded(action)

@router.get("/api/llm/health")
def api_llm_health() -> dict[str, Any]:
    return build_llm_health_report()


@router.get("/api/memory-health")
def api_memory_health(full: bool = False) -> JSONResponse:
    def action() -> dict[str, Any]:
        report = run_memory_health_check(data_dir="data", full=full)
        return api_ok(result=report)

    return guarded(action)



@router.post("/api/planning/blueprint")
async def api_generate_blueprint(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    return guarded(lambda: command_response(commands.generate_blueprint_command(force=bool(isinstance(payload, dict) and payload.get("force")))))


@router.post("/api/planning/assets")
async def api_build_assets(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    return guarded(lambda: command_response(commands.build_assets_command(force=bool(isinstance(payload, dict) and payload.get("force")))))


@router.get("/api/planning/next-chapter")
def api_get_next_chapter_plan() -> JSONResponse:
    def action() -> dict[str, Any]:
        path = Path("data/next_chapter_plan.json")
        if not path.exists():
            return api_ok(result={"plan": {}})
        try:
            plan = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return api_error("章节计划 JSON 无法解析。", [str(exc)])
        return api_ok(result={"plan": plan if isinstance(plan, dict) else {}})
    return guarded(action)


@router.post("/api/planning/next-chapter")
async def api_save_or_plan_next_chapter(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict) or not payload:
        return guarded(lambda: command_response(commands.plan_next_command()))
    def action() -> dict[str, Any]:
        path = Path("data/next_chapter_plan.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        Path("data/next_chapter_plan.md").write_text(commands.render_next_chapter_plan_markdown(payload), encoding="utf-8")
        state_path = Path("data/state.json")
        state = _load_json_safe(state_path, {})
        state["current_stage"] = "next_chapter_planned"
        state["next_chapter_plan"] = {"created": True, "chapter_id": payload.get("chapter_id", 1), "path": "data/next_chapter_plan.json"}
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return api_ok("章节规划已保存。", {"plan": payload, "path": "data/next_chapter_plan.json"})
    return guarded(action)


@router.post("/api/run-chapter")
def api_run_chapter() -> JSONResponse:
    return guarded(lambda: command_response(commands.run_chapter_command(auto_commit=False, require_model=True)))



@router.post("/api/chapters/{chapter_number}/archive")
def api_archive_chapter(chapter_number: int) -> JSONResponse:
    def action() -> dict[str, Any]:
        try:
            result = archive_chapter(chapter_number, "data")
        except ChapterArchiveError as exc:
            return api_error("章节归档失败。", [str(exc)])
        return api_ok("章节已归档。", result, result.get("warnings", []))

    return guarded(action)
@router.post("/api/quality-check")
async def api_quality_check(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    def action() -> dict[str, Any]:
        if not isinstance(payload, dict) or not payload.get("source_type") or not payload.get("version"):
            return command_response(commands.quality_check_command())
        source_type = str(payload.get("source_type", ""))
        version = int(payload.get("version", 0) or 0)
        kwargs: dict[str, Any] = {}
        if source_type == "draft":
            kwargs["draft_version"] = version
        elif source_type == "edited":
            kwargs["edited_version"] = version
        elif source_type == "manual":
            kwargs["manual_version"] = version
        else:
            return api_error("\u672a\u77e5\u7248\u672c\u7c7b\u578b\u3002", ["source_type must be draft, edited, or manual"])
        return command_response(commands.quality_check_command(**kwargs))

    return guarded(action)


@router.get("/api/versions")
def api_versions() -> dict[str, Any]:
    warnings: list[str] = []
    errors: list[str] = []
    try:
        result = commands.compare_drafts_command()
        outputs = result.get("outputs", {}) if result.get("status") != "failed" else {}
        warnings.extend(str(item) for item in result.get("warnings", []) or [])
    except (PermissionError, FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        versions = list_versions(current_target_chapter(), "data")
        outputs = {
            "drafts": versions.get("drafts", []),
            "edited": versions.get("edited", []),
            "manual": versions.get("manual", []),
            "committed": commands._scan_committed_chapters(Path("data")),
            "selected": versions.get("selected", {}),
        }
        message = f"Version command skipped unreadable file: {exc}"
        warnings.append(message)
        errors.append(str(exc))
    return {
        "drafts": outputs.get("drafts", []),
        "edited": outputs.get("edited", []),
        "manual": outputs.get("manual", []),
        "committed": outputs.get("committed", []),
        "selected": outputs.get("selected") or None,
        "warnings": warnings,
        "errors": errors,
    }


@router.get("/api/versions/content")
def api_version_content(
    source_type: str = Query(..., pattern="^(draft|edited|manual|committed)$"),
    version: int = Query(..., ge=1),
) -> JSONResponse:
    return guarded(lambda: api_ok(result=build_version_content(source_type, version)))


@router.get("/api/versions/diff")
def api_version_diff(
    left_type: str = Query(..., pattern="^(draft|edited|manual|committed)$"),
    left_version: int = Query(..., ge=1),
    right_type: str = Query(..., pattern="^(draft|edited|manual|committed)$"),
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
    source_type: str = Query(..., pattern="^(draft|edited|manual|committed)$"),
    version: int = Query(..., ge=1),
) -> JSONResponse:
    return guarded(lambda: api_ok(*quality_report_response(source_type, version)))


@router.post("/api/versions/select")
def api_select_version(request: VersionSelectRequest) -> JSONResponse:
    def action() -> dict[str, Any]:
        select_spec = f"{request.source_type}:{request.version}"
        return command_response(commands.compare_drafts_command(select_spec=select_spec))

    return guarded(action)


@router.post("/api/versions/archive")
def api_archive_version(request: VersionArchiveRequest) -> JSONResponse:
    def action() -> dict[str, Any]:
        try:
            result = archive_version(current_target_chapter(), request.source_type, request.version, "data")
        except VersionArchiveError as exc:
            return api_error("版本归档失败。", [str(exc)])
        return api_ok("版本已归档。", result)

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
    return guarded(lambda: approve_review(force=request.force, polish=request.polish))


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


def _load_json_safe(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default
    return value if isinstance(value, dict) else default


def build_version_content(source_type: str, version: int) -> dict[str, Any]:
    if source_type == "committed":
        chapter_path = Path("data") / "chapters" / f"chapter_{version:03d}.md"
        if not chapter_path.exists():
            raise FileNotFoundError(f"committed:{version} not found")
        text = chapter_path.read_text(encoding="utf-8")
        first_line = text.strip().splitlines()[0].strip() if text.strip() else ""
        title = first_line.lstrip("#").strip() if first_line.startswith("#") else ""
        return {
            "chapter_id": version,
            "source_type": "committed",
            "version": version,
            "version_label": f"chapter_{version:03d}",
            "title": title,
            "text": text,
            "word_count": len([char for char in text if not char.isspace()]),
            "json_path": chapter_path.as_posix(),
            "markdown_path": chapter_path.as_posix(),
            "generation": {"mode": "committed", "model": "", "fallback_used": False},
            "quality": {},
        }
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


def approve_review(force: bool = False, polish: bool | None = None) -> dict[str, Any]:
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

    if polish is None:
        return api_response(True, "", {"review": record}, extra={"polish_available": True})

    if polish:
        edit_result = commands.edit_draft_command()
        if edit_result.get("status") != "success":
            return api_response(False, "AI polish failed.", {"review": record})
    commit_result = commands.commit_chapter_command()
    response = command_response(commit_result)
    response["message"] = "审核通过，章节已提交。" if response["ok"] else response["message"]
    if not response["ok"]:
        return response

    archived_versions, archive_warnings = _archive_versions_after_commit(int(target["chapter_id"]))
    response["result"]["archived_versions"] = archived_versions
    response["warnings"].extend(archive_warnings)

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


def _read_project_asset(asset_id: str) -> dict[str, Any]:
    asset = PROJECT_ASSETS[asset_id]
    path = Path(asset["path"])
    content = ""
    exists = path.exists()
    if exists:
        if asset["format"] == "json":
            data = _load_json_safe(path, {})
            content = json.dumps(data, ensure_ascii=False, indent=2) if isinstance(data, (dict, list)) else str(data)
        else:
            content = path.read_text(encoding="utf-8")
    return {
        "id": asset_id,
        "label": asset["label"],
        "path": asset["path"],
        "format": asset["format"],
        "exists": exists,
        "content": content,
    }

def _load_json_safe(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _normalize_writing_constraints(source: dict[str, Any]) -> dict[str, Any]:
    constraints = source.get("writing_constraints", {})
    if not isinstance(constraints, dict):
        constraints = {}
    chapter = constraints.get("chapter_word_count", {})
    if not isinstance(chapter, dict):
        chapter = {}
    min_words = _int_or_default(chapter.get("min") or source.get("chapter_word_min"), 2500)
    max_words = _int_or_default(chapter.get("max") or source.get("chapter_word_max"), 4500)
    if max_words < min_words:
        max_words = min_words
    return {
        "chapter_word_count": {"min": min_words, "max": max_words},
        "pacing": str(constraints.get("pacing") or source.get("pacing") or "").strip(),
        "chapter_structure": str(constraints.get("chapter_structure") or source.get("chapter_structure") or "").strip(),
        "must_follow": _list_from_any(constraints.get("must_follow") or source.get("must_follow") or source.get("focus")),
        "must_avoid": _list_from_any(constraints.get("must_avoid") or source.get("must_avoid") or source.get("avoid")),
        "ai_style_limits": _list_from_any(constraints.get("ai_style_limits") or source.get("ai_style_limits") or source.get("anti_ai_style_rules")),
    }


def _int_or_default(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _list_from_any(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    normalized = str(value).replace("，", ",").replace("\n", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]
