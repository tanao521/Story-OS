"""Phase 0D4-C read-only Narrative Turn HTTP endpoints.

Endpoints:
    GET  /api/narrative-turn/context       → ContextWireDTO
    GET  /api/narrative-turn/plan          → PlanWireDTO
    POST /api/narrative-turn/feasibility   → ValidationWireDTO
    POST /api/narrative-turn/preview       → PreviewWireDTO

Security boundaries (all enforced as 0 in 0D4-C):
- No Provider calls
- No NarrativeTurnStore.append_* calls
- No NarrativeTurnResult creation
- No NarrativeTurnTransition append
- No Turn confirmation
- No branch create/select/archive/restore
- No branch lifecycle writes
- No NarrativeMemory writes
- No Canon writes
- No Chroma writes
- No real project data writes
- No filesystem writes from this module

All responses include ``Cache-Control: no-store``.
All error responses use the unified envelope with ``code``, ``message``,
and ``request_id`` (always null in 0D4-C).
Custom action raw text never enters URL, logs, response, or exception text.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.contracts.narrative_turn import (
    ActionSource,
    NarrativeScope,
    NarrativeTurnError,
)
from core.project_context import get_project_context
from system.narrative_action_feasibility import (
    MAX_CUSTOM_ACTION_LENGTH,
    NarrativeActionFeasibility,
    normalize_custom_action,
)
from system.narrative_turn_context import NarrativeTurnContextBinder
from system.narrative_turn_planner import NarrativeTurnPlanner
from system.narrative_turn_preview import NarrativeTurnPreviewService
from system.narrative_turn_service import NarrativeTurnService
from web.narrative_turn_wire import (
    assert_json_safe,
    build_confirm_result_wire_dto,
    build_context_wire_dto,
    build_plan_wire_dto,
    build_preview_wire_dto,
    build_validation_wire_dto,
    error_envelope,
)


router = APIRouter(prefix="/api/narrative-turn", tags=["narrative-turn"])

_NO_STORE_HEADERS = {"Cache-Control": "no-store"}

_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _ok(payload: dict[str, Any]) -> JSONResponse:
    """Return 200 with Cache-Control: no-store and JSON-safe payload."""
    assert_json_safe(payload)
    return JSONResponse(payload, headers=_NO_STORE_HEADERS)


def _fail(code: str, message: str, status: int) -> JSONResponse:
    """Return an error envelope with the given HTTP status."""
    return JSONResponse(
        error_envelope(code, message, request_id=None),
        status_code=status,
        headers=_NO_STORE_HEADERS,
    )


def _require_id(value: str | None, name: str) -> str:
    if value is None or not isinstance(value, str) or not value:
        raise _RequestError("MALFORMED_REQUEST", f"{name} is required", 400)
    if not _ID_PATTERN.fullmatch(value):
        raise _RequestError("MALFORMED_REQUEST", f"{name} is invalid", 400)
    return value


def _require_chapter_id(value: str | None) -> int:
    if value is None or not isinstance(value, str) or not value:
        raise _RequestError("MALFORMED_REQUEST", "chapter_id is required", 400)
    if not re.fullmatch(r"\d{1,7}", value):
        raise _RequestError("MALFORMED_REQUEST", "chapter_id must be a positive integer", 400)
    try:
        chapter_id = int(value)
    except (TypeError, ValueError) as exc:
        raise _RequestError("MALFORMED_REQUEST", "chapter_id must be an integer", 400) from exc
    if chapter_id <= 0:
        raise _RequestError("MALFORMED_REQUEST", "chapter_id must be positive", 400)
    return chapter_id


def _optional_fingerprint(value: str | None, name: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not _FINGERPRINT_PATTERN.fullmatch(value):
        raise _RequestError("MALFORMED_REQUEST", f"{name} must be a 64-char hex SHA-256", 400)
    return value


class _RequestError(Exception):
    """Internal control-flow error carrying an HTTP status and code.

    The message must never include raw custom action text, absolute
    paths, or tracebacks.
    """

    def __init__(self, code: str, message: str, status: int) -> None:
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


# ---------------------------------------------------------------------------
# Domain → HTTP error mapping
# ---------------------------------------------------------------------------

def _map_domain_error(exc: NarrativeTurnError) -> _RequestError:
    """Map a NarrativeTurnError to an HTTP error envelope.

    Never leaks absolute paths, raw exceptions, or custom action raw
    text. The message is derived only from the error code and a
    user-safe message.
    """
    code = exc.code
    safe_messages = {
        NarrativeTurnError.SCOPE_MISMATCH: ("SCOPE_MISMATCH", "作用域不匹配，请确认 project/timeline/branch。", 404),
        NarrativeTurnError.MISSING_PARENT_BRANCH: ("BRANCH_NOT_FOUND", "分支不存在或已删除。", 404),
        NarrativeTurnError.BRANCH_LIFECYCLE_CONFLICT: ("BRANCH_ARCHIVED", "分支已归档，无法进行叙事回合操作。", 409),
        NarrativeTurnError.ACTION_INVALID: ("ACTION_INVALID", "行动输入无效。", 422),
        NarrativeTurnError.INVALID_FIELD: ("MALFORMED_REQUEST", "请求字段无效。", 400),
        NarrativeTurnError.INVALID_ID: ("MALFORMED_REQUEST", "ID 格式无效。", 400),
        NarrativeTurnError.INVALID_FINGERPRINT: ("MALFORMED_REQUEST", "指纹格式无效。", 400),
        NarrativeTurnError.INVALID_ENUM: ("MALFORMED_REQUEST", "枚举值无效。", 400),
        NarrativeTurnError.INVALID_TYPE: ("MALFORMED_REQUEST", "字段类型无效。", 400),
        NarrativeTurnError.INVALID_DATETIME: ("MALFORMED_REQUEST", "时间戳格式无效。", 400),
        NarrativeTurnError.INVALID_ACTION_COUNT: ("PLAN_INVALID", "推荐行动数量不合法。", 500),
        NarrativeTurnError.INVALID_ACTION_ORDER: ("PLAN_INVALID", "推荐行动顺序不合法。", 500),
        NarrativeTurnError.DUPLICATE_ACTION_ID: ("PLAN_INVALID", "推荐行动 ID 冲突。", 500),
        NarrativeTurnError.DUPLICATE_ACTION_INTENT: ("PLAN_INVALID", "推荐行动意图冲突。", 500),
        NarrativeTurnError.VALIDATION_ACTION_XOR: ("ACTION_INVALID", "行动来源冲突。", 422),
        NarrativeTurnError.BRANCH_NOT_ACTIVE: ("BRANCH_NOT_ACTIVE", "分支未激活。", 409),
        NarrativeTurnError.OPERATION_COLLISION: ("OPERATION_ID_CONFLICT", "操作 ID 已存在或与其他操作冲突。", 409),
        NarrativeTurnError.IMMUTABLE_RECORD_EXISTS: ("TURN_ALREADY_CONFIRMED", "该回合已被确认。", 409),
        NarrativeTurnError.TRANSITION_COLLISION: ("TURN_ALREADY_CONFIRMED", "该回合已被确认。", 409),
        NarrativeTurnError.BRANCH_OPERATION_STALE_REVISION: ("BRANCH_STATE_REVISION_CONFLICT", "分支状态版本冲突。", 409),
        NarrativeTurnError.LIFECYCLE_EVENT_CHAIN_CORRUPT: ("INTERNAL_ERROR", "服务器内部错误。", 500),
        NarrativeTurnError.ILLEGAL_TRANSITION: ("TURN_ALREADY_CONFIRMED", "该回合状态不允许此操作。", 409),
    }
    if code in safe_messages:
        mapped_code, message, status = safe_messages[code]
        return _RequestError(mapped_code, message, status)
    # Fall-back: 500 safe internal error. Never leak exc info.
    return _RequestError("INTERNAL_ERROR", "服务器内部错误。", 500)


# ---------------------------------------------------------------------------
# Common scope + binding helpers
# ---------------------------------------------------------------------------

def _build_scope(
    project_id: str,
    timeline_id: str,
    branch_id: str,
) -> NarrativeScope:
    return NarrativeScope(
        project_id=_require_id(project_id, "project_id"),
        timeline_id=_require_id(timeline_id, "timeline_id"),
        branch_id=_require_id(branch_id, "branch_id"),
    )


def _bind_context(
    scope: NarrativeScope,
    chapter_id: int,
    source_version_id: str | None,
) -> Any:
    """Bind context using the read-only NarrativeTurnContextBinder.

    ProjectContext is sourced from the active project bound by the
    FastAPI middleware in ``web.app``. We never write to any store
    here; the binder is read-only.
    """
    project_context = get_project_context()
    binder = NarrativeTurnContextBinder(project_context)
    if scope.project_id != project_context.root.name:
        raise _RequestError(
            "SCOPE_MISMATCH",
            "project_id 与当前活动项目不匹配。",
            404,
        )
    try:
        return binder.bind(
            scope,
            chapter_id,
            source_version_id=source_version_id or None,
        )
    except NarrativeTurnError as exc:
        raise _map_domain_error(exc) from exc
    except (FileNotFoundError, OSError) as exc:
        # Project files missing — never leak absolute paths.
        raise _RequestError(
            "PROJECT_DATA_MISSING",
            "项目数据不可读，请检查项目初始化状态。",
            404,
        ) from exc


def _build_plan(snapshot: Any) -> Any:
    try:
        return NarrativeTurnPlanner.build_plan(
            snapshot,
            parent_turn_id=None,
            clock_now=_utc_now(),
        )
    except NarrativeTurnError as exc:
        raise _map_domain_error(exc) from exc


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/context")
def get_context(request: Request) -> JSONResponse:
    """GET /api/narrative-turn/context → ContextWireDTO."""
    try:
        params = request.query_params
        scope = _build_scope(
            params.get("project_id"),
            params.get("timeline_id"),
            params.get("branch_id"),
        )
        chapter_id = _require_chapter_id(params.get("chapter_id"))
        source_version_id = params.get("source_version_id") or None
        if source_version_id:
            _require_id(source_version_id, "source_version_id")

        snapshot = _bind_context(scope, chapter_id, source_version_id)
        dto = build_context_wire_dto(snapshot)
        return _ok(dto)
    except _RequestError as err:
        return _fail(err.code, err.message, err.status)
    except Exception:  # pragma: no cover — defensive guard
        return _fail("INTERNAL_ERROR", "服务器内部错误。", 500)


@router.get("/plan")
def get_plan(request: Request) -> JSONResponse:
    """GET /api/narrative-turn/plan → PlanWireDTO.

    Server rebuilds the plan deterministically; it never persists the
    Plan and never queries NarrativeTurnStore.
    """
    try:
        params = request.query_params
        scope = _build_scope(
            params.get("project_id"),
            params.get("timeline_id"),
            params.get("branch_id"),
        )
        chapter_id = _require_chapter_id(params.get("chapter_id"))
        source_version_id = params.get("source_version_id") or None
        if source_version_id:
            _require_id(source_version_id, "source_version_id")

        snapshot = _bind_context(scope, chapter_id, source_version_id)
        plan = _build_plan(snapshot)
        dto = build_plan_wire_dto(plan)
        return _ok(dto)
    except _RequestError as err:
        return _fail(err.code, err.message, err.status)
    except Exception:  # pragma: no cover — defensive guard
        return _fail("INTERNAL_ERROR", "服务器内部错误。", 500)


async def _read_json_body(request: Request) -> dict[str, Any]:
    """Read JSON body. Never raises with raw text content."""
    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise _RequestError("MALFORMED_REQUEST", "请求体不是合法的 JSON 对象。", 400)
    if not isinstance(body, dict):
        raise _RequestError("MALFORMED_REQUEST", "请求体必须是 JSON 对象。", 400)
    return body


def _extract_scope_and_chapter(body: dict[str, Any]) -> tuple[NarrativeScope, int, str | None, str | None, str | None]:
    project_id = body.get("project_id")
    timeline_id = body.get("timeline_id")
    branch_id = body.get("branch_id")
    scope = _build_scope(project_id, timeline_id, branch_id)

    chapter_raw = body.get("chapter_id")
    if chapter_raw is None:
        raise _RequestError("MALFORMED_REQUEST", "chapter_id is required", 400)
    if isinstance(chapter_raw, int):
        if chapter_raw <= 0:
            raise _RequestError("MALFORMED_REQUEST", "chapter_id must be positive", 400)
        chapter_id = chapter_raw
    elif isinstance(chapter_raw, str):
        chapter_id = _require_chapter_id(chapter_raw)
    else:
        raise _RequestError("MALFORMED_REQUEST", "chapter_id must be an integer or string", 400)

    source_version_id = body.get("source_version_id")
    if source_version_id is not None:
        if not isinstance(source_version_id, str):
            raise _RequestError("MALFORMED_REQUEST", "source_version_id must be a string", 400)
        if source_version_id:
            _require_id(source_version_id, "source_version_id")

    expected_fp = _optional_fingerprint(body.get("expected_context_fingerprint"), "expected_context_fingerprint")
    expected_turn_id_raw = body.get("expected_turn_id")
    expected_turn_id: str | None = None
    if expected_turn_id_raw is not None and expected_turn_id_raw != "":
        if not isinstance(expected_turn_id_raw, str):
            raise _RequestError("MALFORMED_REQUEST", "expected_turn_id must be a string", 400)
        _require_id(expected_turn_id_raw, "expected_turn_id")
        expected_turn_id = expected_turn_id_raw

    return scope, chapter_id, source_version_id or None, expected_fp, expected_turn_id


def _resolve_action_for_feasibility(
    body: dict[str, Any],
    plan: Any,
) -> tuple[str, Any | None, Any | None, str | None]:
    """Resolve action_source + selected action / normalized custom text.

    Returns ``(action_source, selected_action, normalized_custom, custom_raw_text)``.

    The ``custom_raw_text`` is held only in this function's locals; it
    never enters logs, exception text, or the response. The caller
    discards it after feasibility validation completes.
    """
    action_source_raw = body.get("action_source")
    if not isinstance(action_source_raw, str):
        raise _RequestError("MALFORMED_REQUEST", "action_source is required", 400)
    if action_source_raw not in ("recommended", "custom"):
        raise _RequestError("MALFORMED_REQUEST", "action_source must be 'recommended' or 'custom'", 400)

    if action_source_raw == "recommended":
        selected_action_id = body.get("selected_action_id")
        if not isinstance(selected_action_id, str) or not selected_action_id:
            raise _RequestError("MALFORMED_REQUEST", "selected_action_id is required for recommended action", 400)
        _require_id(selected_action_id, "selected_action_id")
        match = next(
            (a for a in plan.recommended_actions if a.action_id == selected_action_id),
            None,
        )
        if match is None:
            raise _RequestError(
                "ACTION_NOT_FOUND",
                "所选行动不在当前 3 个推荐行动中。",
                409,
            )
        return "recommended", match, None, None

    # custom
    custom_raw = body.get("custom_action_text")
    if not isinstance(custom_raw, str):
        raise _RequestError("MALFORMED_REQUEST", "custom_action_text must be a string", 400)
    # Defensive length guard before normalization — never raise with raw text.
    if len(custom_raw) > MAX_CUSTOM_ACTION_LENGTH * 4:
        raise _RequestError("ACTION_TOO_LONG", "自定义行动过长。", 422)
    try:
        normalized = normalize_custom_action(custom_raw)
    except NarrativeTurnError as exc:
        # Map normalize errors to safe 422 codes without raw text.
        code = exc.code
        if code == NarrativeTurnError.ACTION_INVALID:
            # Inspect the safe message portion (no raw text) to sub-classify.
            msg = str(exc)
            if "NUL" in msg or "control character" in msg:
                raise _RequestError("ACTION_UNPARSEABLE", "自定义行动包含非法控制字符。", 422) from exc
            if "too long" in msg.lower() or "max" in msg.lower():
                raise _RequestError("ACTION_TOO_LONG", "自定义行动超过 200 字符上限。", 422) from exc
            if "empty" in msg.lower():
                raise _RequestError("ACTION_EMPTY", "自定义行动不能为空。", 422) from exc
            raise _RequestError("ACTION_UNPARSEABLE", "自定义行动无法被规范化。", 422) from exc
        raise _map_domain_error(exc) from exc
    return "custom", None, normalized, custom_raw  # type: ignore[return-value]


def _run_feasibility(
    snapshot: Any,
    plan: Any,
    action_source: str,
    selected_action: Any | None,
    normalized_custom: Any | None,
) -> Any:
    """Run feasibility validation. Never writes."""
    try:
        if action_source == "recommended":
            return NarrativeActionFeasibility.validate_recommended(
                snapshot,
                selected_action,
                plan.turn_id,
                clock_now=_utc_now(),
            )
        return NarrativeActionFeasibility.validate_custom(
            snapshot,
            normalized_custom,
            plan.turn_id,
            clock_now=_utc_now(),
        )
    except NarrativeTurnError as exc:
        raise _map_domain_error(exc) from exc


@router.post("/feasibility")
async def post_feasibility(request: Request) -> JSONResponse:
    """POST /api/narrative-turn/feasibility → ValidationWireDTO.

    Server re-binds context, validates ``expected_context_fingerprint``,
    rebuilds Plan, validates ``expected_turn_id``, then runs feasibility.
    The response never includes the raw custom action text — only the
    SHA-256 hash.
    """
    custom_raw_text: str | None = None
    try:
        body = await _read_json_body(request)
        scope, chapter_id, source_version_id, expected_fp, expected_turn_id = _extract_scope_and_chapter(body)
        snapshot = _bind_context(scope, chapter_id, source_version_id)

        if expected_fp is not None and expected_fp != snapshot.context_fingerprint:
            raise _RequestError(
                "CONTEXT_STALE",
                "上下文已过期，请重新规划。",
                409,
            )

        plan = _build_plan(snapshot)
        if expected_turn_id is not None and expected_turn_id != plan.turn_id:
            raise _RequestError(
                "TURN_STALE",
                "回合 ID 与当前上下文不匹配。",
                409,
            )

        action_source, selected_action, normalized_custom, custom_raw_text = (
            _resolve_action_for_feasibility(body, plan)
        )

        validation = _run_feasibility(
            snapshot, plan, action_source, selected_action, normalized_custom
        )
        dto = build_validation_wire_dto(validation)
        return _ok(dto)
    except _RequestError as err:
        return _fail(err.code, err.message, err.status)
    except Exception:  # pragma: no cover — defensive guard
        return _fail("INTERNAL_ERROR", "服务器内部错误。", 500)
    finally:
        # Best-effort: ensure raw text does not outlive this handler.
        custom_raw_text = None
        body = None  # type: ignore[assignment]


def _extract_confirm_body(body: dict[str, Any]) -> dict[str, Any]:
    """Extract and validate confirm request fields.

    Never echoes raw custom action text in errors.
    """
    operation_id = _require_id(body.get("operation_id"), "operation_id")

    scope, chapter_id, source_version_id, expected_fp, expected_turn_id = _extract_scope_and_chapter(body)

    expected_validation_id_raw = body.get("expected_validation_id")
    expected_validation_id: str | None = None
    if expected_validation_id_raw is not None and expected_validation_id_raw != "":
        if not isinstance(expected_validation_id_raw, str):
            raise _RequestError("MALFORMED_REQUEST", "expected_validation_id must be a string", 400)
        _require_id(expected_validation_id_raw, "expected_validation_id")
        expected_validation_id = expected_validation_id_raw

    expected_preview_fp = _optional_fingerprint(
        body.get("expected_preview_fingerprint"), "expected_preview_fingerprint"
    )

    action_source_raw = body.get("action_source")
    if not isinstance(action_source_raw, str):
        raise _RequestError("MALFORMED_REQUEST", "action_source is required", 400)
    if action_source_raw not in ("recommended", "custom"):
        raise _RequestError("MALFORMED_REQUEST", "action_source must be 'recommended' or 'custom'", 400)

    selected_action_id: str | None = None
    custom_action_text: str | None = None

    if action_source_raw == "recommended":
        sa_id = body.get("selected_action_id")
        if not isinstance(sa_id, str) or not sa_id:
            raise _RequestError("MALFORMED_REQUEST", "selected_action_id is required for recommended action", 400)
        _require_id(sa_id, "selected_action_id")
        selected_action_id = sa_id
    else:
        custom_raw = body.get("custom_action_text")
        if not isinstance(custom_raw, str):
            raise _RequestError("MALFORMED_REQUEST", "custom_action_text must be a string", 400)
        if len(custom_raw) > MAX_CUSTOM_ACTION_LENGTH * 4:
            raise _RequestError("ACTION_TOO_LONG", "自定义行动过长。", 422)
        custom_action_text = custom_raw

    return {
        "operation_id": operation_id,
        "scope": scope,
        "chapter_id": chapter_id,
        "source_version_id": source_version_id,
        "expected_context_fingerprint": expected_fp,
        "expected_turn_id": expected_turn_id,
        "expected_validation_id": expected_validation_id,
        "expected_preview_fingerprint": expected_preview_fp,
        "action_source": action_source_raw,
        "selected_action_id": selected_action_id,
        "custom_action_text": custom_action_text,
    }


@router.post("/confirm")
async def post_confirm(request: Request) -> JSONResponse:
    """POST /api/narrative-turn/confirm → ConfirmResponseWireDTO.

    Transactional turn confirmation with:
    - Idempotent operation replay
    - First-writer-wins concurrency via immutable Result claim
    - Full legal transition chain
    - Branch-local event journal
    - Branch-state projection with CAS
    - Forward recovery protocol

    Security: raw custom action text never enters storage, logs,
    exceptions, or the response — only the SHA-256 hash persists.
    """
    custom_raw_text: str | None = None
    try:
        body = await _read_json_body(request)
        fields = _extract_confirm_body(body)

        project_context = get_project_context()
        if fields["scope"].project_id != project_context.root.name:
            raise _RequestError(
                "SCOPE_MISMATCH",
                "project_id 与当前活动项目不匹配。",
                404,
            )

        service = NarrativeTurnService(project_context)

        custom_raw_text = fields["custom_action_text"]

        try:
            confirm_result = service.confirm_turn(
                operation_id=fields["operation_id"],
                scope=fields["scope"],
                chapter_id=fields["chapter_id"],
                source_version_id=fields["source_version_id"],
                expected_context_fingerprint=fields["expected_context_fingerprint"],
                expected_turn_id=fields["expected_turn_id"],
                expected_validation_id=fields["expected_validation_id"],
                expected_preview_fingerprint=fields["expected_preview_fingerprint"],
                action_source=fields["action_source"],
                selected_action_id=fields["selected_action_id"],
                custom_action_text=fields["custom_action_text"],
            )
        except NarrativeTurnError as exc:
            raise _map_domain_error(exc) from exc

        dto = build_confirm_result_wire_dto(confirm_result)
        return _ok(dto)
    except _RequestError as err:
        return _fail(err.code, err.message, err.status)
    except Exception:  # pragma: no cover — defensive guard
        return _fail("INTERNAL_ERROR", "服务器内部错误。", 500)
    finally:
        custom_raw_text = None
        body = None  # type: ignore[assignment]


@router.post("/preview")
async def post_preview(request: Request) -> JSONResponse:
    """POST /api/narrative-turn/preview → PreviewWireDTO.

    Server never trusts the client-provided Validation DTO. It re-binds
    context, validates the fingerprint, rebuilds Plan, re-runs
    feasibility, then generates the qualitative preview.
    """
    custom_raw_text: str | None = None
    try:
        body = await _read_json_body(request)
        scope, chapter_id, source_version_id, expected_fp, expected_turn_id = _extract_scope_and_chapter(body)
        snapshot = _bind_context(scope, chapter_id, source_version_id)

        if expected_fp is not None and expected_fp != snapshot.context_fingerprint:
            raise _RequestError(
                "CONTEXT_STALE",
                "上下文已过期，请重新规划。",
                409,
            )

        plan = _build_plan(snapshot)
        if expected_turn_id is not None and expected_turn_id != plan.turn_id:
            raise _RequestError(
                "TURN_STALE",
                "回合 ID 与当前上下文不匹配。",
                409,
            )

        action_source, selected_action, normalized_custom, custom_raw_text = (
            _resolve_action_for_feasibility(body, plan)
        )

        validation = _run_feasibility(
            snapshot, plan, action_source, selected_action, normalized_custom
        )

        try:
            if action_source == "recommended":
                preview = NarrativeTurnPreviewService.preview_recommended(
                    plan=plan,
                    action=selected_action,
                    validation=validation,
                    snapshot=snapshot,
                    clock_now=_utc_now(),
                )
            else:
                preview = NarrativeTurnPreviewService.preview_custom(
                    plan=plan,
                    validation=validation,
                    snapshot=snapshot,
                    clock_now=_utc_now(),
                )
        except NarrativeTurnError as exc:
            raise _map_domain_error(exc) from exc

        dto = build_preview_wire_dto(preview)
        return _ok(dto)
    except _RequestError as err:
        return _fail(err.code, err.message, err.status)
    except Exception:  # pragma: no cover — defensive guard
        return _fail("INTERNAL_ERROR", "服务器内部错误。", 500)
    finally:
        custom_raw_text = None
        body = None  # type: ignore[assignment]
