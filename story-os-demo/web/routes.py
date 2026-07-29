from __future__ import annotations

import json
import inspect
import re
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates

import commands
from core.setup_wizard import create_story_project
from core.project_context import get_project_context
from core.errors import StoryOSError, public_error
from system.narrative_memory_service import EventNotFound, NarrativeMemoryService, NarrativeMemoryError
from system.project_manager import get_project_manager, ProjectManagerError
from system.job_manager import get_job_manager, JobError, JobNotFoundError, JobStateError
from system.planning_service import load_planning, overview as planning_overview, list_entities as planning_list, create_entity as planning_create, update_entity as planning_update, delete_entity as planning_delete, sync_next_plan
from system.revision_service import RevisionService, RevisionError

from system.chapter_archive import ChapterArchiveError, archive_chapter
from system.data_store import DataStore, DataWriteError
from system.planning_mutation_service import PlanningMutationService
from system.continuity_checker import (
    check_chapter_continuity,
    continuity_content_hash,
    load_continuity_report,
    save_continuity_report,
)
from system.manual_editor import create_manual_version
from system.llm_health import build_llm_health_report
from system.memory_health import run_memory_health_check
from system.obsidian_sync import load_local_config, save_local_config
from system.quality_checker import load_quality_report, quality_report_paths, quality_summary_from_report
from system.review_gate import prepare_review_record, save_review_markdown, update_review_status
from system.status_dashboard import build_status_dashboard
from system.story_qa import answer_from_memory, answer_from_state, answer_from_story
from system.text_diff import build_text_diff
from system.todo_manager import create_todo, list_todos, update_todo_status
from system.version_manager import VersionArchiveError, archive_version, list_versions, read_version_payload
from evaluation_engine import EvaluationError, EvaluationService
from evaluation_engine.improvement_policy import ImprovementPolicyError
from evaluation_engine.improvement_service import ImprovementService
from evaluation_engine.candidate_adoption_service import CandidateAdoptionError, CandidateAdoptionService
from evaluation_engine.candidate_partial_adoption_service import PartialAdoptionError, CandidatePartialAdoptionService
from evaluation_engine.planning_evaluation import PlanningEvaluationError, PlanningEvaluationService
from evaluation_engine.planning_comparison import PlanningComparisonError, PlanningEvaluationComparisonService
from evaluation_engine.production_service import EvaluationProductionError, EvaluationProductionService
from evaluation_engine.legacy_adapter import LegacyEvaluationAdapter
from llm.model_gateway import ModelGateway, get_model_gateway
from llm.model_models import ModelGatewayError
from llm.prompt_registry import PromptRegistry
from system.backup_service import BackupService
from system.diagnostics_service import DiagnosticsService
from system.health_checker import HealthChecker
from system.app_logging import recent_logs
from agents.registry import AgentRegistry
from agents.workflow import WorkflowEngine
from agents.executor import AgentExecutor
from agents.memory_scope import scoped_context
from system.context_assembly_service import ContextAssemblyService
from web.schemas import AskRequest, ManualSaveRequest, ProjectCreateRequest, ReviewApproveRequest, TodoCreateRequest, VersionArchiveRequest, VersionSelectRequest
from web.view_models import api_error, api_ok
from web.api_registry import compatibility_headers
from web.api_support import ApiRequestError, parse_pagination


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
    if not ok:
        payload["error"] = {"code": (errors or ["SYS_ERROR"])[0], "message": message or "The operation failed.", "details": {}, "recoverable": True, "suggestions": []}
    return payload


def command_response(result: dict[str, Any]) -> dict[str, Any]:
    ok = result.get("status") != "failed"
    error_code = str(result.get("code") or result.get("message", "操作失败"))
    return api_response(
        ok=ok,
        message=str(result.get("message", "")),
        result=dict(result.get("outputs", {}) or {}),
        warnings=list(result.get("warnings", []) or []),
        errors=[] if ok else [error_code],
    )


def guarded(action: Callable[[], dict[str, Any]]) -> JSONResponse:
    try:
        payload = action()
    except Exception as exc:
        payload = api_error("操作失败", [str(exc)])
    return JSONResponse(payload)


def compatibility_response(payload: dict[str, Any], legacy_path: str, *, status_code: int = 200) -> JSONResponse:
    """Mark a legacy route without altering its established JSON fields."""
    return JSONResponse(payload, status_code=status_code, headers=compatibility_headers(legacy_path))


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")


@router.get("/api/project/init-state")
def api_project_init_state() -> dict[str, Any]:
    context = get_project_context()
    story_spec_path = Path(context.data_dir / "story_spec.json")
    missing_files = []
    for item in ["story_spec.json", "state.json"]:
        if not Path(context.data_dir / item).exists():
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
        planning_config = load_local_config()
        planning_config["use_deepseek_for_planning"] = bool(request.use_deepseek)
        save_local_config(planning_config)
        planning = commands.initialize_planning_command(use_deepseek=request.use_deepseek)
        if (planning.get("status") == "failed"):
            return api_error(
                "项目已创建，但规划层初始化失败。",
                [str(planning.get("message", "planning initialization failed"))],
            )
        return api_ok(
            "小说项目已创建，故事蓝图、角色档案和世界观设定已生成。",
            {**result, "planning": planning.get("outputs", {})},
            warnings=list(planning.get("warnings", [])),
        )

    return guarded(action)


@router.get("/api/status")
def api_status() -> dict[str, Any]:
    # Keep test/downgrade compatibility with legacy one-argument dashboard shims.
    if "data_dir" not in inspect.signature(build_status_dashboard).parameters:
        return build_status_dashboard(full=True)
    return build_status_dashboard(data_dir=get_project_context().data_dir, full=True)




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
        context = get_project_context()
        path = context.root / asset["path"]
        content = payload["content"]
        if asset["format"] == "json":
            try:
                parsed = json.loads(content or "{}")
            except json.JSONDecodeError as exc:
                return api_error("JSON 格式无效，未保存。", [f"line {exc.lineno}, column {exc.colno}: {exc.msg}"])
            DataStore(context).write_json(path, parsed)
        else:
            DataStore(context).write_markdown(path, content)
        return api_ok("项目档案已保存。", {"asset": _read_project_asset(asset_id)})

    return guarded(action)

@router.get("/api/writing-constraints")
def api_writing_constraints() -> JSONResponse:
    def action() -> dict[str, Any]:
        story_spec = _load_json_safe(get_project_context().data_dir / "story_spec.json", {})
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
        context = get_project_context()
        story_spec_path = context.data_dir / "story_spec.json"
        story_spec = _load_json_safe(story_spec_path, {})
        if not isinstance(story_spec, dict) or not story_spec:
            return api_error("尚未创建小说项目。", ["data/story_spec.json not found"])
        constraints = _normalize_writing_constraints({"writing_constraints": payload, **payload})
        story_spec["writing_constraints"] = constraints
        story_spec["anti_ai_style_rules"] = constraints.get("ai_style_limits", [])
        DataStore(context).write_json(story_spec_path, story_spec)
        return api_ok("写作约束已保存。", constraints)

    return guarded(action)

@router.get("/api/llm/health")
def api_llm_health() -> dict[str, Any]:
    return build_llm_health_report()


@router.get("/api/memory-health")
def api_memory_health(full: bool = False) -> JSONResponse:
    def action() -> dict[str, Any]:
        report = run_memory_health_check(data_dir=get_project_context().data_dir, full=full)
        return api_ok(result=report)

    return guarded(action)


# Stage 15.1: a read-only aggregation boundary over existing reports and planning health.
def _evaluation_failure(error: EvaluationError) -> JSONResponse:
    status = 404 if error.code in {"EVALUATION_TARGET_NOT_FOUND", "EVALUATION_PROFILE_NOT_FOUND"} else 422 if error.code == "EVALUATION_INSUFFICIENT_EVIDENCE" else 409 if error.code in {"EVALUATION_TARGET_CHANGED", "EVALUATION_ALREADY_EXISTS"} else 500
    return JSONResponse(api_error(str(error), [error.code]), status_code=status)


def _planning_evaluation_failure(error: PlanningEvaluationError) -> JSONResponse:
    if error.code in {"PLANNING_EVALUATION_SCOPE_NOT_FOUND", "PLANNING_EVALUATION_PROFILE_NOT_FOUND"}: status = 404
    elif error.code in {"PLANNING_EVALUATION_SOURCE_CHANGED", "PLANNING_EVALUATION_OPERATION_CONFLICT"}: status = 409
    elif error.code == "PLANNING_EVALUATION_INSUFFICIENT_EVIDENCE": status = 422
    elif error.code == "PLANNING_EVALUATION_WRITE_FAILED": status = 500
    else: status = 400
    return JSONResponse(api_error(str(error), [error.code]), status_code=status)


def _planning_comparison_failure(error: PlanningComparisonError) -> JSONResponse:
    status = 404 if error.code == "PLANNING_COMPARISON_REPORT_NOT_FOUND" else 409 if error.code in {"PLANNING_COMPARISON_PROJECT_MISMATCH", "PLANNING_COMPARISON_TARGET_MISMATCH", "PLANNING_COMPARISON_SCOPE_MISMATCH", "PLANNING_COMPARISON_PROFILE_MISMATCH"} else 422
    return JSONResponse(api_error(str(error), [error.code]), status_code=status)


def _evaluation_production_failure(error: EvaluationProductionError) -> JSONResponse:
    status = 404 if error.code.endswith("NOT_FOUND") else 409 if error.code.endswith("STALE") else 422
    return JSONResponse(api_error(str(error), [error.code]), status_code=status)


def _improvement_failure(error: ImprovementPolicyError) -> JSONResponse:
    status = 404 if error.code == "IMPROVEMENT_NOT_FOUND" else 409 if error.code in {"IMPROVEMENT_SOURCE_CHANGED", "CHAPTER_OPERATION_CONFLICT", "IMPROVEMENT_CANDIDATE_LIMIT"} else 422
    return JSONResponse(api_error(str(error), [error.code]), status_code=status)


def _adoption_failure(error: CandidateAdoptionError) -> JSONResponse:
    status = 404 if error.code == "IMPROVEMENT_NOT_FOUND" else 409 if error.code in {"CANDIDATE_SOURCE_CHANGED", "DRAFT_VERSION_REVISION_CONFLICT", "DRAFT_VERSION_LOCK_CONFLICT", "CANDIDATE_ALREADY_ADOPTED", "CANDIDATE_ALREADY_DISCARDED", "CANDIDATE_ADOPTION_PREVIEW_STALE"} else 422
    return JSONResponse(api_error(str(error), [error.code]), status_code=status)


def _partial_adoption_failure(error: PartialAdoptionError) -> JSONResponse:
    if error.code in {"IMPROVEMENT_NOT_FOUND", "PARTIAL_ADOPTION_PREVIEW_NOT_FOUND"}: status = 404
    elif error.code in {"PARTIAL_ADOPTION_SOURCE_CHANGED", "PARTIAL_ADOPTION_PREVIEW_STALE", "PARTIAL_ADOPTION_RESULT_HASH_MISMATCH", "PARTIAL_ADOPTION_ALREADY_COMPLETED", "DRAFT_VERSION_LOCK_CONFLICT"}: status = 409
    else: status = 422
    return JSONResponse(api_error(str(error), [error.code]), status_code=status)


@router.get("/api/evaluations/overview")
def api_evaluations_overview() -> JSONResponse:
    try:
        return JSONResponse(api_ok(result=EvaluationService(get_project_context()).overview()))
    except EvaluationError as error:
        return _evaluation_failure(error)


@router.get("/api/evaluations/profiles")
def api_evaluation_profiles() -> dict[str, Any]:
    from evaluation_engine.profiles import profiles
    return api_ok(result={"profiles": profiles()})


@router.get("/api/evaluations")
def api_evaluations_list(
    target_type: str = "", chapter_number: int | None = None, volume_id: str = "", window_id: str = "", status: str = "", limit: int = 20, cursor: str = "",
) -> JSONResponse:
    try:
        page_request = parse_pagination(limit, cursor)
        context = get_project_context()
        chapter_reports = [] if target_type in {"near_planning_window", "current_volume", "whole_book_planning"} else EvaluationService(context).list_reports(target_type=target_type, chapter_number=chapter_number, status=status, limit=page_request.limit)
        planning_reports = PlanningEvaluationService(context).list_reports(target_type=target_type, volume_id=volume_id, window_id=window_id, status=status, limit=page_request.limit) if not target_type or target_type in {"near_planning_window", "current_volume", "whole_book_planning"} else []
        reports = sorted(chapter_reports + planning_reports, key=lambda item: f"{item.get('created_at') or ''}|{item.get('evaluation_id') or ''}", reverse=True)
        if page_request.cursor: reports = [item for item in reports if f"{item.get('created_at') or ''}|{item.get('evaluation_id') or ''}" < page_request.cursor]
        page = reports[:page_request.limit]
        return JSONResponse(api_ok(result={"evaluations": page, "next_cursor": f"{page[-1].get('created_at') or ''}|{page[-1].get('evaluation_id') or ''}" if len(reports) > len(page) and page else None, "limit": page_request.limit}))
    except ApiRequestError as error:
        return JSONResponse(api_error(str(error), [error.code]), status_code=400)
    except EvaluationError as error:
        return _evaluation_failure(error)


@router.get("/api/evaluations/planning/overview")
def api_planning_evaluation_overview() -> JSONResponse:
    try:
        return JSONResponse(api_ok(result=PlanningEvaluationService(get_project_context()).overview()))
    except PlanningEvaluationError as error:
        return _planning_evaluation_failure(error)


