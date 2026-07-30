"""HTTP boundary for Phase 0D6-B chapter progression authority."""
from __future__ import annotations

import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from core.project_context import get_project_context
from system.cross_chapter_readiness_service import CrossChapterReadinessService
from system.cross_chapter_turn_start_service import CrossChapterTurnStartError, CrossChapterTurnStartService
from system.project_identity_resolver import ProjectIdentityResolutionError, ProjectIdentityResolver
from web.schemas import ChapterProgressionStartRequest


router = APIRouter(prefix="/api/chapter-progression", tags=["chapter-progression"])
_NO_STORE = {"Cache-Control": "no-store"}


def _project_boundary(project_id: str):
    """Resolve canonical UUIDs without falling back after UUID failure."""
    try:
        uuid.UUID(project_id)
    except (ValueError, AttributeError):
        context = get_project_context()
        if project_id != context.root.name:
            raise ProjectIdentityResolutionError("PROJECT_NOT_FOUND", "Project not found")
        return context, project_id
    identity = ProjectIdentityResolver().resolve(project_id)
    return identity.context, identity.project_id


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
        context, canonical_project_id = _project_boundary(project_id)
        result = CrossChapterReadinessService(
            context, canonical_project_id=canonical_project_id
        ).readiness(
            project_id=project_id, timeline_id=timeline_id,
            branch_id=branch_id, previous_chapter_id=previous_chapter_id)
        return _ok(result)
    except ProjectIdentityResolutionError:
        return _fail("PROJECT_NOT_FOUND", "Project not found", 404)
    except Exception:
        return _fail("BLOCKED_CORRUPT_AUTHORITY", "Readiness authority is invalid")


@router.post("/start-turn")
def start_turn(payload: ChapterProgressionStartRequest) -> JSONResponse:
    try:
        context, canonical_project_id = _project_boundary(payload.project_id)
        result = CrossChapterTurnStartService(
            context, canonical_project_id=canonical_project_id
        ).start_turn(
            **payload.model_dump())
        return _ok(result)
    except ProjectIdentityResolutionError:
        return _fail("PROJECT_NOT_FOUND", "Project not found", 404)
    except CrossChapterTurnStartError as exc:
        return _fail(exc.code, str(exc),
                     400 if exc.code == "MALFORMED_REQUEST" else 409)
    except Exception:
        return _fail("TURN_START_INTERNAL_ERROR",
                     "Turn start could not complete", 500)
