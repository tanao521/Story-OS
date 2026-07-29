"""Explicit branch-scoped NarrativeMemory HTTP API (Phase 0D4-E2)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse

from core.project_context import get_project_context
from system.branch_narrative_memory_service import (
    BranchMemoryArchived,
    BranchMemoryConflict,
    BranchMemoryInactive,
    BranchMemoryNotFound,
    BranchMemoryScopeError,
    BranchMemoryService,
    BranchNarrativeMemoryError,
    MigrationError,
    NarrativeMemoryMigrationService,
)


router = APIRouter()


def _ok(result: Any, message: str = "") -> JSONResponse:
    return JSONResponse({"ok": True, "message": message, "result": result, "warnings": [], "errors": []}, headers={"Cache-Control": "no-store"})


def _error(exc: Exception) -> JSONResponse:
    code = getattr(exc, "code", "BRANCH_MEMORY_ERROR")
    status = 404 if isinstance(exc, BranchMemoryNotFound) else 409 if isinstance(exc, (BranchMemoryArchived, BranchMemoryInactive, BranchMemoryConflict, MigrationError)) else 400
    return JSONResponse({"ok": False, "message": str(exc), "result": {}, "warnings": [], "errors": [code]}, status_code=status, headers={"Cache-Control": "no-store"})


def _service(project_id: str, timeline_id: str, branch_id: str) -> tuple[BranchMemoryService, Any]:
    service = BranchMemoryService(get_project_context())
    return service, service.scope(project_id, timeline_id, branch_id)


@router.get("/api/narrative-memory/branch/events")
def branch_events(project_id: str = Query(...), timeline_id: str = Query(...), branch_id: str = Query(...), chapter_id: int | None = None, administrative: bool = False):
    try:
        service, scope = _service(project_id, timeline_id, branch_id)
        return _ok({"events": service.events(scope, branch_id, chapter_id, administrative=administrative)})
    except Exception as exc:
        return _error(exc)


@router.post("/api/narrative-memory/branch/events")
def branch_append_event(payload: dict[str, Any] = Body(...)):
    try:
        service, scope = _service(payload.get("project_id"), payload.get("timeline_id"), payload.get("branch_id"))
        return _ok({"event": service.append_event(scope, payload["branch_id"], payload, operation_id=payload.get("operation_id"))}, "Branch memory event appended.")
    except Exception as exc:
        return _error(exc)


@router.post("/api/narrative-memory/branch/events/{event_id}/confirm")
def branch_confirm_event(event_id: str, payload: dict[str, Any] = Body(...)):
    try:
        service, scope = _service(payload.get("project_id"), payload.get("timeline_id"), payload.get("branch_id"))
        return _ok({"event": service.confirm_event(scope, payload["branch_id"], event_id, payload.get("status", "confirmed"), payload.get("patch"))}, "Branch memory event updated.")
    except Exception as exc:
        return _error(exc)


@router.get("/api/narrative-memory/branch/snapshots/{chapter_id}")
def branch_snapshot(chapter_id: int, project_id: str = Query(...), timeline_id: str = Query(...), branch_id: str = Query(...), administrative: bool = False):
    try:
        service, scope = _service(project_id, timeline_id, branch_id)
        path = service._path("snapshots", scope, branch_id, f"chapter_{chapter_id:03d}.json")
        branch = service._branch(scope, branch_id)
        if getattr(branch, "lifecycle_status", None).value == "archived" and not administrative:
            raise BranchMemoryArchived("Archived branch reads require administrative=true")
        snapshot = service._read(path, None)
        if snapshot is None:
            raise BranchMemoryNotFound("Snapshot not found")
        return _ok({"snapshot": snapshot})
    except Exception as exc:
        return _error(exc)


@router.post("/api/narrative-memory/branch/snapshots/{chapter_id}")
def branch_create_snapshot(chapter_id: int, payload: dict[str, Any] = Body(...)):
    try:
        service, scope = _service(payload.get("project_id"), payload.get("timeline_id"), payload.get("branch_id"))
        return _ok({"snapshot": service.snapshot(scope, payload["branch_id"], chapter_id, state_revision=payload.get("state_revision"))}, "Branch snapshot saved.")
    except Exception as exc:
        return _error(exc)


@router.post("/api/narrative-memory/branch/overrides/{kind}")
def branch_override(kind: str, payload: dict[str, Any] = Body(...)):
    try:
        service, scope = _service(payload.get("project_id"), payload.get("timeline_id"), payload.get("branch_id"))
        return _ok({"override": service.override(scope, payload["branch_id"], kind, payload.get("value"))}, "Branch override saved.")
    except Exception as exc:
        return _error(exc)


@router.get("/api/narrative-memory/branch/retrieval-history")
def branch_retrieval_history(project_id: str = Query(...), timeline_id: str = Query(...), branch_id: str = Query(...), administrative: bool = False):
    try:
        service, scope = _service(project_id, timeline_id, branch_id)
        return _ok(service.retrieval_history(scope, branch_id, administrative=administrative))
    except Exception as exc:
        return _error(exc)


@router.post("/api/narrative-memory/branch/retrieval-history")
def branch_record_retrieval(payload: dict[str, Any] = Body(...)):
    try:
        service, scope = _service(payload.get("project_id"), payload.get("timeline_id"), payload.get("branch_id"))
        return _ok(service.retrieval_history(scope, payload["branch_id"], chapter_id=payload.get("chapter_id"), selected=payload.get("selected", [])), "Branch retrieval history recorded.")
    except Exception as exc:
        return _error(exc)


@router.get("/api/narrative-memory/branch/state")
def branch_state(project_id: str = Query(...), timeline_id: str = Query(...), branch_id: str = Query(...), administrative: bool = False):
    try:
        service, scope = _service(project_id, timeline_id, branch_id)
        branch = service._branch(scope, branch_id)
        if branch.lifecycle_status.value == "archived" and not administrative:
            raise BranchMemoryArchived("Archived branch reads require administrative=true")
        path = service._path("state", scope, branch_id, "current.json")
        return _ok({"state": service._read(path, {}) or {}})
    except Exception as exc:
        return _error(exc)


@router.post("/api/narrative-memory/migrations/plan")
def migration_plan(payload: dict[str, Any] = Body(...)):
    try:
        service = NarrativeMemoryMigrationService(get_project_context())
        return _ok({"plan": service.plan(operation_id=payload.get("operation_id"), project_id=payload.get("project_id"), timeline_id=payload.get("timeline_id"), target_branch_id=payload.get("target_branch_id"), mode=payload.get("mode", "dry_run"), legacy_scope_acknowledged=payload.get("legacy_scope_acknowledged") is True)})
    except Exception as exc:
        return _error(exc)


@router.post("/api/narrative-memory/migrations/execute")
def migration_execute(payload: dict[str, Any] = Body(...)):
    try:
        service = NarrativeMemoryMigrationService(get_project_context())
        plan = payload.get("plan") if isinstance(payload.get("plan"), dict) else payload
        return _ok(service.execute(plan, operation_id=payload.get("operation_id") or plan.get("operation_id"), dry_run_plan_fingerprint=payload.get("dry_run_plan_fingerprint") or plan.get("dry_run_plan_fingerprint")), "Legacy NarrativeMemory copied into explicit branch scope.")
    except Exception as exc:
        return _error(exc)
