"""HTTP boundary for project-scoped commercial writing analytics."""
from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from analytics.service import AnalyticsService
from core.project_context import get_project_context
from web.view_models import api_error, api_ok

router = APIRouter(tags=["analytics"])

def _service() -> AnalyticsService: return AnalyticsService(get_project_context())
def _ok(result: dict[str, Any], message: str = "Analytics updated.") -> JSONResponse: return JSONResponse(api_ok(message, result))
async def _body(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except Exception: return {}

@router.get("/api/analytics/project")
def project_analytics() -> JSONResponse: return _ok(_service().dashboard(), "Project analytics loaded.")
@router.put("/api/analytics/project")
async def update_project_analytics(request: Request) -> JSONResponse: return _ok({"profile": _service().update_profile(await _body(request))}, "Story analytics profile saved.")
@router.post("/api/analytics/market")
async def market(request: Request) -> JSONResponse: return _ok({"market": _service().market(await _body(request))}, "Market analysis generated.")
@router.post("/api/analytics/audience")
async def audience(request: Request) -> JSONResponse: return _ok({"audience": _service().audience(await _body(request))}, "Audience simulation generated.")
@router.get("/api/analytics/chapter/{chapter_id}")
def chapter(chapter_id: int) -> JSONResponse: return _ok({"chapter": _service().chapter(chapter_id)}, "Chapter analysis generated.")
@router.get("/api/analytics/retention")
def retention() -> JSONResponse: return _ok({"retention": _service().retention()}, "Retention simulation generated.")
@router.get("/api/analytics/emotion")
def emotion(chapter_id: int = 1) -> JSONResponse: return _ok({"emotion": _service().chapter(chapter_id).get("emotion_curve", [])}, "Emotion timeline generated.")
@router.get("/api/analytics/satisfaction")
def satisfaction(chapter_id: int = 1) -> JSONResponse: return _ok({"satisfaction": _service().chapter(chapter_id).get("satisfaction_points", [])}, "Satisfaction analysis generated.")
@router.get("/api/analytics/report")
def report() -> JSONResponse: return _ok({"report": _service().report()}, "Story market report generated.")
