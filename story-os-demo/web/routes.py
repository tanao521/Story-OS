from __future__ import annotations

import json
import inspect
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Query, Request
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
    return guarded(lambda: command_response(commands.initialize_vector_index_command(rebuild=bool(payload.get("rebuild", False)))))




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


def _continuity_source_hashes(chapter_id: int, current_text: str) -> tuple[str, str]:
    previous_text = ""
    if chapter_id > 1:
        previous_path = Path("data") / "chapters" / f"chapter_{chapter_id - 1:03d}.md"
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
        previous_path = Path("data") / "chapters" / f"chapter_{chapter_id - 1:03d}.md"
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
@router.get("/api/narrative-memory/overview")
def nm_overview(): return JSONResponse({"ok":True,"message":"","result":_nm().overview(),"warnings":[],"errors":[]})
@router.get("/api/narrative-memory/events")
def nm_events(chapter_id:int|None=None): return JSONResponse({"ok":True,"message":"","result":{"events":_nm().events(chapter_id)},"warnings":[],"errors":[]})
@router.post("/api/narrative-memory/chapters/{chapter_id}/extract")
def nm_extract(chapter_id:int):
 try:return JSONResponse({"ok":True,"message":"","result":{"events":_nm().extract(chapter_id)},"warnings":[],"errors":[]})
 except Exception as exc:return JSONResponse({"ok":False,"message":"Extraction failed.","result":{},"warnings":[],"errors":[str(exc)[:300]]},status_code=409)
@router.get("/api/narrative-memory/timeline")
def nm_timeline(): return JSONResponse({"ok":True,"message":"","result":{"timeline":_nm().store.read_json('data/narrative_memory/timeline.json',default=[],expected_type=list) or []},"warnings":[],"errors":[]})
@router.get("/api/narrative-memory/conflicts")
def nm_conflicts(): return JSONResponse({"ok":True,"message":"","result":{"conflicts":_nm().conflicts()},"warnings":[],"errors":[]})
@router.post("/api/continuity/preflight")
async def nm_preflight(request:Request):
 p=await request.json(); r=_nm().preflight(int(p.get('chapter_id',1))); return JSONResponse({"ok":r['status']!='blocked',"message":"","result":r,"warnings":[],"errors":[]},status_code=409 if r['status']=='blocked' else 200)
@router.post("/api/narrative-memory/events/{event_id}/confirm")
async def nm_confirm(event_id:str,request:Request):
 try:
  payload=await request.json(); decision=str(payload.get('decision','confirmed')); patch=payload.get('patch') or {}
  if decision not in {'confirmed','corrected','rejected'}: return _fail('Invalid confirmation decision.','INVALID_CONFIRMATION',422)
  if not isinstance(patch,dict): return _fail('Event patch must be an object.','INVALID_EVENT_PATCH',422)
  return _ok({'event':_nm().confirm(event_id,decision,patch)},'Narrative event updated.')
 except EventNotFound:return _fail('Narrative event not found.','NARRATIVE_EVENT_NOT_FOUND',404)
 except NarrativeMemoryError as exc:return _fail(str(exc),getattr(exc,'code','NARRATIVE_MEMORY_ERROR'),409)
@router.post("/api/narrative-memory/project")
def nm_project(): return _ok({'state':_nm().project()},'Narrative state projection rebuilt.')
@router.post("/api/narrative-memory/chapters/{chapter_id}/snapshot")
def nm_snapshot(chapter_id:int):
 try:return _ok({'snapshot':_nm().snapshot(chapter_id)},'Narrative snapshot saved.')
 except Exception as exc:return _fail(str(exc),'NARRATIVE_SNAPSHOT_ERROR',409)
@router.get("/api/narrative-memory/context-preview")
def nm_preview(chapter_id:int=1):
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
 return _ok({'preview':preview})
@router.post("/api/narrative-memory/overrides/{kind}")
async def nm_override(kind:str,request:Request):
 try:
  payload=await request.json(); return _ok({'values':_nm().set_override(kind,payload.get('value'))},'Narrative override saved.')
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
@router.get('/api/archive/{archive_id}')
def p_archive_detail(archive_id:str):
 try:return _ok({'item':RevisionService(_ctx()).get_archive(archive_id)})
 except RevisionError as e:return _fail(str(e),e.code,404)

@router.post('/api/planning/chapters/{chapter_id}/sync-next')
def p_plan_sync_next(chapter_id:str):
 try:return _ok({'plan':sync_next_plan(chapter_id,_ctx())})
 except Exception as e:return _fail(str(e),'PLANNING_SYNC_ERROR',409)
