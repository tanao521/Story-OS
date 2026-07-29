"""HTTP boundary for Phase 0D6-B chapter progression authority."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from core.project_context import get_project_context
from system.cross_chapter_readiness_service import CrossChapterReadinessService
from system.cross_chapter_turn_start_service import CrossChapterTurnStartError, CrossChapterTurnStartService
from web.schemas import ChapterProgressionStartRequest


router = APIRouter(prefix="/api/chapter-progression", tags=["chapter-progression"])
_NO_STORE = {"Cache-Control": "no-store"}


def _ok(result: dict) -> JSONResponse:
    return JSONResponse(
        {"ok": True, "message": "", "result": result,
         "warnings": result.get("warnings", []), "errors": []},
        headers=_NO_STORE)


def _fail(code: str, message: str, status: int = 409) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "message": message, "result": {},
         "warnings": [], "errors": [code]},
        status_code=status, headers=_NO_STORE)


@router.get("/readiness")
def readiness(project_id: str, timeline_id: str = "main",
              branch_id: str | None = None,
              previous_chapter_id: int | None = None) -> JSONResponse:
    try:
        result = CrossChapterReadinessService(get_project_context()).readiness(
            project_id=project_id, timeline_id=timeline_id,
            branch_id=branch_id, previous_chapter_id=previous_chapter_id)
        return _ok(result)
    except Exception:
        return _fail("BLOCKED_CORRUPT_AUTHORITY", "Readiness authority is invalid")


@router.post("/start-turn")
def start_turn(payload: ChapterProgressionStartRequest) -> JSONResponse:
    try:
        result = CrossChapterTurnStartService(get_project_context()).start_turn(
            **payload.model_dump())
        return _ok(result)
    except CrossChapterTurnStartError as exc:
        return _fail(exc.code, str(exc),
                     400 if exc.code == "MALFORMED_REQUEST" else 409)
    except Exception:
        return _fail("TURN_START_INTERNAL_ERROR",
                     "Turn start could not complete", 500)
