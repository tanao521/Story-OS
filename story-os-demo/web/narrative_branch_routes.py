"""Phase 0D4-E1 Branch Lifecycle HTTP API."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.contracts.narrative_turn import NarrativeTurnError
from core.project_context import get_project_context
from system.narrative_branch_lifecycle_service import BranchLifecycleService
from web.narrative_branch_wire import branch_list_wire, branch_operation_wire, branch_wire
from web.narrative_turn_wire import error_envelope


router = APIRouter(prefix="/api/narrative-branches", tags=["narrative-branches"])
_NO_STORE = {"Cache-Control": "no-store"}


class _RequestError(Exception):
    def __init__(self, code: str, message: str, status: int) -> None:
        self.code, self.message, self.status = code, message, status


def _ok(payload: dict[str, Any]) -> JSONResponse:
    return JSONResponse(payload, headers=_NO_STORE)


def _fail(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(error_envelope(code, message, request_id=None), status_code=status, headers=_NO_STORE)


def _required(data: dict[str, Any], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value:
        raise _RequestError("MALFORMED_REQUEST", f"{name} is required", 400)
    return value


def _operation_id(data: dict[str, Any]) -> str:
    value = _required(data, "operation_id")
    if "/" in value or "\\" in value or ".." in value or not value.replace("_", "").replace("-", "").isalnum():
        raise _RequestError("INVALID_OPERATION_ID", "operation_id is invalid", 400)
    return value


def _body(request: Request) -> dict[str, Any]:
    # FastAPI's sync TestClient and production async requests both support this
    # route through the async handler below; malformed JSON is mapped safely.
    return request.state.branch_body


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception as exc:
        raise _RequestError("MALFORMED_REQUEST", "Request body must be valid JSON", 400) from exc
    if not isinstance(data, dict):
        raise _RequestError("MALFORMED_REQUEST", "Request body must be a JSON object", 400)
    return data


def _map(exc: Exception) -> tuple[str, str, int]:
    if isinstance(exc, _RequestError):
        return exc.code, exc.message, exc.status
    if isinstance(exc, NarrativeTurnError):
        mapping = {
            NarrativeTurnError.SCOPE_MISMATCH: ("PROJECT_NOT_FOUND", "Project not found", 404),
            NarrativeTurnError.PROJECT_NOT_FOUND: ("PROJECT_NOT_FOUND", "Project not found", 404),
            NarrativeTurnError.TIMELINE_NOT_FOUND: ("TIMELINE_NOT_FOUND", "Timeline not found", 404),
            NarrativeTurnError.BRANCH_NOT_FOUND: ("BRANCH_NOT_FOUND", "Branch not found", 404),
            NarrativeTurnError.PARENT_BRANCH_NOT_FOUND: ("PARENT_BRANCH_NOT_FOUND", "Parent branch not found", 404),
            NarrativeTurnError.REPLACEMENT_BRANCH_NOT_FOUND: ("REPLACEMENT_BRANCH_NOT_FOUND", "Replacement branch not found", 404),
            NarrativeTurnError.BRANCH_ALREADY_EXISTS: ("BRANCH_ALREADY_EXISTS", "Branch already exists", 409),
            NarrativeTurnError.PARENT_BRANCH_ARCHIVED: ("PARENT_BRANCH_ARCHIVED", "Parent branch is archived", 409),
            NarrativeTurnError.INVALID_REPLACEMENT_BRANCH: ("INVALID_REPLACEMENT_BRANCH", "Replacement branch is invalid", 409),
            NarrativeTurnError.INVALID_ID: ("INVALID_BRANCH_ID", "Branch identifier is invalid", 400),
            NarrativeTurnError.INVALID_FIELD: ("BRANCH_NOT_FOUND", "Branch, parent, replacement, or timeline not found", 404),
            NarrativeTurnError.BRANCH_OPERATION_STALE_REVISION: ("REGISTRY_REVISION_CONFLICT", "Registry revision is stale", 409),
            NarrativeTurnError.BRANCH_NOT_ACTIVE: ("BRANCH_ARCHIVED", "Archived branch cannot be selected", 409),
            NarrativeTurnError.BRANCH_LIFECYCLE_CONFLICT: ("ACTIVE_BRANCH_ARCHIVE_REQUIRES_REPLACEMENT", "Active branch archive requires an open replacement", 409),
            NarrativeTurnError.BRANCH_OPERATION_REPLACEMENT_ARCHIVED: ("INVALID_REPLACEMENT_BRANCH", "Replacement branch is archived or invalid", 409),
            NarrativeTurnError.BRANCH_OPERATION_CONFLICT: ("OPERATION_ID_CONFLICT", "Operation conflicts with an existing operation", 409),
            NarrativeTurnError.OPERATION_COLLISION: ("OPERATION_ID_CONFLICT", "Operation ID conflicts with another request", 409),
            NarrativeTurnError.IMMUTABLE_RECORD_EXISTS: ("BRANCH_ALREADY_EXISTS", "Branch already exists", 409),
            NarrativeTurnError.CONFIRM_RECOVERY_REQUIRED: ("BRANCH_OPERATION_RECOVERY_REQUIRED", "Branch operation recovery is required", 409),
        }
        return mapping.get(exc.code, ("INTERNAL_ERROR", "服务器内部错误。", 500))
    return "INTERNAL_ERROR", "服务器内部错误。", 500


def _service() -> BranchLifecycleService:
    return BranchLifecycleService(get_project_context())


@router.get("")
async def list_branches(project_id: str, timeline_id: str) -> JSONResponse:
    try:
        result = _service().list_branches(project_id, timeline_id)
        return _ok({"ok": True, "message": "", "result": branch_list_wire(result), "warnings": [], "errors": []})
    except Exception as exc:
        code, message, status = _map(exc)
        return _fail(code, message, status)


@router.get("/{branch_id}")
async def get_branch(branch_id: str, project_id: str, timeline_id: str) -> JSONResponse:
    try:
        result = _service().get_branch(project_id, timeline_id, branch_id)
        result["branch"] = branch_wire(result["branch"])
        return _ok({"ok": True, "message": "", "result": result, "warnings": [], "errors": []})
    except Exception as exc:
        code, message, status = _map(exc)
        return _fail(code, message, status)


async def _mutate(request: Request, operation: str) -> JSONResponse:
    try:
        data = await _json_body(request)
        operation_id = _operation_id(data)
        for field in ("project_id", "timeline_id", "branch_id"):
            _required(data, field)
        result = getattr(_service(), operation)(operation_id, data)
        result["operation_type"] = operation
        return _ok({"ok": True, "message": "", "result": branch_operation_wire(result), "warnings": [], "errors": []})
    except Exception as exc:
        code, message, status = _map(exc)
        return _fail(code, message, status)


@router.post("/create")
async def create_branch(request: Request) -> JSONResponse:
    return await _mutate(request, "create")


@router.post("/select")
async def select_branch(request: Request) -> JSONResponse:
    return await _mutate(request, "select")


@router.post("/archive")
async def archive_branch(request: Request) -> JSONResponse:
    return await _mutate(request, "archive")


@router.post("/restore")
async def restore_branch(request: Request) -> JSONResponse:
    return await _mutate(request, "restore")
