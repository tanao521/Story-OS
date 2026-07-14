"""HTTP surface for the author-confirmed creative evolution loop."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.project_context import get_project_context
from creative_loop.integration import CreativeLoop
from system.job_manager import JobError, get_job_manager
from web.view_models import api_error, api_ok

router = APIRouter(prefix="/api/creative-loop", tags=["creative-loop"])


def _loop() -> CreativeLoop: return CreativeLoop(get_project_context())
def _body(value: Any) -> dict[str, Any]: return value if isinstance(value, dict) else {}
def _failure(exc: Exception, code: str = "CREATIVE_LOOP_ERROR") -> JSONResponse: return JSONResponse(api_error(str(exc) or "创作闭环操作失败。", [code]), status_code=409)


@router.get("/overview")
def overview() -> dict[str, Any]: return api_ok(result=_loop().overview())

@router.get("/reflections")
def reflections(chapter_id: int | None = None) -> dict[str, Any]: return api_ok(result={"reflections": _loop().reflections.list(chapter_id)})

@router.get("/reflections/{reflection_id}")
def reflection(reflection_id: str) -> dict[str, Any]:
    try: return api_ok(result={"reflection": _loop().reflections.get(reflection_id)})
    except KeyError: return api_error("未找到章节复盘。", ["REFLECTION_NOT_FOUND"])

@router.post("/reflections")
async def create_reflection(request: Request) -> JSONResponse:
    data = _body(await request.json()); chapter_id = int(data.get("chapter_id") or 0)
    if chapter_id <= 0: return JSONResponse(api_error("需要有效的章节编号。", ["CHAPTER_ID_INVALID"]), status_code=422)
    try:
        job = get_job_manager().create_job("chapter_reflection", {"chapter_id": chapter_id, "force": bool(data.get("force", False)), "profile": str(data.get("profile") or "standard"), "created_by": "user"}, context=get_project_context())
        return JSONResponse(api_ok("章节复盘任务已创建。", {"job": job}), status_code=202)
    except JobError as exc: return _failure(exc, getattr(exc, "code", "JOB_ERROR"))

@router.get("/health")
def health(limit: int = 20) -> dict[str, Any]:
    service = _loop().health; return api_ok(result={"latest": service.latest(), "history": service.history(limit)})

@router.get("/system-health")
def system_health() -> dict[str, Any]: return api_ok(result={"health": _loop().system_health()})

@router.get("/analysis-profile")
def analysis_profile() -> dict[str, Any]: return api_ok(result={"profile": _loop().profiles.get()})

@router.put("/analysis-profile")
async def update_analysis_profile(request: Request) -> JSONResponse:
    try: return JSONResponse(api_ok("分析档位已保存。", {"profile": _loop().profiles.update(_body(await request.json()))}))
    except Exception as exc: return _failure(exc, "ANALYSIS_PROFILE_UPDATE_FAILED")

@router.get("/issues")
def issues(status: str | None = None) -> dict[str, Any]: return api_ok(result={"issues": _loop().issues.list(status)})

@router.patch("/issues/{issue_id}")
async def issue_status(issue_id: str, request: Request) -> JSONResponse:
    data = _body(await request.json())
    try: return JSONResponse(api_ok("问题状态已更新。", {"issue": _loop().issues.update_status(issue_id, str(data.get("status") or ""), str(data.get("reason") or ""))}))
    except Exception as exc: return _failure(exc, "ISSUE_UPDATE_FAILED")

@router.get("/proposals")
def proposals(status: str | None = None) -> dict[str, Any]: return api_ok(result={"proposals": _loop().proposals.list(status)})

@router.post("/proposals")
async def create_proposal(request: Request) -> JSONResponse:
    data = _body(await request.json())
    try:
        job = get_job_manager().create_job("generate_creative_proposal", {"issue_ids": data.get("issue_ids") if isinstance(data.get("issue_ids"), list) else [], "reflection_ids": data.get("reflection_ids") if isinstance(data.get("reflection_ids"), list) else [], "health_ids": data.get("health_ids") if isinstance(data.get("health_ids"), list) else [], "scope": data.get("scope") if isinstance(data.get("scope"), dict) else None, "title": str(data.get("title") or "")}, context=get_project_context())
        return JSONResponse(api_ok("策略提案任务已创建。", {"job": job}), status_code=202)
    except JobError as exc: return _failure(exc, getattr(exc, "code", "JOB_ERROR"))

@router.patch("/proposals/{proposal_id}")
async def decide_proposal(proposal_id: str, request: Request) -> JSONResponse:
    data = _body(await request.json())
    try: return JSONResponse(api_ok("作者决定已保存；系统未自动修改任何计划或正史。", {"proposal": _loop().proposals.decide(proposal_id, str(data.get("status") or ""), accepted_changes=data.get("accepted_changes") if isinstance(data.get("accepted_changes"), list) else [], note=str(data.get("note") or ""))}))
    except Exception as exc: return _failure(exc, "PROPOSAL_DECISION_FAILED")

@router.get("/experiments")
def experiments() -> dict[str, Any]: return api_ok(result={"experiments": _loop().experiments.list()})

@router.post("/experiments")
async def create_experiment(request: Request) -> JSONResponse:
    try: return JSONResponse(api_ok("创作实验已创建，尚未写入正史。", {"experiment": _loop().experiments.create(_body(await request.json()))}), status_code=201)
    except Exception as exc: return _failure(exc, "EXPERIMENT_CREATE_FAILED")

@router.post("/experiments/{experiment_id}/variants")
async def variants(experiment_id: str, request: Request) -> JSONResponse:
    data = _body(await request.json())
    try: return JSONResponse(api_ok("实验方案生成任务已创建。", {"job": get_job_manager().create_job("generate_experiment_variants", {"experiment_id": experiment_id, "count": int(data.get("count") or 2)}, context=get_project_context())}), status_code=202)
    except Exception as exc: return _failure(exc, "EXPERIMENT_VARIANTS_FAILED")

@router.post("/experiments/{experiment_id}/evaluate")
def evaluate(experiment_id: str) -> JSONResponse:
    try: return JSONResponse(api_ok("实验评估任务已创建。", {"job": get_job_manager().create_job("evaluate_experiment", {"experiment_id": experiment_id}, context=get_project_context())}), status_code=202)
    except Exception as exc: return _failure(exc, "EXPERIMENT_EVALUATION_FAILED")

@router.patch("/experiments/{experiment_id}/select")
async def select(experiment_id: str, request: Request) -> JSONResponse:
    data = _body(await request.json())
    try: return JSONResponse(api_ok("作者选择已保存；候选方案仍保持隔离。", {"experiment": _loop().experiments.select(experiment_id, str(data.get("variant_id") or ""))}))
    except Exception as exc: return _failure(exc, "EXPERIMENT_SELECTION_FAILED")

@router.get("/patterns")
def patterns() -> dict[str, Any]: return api_ok(result={"patterns": _loop().patterns.list()})

@router.post("/patterns")
async def create_pattern(request: Request) -> JSONResponse:
    data = _body(await request.json())
    try: return JSONResponse(api_ok("模式候选已创建，等待作者确认。", {"pattern": _loop().patterns.propose(str(data.get("kind") or ""), data.get("evidence") if isinstance(data.get("evidence"), list) else [], str(data.get("summary") or ""), data.get("conditions") if isinstance(data.get("conditions"), list) else [])}), status_code=201)
    except Exception as exc: return _failure(exc, "PATTERN_CREATE_FAILED")

@router.patch("/patterns/{pattern_id}")
async def decide_pattern(pattern_id: str, request: Request) -> JSONResponse:
    data = _body(await request.json())
    try: return JSONResponse(api_ok("模式决定已保存。", {"pattern": _loop().patterns.decide(pattern_id, bool(data.get("confirm")), str(data.get("note") or ""))}))
    except Exception as exc: return _failure(exc, "PATTERN_DECISION_FAILED")

@router.get("/evolution")
def evolution(chapter_id: int | None = None, limit: int = 100) -> dict[str, Any]: return api_ok(result={"events": _loop().evolution.timeline(chapter_id, limit)})

@router.get("/outcomes")
def outcomes() -> dict[str, Any]: return api_ok(result={"outcomes": _loop().outcomes.list()})

@router.post("/proposals/{proposal_id}/outcome")
async def proposal_outcome(proposal_id: str, request: Request) -> JSONResponse:
    data = _body(await request.json())
    try:
        proposal = _loop().proposals.get(proposal_id)
        return JSONResponse(api_ok("策略效果已按相关性方式记录。", {"outcome": _loop().outcomes.evaluate(proposal, int(data.get("after_chapter_id") or 0))}))
    except Exception as exc: return _failure(exc, "OUTCOME_EVALUATION_FAILED")