@router.post("/api/evaluations/planning")
async def api_planning_evaluation_generate(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        return JSONResponse(api_error("Planning evaluation request must be a JSON object.", ["PLANNING_EVALUATION_SCOPE_INVALID"]), status_code=400)
    try:
        report, replayed = PlanningEvaluationService(get_project_context()).generate(payload)
        return JSONResponse(api_ok("Planning evaluation was generated from existing planning sources; no model or planning mutation was used.", {"evaluation": report, "replayed": replayed}))
    except PlanningEvaluationError as error:
        return _planning_evaluation_failure(error)


@router.post("/api/evaluations")
async def api_evaluation_generate(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        return JSONResponse(api_error("Evaluation request must be a JSON object.", ["EVALUATION_SOURCE_INVALID"]), status_code=400)
    try:
        report, replayed = EvaluationService(get_project_context()).generate(payload)
        return JSONResponse(api_ok("统一叙事评估报告已生成；未调用模型或修改正文。", {"evaluation": report, "replayed": replayed}), status_code=200)
    except EvaluationError as error:
        return _evaluation_failure(error)


@router.get("/api/evaluations/{evaluation_id}")
def api_evaluation_detail(evaluation_id: str) -> JSONResponse:
    try:
        return JSONResponse(api_ok(result={"evaluation": EvaluationService(get_project_context()).detail(evaluation_id)}))
    except EvaluationError as error:
        try:
            return JSONResponse(api_ok(result={"evaluation": PlanningEvaluationService(get_project_context()).detail(evaluation_id)}))
        except PlanningEvaluationError as planning_error:
            return _planning_evaluation_failure(planning_error) if planning_error.code != "PLANNING_EVALUATION_SCOPE_NOT_FOUND" else _evaluation_failure(error)


@router.get("/api/evaluations/{evaluation_id}/comparison")
def api_planning_evaluation_comparison(evaluation_id: str, baseline_evaluation_id: str | None = None) -> JSONResponse:
    try:
        return JSONResponse(api_ok(result={"comparison": PlanningEvaluationComparisonService(get_project_context()).comparison(evaluation_id, baseline_evaluation_id)}))
    except PlanningComparisonError as error:
        return _planning_comparison_failure(error)


@router.get("/api/evaluations/{evaluation_id}/comparable-reports")
def api_planning_evaluation_comparable_reports(evaluation_id: str) -> JSONResponse:
    try:
        return JSONResponse(api_ok(result={"reports": PlanningEvaluationComparisonService(get_project_context()).comparable_reports(evaluation_id)}))
    except PlanningComparisonError as error:
        return _planning_comparison_failure(error)


@router.get("/api/evaluations/{evaluation_id}/planning-proposals")
def api_planning_evaluation_proposals(evaluation_id: str) -> JSONResponse:
    try:
        return JSONResponse(api_ok(result=PlanningEvaluationComparisonService(get_project_context()).proposals(evaluation_id)))
    except PlanningComparisonError as error:
        return _planning_comparison_failure(error)


@router.get("/api/evaluations/usage/summary")
def api_evaluation_usage_summary(chapter_number: int | None = None, evaluation_id: str = "", improvement_request_id: str = "", candidate_id: str = "", date_from: str = "", date_to: str = "") -> JSONResponse:
    return JSONResponse(api_ok(result=EvaluationProductionService(get_project_context()).usage_summary(chapter_number=chapter_number, evaluation_id=evaluation_id, improvement_request_id=improvement_request_id, candidate_id=candidate_id, date_from=date_from, date_to=date_to)))


@router.get("/api/evaluations/usage/events")
def api_evaluation_usage_events(cursor: str = "", limit: int = 20, chapter_number: int | None = None, evaluation_id: str = "", improvement_request_id: str = "", candidate_id: str = "", date_from: str = "", date_to: str = "") -> JSONResponse:
    return JSONResponse(api_ok(result=EvaluationProductionService(get_project_context()).usage_events(cursor=cursor, limit=limit, chapter_number=chapter_number, evaluation_id=evaluation_id, improvement_request_id=improvement_request_id, candidate_id=candidate_id, date_from=date_from, date_to=date_to)))


@router.get("/api/evaluations/maintenance/preview")
def api_evaluation_maintenance_preview() -> JSONResponse:
    return JSONResponse(api_ok(result=EvaluationProductionService(get_project_context()).maintenance_preview()))


@router.post("/api/evaluations/maintenance/cleanup")
async def api_evaluation_maintenance_cleanup(request: Request) -> JSONResponse:
    try: payload = await request.json()
    except Exception: payload = {}
    if not isinstance(payload, dict): return JSONResponse(api_error("Maintenance request must be a JSON object.", ["EVALUATION_MAINTENANCE_REQUEST_INVALID"]), status_code=422)
    try: return JSONResponse(api_ok(result=EvaluationProductionService(get_project_context()).cleanup(payload)))
    except EvaluationProductionError as error: return _evaluation_production_failure(error)


@router.get("/api/evaluations/{evaluation_id}/export")
def api_evaluation_export(evaluation_id: str, format: str = "json") -> PlainTextResponse:
    try:
        content_type, body = EvaluationProductionService(get_project_context()).export(evaluation_id, format)
        return PlainTextResponse(body, media_type=content_type)
    except EvaluationProductionError as error:
        return PlainTextResponse(json.dumps(api_error(str(error), [error.code]), ensure_ascii=False), status_code=404 if error.code.endswith("NOT_FOUND") else 422, media_type="application/json")


@router.get("/api/evaluations/{evaluation_id}/comparison/export")
def api_planning_comparison_export(evaluation_id: str, format: str = "markdown") -> PlainTextResponse:
    try:
        content_type, body = EvaluationProductionService(get_project_context()).export(evaluation_id, format, comparison=True)
        return PlainTextResponse(body, media_type=content_type)
    except EvaluationProductionError as error:
        return PlainTextResponse(json.dumps(api_error(str(error), [error.code]), ensure_ascii=False), status_code=404 if error.code.endswith("NOT_FOUND") else 422, media_type="application/json")


# Stage 15.2A: request a restricted candidate only. This API never activates or applies it.
@router.post("/api/evaluations/{evaluation_id}/improvements")
async def api_evaluation_improvement_create(evaluation_id: str, request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        return JSONResponse(api_error("Improvement request must be a JSON object.", ["INVALID_REQUEST"]), status_code=400)
    try:
        context = get_project_context(); service = ImprovementService(context)
        improvement, replayed = service.prepare(evaluation_id, payload, get_job_manager().active_jobs(context=context))
        if replayed:
            return JSONResponse(api_ok(result={"improvement": service.public(improvement), "replayed": True}))
        job = get_job_manager().create_job("quality_improvement", {"improvement_id": improvement["improvement_id"], "chapter_id": improvement["chapter_id"]}, context=context)
        return JSONResponse(api_ok("受限候选修订任务已创建；不会覆盖或提交正文。", {"improvement": service.public(improvement), "job": job, "replayed": False}), status_code=202)
    except ImprovementPolicyError as error:
        return _improvement_failure(error)
    except JobError as error:
        return JSONResponse(api_error(str(error), [getattr(error, "code", "JOB_ERROR")]), status_code=409)


@router.get("/api/evaluations/improvements/{improvement_id}")
def api_evaluation_improvement_detail(improvement_id: str) -> JSONResponse:
    try:
        service = ImprovementService(get_project_context())
        return JSONResponse(api_ok(result={"improvement": service.public(service.get(improvement_id))}))
    except ImprovementPolicyError as error:
        return _improvement_failure(error)


@router.get("/api/evaluations/improvements/{improvement_id}/plan")
def api_evaluation_improvement_plan(improvement_id: str) -> JSONResponse:
    try:
        item = ImprovementService(get_project_context()).get(improvement_id)
        return JSONResponse(api_ok(result={"plan": item.get("plan"), "state": item.get("state")}))
    except ImprovementPolicyError as error:
        return _improvement_failure(error)


@router.get("/api/evaluations/improvements/{improvement_id}/candidate")
def api_evaluation_improvement_candidate(improvement_id: str) -> JSONResponse:
    try:
        service = ImprovementService(get_project_context()); item = service.get(improvement_id)
        candidate = item.get("candidate") or {}
        content = service.store.read_markdown(str(candidate.get("content_path") or ""), default="") if candidate else ""
        return JSONResponse(api_ok(result={"candidate": service.public(item).get("candidate"), "content": content, "state": item.get("state")}))
    except ImprovementPolicyError as error:
        return _improvement_failure(error)


@router.get("/api/evaluations/improvements/{improvement_id}/diff")
def api_evaluation_improvement_diff(improvement_id: str) -> JSONResponse:
    try:
        item = ImprovementService(get_project_context()).get(improvement_id)
        return JSONResponse(api_ok(result={"diff": (item.get("candidate") or {}).get("diff"), "state": item.get("state")}))
    except ImprovementPolicyError as error:
        return _improvement_failure(error)


@router.get("/api/evaluations/improvements/{improvement_id}/comparison")
def api_evaluation_improvement_comparison(improvement_id: str) -> JSONResponse:
    try:
        item = ImprovementService(get_project_context()).get(improvement_id)
        return JSONResponse(api_ok(result={"comparison": item.get("comparison"), "evaluation": item.get("evaluation"), "state": item.get("state")}))
    except ImprovementPolicyError as error:
        return _improvement_failure(error)


@router.post("/api/evaluations/improvements/{request_id}/adoption-preview")
def api_candidate_adoption_preview(request_id: str) -> JSONResponse:
    try:
        return JSONResponse(api_ok(result={"preview": CandidateAdoptionService(get_project_context()).preview(request_id)}))
    except (CandidateAdoptionError, ImprovementPolicyError) as error:
        return _adoption_failure(error)


@router.post("/api/evaluations/improvements/{request_id}/partial-adoption-preview")
async def api_candidate_partial_adoption_preview(request_id: str, request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict): return JSONResponse(api_error("Partial-adoption preview request must be a JSON object.", ["INVALID_REQUEST"]), status_code=400)
    try:
        preview = CandidatePartialAdoptionService(get_project_context()).preview(request_id, payload)
        return JSONResponse(api_ok(result={"preview": preview, "result_diff": preview["result_diff"], "selected_patch_count": len(preview["selected_patch_ids"]), "unselected_patch_count": len(preview["unselected_patch_ids"])}))
    except (PartialAdoptionError, ImprovementPolicyError) as error:
        return _partial_adoption_failure(error)
    except DataWriteError as error:
        return JSONResponse(api_error(str(error), ["PARTIAL_ADOPTION_WRITE_FAILED"]), status_code=500)


@router.post("/api/evaluations/improvements/{request_id}/partial-adopt")
async def api_candidate_partial_adopt(request_id: str, request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict): return JSONResponse(api_error("Partial-adoption request must be a JSON object.", ["INVALID_REQUEST"]), status_code=400)
    try:
        result, replayed = CandidatePartialAdoptionService(get_project_context()).adopt(request_id, payload)
        item = result["request"]
        return JSONResponse(api_ok("Selected patches were adopted into a new work-text version; canon is unchanged.", {**result, "replayed": replayed, "candidate_id": (item.get("candidate") or {}).get("candidate_id"), "previous_version_id": (result.get("new_version") or {}).get("parent_version_id"), "new_version_id": (result.get("new_version") or {}).get("version_id"), "selected_patch_ids": (item.get("partial_adoption") or {}).get("selected_patch_ids", []), "unselected_patch_ids": (item.get("partial_adoption") or {}).get("unselected_patch_ids", []), "candidate_status": item.get("state"), "canon_changed": False, "evaluation_status": "stale"}))
    except (PartialAdoptionError, ImprovementPolicyError) as error:
        return _partial_adoption_failure(error)
    except DataWriteError as error:
        return JSONResponse(api_error(str(error), ["PARTIAL_ADOPTION_WRITE_FAILED"]), status_code=500)


@router.post("/api/evaluations/improvements/{request_id}/adopt")
async def api_candidate_adopt(request_id: str, request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict): return JSONResponse(api_error("Adoption request must be a JSON object.", ["INVALID_REQUEST"]), status_code=400)
    try:
        result, replayed = CandidateAdoptionService(get_project_context()).adopt(request_id, payload)
        return JSONResponse(api_ok("候选已晋升为新的工作正文版本；尚未提交正史。", {**result, "replayed": replayed}))
    except (CandidateAdoptionError, ImprovementPolicyError) as error:
        return _adoption_failure(error)


@router.post("/api/evaluations/improvements/{request_id}/discard")
async def api_candidate_discard(request_id: str, request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict): return JSONResponse(api_error("Discard request must be a JSON object.", ["INVALID_REQUEST"]), status_code=400)
    try:
        result, replayed = CandidateAdoptionService(get_project_context()).discard(request_id, payload)
        return JSONResponse(api_ok("候选已放弃，候选正文与评估证据仍保留。", {"improvement": result, "replayed": replayed}))
    except (CandidateAdoptionError, ImprovementPolicyError) as error:
        return _adoption_failure(error)


@router.get("/api/quality-reports/status")
def api_quality_reports_status(chapter_id: int | None = None) -> JSONResponse:
    from system.memory_repair_service import MemoryRepairService
    return guarded(lambda: api_ok(result=MemoryRepairService(get_project_context()).quality_status(chapter_id)))


@router.post("/api/quality-reports/repair")
async def api_repair_quality_reports(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    payload = payload if isinstance(payload, dict) else {}
    chapter = payload.get("chapter_id")
    try:
        chapter = int(chapter) if chapter is not None else None
    except (TypeError, ValueError):
        return JSONResponse(api_error("\u7ae0\u8282\u7f16\u53f7\u65e0\u6548\u3002", ["INVALID_CHAPTER_ID"]), status_code=422)
    return guarded(lambda: command_response(commands.repair_current_quality_report_command(chapter_id=chapter, force=bool(payload.get("force", False)))))


@router.get("/api/vector-index/status")
def api_vector_index_status() -> JSONResponse:
    from system.memory_repair_service import MemoryRepairService
    return guarded(lambda: api_ok(result=MemoryRepairService(get_project_context()).vector_status()))


@router.post("/api/vector-index/initialize")
async def api_initialize_vector_index(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    payload = payload if isinstance(payload, dict) else {}
    try:
        response = command_response(commands.initialize_vector_index_command(
            rebuild=bool(payload.get("rebuild", False)),
            project_id=payload.get("project_id"),
            timeline_id=payload.get("timeline_id"),
            branch_id=payload.get("branch_id"),
            canon_revision_id=payload.get("canon_revision_id"),
        ))
    except Exception:
        response = api_error("Vector index initialization failed.", ["VECTOR_INDEX_INITIALIZATION_FAILED"])
    return JSONResponse(response, headers={"Cache-Control": "no-store"})




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
    try:
        plan = DataStore(get_project_context()).read_json("data/next_chapter_plan.json", default={}, expected_type=dict) or {}
        return compatibility_response(api_ok(result={"plan": plan}), "/api/planning/next-chapter")
    except Exception as exc:
        return compatibility_response(api_error("章节计划读取失败。", [str(exc)]), "/api/planning/next-chapter", status_code=500)


@router.post("/api/planning/next-chapter")
async def api_save_or_plan_next_chapter(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict) or not payload:
        return guarded(lambda: command_response(commands.plan_next_command()))
    def action() -> dict[str, Any]:
        PlanningMutationService().write_bundle_legacy(
            [
                ("next_chapter_plan", payload),
                ("next_chapter_plan_markdown", commands.render_next_chapter_plan_markdown(payload)),
                ("planning_state", {"current_stage": "next_chapter_planned", "next_chapter_plan": {"created": True, "chapter_id": payload.get("chapter_id", 1), "path": "data/next_chapter_plan.json"}}),
            ],
            mutation_type="save_next_chapter_plan",
            reason="save next chapter plan",
        )
        return api_ok("章节规划已保存。", {"plan": payload, "path": "data/next_chapter_plan.json"})
    return guarded(action)


def _continuity_source_hashes(chapter_id: int, current_text: str, context=None) -> tuple[str, str]:
    previous_text = ""
    if chapter_id > 1:
        ctx = context if context is not None else get_project_context()
        previous_path = ctx.chapters_dir / f"chapter_{chapter_id - 1:03d}.md"
        if previous_path.exists():
            previous_text = previous_path.read_text(encoding="utf-8")
    return continuity_content_hash(current_text), continuity_content_hash(previous_text)


@router.get("/api/continuity-report")
def api_get_continuity_report(
    source_type: str = Query(..., pattern="^(draft|edited|manual|committed)$"),
    version: int = Query(..., ge=1),
) -> JSONResponse:
    def action() -> dict[str, Any]:
        current = build_version_content(source_type, version)
        chapter_id = int(current.get("chapter_id", 0) or 0)
        current_hash, previous_hash = _continuity_source_hashes(chapter_id, str(current.get("text", "")))
        report = LegacyEvaluationAdapter(get_project_context()).continuity_view(
            chapter_id=chapter_id, source_type=source_type, source_version=version,
            content_hash=current_hash, previous_content_hash=previous_hash,
        )
        return api_ok(result=report)

    try:
        return compatibility_response(action(), "/api/continuity-report")
    except Exception as exc:
        return compatibility_response(api_error("操作失败", [str(exc)]), "/api/continuity-report", status_code=500)


@router.post("/api/continuity-check")
async def api_continuity_check(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    def action() -> dict[str, Any]:
        if not isinstance(payload, dict):
            return api_error("连贯性检查参数无效。", ["payload must be an object"])
        source_type = str(payload.get("source_type", "")).strip()
        try:
            version = int(payload.get("version", 0) or 0)
        except (TypeError, ValueError):
            version = 0
        if source_type not in {"draft", "edited", "manual", "committed"} or version < 1:
            return api_error("请先选择一个有效的正文版本。", ["source_type and version are required"])
        current = build_version_content(source_type, version)
        chapter_id = int(current.get("chapter_id", 0) or 0)
        if chapter_id <= 1:
            return api_ok("首章没有上一章可供比对。", {"status": "not_applicable", "message": "首章没有上一已提交章节可供比对。"})
        ctx = get_project_context()
        previous_path = ctx.chapters_dir / f"chapter_{chapter_id - 1:03d}.md"
        if not previous_path.exists():
            return api_ok("缺少上一已提交章节，暂无法检查。", {"status": "not_applicable", "message": "缺少上一已提交章节，暂无法检查。"})
        previous_text = previous_path.read_text(encoding="utf-8")
        current_text = str(current.get("text", ""))
        result = check_chapter_continuity(previous_text, current_text)
        warnings = list(result.pop("warnings", [])) if isinstance(result, dict) else []
        report = {
            "chapter_id": chapter_id,
            "source_type": source_type,
            "source_version": version,
            "source_path": current.get("json_path", ""),
            "previous_chapter_id": chapter_id - 1,
            "content_hash": continuity_content_hash(current_text),
            "previous_content_hash": continuity_content_hash(previous_text),
            **result,
        }
        json_path, markdown_path = save_continuity_report(report, "data")
        return api_ok(
            "剧情连贯性检查完成。",
            {"status": "completed", "exists": True, "json_path": json_path, "markdown_path": markdown_path, **report},
            warnings=warnings,
        )

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
        kwargs: dict[str, Any] = {"allow_refinement": not bool(payload.get("assessment_only", False))}
        if source_type == "draft":
            kwargs["draft_version"] = version
        elif source_type == "edited":
            kwargs["edited_version"] = version
        elif source_type == "manual":
            kwargs["manual_version"] = version
        elif source_type == "committed":
            kwargs["committed_chapter"] = version
            kwargs["allow_refinement"] = False
        else:
            return api_error("\u672a\u77e5\u7248\u672c\u7c7b\u578b\u3002", ["source_type must be draft, edited, manual, or committed"])
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
        ctx = get_project_context()
        versions = list_versions(current_target_chapter(), ctx.data_dir)
        outputs = {
            "drafts": versions.get("drafts", []),
            "edited": versions.get("edited", []),
            "manual": versions.get("manual", []),
            "committed": commands._scan_committed_chapters(ctx.data_dir),
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
    def action() -> dict[str, Any]:
        chapter_id = version if source_type == "committed" else current_target_chapter()
        result = LegacyEvaluationAdapter(get_project_context()).quality_view(
            chapter_id=chapter_id, source_type=source_type, source_version=version,
        )
        return api_ok(result=result)
    try:
        return compatibility_response(action(), "/api/quality-report")
    except Exception as exc:
        return compatibility_response(api_error("操作失败", [str(exc)]), "/api/quality-report", status_code=500)


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
async def api_sync_obsidian(request: Request) -> JSONResponse:
    try:
        data = await request.json()
    except Exception:
        data = {}
    dry_run = data.get("dry_run", False)
    prune_stale = data.get("prune_stale", False)
    return guarded(lambda: command_response(commands.sync_obsidian_command(dry_run=dry_run, prune_stale=prune_stale)))


@router.post("/api/obsidian/pull/scan")
async def api_pull_scan(request: Request) -> JSONResponse:
    return guarded(lambda: command_response(commands.pull_obsidian_command()))


@router.post("/api/obsidian/pull/preview")
async def api_pull_preview(request: Request) -> JSONResponse:
    try:
        data = await request.json()
    except Exception:
        data = {}
    relative_path = data.get("relative_path")
    if not relative_path:
        return _fail("relative_path is required", "MISSING_PATH", 400)
    return guarded(lambda: command_response(commands.pull_obsidian_command(file=relative_path)))


@router.post("/api/obsidian/pull/apply")
async def api_pull_apply(request: Request) -> JSONResponse:
    try:
        data = await request.json()
    except Exception:
        data = {}
    relative_path = data.get("relative_path")
    expected_hash = data.get("expected_target_hash")
    if not relative_path:
        return _fail("relative_path is required", "MISSING_PATH", 400)
    if not expected_hash:
        return _fail("expected_target_hash is required", "MISSING_HASH", 400)
    return guarded(lambda: command_response(
        commands.pull_obsidian_command(file=relative_path, expected_hash=expected_hash, apply=True)
    ))


@router.post("/api/obsidian/pull/repair-converged")
async def api_pull_repair_converged(request: Request) -> JSONResponse:
    return guarded(lambda: command_response(commands.pull_obsidian_command(repair_converged=True)))


@router.get("/api/projects/{project_id}/obsidian-binding")
def api_get_obsidian_binding(project_id: str, timeline: str = "main") -> JSONResponse:
    try:
        from system.obsidian_binding_service import ObsidianBindingService
        from core.project import resolve_workspace_root

        workspace_root = resolve_workspace_root()
        service = ObsidianBindingService(workspace_root)
        status = service.status(project_id, timeline)
        return _ok(status, "Binding status retrieved.")
    except Exception as e:
        return _fail(str(e), "BINDING_ERROR", 500)


@router.put("/api/projects/{project_id}/obsidian-binding")
async def api_put_obsidian_binding(project_id: str, request: Request) -> JSONResponse:
    try:
        data = await request.json()
        vault_root = data.get("vault_root")
        target_relative_path = data.get("target_relative_path")
        timeline_id = data.get("timeline_id", "main")

        if not vault_root:
            return _fail("vault_root is required", "VAULT_ROOT_REQUIRED", 400)
        if not target_relative_path:
            return _fail("target_relative_path is required", "TARGET_PATH_REQUIRED", 400)

        from system.obsidian_binding_service import (
            ObsidianBindingService,
            ObsidianBindingConflict,
            ObsidianTargetUnsafe,
            ObsidianMarkerMismatch,
        )
        from core.project import resolve_workspace_root

        workspace_root = resolve_workspace_root()
        service = ObsidianBindingService(workspace_root)

        try:
            binding = service.bind(project_id, timeline_id, Path(vault_root), target_relative_path)
            return _ok({
                "binding_id": binding.binding_id,
                "project_id": binding.project_id,
                "timeline_id": binding.timeline_id,
                "vault_root": binding.vault_root.as_posix(),
                "target_relative_path": binding.target_relative_path,
                "target_full_path": binding.target_full_path.as_posix(),
                "status": binding.status.value,
            }, "Binding created.")
        except ObsidianTargetUnsafe as e:
            return _fail(str(e), "TARGET_UNSAFE", 400)
        except ObsidianBindingConflict as e:
            return _fail(str(e), "BINDING_CONFLICT", 409)
        except ObsidianMarkerMismatch as e:
            return _fail(str(e), "MARKER_MISMATCH", 409)
    except Exception as e:
        return _fail(str(e), "BINDING_ERROR", 500)


@router.delete("/api/projects/{project_id}/obsidian-binding")
def api_delete_obsidian_binding(project_id: str, timeline: str = "main") -> JSONResponse:
    try:
        from system.obsidian_binding_service import ObsidianBindingService
        from core.project import resolve_workspace_root

        workspace_root = resolve_workspace_root()
        service = ObsidianBindingService(workspace_root)
        result = service.unbind(project_id, timeline)

        if result["deleted"]:
            return _ok({}, "Binding removed.")
        if result["reason"] == "NOT_FOUND":
            return _fail("Binding not found", "BINDING_NOT_FOUND", 404)
        if result["reason"].startswith("FOREIGN_MARKER"):
            return _fail("Target has foreign marker", "MARKER_MISMATCH", 409)
        if result["reason"] == "MARKER_DELETE_FAILED":
            return _fail("Marker delete failed", "MARKER_DELETE_FAILED", 500)
        return _fail("Unbind failed", "UNBIND_FAILED", 500)
    except Exception as e:
        return _fail(str(e), "BINDING_ERROR", 500)


@router.post("/api/index-vault")
def api_index_vault() -> JSONResponse:
    return guarded(lambda: command_response(commands.index_vault_command()))


@router.post("/api/simulator/reader/run")
async def api_run_reader_simulation(request: Request) -> JSONResponse:
    try:
        from core.project_context import bind_project_context, get_project_context
        from core.contracts.reader_simulation import ReaderSimulationRequest, SimulationMode
        from system.reader_simulator import ReaderSimulatorService, ReaderSimulatorError
        from system.reader_simulation_store import ReaderSimulationStore

        data = await request.json()
        chapter_id = data.get("chapter_id")
        source_version_id = data.get("source_version_id")
        project_root = data.get("project_root")

        if chapter_id is None:
            return _fail("chapter_id is required", "CHAPTER_ID_REQUIRED", 400)

        context = get_project_context(project_root)

        state_path = context.data_dir / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
        project_id = state.get("project_id", "default-project")
        timeline_id = state.get("timeline_id", "main")

        req = ReaderSimulationRequest(
            project_id=project_id,
            timeline_id=timeline_id,
            chapter_id=int(chapter_id),
            source_version_id=source_version_id,
            mode=SimulationMode.RULE,
        )

        with bind_project_context(context):
            simulator = ReaderSimulatorService(context)
            run = simulator.run_simulation(req)

            store = ReaderSimulationStore(context)
            store.save_run(run)

        if run.status.value == "failed":
            return _fail(run.error or "Simulation failed", "SIMULATION_FAILED", 500)

        result = run.result
        return _ok({
            "run_id": run.run_id,
            "chapter_id": chapter_id,
            "source_version_id": run.snapshot.source.source_version_id,
            "engagement_score": {
                "score": result.engagement_score.score,
                "level": result.engagement_score.level,
                "reasons": result.engagement_score.reasons,
                "evidence": result.engagement_score.evidence,
            },
            "retention_risk": {
                "score": result.retention_risk.score,
                "level": result.retention_risk.level.value,
                "risk_points": result.retention_risk.risk_points,
            },
            "novel_health": {
                "overall_score": result.novel_health.overall_score,
                "pacing": result.novel_health.pacing,
                "clarity": result.novel_health.clarity,
                "continuity": result.novel_health.continuity,
                "conflict": result.novel_health.conflict,
                "payoff": result.novel_health.payoff,
                "style_stability": result.novel_health.style_stability,
                "warnings": result.novel_health.warnings,
            },
            "evaluator_version": result.evaluator_version,
            "created_at": run.created_at.isoformat(),
        }, "Reader simulation completed.")

    except ReaderSimulatorError as exc:
        return _fail(exc.message, exc.code, 400)
    except Exception as exc:
        return _fail(str(exc), "SIMULATION_ERROR", 500)


@router.get("/api/simulator/reader/runs")
def api_list_reader_simulations(chapter_id: int | None = None, project_root: str | None = None) -> JSONResponse:
    try:
        from core.project_context import bind_project_context, get_project_context
        from system.reader_simulation_store import ReaderSimulationStore

        context = get_project_context(project_root)

        with bind_project_context(context):
            store = ReaderSimulationStore(context)
            runs = store.list_runs(chapter_id=chapter_id)

        output = []
        for run in runs:
            output.append({
                "run_id": run.run_id,
                "chapter_id": run.request.chapter_id,
                "source_version_id": run.snapshot.source.source_version_id,
                "status": run.status.value,
                "created_at": run.created_at.isoformat(),
                "engagement_score": run.result.engagement_score.score if run.result else None,
                "retention_risk": run.result.retention_risk.score if run.result else None,
            })

        return _ok({"simulations": output}, f"{len(output)} simulations found.")

    except Exception as exc:
        return _fail(str(exc), "LIST_ERROR", 500)


@router.get("/api/simulator/reader/runs/{run_id}")
def api_get_reader_simulation(run_id: str, project_root: str | None = None) -> JSONResponse:
    try:
        from core.project_context import bind_project_context, get_project_context
        from system.reader_simulation_store import ReaderSimulationStore

        context = get_project_context(project_root)

        with bind_project_context(context):
            store = ReaderSimulationStore(context)
            run = store.load_run(run_id)
            if run is None:
                return _fail(f"run_id '{run_id}' not found", "RUN_NOT_FOUND", 404)
            staleness = store.check_run_staleness(run_id)

        result_state = staleness.state.value
        stale_reasons = [r.value for r in staleness.stale_reasons]

        result = {}
        if run.result:
            result = {
                "engagement_score": {
                    "score": run.result.engagement_score.score,
                    "level": run.result.engagement_score.level,
                    "reasons": run.result.engagement_score.reasons,
                    "evidence": run.result.engagement_score.evidence,
                },
                "retention_risk": {
                    "score": run.result.retention_risk.score,
                    "level": run.result.retention_risk.level.value,
                    "risk_points": run.result.retention_risk.risk_points,
                },
                "reader_emotion_curve": [
                    {
                        "position": node.position,
                        "segment_label": node.segment_label,
                        "tension": node.tension,
                        "curiosity": node.curiosity,
                        "emotional_intensity": node.emotional_intensity,
                        "payoff": node.payoff,
                    }
                    for node in run.result.reader_emotion_curve
                ],
                "problem_flags": [
                    {
                        "code": flag.code,
                        "severity": flag.severity.value,
                        "category": flag.category.value,
                        "message": flag.message,
                    }
                    for flag in run.result.problem_flags
                ],
                "optimization_suggestions": [
                    {
                        "priority": s.priority,
                        "target": s.target,
                        "reason": s.reason,
                        "expected_effect": s.expected_effect,
                    }
                    for s in run.result.optimization_suggestions
                ],
                "novel_health": {
                    "overall_score": run.result.novel_health.overall_score,
                    "pacing": run.result.novel_health.pacing,
                    "clarity": run.result.novel_health.clarity,
                    "continuity": run.result.novel_health.continuity,
                    "conflict": run.result.novel_health.conflict,
                    "payoff": run.result.novel_health.payoff,
                    "style_stability": run.result.novel_health.style_stability,
                    "warnings": run.result.novel_health.warnings,
                },
                "evaluator_version": run.result.evaluator_version,
                "evaluated_at": run.result.evaluated_at.isoformat(),
            }

        return _ok({
            "run_id": run.run_id,
            "status": run.status.value,
            "result_state": result_state,
            "stale_reasons": stale_reasons,
            "chapter_id": run.snapshot.chapter_id,
            "project_id": run.snapshot.project_id,
            "timeline_id": run.snapshot.timeline_id,
            "source": {
                "source_version_id": run.snapshot.source.source_version_id,
                "source_type": run.snapshot.source.source_type,
                "source_hash": run.snapshot.source.source_hash,
                "title": run.snapshot.source.title,
            },
            "result": result,
            "created_at": run.created_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }, f"Simulation details (state: {result_state}).")

    except Exception as exc:
        return _fail(str(exc), "GET_ERROR", 500)


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
        ctx = get_project_context()
        chapter_path = ctx.chapters_dir / f"chapter_{version:03d}.md"
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
    chapter_id = version if source_type == "committed" else current_target_chapter()
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
    ctx = get_project_context()
    plan_path = ctx.data_dir / "next_chapter_plan.json"
    if plan_path.exists():
        try:
            return int(json.loads(plan_path.read_text(encoding="utf-8")).get("chapter_id", 1) or 1)
        except json.JSONDecodeError:
            return 1
    state_path = ctx.data_dir / "state.json"
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

    from core.project_context import get_project_context
    from system.chapter_commit_service import ChapterCommitService, PostCommitPolicy
    context = get_project_context()
    commit_service = ChapterCommitService(context)
    commit_result = commit_service.commit_chapter(
        int(target["chapter_id"]),
        post_commit_policy=PostCommitPolicy.FULL,
    )

    if commit_result.status == "failed":
        return api_response(False, "\n".join(commit_result.warnings), {"review": record})

    if commit_result.status == "already_committed":
        return api_response(
            True,
            "审核通过，章节已提交（内容未变化）。",
            {
                "review": record,
                "chapter_id": commit_result.chapter_id,
                "canon_revision_id": commit_result.canon_revision_id,
                "post_commit": commit_result.post_commit,
            },
            warnings=commit_result.warnings,
        )

    archived, archive_warnings = _archive_versions_after_commit(int(target["chapter_id"]))
    commit_result.warnings.extend(archive_warnings)

    return api_response(
        True,
        "审核通过，章节已提交。",
        {
            "review": record,
            "chapter_id": commit_result.chapter_id,
            "commit_id": commit_result.commit_id,
            "canon_revision_id": commit_result.canon_revision_id,
            "source_type": commit_result.source_type.value,
            "post_commit": commit_result.post_commit,
            "archived_versions": archived,
        },
        warnings=commit_result.warnings,
    )


def _archive_versions_after_commit(chapter_id: int) -> tuple[list[dict[str, Any]], list[str]]:
    """Archive all non-committed versions after a chapter is approved and committed."""
    versions = list_versions(chapter_id, "data")
    archived: list[dict[str, Any]] = []
    warnings: list[str] = []
    for source_type, collection_key in (("draft", "drafts"), ("edited", "edited"), ("manual", "manual")):
        entries = versions.get(collection_key, [])
        if not isinstance(entries, list):
            continue
        for entry in list(entries):
            try:
                version = int(entry.get("version", 0) or 0)
            except (TypeError, ValueError):
                continue
            if version < 1:
                continue
            try:
                result = archive_version(
                    chapter_id,
                    source_type,
                    version,
                    "data",
                    reason="review_approved_commit",
                )
                archived.append({
                    "source_type": source_type,
                    "version": version,
                    "archive_dir": result.get("archive_dir", ""),
                    "files": result.get("files", []),
                })
            except (VersionArchiveError, FileNotFoundError) as exc:
                warnings.append(f"{source_type}_v{version:03d} 归档失败：{exc}")
    return archived, warnings


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
    context = get_project_context()
    path = context.root / asset["path"]
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


# Restored Stage 7 narrative-memory API: all reads/writes use the active ProjectContext.
def _nm() -> NarrativeMemoryService: return NarrativeMemoryService(get_project_context())

def _branch_nm_scope(project_id: str | None, timeline_id: str | None, branch_id: str | None):
 if any(value is not None for value in (project_id, timeline_id, branch_id)):
  if not all(isinstance(value, str) and value for value in (project_id, timeline_id, branch_id)):
   raise ValueError("BRANCH_MEMORY_SCOPE_REQUIRED")
  from system.branch_narrative_memory_service import BranchMemoryService
  service=BranchMemoryService(get_project_context()); return service, service.scope(project_id, timeline_id, branch_id)
 return None
@router.get("/api/narrative-memory/overview")
def nm_overview(project_id: str | None = None, timeline_id: str | None = None, branch_id: str | None = None):
 try:
  branch = _branch_nm_scope(project_id, timeline_id, branch_id)
  if branch:
   service, scope = branch; events = service.events(scope, branch_id)
   return _ok({"events": len(events), "confirmed_events": sum(row.get("status") in {"confirmed", "corrected"} for row in events), "branch_id": branch_id})
  return _ok({**_nm().overview(), "legacy_unscoped": True, "deprecated": True, "mutation_allowed": False})
 except Exception as exc: return _fail("NarrativeMemory scope invalid", getattr(exc, "code", "BRANCH_MEMORY_SCOPE_REQUIRED"), 400)
@router.get("/api/narrative-memory/events")
def nm_events(chapter_id:int|None=None, project_id: str | None = None, timeline_id: str | None = None, branch_id: str | None = None):
 try:
  branch = _branch_nm_scope(project_id, timeline_id, branch_id)
  if branch:
   service, scope = branch; return _ok({"events": service.events(scope, branch_id, chapter_id)})
  return _ok({"events":_nm().events(chapter_id), "legacy_unscoped": True, "deprecated": True, "mutation_allowed": False})
 except Exception as exc: return _fail("NarrativeMemory scope invalid", getattr(exc, "code", "BRANCH_MEMORY_SCOPE_REQUIRED"), 400)
@router.post("/api/narrative-memory/chapters/{chapter_id}/extract")
def nm_extract(chapter_id:int):
 return _fail('Legacy NarrativeMemory mutation is disabled.','LEGACY_MEMORY_MUTATION_DISABLED',410)
@router.get("/api/narrative-memory/timeline")
def nm_timeline(): return _ok({"timeline":_nm().store.read_json('data/narrative_memory/timeline.json',default=[],expected_type=list) or [],"legacy_unscoped":True,"deprecated":True,"mutation_allowed":False})
@router.get("/api/narrative-memory/conflicts")
def nm_conflicts(): return _ok({"conflicts":_nm().store.read_json('data/narrative_memory/conflicts/conflicts.json',default=[],expected_type=list) or [],"legacy_unscoped":True,"deprecated":True,"mutation_allowed":False})
@router.post("/api/continuity/preflight")
async def nm_preflight(request:Request):
 return _fail('Legacy NarrativeMemory mutation is disabled.','LEGACY_MEMORY_MUTATION_DISABLED',410)
@router.post("/api/narrative-memory/events/{event_id}/confirm")
async def nm_confirm(event_id:str,request:Request):
 return _fail('Legacy NarrativeMemory mutation is disabled.','LEGACY_MEMORY_MUTATION_DISABLED',410)
@router.post("/api/narrative-memory/project")
def nm_project(project_id: str | None = None, timeline_id: str | None = None, branch_id: str | None = None):
 try:
  branch = _branch_nm_scope(project_id, timeline_id, branch_id)
  if branch:
   service, scope = branch; return _ok({'state':service.project_state(scope, branch_id)},'Branch narrative state projected.')
  return _fail('Legacy NarrativeMemory mutation is disabled.','LEGACY_MEMORY_MUTATION_DISABLED',410)
 except Exception as exc: return _fail("NarrativeMemory scope invalid", getattr(exc, "code", "BRANCH_MEMORY_SCOPE_REQUIRED"), 400)
@router.post("/api/narrative-memory/chapters/{chapter_id}/snapshot")
def nm_snapshot(chapter_id:int, project_id: str | None = None, timeline_id: str | None = None, branch_id: str | None = None):
 try:
  branch = _branch_nm_scope(project_id, timeline_id, branch_id)
  if branch:
   service, scope = branch; return _ok({'snapshot':service.snapshot(scope, branch_id, chapter_id)},'Branch narrative snapshot saved.')
  return _fail('Legacy NarrativeMemory mutation is disabled.','LEGACY_MEMORY_MUTATION_DISABLED',410)
 except Exception as exc:return _fail(str(exc),'NARRATIVE_SNAPSHOT_ERROR',409)
@router.get("/api/narrative-memory/context-preview")
def nm_preview(chapter_id:int=1, project_id: str | None = None, timeline_id: str | None = None, branch_id: str | None = None):
 branch = _branch_nm_scope(project_id, timeline_id, branch_id)
 if branch:
  service, scope = branch; return _ok({'preview':service.retrieval_history(scope, branch_id, chapter_id=chapter_id)})
 context=_ctx(); store=DataStore(context)
 preview=ContextAssemblyService(context).assemble(
  state=store.read_json('data/state.json',default={},expected_type=dict) or {},
  memory_index=store.read_json('data/memory/memory_index.json',default={},expected_type=dict) or {},
  query='', story_spec=store.read_json('data/story_spec.json',default={},expected_type=dict) or {},
  characters=store.read_json('data/characters.json',default={},expected_type=dict) or {},
  world_bible=store.read_json('data/world_bible.json',default={},expected_type=dict) or {},
  purpose='chapter_drafting',
 )
 preview['context_ref']=f"context:{chapter_id or preview.get('chapter_number',1)}"
 return _ok({'preview':preview,'legacy_unscoped':True,'deprecated':True,'mutation_allowed':False})
@router.post("/api/narrative-memory/overrides/{kind}")
async def nm_override(kind:str,request:Request):
 try:
  payload=await request.json()
  branch = _branch_nm_scope(payload.get('project_id'), payload.get('timeline_id'), payload.get('branch_id'))
  if branch:
   service, scope = branch; return _ok({'override':service.override(scope, payload['branch_id'], kind, payload.get('value'))},'Branch narrative override saved.')
  return _fail('Legacy NarrativeMemory mutation is disabled.','LEGACY_MEMORY_MUTATION_DISABLED',410)
 except NarrativeMemoryError as exc:return _fail(str(exc),getattr(exc,'code','NARRATIVE_MEMORY_ERROR'),422)


# Reconstructed phase 2-6 API bridge.  Services remain the sole business authority.
def _ok(result=None,message=""): return JSONResponse(api_ok(message,result or {}))
def _fail(message,code,status=400):
 return JSONResponse(api_error(message,[code]),status_code=status)
def _ctx(): return get_project_context()

def _agent_context(chapter_id: int | None = None, draft_text: str = "") -> dict[str, Any]:
 """The web layer, not an agent, builds the approved context snapshot."""
 context=_ctx(); store=DataStore(context)
 state=store.read_json('data/state.json',default={},expected_type=dict) or {}
 memory=store.read_json('data/memory/memory_index.json',default={},expected_type=dict) or {}
 story=store.read_json('data/story_spec.json',default={},expected_type=dict) or {}
 characters=store.read_json('data/characters.json',default={},expected_type=dict) or {}
 world=store.read_json('data/world_bible.json',default={},expected_type=dict) or {}
 snapshot=ContextAssemblyService(context).assemble(
  state=state,memory_index=memory,query='',story_spec=story,characters=characters,
  world_bible=world,purpose='chapter_drafting',
 )
 snapshot.update({'characters':characters,'chapter_plan':store.read_json('data/next_chapter_plan.json',default={},expected_type=dict) or {},'context_ref':f"context:{chapter_id or snapshot.get('next_chapter_id',1)}"})
 if draft_text: snapshot['draft_text']=draft_text
 return snapshot


@router.get('/api/system/health')
def p_system_health(): return _ok(HealthChecker(_ctx()).check())
@router.get('/api/system/diagnostics')
def p_system_diagnostics(): return _ok(DiagnosticsService(_ctx()).snapshot())
@router.post('/api/system/check')
def p_system_check(): return _ok(HealthChecker(_ctx()).check(),'System check completed.')
@router.get('/api/system/logs')
def p_system_logs(level:str|None=None,limit:int=100): return _ok({'entries':recent_logs(_ctx(),level=level,limit=limit)})
@router.get('/api/system/errors')
def p_system_errors(limit:int=100): return _ok({'entries':recent_logs(_ctx(),level='ERROR',limit=limit)})
@router.post('/api/system/export-report')
def p_system_export_report(): return _ok(DiagnosticsService(_ctx()).export(),'Diagnostic report exported.')


def _project_context_for_id(project_id:str):
 project=get_project_manager().get_project(project_id)
 root=Path.cwd() if project.get('project_root')=='.' else Path.cwd()/str(project.get('project_root',''))
 return get_project_context(root)
@router.get('/api/projects/{project_id}/health')
def p_project_health(project_id:str):
 try:return _ok(HealthChecker(_project_context_for_id(project_id)).check())
 except ProjectManagerError as exc:return _fail('Project not found.','PROJECT_NOT_FOUND',404)
@router.post('/api/projects/{project_id}/backup')
def p_project_backup(project_id:str):
 try:return _ok({'backup':BackupService(_project_context_for_id(project_id)).create('manual')},'Project backup created.')
 except ProjectManagerError:return _fail('Project not found.','PROJECT_NOT_FOUND',404)
 except StoryOSError as exc:return _fail(str(exc),exc.code,409)
@router.get('/api/projects/{project_id}/backups')
def p_project_backups(project_id:str):
 try:return _ok({'backups':BackupService(_project_context_for_id(project_id)).list()})
 except ProjectManagerError:return _fail('Project not found.','PROJECT_NOT_FOUND',404)
@router.post('/api/projects/{project_id}/restore')
async def p_project_restore(project_id:str,request:Request):
 try:
  payload=await request.json(); backup_id=str(payload.get('backup_id','')); files=payload.get('files')
  if not backup_id:return _fail('backup_id is required.','DATA_BACKUP_NOT_FOUND',422)
  return _ok({'restore':BackupService(_project_context_for_id(project_id)).restore(backup_id,files=files if isinstance(files,list) else None)},'Project data restored.')
 except ProjectManagerError:return _fail('Project not found.','PROJECT_NOT_FOUND',404)
 except StoryOSError as exc:return _fail(str(exc),exc.code,409)
async def _create_revision_check_job(revision_id:str,request:Request,job_type:str) -> JSONResponse:
 try:
  revision=RevisionService(_ctx()).get_revision(revision_id)
  try: payload=await request.json()
  except Exception: payload={}
  if not isinstance(payload,dict): return _fail('Request body must be an object.','INVALID_REQUEST',422)
  job=get_job_manager().create_job(job_type,{'revision_id':revision_id,'candidate_version_id':payload.get('candidate_version_id'),'chapter_id':revision['chapter_id']},context=_ctx())
  return _ok({'job':job},'Revision check task created.')
 except RevisionError as exc:return _fail(str(exc),exc.code,404)
 except JobError as exc:return _fail(str(exc),getattr(exc,'code','JOB_ERROR'),409)
@router.get('/api/projects')
def p_projects():
 try:return _ok(get_project_manager().list_projects())
 except Exception as e:return _fail(str(e),'PROJECT_ERROR')
@router.get('/api/agents')
def p_agents(): return _ok({'agents':AgentRegistry(_ctx()).list()})
@router.get('/api/agents/{agent_id}')
def p_agent(agent_id:str):
 try:return _ok({'agent':AgentRegistry(_ctx()).get(agent_id).public()})
 except KeyError:return _fail('Agent not found.','AGENT_NOT_FOUND',404)
@router.put('/api/agents/{agent_id}')
async def p_agent_update(agent_id:str,request:Request):
 try:
  data=await request.json(); return _ok({'agent':AgentRegistry(_ctx()).update(agent_id,data if isinstance(data,dict) else {})},'Agent configuration saved.')
 except KeyError:return _fail('Agent not found.','AGENT_NOT_FOUND',404)
@router.get('/api/workflows')
def p_workflows(): return _ok({'workflows':WorkflowEngine(_ctx()).definitions()})
@router.post('/api/workflows/run')
async def p_workflow_run(request:Request):
 try:
  data=await request.json(); data=data if isinstance(data,dict) else {}
  chapter_id=data.get('chapter_id'); draft=str(data.get('draft_text',''))
  snapshot=_agent_context(int(chapter_id) if chapter_id else None,draft); snapshot['allow_model_calls']=bool(data.get('allow_model_calls',False))
  params={'workflow_id':str(data.get('workflow_id','chapter_creative_v1')),'context_snapshot':snapshot,'decisions':data.get('decisions') if isinstance(data.get('decisions'),dict) else {}}
  if data.get('run_id'): params={'workflow_run_id':str(data['run_id']),'decisions':params['decisions'],'context_snapshot':params['context_snapshot']}
  job=get_job_manager().create_job('agent_workflow',params,context=_ctx())
  return _ok({'job':job},'Creative workflow task created.')
 except KeyError as exc:return _fail('Workflow not found.',str(exc).strip("'"),404)
 except JobError as exc:return _fail(str(exc),getattr(exc,'code','JOB_ERROR'),409)
@router.get('/api/workflows/{workflow_id}/runs')
def p_workflow_runs(workflow_id:str): return _ok({'runs':WorkflowEngine(_ctx()).runs(workflow_id)})
@router.get('/api/creative/reviews')
def p_creative_reviews(limit:int=30):
 return _ok({'traces':[row for row in AgentExecutor(_ctx()).traces(limit=limit) if row.get('agent_id') in {'reader_simulator','editor','continuity_checker'}]})
@router.post('/api/creative/debate')
async def p_creative_debate(request:Request):
 data=await request.json(); data=data if isinstance(data,dict) else {}
 return _ok({'debate':WorkflowEngine(_ctx()).debate(_agent_context(data.get('chapter_id'),str(data.get('draft_text',''))))},'Creative debate prepared for author review.')
@router.post('/api/reader/simulate')
async def p_reader_simulate(request:Request):
 data=await request.json(); data=data if isinstance(data,dict) else {}
 snapshot=_agent_context(data.get('chapter_id'),str(data.get('draft_text',''))); snapshot['allow_model_calls']=True
 trace=AgentExecutor(_ctx()).execute('reader_simulator',snapshot)
 return _ok({'review':trace['result'],'trace_id':trace['trace_id']})
@router.post('/api/character/simulate')
async def p_character_simulate(request:Request):
 data=await request.json(); data=data if isinstance(data,dict) else {}
 snapshot=_agent_context(data.get('chapter_id'),str(data.get('draft_text',''))); snapshot['allow_model_calls']=True
 trace=AgentExecutor(_ctx()).execute('character_simulator',snapshot)
 return _ok({'simulation':trace['result'],'trace_id':trace['trace_id']})
@router.get('/api/projects/active')
def p_active(): return _ok({'project':get_project_manager().get_active_project()})


@router.get('/api/simulator/context')
def api_simulator_context(
    project_id: str = Query(..., min_length=1),
    timeline_id: str | None = None,
    chapter_id: int | None = Query(None, ge=1),
) -> JSONResponse:
    """Return safe, read-only navigator metadata for one project scope."""
    try:
        manager = get_project_manager()
        project = manager.get_project(project_id)
        if not project.get("valid"):
            return _fail("Project context is unavailable", "PROJECT_CONTEXT_INVALID", 404)
        context = get_project_context(str(project["project_root"]))
        state = DataStore(context).read_json(context.data_dir / "state.json", default={}, expected_type=dict) or {}
        effective_timeline = str(timeline_id or state.get("timeline_id") or "main")
        if effective_timeline != str(state.get("timeline_id") or "main"):
            return _fail("Timeline is not available in this project", "TIMELINE_NOT_FOUND", 404)
        chapter_ids: set[int] = set()
        for path in (context.chapters_dir, context.versions_dir, context.drafts_dir, context.edited_dir, context.manual_dir):
            if path.exists():
                for item in path.glob("*"):
                    match = re.search(r"chapter[_-](\d+)", item.stem)
                    if match: chapter_ids.add(int(match.group(1)))
        current_chapter = int(state.get("current_chapter", 0) or 0)
        if current_chapter > 0: chapter_ids.add(current_chapter)
        chapters = [{"chapter_id": number, "title": f"第 {number} 章", "current": number == current_chapter} for number in sorted(chapter_ids)]
        selected_chapter = chapter_id if chapter_id in chapter_ids else (current_chapter or (min(chapter_ids) if chapter_ids else None))
        versions: list[dict[str, Any]] = []
        runs: list[dict[str, Any]] = []
        if selected_chapter is not None:
            version_data = list_versions(selected_chapter, context.data_dir)
            for source_type in ("draft", "edited", "manual"):
                for item in version_data.get(source_type, []):
                    versions.append({"source_type": source_type, "version": item.get("version"), "version_label": item.get("version_label"), "source_version_id": item.get("source_version_id"), "selected": version_data.get("selected", {}).get("source_type") == source_type and version_data.get("selected", {}).get("version") == item.get("version")})
            for item in commands._scan_committed_chapters(context.data_dir):
                if int(item.get("chapter_id", 0) or 0) == selected_chapter:
                    versions.append({"source_type": "committed", "version": item.get("version"), "version_label": item.get("version_label"), "source_version_id": item.get("source_version_id"), "selected": False})
            from core.project_context import bind_project_context
            from system.model_persona_panel_execution_service import ModelPersonaPanelExecutionService
            with bind_project_context(context):
                for run in ModelPersonaPanelExecutionService(context).list_runs(selected_chapter):
                    payload = _panel_result_payload(run)
                    runs.append({"panel_execution_id": payload["panel_execution_id"], "status": payload["status"], "staleness": payload["staleness"], "usage_completeness": payload["usage_completeness"], "ordered_persona_ids": payload["ordered_persona_ids"]})
        source_available = False
        if selected_chapter is not None:
            try:
                from core.contracts.reader_simulation import ReaderSimulationRequest, SimulationMode
                from system.reader_simulator import ReaderSimulatorService
                ReaderSimulatorService(context)._build_snapshot(ReaderSimulationRequest(
                    project_id=str(state.get("project_id") or "default-project"), timeline_id=effective_timeline,
                    chapter_id=selected_chapter, source_version_id=None, mode=SimulationMode.RULE,
                ))
                source_available = True
            except Exception:
                source_available = False
        # Branch listing (read-only): expose branch metadata for the Narrative Turn
        # branch selector. This does NOT mutate the registry or any branch state.
        branches_payload: list[dict[str, Any]] = []
        try:
            from core.contracts.narrative_turn import TimelineContext
            from system.narrative_branch_store import NarrativeBranchStore
            tl_ctx = TimelineContext(project_id=str(state.get("project_id") or "default-project"), timeline_id=effective_timeline)
            store = NarrativeBranchStore(context)
            for b in store.list_branches(tl_ctx):
                branches_payload.append({
                    "branch_id": b.branch_id,
                    "display_name": b.display_name,
                    "lifecycle_status": b.lifecycle_status.value,
                })
        except Exception:
            branches_payload = []
        return _ok({"project": {"project_id": project["project_id"], "title": project["title"], "legacy": project.get("legacy", False), "scope_project_id": str(state.get("project_id") or "default-project")}, "timelines": [{"timeline_id": effective_timeline, "title": "主时间线"}], "chapters": chapters, "selected_chapter_id": selected_chapter, "source_versions": versions, "source_available": source_available, "panel_runs": runs, "branches": branches_payload})
    except ProjectManagerError:
        return _fail("Project not found", "PROJECT_NOT_FOUND", 404)
    except Exception:
        return _fail("Unable to load simulator context", "SIMULATOR_CONTEXT_ERROR", 500)
@router.post('/api/projects/{project_id}/activate')
def p_activate(project_id:str):
 try:return _ok({'project':get_project_manager().activate_project(project_id)},'Project activated.')
 except ProjectManagerError as e:return _fail(str(e),'PROJECT_NOT_FOUND',404)
@router.post('/api/jobs')
async def p_job(request:Request):
 try:
  data=await request.json(); job=get_job_manager().create_job(str(data.get('job_type','')),dict(data.get('parameters') or {}),context=_ctx()); return _ok({'job':job},'Task created.')
 except JobError as e:return _fail(str(e),getattr(e,'code','JOB_ERROR'),409)
@router.get('/api/jobs')
def p_jobs(): return _ok({'jobs':get_job_manager().list_jobs(context=_ctx())})


# Phase 8 model centre.  Routing, tracing and persistence remain in llm services.
def _gateway() -> ModelGateway: return get_model_gateway(_ctx())
def _model_error(exc: Exception, status: int = 409) -> JSONResponse:
 return _fail(str(exc),getattr(exc,'code','MODEL_GATEWAY_ERROR'),status)
@router.get('/api/models/providers')
def p_model_providers():
 try:
  models=_gateway().registry.models(); providers={m.provider for m in models}
  return _ok({'providers':[{'provider':p,'models':sum(1 for m in models if m.provider==p)} for p in sorted(providers)]})
 except ModelGatewayError as e:return _model_error(e)
@router.get('/api/models')
def p_models():
 try:return _ok({'models':[model.public() for model in _gateway().registry.models()]})
 except ModelGatewayError as e:return _model_error(e)
@router.get('/api/models/routes')
def p_model_routes():
 try:return _ok({'routes':{key:value.to_dict() for key,value in _gateway().registry.routes().items()}})
 except ModelGatewayError as e:return _model_error(e)
@router.put('/api/models/routes')
async def p_model_routes_update(request:Request):
 try:
  data=await request.json(); routes=data.get('routes',data) if isinstance(data,dict) else None
  return _ok({'routes':{key:value.to_dict() for key,value in _gateway().registry.update_routes(routes).items()}},'Model routes saved.')
 except ModelGatewayError as e:return _model_error(e,422)
@router.get('/api/models/health')
def p_model_health():
 try:return _ok({'health':_gateway().health()})
 except ModelGatewayError as e:return _model_error(e)
@router.post('/api/models/{model_key}/health-check')
def p_model_health_check(model_key:str):
 try:return _ok({'health':_gateway().health_check(model_key)})
 except ModelGatewayError as e:return _model_error(e,404 if getattr(e,'code','')=='MODEL_NOT_FOUND' else 409)
@router.get('/api/models/pricing')
def p_model_pricing(): return _ok({'pricing':_gateway().registry.pricing()})
@router.put('/api/models/pricing')
async def p_model_pricing_update(request:Request):
 try:return _ok({'pricing':_gateway().registry.update_pricing(await request.json())},'Model pricing saved.')
 except ModelGatewayError as e:return _model_error(e,422)
@router.get('/api/models/limits')
def p_model_limits(): return _ok({'limits':_gateway().registry.limits()})
@router.put('/api/models/limits')
async def p_model_limits_update(request:Request):
 try:return _ok({'limits':_gateway().registry.update_limits(await request.json())},'Project model limits saved.')
 except ModelGatewayError as e:return _model_error(e,422)
@router.get('/api/models/usage')
def p_model_usage(): return _ok(_gateway().recorder.usage_summary())
@router.get('/api/models/runs')
def p_model_runs(task_type:str|None=None,model_key:str|None=None,status:str|None=None,limit:int=50):
 return _ok({'runs':_gateway().recorder.list(task_type=task_type,model_key=model_key,status=status,limit=limit)})
@router.get('/api/models/runs/{run_id}')
def p_model_run(run_id:str):
 run=_gateway().recorder.get(run_id)
 return _ok({'run':run}) if run else _fail('Model run not found.','MODEL_RUN_NOT_FOUND',404)
@router.post('/api/models/runs/{run_id}/retry')
def p_model_run_retry(run_id:str):
 run=_gateway().recorder.get(run_id)
 if not run:return _fail('Model run not found.','MODEL_RUN_NOT_FOUND',404)
 if run.get('status') not in {'failed','cancelled'}:return _fail('Only failed or cancelled model calls can be retried.','MODEL_RUN_NOT_RETRYABLE',409)
 if run.get('job_id'):
  try:return _ok({'job':get_job_manager().retry_job(str(run['job_id']),context=_ctx())},'Retry task created from the owning model run.')
  except JobError as e:return _fail(str(e),getattr(e,'code','JOB_ERROR'),409)
 return _fail('The original prompt is intentionally not persisted; retry the owning task.','PROMPT_NOT_PERSISTED',409)
@router.get('/api/prompts')
def p_prompts(): return _ok({'prompts':PromptRegistry().list()})
@router.get('/api/prompts/{prompt_id}')
def p_prompt(prompt_id:str):
 prompt=PromptRegistry().get(prompt_id)
 return _ok({'prompt':prompt}) if prompt else _fail('Prompt not found.','PROMPT_NOT_FOUND',404)
@router.get('/api/jobs/active')
def p_active_jobs(): return _ok({'jobs':get_job_manager().active_jobs(context=_ctx())})
@router.get('/api/jobs/{job_id}')
def p_job_get(job_id:str):
 try:return _ok({'job':get_job_manager().get_job(job_id,context=_ctx())})
 except JobNotFoundError:return _fail('Task not found.','JOB_NOT_FOUND',404)
@router.post('/api/jobs/{job_id}/cancel')
def p_job_cancel(job_id:str):
 try:return _ok({'job':get_job_manager().cancel_job(job_id,context=_ctx())})
 except JobError as e:return _fail(str(e),getattr(e,'code','JOB_ERROR'),409)
@router.get('/api/planning/overview')
def p_plan_overview(): return _ok(planning_overview(_ctx()))
@router.get('/api/planning/{kind}')
def p_plan_list(kind:str): return _ok({kind:planning_list(kind,_ctx())})
@router.post('/api/revisions')
async def p_revision(request:Request):
 try:
  d=await request.json(); r=RevisionService(_ctx()).create_revision(int(d['chapter_id']),reason=str(d.get('reason',''))); return _ok({'revision':r})
 except Exception as e:return _fail(str(e),'REVISION_ERROR',409)
@router.get('/api/revisions')
def p_revisions(): return _ok({'revisions':RevisionService(_ctx()).list_revisions()})
@router.get('/api/revisions/{revision_id}')
def p_revision_get(revision_id:str):
 try:
  svc=RevisionService(_ctx());return _ok({'revision':svc.get_revision(revision_id),'candidates':svc.list_candidates(revision_id)})
 except RevisionError as e:return _fail(str(e),e.code,404)


@router.get('/api/jobs/{job_id}/logs')
def p_job_logs(job_id:str,after:int=0,limit:int=100):
 try:return _ok(get_job_manager().get_logs(job_id,context=_ctx(),after=after,limit=limit))
 except JobNotFoundError:return _fail('Task not found.','JOB_NOT_FOUND',404)
@router.post('/api/jobs/{job_id}/retry')
def p_job_retry(job_id:str):
 try:return _ok({'job':get_job_manager().retry_job(job_id,context=_ctx())},'Retry task created.')
 except JobNotFoundError:return _fail('Task not found.','JOB_NOT_FOUND',404)
 except JobError as e:return _fail(str(e),getattr(e,'code','JOB_ERROR'),409)
@router.post('/api/planning/{kind}')
async def p_plan_create(kind:str,request:Request):
 try:return _ok({'item':planning_create(kind,(await request.json()).get('payload',{}),_ctx())})
 except Exception as e:return _fail(str(e),'PLANNING_ERROR')
@router.put('/api/planning/{kind}/{entity_id}')
async def p_plan_update(kind:str,entity_id:str,request:Request):
 try:return _ok({'item':planning_update(kind,entity_id,(await request.json()).get('payload',{}),_ctx())})
 except KeyError:return _fail('Planning item not found.','PLANNING_ITEM_NOT_FOUND',404)
@router.delete('/api/planning/{kind}/{entity_id}')
def p_plan_delete(kind:str,entity_id:str):
 try:return _ok({'item':planning_delete(kind,entity_id,_ctx())})
 except Exception as e:return _fail(str(e),'PLANNING_ERROR',409)
@router.post('/api/revisions/{revision_id}/candidates')
async def p_revision_candidate(revision_id:str,request:Request):
 try:
  d=await request.json(); c=RevisionService(_ctx()).save_candidate(revision_id,str(d.get('content','')),source=str(d.get('source','manual')),notes=str(d.get('notes','')));return _ok({'candidate':c})
 except RevisionError as e:return _fail(str(e),e.code,409)
@router.get('/api/revisions/{revision_id}/diff')
def p_revision_diff(revision_id:str):
 try:return _ok({'diff':RevisionService(_ctx()).diff(revision_id)})
 except RevisionError as e:return _fail(str(e),e.code,404)
@router.post('/api/revisions/{revision_id}/review')
async def p_revision_review(revision_id:str,request:Request):
 try:
  d=await request.json(); return _ok(RevisionService(_ctx()).review(revision_id,str(d.get('decision','')),candidate_id=d.get('candidate_version_id'),comment=str(d.get('comment','')),confirmed_risks=bool(d.get('confirmed_risks'))))
 except RevisionError as e:return _fail(str(e),e.code,409)
@router.post('/api/revisions/{revision_id}/apply')
def p_revision_apply(revision_id:str):
 try:
  r=RevisionService(_ctx()).get_revision(revision_id);j=get_job_manager().create_job('apply_revision',{'revision_id':revision_id,'chapter_id':r['chapter_id']},context=_ctx());return _ok({'job':j})
 except Exception as e:return _fail(str(e),'REVISION_APPLY_ERROR',409)
@router.post('/api/revisions/{revision_id}/cancel')
def p_revision_cancel(revision_id:str):
 try:return _ok({'revision':RevisionService(_ctx()).cancel(revision_id)},'Revision cancelled.')
 except RevisionError as e:return _fail(str(e),e.code,409)
@router.get('/api/revisions/{revision_id}/candidates')
def p_revision_candidates(revision_id:str):
 try:return _ok({'candidates':RevisionService(_ctx()).list_candidates(revision_id)})
 except RevisionError as e:return _fail(str(e),e.code,404)
@router.get('/api/revisions/{revision_id}/candidates/{candidate_id}')
def p_revision_candidate_get(revision_id:str,candidate_id:str):
 try:return _ok({'candidate':RevisionService(_ctx()).get_candidate(revision_id,candidate_id)})
 except RevisionError as e:return _fail(str(e),e.code,404)
@router.put('/api/revisions/{revision_id}/candidates/{candidate_id}')
async def p_revision_candidate_update(revision_id:str,candidate_id:str,request:Request):
 try:
  svc=RevisionService(_ctx()); prior=svc.get_candidate(revision_id,candidate_id); d=await request.json()
  content=str(d.get('content',prior['content'])); created=svc.save_candidate(revision_id,content,source=str(d.get('source','manual')),notes=str(d.get('notes','Updated from '+candidate_id)))
  return _ok({'candidate':created,'replaces_candidate_id':candidate_id},'Saved as a new immutable revision candidate.')
 except RevisionError as e:return _fail(str(e),e.code,409)
@router.post('/api/revisions/{revision_id}/quality-check')
async def p_revision_quality(revision_id:str,request:Request):
 return await _create_revision_check_job(revision_id,request,'revision_quality_check')
@router.post('/api/revisions/{revision_id}/continuity-check')
async def p_revision_continuity(revision_id:str,request:Request):
 return await _create_revision_check_job(revision_id,request,'revision_continuity_check')
@router.post('/api/revisions/{revision_id}/impact-analysis')
async def p_revision_impact(revision_id:str,request:Request):
 return await _create_revision_check_job(revision_id,request,'revision_impact_analysis')
@router.get('/api/chapters/{chapter_id}/canon-versions')
def p_canon_versions(chapter_id:int):
 try:return _ok({'versions':RevisionService(_ctx()).list_canon_versions(chapter_id)})
 except RevisionError as e:return _fail(str(e),e.code,404)
@router.get('/api/chapters/{chapter_id}/canon-versions/{version_id}')
def p_canon_version_get(chapter_id:int,version_id:str):
 try:return _ok({'version':RevisionService(_ctx()).get_canon_version(chapter_id,version_id)})
 except RevisionError as e:return _fail(str(e),e.code,404)
@router.post('/api/chapters/{chapter_id}/canon-versions/{version_id}/restore')
async def p_canon_restore(chapter_id:int,version_id:str,request:Request):
 try:
  d=await request.json();j=get_job_manager().create_job('restore_canon_version',{'chapter_id':chapter_id,'version_id':version_id,'confirmed_risks':bool(d.get('confirmed_risks'))},context=_ctx());return _ok({'job':j})
 except Exception as e:return _fail(str(e),'CANON_RESTORE_ERROR',409)
@router.get('/api/archive')
def p_archive(): return _ok({'items':RevisionService(_ctx()).list_archive()})
@router.post('/api/archive/{archive_id}/restore')
def p_archive_restore(archive_id:str):
 try:return _ok({'restore':RevisionService(_ctx()).restore_archive(archive_id)})
 except RevisionError as e:return _fail(str(e),e.code,409)


@router.post('/api/projects')
async def p_create_project(request:Request):
 try:
  data=await request.json(); return _ok({'project':get_project_manager().create_project(data)},'Project created.')
 except Exception as e:return _fail(str(e),'PROJECT_CREATE_ERROR',409)

@router.post('/api/projects/{project_id}/clone')
async def p_clone_project(project_id:str,request:Request):
 try:
  data=await request.json(); name=data.get('name',''); slug=data.get('slug'); 
  if not name:return _fail('name is required','CLONE_NAME_REQUIRED',400)
  from system.project_manager import ProjectNotFound
  try:
   result=get_project_manager().clone_project(project_id,name,slug)
   return _ok(result,'Project cloned.')
  except ProjectNotFound as e:return _fail(str(e),'PROJECT_NOT_FOUND',404)
 except ProjectManagerError as e:return _fail(str(e),'PROJECT_CLONE_ERROR',409)
 except Exception as e:return _fail(str(e),'PROJECT_CLONE_ERROR',500)
@router.get('/api/archive/{archive_id}')
def p_archive_detail(archive_id:str):
 try:return _ok({'item':RevisionService(_ctx()).get_archive(archive_id)})
 except RevisionError as e:return _fail(str(e),e.code,404)

@router.post('/api/planning/chapters/{chapter_id}/sync-next')
def p_plan_sync_next(chapter_id:str):
 try:return _ok({'plan':sync_next_plan(chapter_id,_ctx())})
 except Exception as e:return _fail(str(e),'PLANNING_SYNC_ERROR',409)


@router.get("/api/simulator/reader/personas")
def api_list_reader_personas() -> JSONResponse:
    try:
        from system.reader_persona_registry import ReaderPersonaRegistry

        registry = ReaderPersonaRegistry()
        personas = registry.list_personas()

        result = []
        for order, persona in enumerate(personas, start=1):
            result.append({
                "persona_id": persona.persona_id,
                "display_name": persona.display_name,
                "short_description": persona.description,
                "enabled": persona.enabled,
                "deterministic_order": order,
            })

        return _ok({"personas": result}, "Reader personas loaded.")
    except Exception as exc:
        return _fail(str(exc), "PERSONA_ERROR", 500)


@router.get("/api/reader-persona/options")
def api_reader_persona_options() -> JSONResponse:
    """Stable, safe Persona option metadata for planning UI."""
    return api_list_reader_personas()


@router.post("/api/simulator/reader/panels/run")
async def api_run_reader_panel(request: Request) -> JSONResponse:
    try:
        from core.project_context import bind_project_context, get_project_context
        from core.contracts.reader_persona import PanelMode, ReaderPanelRequest
        from system.reader_panel_service import ReaderPanelService

        data = await request.json()
        chapter_id = data.get("chapter_id")
        persona_ids = data.get("persona_ids", [])
        project_root = data.get("project_root")

        if chapter_id is None:
            return _fail("chapter_id is required", "CHAPTER_ID_REQUIRED", 400)

        if not isinstance(persona_ids, list) or len(persona_ids) < 2:
            return _fail("At least 2 personas required", "PERSONA_COUNT_ERROR", 400)

        context = get_project_context(project_root)

        state_path = context.data_dir / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
        project_id = state.get("project_id", "default-project")
        timeline_id = state.get("timeline_id", "main")

        req = ReaderPanelRequest(
            project_id=project_id,
            timeline_id=timeline_id,
            chapter_id=int(chapter_id),
            persona_ids=persona_ids,
            mode=PanelMode.DETERMINISTIC,
        )

        with bind_project_context(context):
            service = ReaderPanelService(context)
            run = service.run_panel(req)

        if run.status.value == "failed":
            return _fail(run.error or "Panel run failed", "PANEL_RUN_FAILED", 500)

        result = run.result
        return _ok({
            "panel_run_id": run.panel_run_id,
            "chapter_id": chapter_id,
            "persona_count": len(persona_ids),
            "panel_score": result.panel_score if result else None,
            "panel_retention_risk": result.panel_retention_risk if result else None,
            "agreement_level": result.agreement.agreement_level.value if result else None,
            "status": run.status.value,
        }, "Reader panel simulation completed.")

    except Exception as exc:
        return _fail(str(exc), "PANEL_ERROR", 500)


@router.get("/api/simulator/reader/panels")
def api_list_reader_panels(chapter_id: int | None = None, project_root: str | None = None) -> JSONResponse:
    try:
        from core.project_context import bind_project_context, get_project_context
        from system.reader_panel_store import ReaderPanelStore

        context = get_project_context(project_root)

        with bind_project_context(context):
            store = ReaderPanelStore(context)
            runs = store.list_runs(chapter_id=chapter_id)

        result = []
        for run in runs:
            staleness = store.check_run_staleness(run.panel_run_id)
            result.append({
                "panel_run_id": run.panel_run_id,
                "chapter_id": run.request.chapter_id,
                "persona_count": len(run.request.persona_ids),
                "status": run.status.value,
                "result_state": staleness.state.value,
                "panel_score": run.result.panel_score if run.result else None,
                "created_at": run.created_at.isoformat(),
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            })

        return _ok({"panels": result}, f"Found {len(result)} panel runs.")
    except Exception as exc:
        return _fail(str(exc), "PANEL_LIST_ERROR", 500)


@router.get("/api/simulator/reader/panels/{panel_run_id}")
def api_get_reader_panel(panel_run_id: str, project_root: str | None = None) -> JSONResponse:
    try:
        from core.project_context import bind_project_context, get_project_context
        from system.reader_panel_store import ReaderPanelStore

        context = get_project_context(project_root)

        with bind_project_context(context):
            store = ReaderPanelStore(context)
            run = store.load_run(panel_run_id)

        if run is None:
            return _fail("Panel run not found", "PANEL_NOT_FOUND", 404)

        staleness = store.check_run_staleness(panel_run_id)
        result_state = staleness.state.value
        stale_reasons = [r.value for r in staleness.stale_reasons]

        result = {}
        if run.result:
            persona_results = []
            for pr in run.result.persona_results:
                persona_results.append({
                    "persona_id": pr.persona_id,
                    "engagement_score": pr.engagement_score,
                    "retention_risk": pr.retention_risk,
                    "priority_flags": [
                        {"flag_code": f.flag_code, "severity": f.persona_severity, "priority": f.priority}
                        for f in pr.priority_flags
                    ],
                    "observations": [o.message for o in pr.persona_observations],
                    "optimization_priorities": [o.target for o in pr.optimization_priorities],
                })

            result = {
                "panel_score": run.result.panel_score,
                "panel_retention_risk": run.result.panel_retention_risk,
                "agreement": {
                    "score_spread": run.result.agreement.score_spread,
                    "score_stddev": run.result.agreement.score_stddev,
                    "agreement_level": run.result.agreement.agreement_level.value,
                    "shared_flag_codes": run.result.agreement.shared_flag_codes,
                },
                "disagreements": [
                    {"topic": d.topic, "persona_positions": d.persona_positions, "explanation": d.explanation}
                    for d in run.result.disagreements
                ],
                "consensus_flags": [
                    {"flag_code": f.flag_code, "severity": f.severity, "supporting_personas": f.supporting_personas}
                    for f in run.result.consensus_flags
                ],
                "minority_flags": [
                    {"flag_code": f.flag_code, "severity": f.severity, "supporting_personas": f.supporting_personas}
                    for f in run.result.minority_flags
                ],
                "panel_suggestions": [
                    {"target": s.target, "priority": s.priority, "reason": s.reason, "source_personas": s.source_personas}
                    for s in run.result.panel_suggestions
                ],
                "persona_results": persona_results,
                "panel_evaluator_version": run.result.panel_evaluator_version,
                "persona_set_fingerprint": run.result.persona_set_fingerprint,
            }

        return _ok({
            "panel_run_id": run.panel_run_id,
            "status": run.status.value,
            "result_state": result_state,
            "stale_reasons": stale_reasons,
            "chapter_id": run.request.chapter_id,
            "project_id": run.request.project_id,
            "timeline_id": run.request.timeline_id,
            "persona_ids": run.request.persona_ids,
            "result": result,
            "base_simulation_run_id": run.base_simulation_run_id,
            "snapshot_id": run.snapshot_id,
            "created_at": run.created_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }, "Panel details retrieved.")
    except Exception as exc:
        return _fail(str(exc), "PANEL_DETAIL_ERROR", 500)


@router.post("/api/simulator/reader/personas/model/run")
async def api_run_reader_persona_model(request: Request) -> JSONResponse:
    try:
        from core.project_context import bind_project_context, get_project_context
        from core.contracts.model_persona_execution import (
            ExecutionMode,
            ModelPersonaExecutionRequest,
        )
        from system.model_persona_execution_service import ModelPersonaExecutionService

        data = await request.json()
        chapter_id = data.get("chapter_id")
        persona_id = data.get("persona_id")
        mode = data.get("mode", "mock")
        execution_profile = data.get("execution_profile", "default")
        allow_model_call = bool(data.get("allow_model_call", False))
        force = bool(data.get("force", False))
        source_version_id = data.get("source_version_id")
        project_root = data.get("project_root")

        # Reject credentials or base URL in request
        if data.get("api_key") or data.get("base_url"):
            return _fail("Credentials or base URL are not accepted in request body", "FORBIDDEN_INPUT", 400)

        if chapter_id is None:
            return _fail("chapter_id is required", "CHAPTER_ID_REQUIRED", 400)
        if not persona_id or not isinstance(persona_id, str):
            return _fail("persona_id is required (single string)", "PERSONA_ID_REQUIRED", 400)
        if isinstance(persona_id, list):
            return _fail("Only one persona per request", "MULTI_PERSONA_REJECTED", 400)

        try:
            exec_mode = ExecutionMode(mode)
        except ValueError:
            return _fail(f"Unknown mode: {mode}", "INVALID_MODE", 400)
        if exec_mode == ExecutionMode.LIVE:
            return _fail("Live execution requires a server-issued consent ticket", "LIVE_REQUIRES_CONSENT_TICKET", 400)

        context = get_project_context(project_root)
        state_path = context.data_dir / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
        project_id = state.get("project_id", "default-project")
        timeline_id = state.get("timeline_id", "main")

        request_obj = ModelPersonaExecutionRequest(
            project_id=project_id,
            timeline_id=timeline_id,
            chapter_id=int(chapter_id),
            persona_id=persona_id,
            source_version_id=source_version_id,
            execution_mode=exec_mode,
            execution_profile=execution_profile,
            allow_model_call=allow_model_call,
            force=force,
        )

        with bind_project_context(context):
            service = ModelPersonaExecutionService(context)
            result = service.execute(request_obj)

        if result.status.value == "blocked":
            error_code = result.error_code or "MODEL_CALL_BLOCKED"
            if error_code == "PROVIDER_NOT_CONFIGURED":
                status_code = 503
            else:
                status_code = 400
            return _fail(result.error or error_code, error_code, status_code)

        if result.status.value == "failed":
            error_code = result.error_code or "PROVIDER_ERROR"
            status_map = {
                "PROVIDER_AUTH_ERROR": 401,
                "PROVIDER_RATE_LIMITED": 429,
                "PROVIDER_TIMEOUT": 504,
                "PROVIDER_ERROR": 502,
            }
            status_code = status_map.get(error_code, 502)
            return _fail(result.error or error_code, error_code, status_code)

        if result.status.value == "invalid_output":
            error_code = result.error_code or "MODEL_OUTPUT_INVALID"
            return _fail(
                result.error or "Model output failed validation",
                error_code,
                422,
            )

        return _ok({
            "execution_id": result.execution_id,
            "status": result.status.value,
            "persona_id": result.persona_id,
            "error_code": result.error_code,
            "cache_status": result.cache_status,
            "authoritative_scores": result.authoritative_scores.to_dict(),
            "has_feedback": result.model_feedback is not None,
            "usage": result.usage.to_dict() if result.usage else None,
        }, "Model persona execution completed.")
    except Exception as exc:
        return _fail(str(exc), "MODEL_PERSONA_ERROR", 500)


@router.get("/api/simulator/reader/personas/model/runs")
def api_list_reader_persona_model_runs(
    chapter_id: int | None = None,
    persona_id: str | None = None,
    project_root: str | None = None,
) -> JSONResponse:
    try:
        from core.project_context import bind_project_context, get_project_context
        from system.model_persona_execution_service import ModelPersonaExecutionService

        context = get_project_context(project_root)
        with bind_project_context(context):
            service = ModelPersonaExecutionService(context)
            runs = service.list_runs(chapter_id=chapter_id, persona_id=persona_id)

        result = []
        for run in runs:
            result.append({
                "execution_id": run.execution_id,
                "status": run.status.value,
                "persona_id": run.persona_id,
                "cache_status": run.cache_status,
                "created_at": run.created_at.isoformat(),
            })

        return _ok({"runs": result}, f"Found {len(result)} model persona runs.")
    except Exception as exc:
        return _fail(str(exc), "MODEL_PERSONA_LIST_ERROR", 500)


@router.get("/api/simulator/reader/personas/model/runs/{execution_id}")
def api_get_reader_persona_model_run(
    execution_id: str,
    project_root: str | None = None,
) -> JSONResponse:
    try:
        from core.project_context import bind_project_context, get_project_context
        from system.model_persona_execution_service import ModelPersonaExecutionService

        context = get_project_context(project_root)
        with bind_project_context(context):
            service = ModelPersonaExecutionService(context)
            run = service.get_run(execution_id)

        if run is None:
            return _fail(f"execution_id not found: {execution_id}", "RUN_NOT_FOUND", 404)

        result = {
            "execution_id": run.execution_id,
            "status": run.status.value,
            "persona_id": run.persona_id,
            "persona_version": run.persona_version,
            "persona_fingerprint": run.persona_fingerprint,
            "source_hash": run.source_hash,
            "context_hash": run.context_hash,
            "reader_evaluator_version": run.reader_evaluator_version,
            "prompt_template_version": run.prompt_template_version,
            "provider_id": run.provider_id,
            "model_id": run.model_id,
            "generation_parameters": run.generation_parameters.to_dict(),
            "input_fingerprint": run.input_fingerprint,
            "authoritative_scores": run.authoritative_scores.to_dict(),
            "execution_mode": run.execution_mode.value if run.execution_mode else None,
            "execution_profile": run.execution_profile,
            "execution_profile_version": run.execution_profile_version,
            "provider_config_fingerprint": run.provider_config_fingerprint,
            "error_code": run.error_code,
            "cache_status": run.cache_status,
            "usage": run.usage.to_dict() if run.usage else None,
            "warnings": run.warnings,
            "error": run.error,
            "created_at": run.created_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }

        if run.model_feedback:
            result["model_feedback"] = {
                "reader_reaction": run.model_feedback.reader_reaction,
                "overall_impression": run.model_feedback.overall_impression,
                "strengths_count": len(run.model_feedback.strengths),
                "concerns_count": len(run.model_feedback.concerns),
                "reader_questions_count": len(run.model_feedback.reader_questions),
                "optimization_directions_count": len(run.model_feedback.optimization_directions),
            }

        if run.grounding_report:
            result["grounding_report"] = {
                "valid_reference_count": run.grounding_report.valid_reference_count,
                "invalid_reference_count": run.grounding_report.invalid_reference_count,
                "unsupported_item_count": run.grounding_report.unsupported_item_count,
                "grounding_coverage": run.grounding_report.grounding_coverage,
            }

        return _ok(result, "Model persona run details retrieved.")
    except Exception as exc:
        return _fail(str(exc), "MODEL_PERSONA_DETAIL_ERROR", 500)


def _panel_result_payload(result) -> dict:
    return {
        "panel_execution_id": result.panel_execution_id, "status": result.status.value,
        "ordered_persona_ids": result.ordered_persona_ids,
        "child_execution_ids": result.child_execution_ids, "child_statuses": result.child_statuses,
        "expected_provider_call_count": result.expected_provider_call_count,
        "actual_provider_call_count": result.actual_provider_call_count,
        "cache_hit_count": result.cache_hit_count, "cache_miss_count": result.cache_miss_count,
        "usage": result.usage.to_dict() if result.usage else None,
        "usage_completeness": result.usage_completeness, "error_code": result.error_code,
        "staleness": result.staleness.value,
    }


async def _panel_request_from_http(request: Request):
    from core.contracts.model_persona_execution import ExecutionMode
    from core.contracts.model_persona_panel_execution import ModelPersonaPanelExecutionRequest
    from core.project_context import get_project_context
    data = await request.json()
    forbidden = {"api_key", "authorization", "base_url", "endpoint", "provider_secret", "provider_config"}
    if forbidden.intersection(data):
        raise ValueError("FORBIDDEN_INPUT")
    if not isinstance(data.get("persona_ids"), list):
        raise ValueError("INVALID_PERSONA_SELECTION")
    try:
        mode = ExecutionMode(data.get("mode", "mock"))
    except ValueError as exc:
        raise ValueError("INVALID_MODE") from exc
    if mode == ExecutionMode.LIVE:
        # Live has its own ticket-only routes.  This legacy parser remains for
        # Mock compatibility and must never become a Live bypass.
        raise ValueError("LIVE_REQUIRES_CONSENT_TICKET")
    project_root = data.get("project_root")
    if not project_root and data.get("project_key"):
        try:
            project = get_project_manager().get_project(str(data["project_key"]))
        except ProjectManagerError as exc:
            raise ValueError("PROJECT_NOT_FOUND") from exc
        if not project.get("valid"):
            raise ValueError("PROJECT_CONTEXT_INVALID")
        project_root = project.get("project_root")
    context = get_project_context(project_root)
    state_path = context.data_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    request_obj = ModelPersonaPanelExecutionRequest(
        project_id=state.get("project_id", "default-project"), timeline_id=state.get("timeline_id", "main"),
        chapter_id=int(data.get("chapter_id", 0)), persona_ids=data["persona_ids"],
        source_version_id=data.get("source_version_id"), execution_mode=mode,
        execution_profile=data.get("execution_profile", "default"),
        allow_model_call=bool(data.get("allow_model_call", False)),
        max_provider_calls=data.get("max_provider_calls", 1), force=bool(data.get("force", False)),
    )
    return context, request_obj


def _live_context_from_safe_project_key(data: dict):
    """Resolve a selected project without accepting a local path from Live HTTP."""
    from core.project_context import get_project_context

    forbidden = {
        "project_root", "project_id", "timeline_id", "mode", "force", "api_key",
        "authorization", "base_url", "endpoint", "provider_secret", "provider_config",
        "provider_id", "model_id", "endpoint_identity",
    }
    if forbidden.intersection(data):
        raise ValueError("FORBIDDEN_LIVE_INPUT")
    project_key = data.get("project_key")
    if not isinstance(project_key, str) or not project_key:
        raise ValueError("PROJECT_KEY_REQUIRED")
    try:
        project = get_project_manager().get_project(project_key)
    except ProjectManagerError as exc:
        raise ValueError("PROJECT_NOT_FOUND") from exc
    if not project.get("valid"):
        raise ValueError("PROJECT_CONTEXT_INVALID")
    context = get_project_context(project.get("project_root"))
    state_path = context.data_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    return context, state


@router.get("/api/reader-persona/live/profiles")
def api_list_live_execution_profiles() -> JSONResponse:
    """Safe projection only; no endpoint, credentials, or configuration detail."""
    try:
        from system.live_panel_execution_service import LivePanelExecutionService, public_live_capability

        service = LivePanelExecutionService(get_project_context())
        return _ok({"profiles": service.list_public_profiles(), "registry_revision": service.profile_registry_revision(), "capability": public_live_capability()})
    except Exception:
        return _fail("Unable to load Live execution profiles", "LIVE_PROFILE_LIST_ERROR", 500)


@router.post("/api/reader-persona/model-panel/live/consent")
async def api_issue_live_panel_consent(request: Request) -> JSONResponse:
    try:
        from core.project_context import bind_project_context
        from system.live_panel_execution_service import LivePanelExecutionService

        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError("INVALID_LIVE_REQUEST")
        context, state = _live_context_from_safe_project_key(data)
        persona_ids = data.get("persona_ids")
        if not isinstance(persona_ids, list):
            raise ValueError("INVALID_PERSONA_SELECTION")
        chapter_id = data.get("chapter_id")
        if not isinstance(chapter_id, int):
            raise ValueError("INVALID_CHAPTER_ID")
        requested_max = data.get("max_provider_calls")
        if not isinstance(requested_max, int):
            raise ValueError("INVALID_BUDGET")
        profile_id = data.get("profile_id")
        if not isinstance(profile_id, str):
            raise ValueError("INVALID_PROFILE")
        with bind_project_context(context):
            service = LivePanelExecutionService(context)
            ticket, error_code = service.issue_consent(
                project_id=state.get("project_id", "default-project"),
                timeline_id=state.get("timeline_id", "main"), chapter_id=chapter_id,
                source_version_id=data.get("source_version_id"), persona_ids=persona_ids,
                profile_id=profile_id, requested_max_provider_calls=requested_max,
                consent_text_version=data.get("consent_text_version", ""),
            )
        if ticket is None:
            return _fail("Live consent could not be issued", error_code or "LIVE_CONSENT_REJECTED", 400)
        return _ok({"ticket": ticket.to_dict()}, "Live consent issued without provider execution.")
    except ValueError as exc:
        return _fail("Invalid Live consent request", str(exc), 400)
    except Exception:
        return _fail("Unable to issue Live consent", "LIVE_CONSENT_ERROR", 500)


@router.post("/api/reader-persona/model-panel/live/runs")
async def api_run_live_panel_with_consent(request: Request, idempotency_key: str = Header(default="", alias="X-StoryOS-Idempotency-Key")) -> JSONResponse:
    try:
        from core.project_context import bind_project_context
        from system.live_panel_execution_service import LivePanelExecutionService, live_execution_ui_enabled

        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError("INVALID_LIVE_REQUEST")
        allowed = {"project_key", "ticket_id"}
        if set(data).difference(allowed):
            raise ValueError("FORBIDDEN_LIVE_INPUT")
        if not live_execution_ui_enabled():
            return _fail("Live execution is disabled", "LIVE_EXECUTION_DISABLED", 403)
        context, _state = _live_context_from_safe_project_key(data)
        ticket_id = data.get("ticket_id")
        if not isinstance(ticket_id, str) or not ticket_id:
            raise ValueError("LIVE_TICKET_REQUIRED")
        with bind_project_context(context):
            result = LivePanelExecutionService(context).execute_ticket(ticket_id, idempotency_key)
        return _ok(result, "Live execution state returned.")
    except ValueError as exc:
        return _fail("Invalid Live execution request", str(exc), 400)
    except Exception:
        return _fail("Unable to start Live execution", "LIVE_EXECUTION_ERROR", 500)


@router.post("/api/reader-persona/model-panel/live/cancel")
async def api_cancel_live_panel_execution(request: Request, idempotency_key: str = Header(default="", alias="X-StoryOS-Idempotency-Key")) -> JSONResponse:
    try:
        from core.project_context import bind_project_context
        from system.live_panel_execution_service import LivePanelExecutionService

        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError("INVALID_LIVE_REQUEST")
        context, _state = _live_context_from_safe_project_key(data)
        allowed = {"project_key", "ticket_id"}
        if set(data).difference(allowed):
            raise ValueError("FORBIDDEN_LIVE_INPUT")
        ticket_id = data.get("ticket_id")
        if not isinstance(ticket_id, str) or not ticket_id:
            raise ValueError("LIVE_TICKET_REQUIRED")
        with bind_project_context(context):
            result = LivePanelExecutionService(context).request_cancellation(ticket_id, idempotency_key)
        return _ok(result, "Live cancellation state returned.")
    except ValueError as exc:
        return _fail("Invalid Live cancellation request", str(exc), 400)
    except Exception:
        return _fail("Unable to update Live cancellation state", "LIVE_CANCELLATION_ERROR", 500)


@router.get("/api/reader-persona/model-panel/live/status/{ticket_id}")
def api_get_live_panel_status(ticket_id: str, project_key: str, idempotency_key: str = Header(default="", alias="X-StoryOS-Idempotency-Key")) -> JSONResponse:
    try:
        from core.project_context import bind_project_context
        from system.live_panel_execution_service import LivePanelExecutionService

        context, _state = _live_context_from_safe_project_key({"project_key": project_key})
        with bind_project_context(context):
            result = LivePanelExecutionService(context).recover(ticket_id, idempotency_key)
        return _ok(result, "Live execution recovery state returned.")
    except ValueError as exc:
        return _fail("Invalid Live recovery request", str(exc), 400)
    except Exception:
        return _fail("Unable to load Live execution recovery state", "LIVE_RECOVERY_ERROR", 500)


@router.post("/api/reader-persona/model-panel/plan")
async def api_plan_reader_persona_model_panel(request: Request) -> JSONResponse:
    try:
        from core.project_context import bind_project_context
        from system.model_persona_panel_execution_service import ModelPersonaPanelExecutionService
        context, request_obj = await _panel_request_from_http(request)
        with bind_project_context(context): plan = ModelPersonaPanelExecutionService(context).plan(request_obj)
        return _ok({
            "requested_persona_ids": plan.requested_persona_ids, "ordered_persona_ids": plan.ordered_persona_ids,
            "cache_hit_persona_ids": plan.cache_hit_persona_ids, "cache_miss_persona_ids": plan.cache_miss_persona_ids,
            "expected_provider_calls": plan.expected_provider_calls, "max_provider_calls": plan.max_provider_calls,
            "can_execute": plan.can_execute, "blocked_reason": plan.blocked_reason, "error_code": plan.error_code,
        }, "Model persona panel plan completed.")
    except ValueError as exc:
        return _fail("Invalid panel request", str(exc), 400)
    except Exception:
        return _fail("Unable to create model persona panel plan", "MODEL_PERSONA_PANEL_PLAN_ERROR", 500)


@router.post("/api/reader-persona/model-panel/runs")
async def api_run_reader_persona_model_panel(request: Request) -> JSONResponse:
    try:
        from core.project_context import bind_project_context
        from system.model_persona_panel_execution_service import ModelPersonaPanelExecutionService
        context, request_obj = await _panel_request_from_http(request)
        with bind_project_context(context): result = ModelPersonaPanelExecutionService(context).execute(request_obj)
        if result.status.value == "blocked":
            return _fail("Model persona panel execution blocked", result.error_code or "MODEL_CALL_BLOCKED", 503 if result.error_code == "PROVIDER_NOT_CONFIGURED" else 400)
        return _ok(_panel_result_payload(result), "Model persona panel execution completed.")
    except ValueError as exc:
        return _fail("Invalid panel request", str(exc), 400)
    except Exception:
        return _fail("Unable to run model persona panel", "MODEL_PERSONA_PANEL_ERROR", 500)


@router.get("/api/reader-persona/model-panel/runs")
def api_list_reader_persona_model_panel_runs(chapter_id: int | None = None, project_root: str | None = None) -> JSONResponse:
    try:
        from core.project_context import bind_project_context, get_project_context
        from system.model_persona_panel_execution_service import ModelPersonaPanelExecutionService
        context = get_project_context(project_root)
        with bind_project_context(context): runs = ModelPersonaPanelExecutionService(context).list_runs(chapter_id)
        return _ok({"runs": [_panel_result_payload(run) for run in runs]}, "Model persona panel runs loaded.")
    except Exception:
        return _fail("Unable to list model persona panel runs", "MODEL_PERSONA_PANEL_LIST_ERROR", 500)


@router.get("/api/reader-persona/model-panel/runs/{panel_execution_id}")
def api_get_reader_persona_model_panel_run(panel_execution_id: str, project_root: str | None = None) -> JSONResponse:
    try:
        from core.project_context import bind_project_context, get_project_context
        from system.model_persona_panel_execution_service import ModelPersonaPanelExecutionService
        context = get_project_context(project_root)
        with bind_project_context(context):
            service = ModelPersonaPanelExecutionService(context)
            run = service.get_run(panel_execution_id)
            if run is None: return _fail("Panel run not found", "PANEL_RUN_NOT_FOUND", 404)
            payload = _panel_result_payload(run)
            payload["staleness"] = service.check_staleness(panel_execution_id).value
        return _ok(payload, "Model persona panel run loaded.")
    except Exception:
        return _fail("Panel run not found", "PANEL_RUN_NOT_FOUND", 404)


@router.get("/api/reader-persona/model-panel/review")
def api_get_reader_persona_panel_review(
    chapter_id: int = Query(...),
    source_version_id: str | None = None,
    panel_execution_id: str | None = None,
    project_root: str | None = None,
) -> JSONResponse:
    try:
        from core.project_context import bind_project_context, get_project_context
        from system.model_persona_panel_review_service import ModelPersonaPanelReviewService, ModelPersonaPanelReviewServiceError
        context = get_project_context(project_root)
        with bind_project_context(context):
            review = ModelPersonaPanelReviewService(context).review(
                chapter_id=chapter_id, source_version_id=source_version_id,
                panel_execution_id=panel_execution_id,
            )
        return _ok(review.to_dict(), "Deterministic reader persona panel review loaded.")
    except ModelPersonaPanelReviewServiceError as exc:
        status = 404 if exc.code == "PANEL_RUN_NOT_FOUND" else 400
        return _fail("Panel review unavailable", exc.code, status)
    except Exception:
        return _fail("Unable to load panel review", "PANEL_REVIEW_ERROR", 500)


@router.get("/api/reader-persona/model-panel/runs/{panel_execution_id}/review")
def api_get_reader_persona_panel_run_review(
    panel_execution_id: str,
    chapter_id: int | None = None,
    source_version_id: str | None = None,
    project_root: str | None = None,
) -> JSONResponse:
    try:
        from core.project_context import bind_project_context, get_project_context
        from system.model_persona_panel_review_service import ModelPersonaPanelReviewService, ModelPersonaPanelReviewServiceError
        context = get_project_context(project_root)
        with bind_project_context(context):
            service = ModelPersonaPanelReviewService(context)
            run = service.panel_store.load_run(panel_execution_id)
            if run is None:
                return _fail("Panel run not found", "PANEL_RUN_NOT_FOUND", 404)
            if chapter_id is not None and run.chapter_id != chapter_id:
                return _fail("Panel run not found", "PANEL_RUN_NOT_FOUND", 404)
            review = service.review(
                chapter_id=run.chapter_id, source_version_id=source_version_id,
                panel_execution_id=panel_execution_id,
            )
        return _ok(review.to_dict(), "Deterministic reader persona panel review loaded.")
    except ModelPersonaPanelReviewServiceError as exc:
        status = 404 if exc.code == "PANEL_RUN_NOT_FOUND" else 400
        return _fail("Panel review unavailable", exc.code, status)
    except Exception:
        return _fail("Unable to load panel review", "PANEL_REVIEW_ERROR", 500)
