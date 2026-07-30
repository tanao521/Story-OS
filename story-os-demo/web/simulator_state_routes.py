"""Read-only Simulator product state endpoint (Phase 0D5-B)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.project_context import get_project_context
from system.project_identity_resolver import (
    ProjectIdentityResolutionError,
    ProjectIdentityResolver,
    ResolvedProjectIdentity,
)
from system.simulator_loop_state import SimulatorLoopStateError, SimulatorLoopStateService

router = APIRouter(prefix="/api/simulator", tags=["simulator"])
_NO_STORE = {"Cache-Control": "no-store"}


def _fail(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse({"ok": False, "error": {"code": code, "message": message}, "result": {}, "warnings": [], "errors": [code]}, status_code=status, headers=_NO_STORE)


def _project_boundary(project_id: str) -> ResolvedProjectIdentity:
    try:
        uuid.UUID(project_id)
    except (ValueError, AttributeError):
        context = get_project_context()
        if project_id != context.root.name:
            raise ProjectIdentityResolutionError("PROJECT_NOT_FOUND", "Project not found")
        return ResolvedProjectIdentity(project_id, project_id, context)
    return ProjectIdentityResolver().resolve(project_id)


@router.get("/state")
def simulator_state(request: Request) -> JSONResponse:
    params = request.query_params
    try:
        chapter_raw = params.get("chapter_id")
        chapter_id = int(chapter_raw) if chapter_raw is not None else 0
        project_id = str(params.get("project_id") or "")
        identity = _project_boundary(project_id)
        state = SimulatorLoopStateService(
            identity.context, canonical_project_id=identity.project_id
        ).build(
            project_id=identity.project_id,
            timeline_id=str(params.get("timeline_id") or ""),
            chapter_id=chapter_id,
            branch_id=str(params.get("branch_id") or ""),
            source_version_id=params.get("source_version_id") or None,
        )
        return JSONResponse({"ok": True, "result": state.to_dict(), "warnings": [], "errors": []}, headers=_NO_STORE)
    except ProjectIdentityResolutionError as exc:
        status = 404 if exc.code == "PROJECT_NOT_FOUND" else 503
        return _fail(exc.code, str(exc), status)
    except SimulatorLoopStateError as exc:
        status = 404 if exc.code in {"PROJECT_NOT_FOUND", "BRANCH_NOT_FOUND"} else 400
        return _fail(exc.code, str(exc), status)
    except Exception:
        return _fail("SIMULATOR_STATE_UNAVAILABLE", "Simulator state is unavailable", 500)
