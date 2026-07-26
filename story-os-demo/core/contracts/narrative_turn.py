"""Narrative Turn contracts: immutable entities, state journal, scope binding.

Phase 0D4-A-FIX-RC2: lifecycle sequence-only filenames, recoverable active
archive operations, deterministic registry event journal, recursively
frozen state deltas.
"""
from __future__ import annotations

import json
import math
import re
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Any

SCHEMA_VERSION = "1.0"
_SUPPORTED_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION})

_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class NarrativeTurnError(ValueError):
    """Safe domain error that never includes raw filesystem paths or record data."""

    INVALID_SCHEMA_VERSION = "NARRATIVE_TURN_INVALID_SCHEMA_VERSION"
    INVALID_FIELD = "NARRATIVE_TURN_INVALID_FIELD"
    INVALID_ID = "NARRATIVE_TURN_INVALID_ID"
    INVALID_FINGERPRINT = "NARRATIVE_TURN_INVALID_FINGERPRINT"
    INVALID_DATETIME = "NARRATIVE_TURN_INVALID_DATETIME"
    INVALID_ENUM = "NARRATIVE_TURN_INVALID_ENUM"
    INVALID_ACTION_COUNT = "NARRATIVE_TURN_INVALID_ACTION_COUNT"
    INVALID_ACTION_ORDER = "NARRATIVE_TURN_INVALID_ACTION_ORDER"
    DUPLICATE_ACTION_ID = "NARRATIVE_TURN_DUPLICATE_ACTION_ID"
    DUPLICATE_ACTION_INTENT = "NARRATIVE_TURN_DUPLICATE_ACTION_INTENT"
    INVALID_PARENT_TURN = "NARRATIVE_TURN_INVALID_PARENT_TURN"
    VALIDATION_ACTION_XOR = "NARRATIVE_TURN_VALIDATION_ACTION_XOR"
    SCOPE_MISMATCH = "NARRATIVE_TURN_SCOPE_MISMATCH"
    ILLEGAL_TRANSITION = "NARRATIVE_TURN_ILLEGAL_TRANSITION"
    TERMINAL_STATE = "NARRATIVE_TURN_TERMINAL_STATE"
    TRANSITION_COLLISION = "NARRATIVE_TURN_TRANSITION_COLLISION"
    TRANSITION_SEQUENCE_COLLISION = "NARRATIVE_TURN_TRANSITION_SEQUENCE_COLLISION"
    TRANSITION_PREVIOUS_MISMATCH = "NARRATIVE_TURN_TRANSITION_PREVIOUS_MISMATCH"
    TRANSITION_STALE_FROM_STATE = "NARRATIVE_TURN_TRANSITION_STALE_FROM_STATE"
    BRANCH_NOT_ACTIVE = "NARRATIVE_TURN_BRANCH_NOT_ACTIVE"
    BRANCH_LIFECYCLE_CONFLICT = "NARRATIVE_TURN_BRANCH_LIFECYCLE_CONFLICT"
    BRANCH_CYCLE = "NARRATIVE_TURN_BRANCH_CYCLE"
    MISSING_PARENT_BRANCH = "NARRATIVE_TURN_MISSING_PARENT_BRANCH"
    BLOCKED_BY_CANON = "NARRATIVE_TURN_BLOCKED_BY_CANON"
    BLOCKED_BY_CAPABILITY = "NARRATIVE_TURN_BLOCKED_BY_CAPABILITY"
    REQUIRES_RESOURCE = "NARRATIVE_TURN_REQUIRES_RESOURCE"
    REQUIRES_CLARIFICATION = "NARRATIVE_TURN_REQUIRES_CLARIFICATION"
    ACTION_INVALID = "NARRATIVE_TURN_ACTION_INVALID"
    INVALID_TYPE = "NARRATIVE_TURN_INVALID_TYPE"
    IMMUTABLE_RECORD_EXISTS = "NARRATIVE_TURN_IMMUTABLE_RECORD_EXISTS"
    OPERATION_COLLISION = "NARRATIVE_TURN_OPERATION_COLLISION"
    LIFECYCLE_EVENT_CHAIN_CORRUPT = "NARRATIVE_TURN_LIFECYCLE_EVENT_CHAIN_CORRUPT"
    REGISTRY_EVENT_CHAIN_CORRUPT = "NARRATIVE_TURN_REGISTRY_EVENT_CHAIN_CORRUPT"
    REGISTRY_PROJECTION_MISMATCH = "NARRATIVE_TURN_REGISTRY_PROJECTION_MISMATCH"
    BRANCH_OPERATION_INCOMPLETE = "NARRATIVE_TURN_BRANCH_OPERATION_INCOMPLETE"
    BRANCH_OPERATION_REPLACEMENT_ARCHIVED = "NARRATIVE_TURN_BRANCH_OPERATION_REPLACEMENT_ARCHIVED"
    BRANCH_OPERATION_STALE_REVISION = "NARRATIVE_TURN_BRANCH_OPERATION_STALE_REVISION"
    BRANCH_OPERATION_CONFLICT = "NARRATIVE_TURN_BRANCH_OPERATION_CONFLICT"

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


class TurnState(str, Enum):
    PLANNED = "planned"
    AWAITING_ACTION = "awaiting_action"
    VALIDATING = "validating"
    VALIDATED = "validated"
    BLOCKED = "blocked"
    REQUIRES_CLARIFICATION = "requires_clarification"
    PREVIEWED = "previewed"
    CONFIRMED = "confirmed"
    APPLIED_TO_BRANCH = "applied_to_branch"
    INCLUDED_IN_CHAPTER = "included_in_chapter"
    COMMITTED = "committed"
    SUPERSEDED = "superseded"


class ActionType(str, Enum):
    ADVANCE = "advance"
    INVESTIGATE = "investigate"
    RETREAT = "retreat"
    NEGOTIATE = "negotiate"
    SACRIFICE = "sacrifice"
    CUSTOM_ENTRY = "custom_entry"


class ActionSource(str, Enum):
    RECOMMENDED = "recommended"
    CUSTOM = "custom"


class ValidationStatus(str, Enum):
    ALLOWED = "allowed"
    ALLOWED_WITH_COST = "allowed_with_cost"
    REQUIRES_CLARIFICATION = "requires_clarification"
    BLOCKED = "blocked"


class ResultStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    BLOCKED = "blocked"


class BranchLifecycleStatus(str, Enum):
    OPEN = "open"
    ARCHIVED = "archived"


def _validate_id(value: str, field_name: str) -> None:
    if not isinstance(value, str) or _ID_PATTERN.fullmatch(value) is None:
        raise NarrativeTurnError(NarrativeTurnError.INVALID_ID, f"Invalid {field_name}: {value!r}")


def _validate_fingerprint(value: str, field_name: str) -> None:
    if not isinstance(value, str) or _FINGERPRINT_PATTERN.fullmatch(value) is None:
        raise NarrativeTurnError(NarrativeTurnError.INVALID_FINGERPRINT, f"Invalid {field_name}: {value!r}")


def _validate_non_empty_string(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, f"{field_name} must be a non-empty string")


def _validate_datetime(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise NarrativeTurnError(NarrativeTurnError.INVALID_DATETIME, f"{field_name} must be a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise NarrativeTurnError(NarrativeTurnError.INVALID_DATETIME, f"Invalid {field_name}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise NarrativeTurnError(NarrativeTurnError.INVALID_DATETIME, f"{field_name} must have timezone")


def _validate_int(value: int, field_name: str, allow_zero: bool = False) -> None:
    if type(value) is not int:
        raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, f"{field_name} must be int, not {type(value).__name__}")
    if value < 0 or (value == 0 and not allow_zero):
        raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, f"{field_name} must be positive")


def _require_tuple(value: Any, field_name: str) -> tuple:
    """Strict tuple validator: rejects list, dict, and other types."""
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        raise NarrativeTurnError(
            NarrativeTurnError.INVALID_TYPE,
            f"{field_name} must be a tuple, not list; list input is rejected",
        )
    raise NarrativeTurnError(
        NarrativeTurnError.INVALID_TYPE,
        f"{field_name} must be a tuple, not {type(value).__name__}",
    )


def _require_tuple_of_tuples(value: Any, field_name: str) -> tuple[tuple[Any, ...], ...]:
    """Strict tuple-of-tuples validator: rejects dict and list."""
    if isinstance(value, dict):
        raise NarrativeTurnError(
            NarrativeTurnError.INVALID_TYPE,
            f"{field_name} must be a tuple of tuples, not dict; dict input is rejected",
        )
    if isinstance(value, list):
        raise NarrativeTurnError(
            NarrativeTurnError.INVALID_TYPE,
            f"{field_name} must be a tuple of tuples, not list; list input is rejected",
        )
    if not isinstance(value, tuple):
        raise NarrativeTurnError(
            NarrativeTurnError.INVALID_TYPE,
            f"{field_name} must be a tuple of tuples, not {type(value).__name__}",
        )
    return value


_MAX_NESTING_DEPTH = 8
_MAX_TOTAL_ELEMENTS = 1000


def _recursive_freeze(value: Any, field_name: str, _depth: int = 0) -> Any:
    """Recursively freeze a value into an immutable form.

    Rules:
    - Scalars (str, int, float, bool, None) are accepted as-is (immutable in Python).
    - ``float`` must be finite (rejects NaN and Infinity).
    - ``bool`` is accepted for int-typed fields only if the field explicitly
      permits it; the general ``_validate_int`` continues to reject bool.
    - ``dict`` is deep-copied into a ``tuple[tuple[str, FrozenValue], ...]``
      with sorted keys. Keys must be non-empty strings.
    - ``list`` is **rejected** (fail-closed strict type policy).
    - ``tuple`` is recursively frozen element-by-element.
    - ``set``, custom objects, ``bytes``, ``Path`` are rejected.
    - Nesting depth and total element count are bounded.
    """
    if _depth > _MAX_NESTING_DEPTH:
        raise NarrativeTurnError(
            NarrativeTurnError.INVALID_FIELD,
            f"{field_name} exceeds maximum nesting depth of {_MAX_NESTING_DEPTH}",
        )

    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise NarrativeTurnError(
                NarrativeTurnError.INVALID_FIELD,
                f"{field_name} contains NaN or Infinity",
            )
        return value

    if isinstance(value, str):
        return value

    if isinstance(value, list):
        raise NarrativeTurnError(
            NarrativeTurnError.INVALID_TYPE,
            f"{field_name} must be a tuple, not list; list input is rejected",
        )

    if isinstance(value, set) or isinstance(value, frozenset):
        raise NarrativeTurnError(
            NarrativeTurnError.INVALID_TYPE,
            f"{field_name} must be a tuple, not set",
        )

    if isinstance(value, dict):
        result: list[tuple[str, Any]] = []
        for key in sorted(value.keys()):
            if not isinstance(key, str) or not key:
                raise NarrativeTurnError(
                    NarrativeTurnError.INVALID_FIELD,
                    f"{field_name} dict keys must be non-empty strings",
                )
            frozen_val = _recursive_freeze(value[key], f"{field_name}.{key}", _depth + 1)
            result.append((key, frozen_val))
        return tuple(result)

    if isinstance(value, tuple):
        result_list: list[Any] = []
        total = 0
        for i, item in enumerate(value):
            total += 1
            if total > _MAX_TOTAL_ELEMENTS:
                raise NarrativeTurnError(
                    NarrativeTurnError.INVALID_FIELD,
                    f"{field_name} exceeds maximum total element count of {_MAX_TOTAL_ELEMENTS}",
                )
            result_list.append(_recursive_freeze(item, f"{field_name}[{i}]", _depth + 1))
        return tuple(result_list)

    if isinstance(value, bytes):
        raise NarrativeTurnError(
            NarrativeTurnError.INVALID_TYPE,
            f"{field_name} must not contain bytes",
        )

    raise NarrativeTurnError(
        NarrativeTurnError.INVALID_TYPE,
        f"{field_name} contains unsupported type: {type(value).__name__}",
    )


@dataclass(frozen=True)
class TimelineContext:
    project_id: str
    timeline_id: str

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.project_id, "project_id")
        _validate_non_empty_string(self.timeline_id, "timeline_id")


@dataclass(frozen=True)
class NarrativeScope:
    project_id: str
    timeline_id: str
    branch_id: str

    def __post_init__(self) -> None:
        _validate_id(self.project_id, "project_id")
        _validate_id(self.timeline_id, "timeline_id")
        _validate_id(self.branch_id, "branch_id")

    def assert_matches(self, other: "NarrativeScope") -> None:
        if self.project_id != other.project_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "project_id mismatch")
        if self.timeline_id != other.timeline_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "timeline_id mismatch")
        if self.branch_id != other.branch_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "branch_id mismatch")


@dataclass(frozen=True)
class NarrativeCustomActionPolicy:
    max_length: int
    forbidden_patterns: tuple[str, ...]
    feasibility_pipeline: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_int(self.max_length, "max_length", allow_zero=False)
        object.__setattr__(self, "forbidden_patterns", _require_tuple(self.forbidden_patterns, "forbidden_patterns"))
        object.__setattr__(self, "feasibility_pipeline", _require_tuple(self.feasibility_pipeline, "feasibility_pipeline"))


@dataclass(frozen=True)
class NarrativeActionOption:
    action_id: str
    action_type: ActionType
    display_text: str
    intent: str
    expected_costs: tuple[tuple[str, str], ...]
    expected_risks: tuple[tuple[str, str], ...]
    required_conditions: tuple[str, ...]
    unavailable_reasons: tuple[str, ...]
    provenance: str
    deterministic_order: int

    def __post_init__(self) -> None:
        _validate_id(self.action_id, "action_id")
        if not isinstance(self.action_type, ActionType):
            raise NarrativeTurnError(NarrativeTurnError.INVALID_ENUM, f"Invalid action_type: {self.action_type}")
        _validate_non_empty_string(self.display_text, "display_text")
        _validate_non_empty_string(self.intent, "intent")
        object.__setattr__(self, "expected_costs", _require_tuple_of_tuples(self.expected_costs, "expected_costs"))
        object.__setattr__(self, "expected_risks", _require_tuple_of_tuples(self.expected_risks, "expected_risks"))
        object.__setattr__(self, "required_conditions", _require_tuple(self.required_conditions, "required_conditions"))
        object.__setattr__(self, "unavailable_reasons", _require_tuple(self.unavailable_reasons, "unavailable_reasons"))
        _validate_non_empty_string(self.provenance, "provenance")
        if self.provenance != "deterministic-planner":
            raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, f"provenance must be 'deterministic-planner': {self.provenance}")
        _validate_int(self.deterministic_order, "deterministic_order")
        if self.deterministic_order not in {1, 2, 3}:
            raise NarrativeTurnError(NarrativeTurnError.INVALID_ACTION_ORDER, f"deterministic_order must be 1, 2, or 3: {self.deterministic_order}")


@dataclass(frozen=True)
class NarrativeTurnPlan:
    schema_version: str
    turn_id: str
    scope: NarrativeScope
    chapter_id: int
    source_version_id: str | None
    parent_turn_id: str | None
    context_fingerprint: str
    planning_revision: str
    canon_revision: str | None
    created_at: str
    recommended_actions: tuple[NarrativeActionOption, ...]
    custom_action_policy: NarrativeCustomActionPolicy

    def __post_init__(self) -> None:
        if self.schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
            raise NarrativeTurnError(NarrativeTurnError.INVALID_SCHEMA_VERSION, f"Unsupported schema version: {self.schema_version}")
        _validate_id(self.turn_id, "turn_id")
        if not isinstance(self.scope, NarrativeScope):
            raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, "scope must be NarrativeScope")
        _validate_int(self.chapter_id, "chapter_id")
        if self.source_version_id is not None:
            _validate_id(self.source_version_id, "source_version_id")
        if self.parent_turn_id is not None:
            _validate_id(self.parent_turn_id, "parent_turn_id")
            if self.parent_turn_id == self.turn_id:
                raise NarrativeTurnError(NarrativeTurnError.INVALID_PARENT_TURN, "parent_turn_id cannot equal turn_id")
        _validate_fingerprint(self.context_fingerprint, "context_fingerprint")
        _validate_non_empty_string(self.planning_revision, "planning_revision")
        if self.canon_revision is not None:
            _validate_id(self.canon_revision, "canon_revision")
        _validate_datetime(self.created_at, "created_at")
        object.__setattr__(self, "recommended_actions", _require_tuple(self.recommended_actions, "recommended_actions"))
        if len(self.recommended_actions) != 3:
            raise NarrativeTurnError(NarrativeTurnError.INVALID_ACTION_COUNT, f"recommended_actions must have exactly 3 items: {len(self.recommended_actions)}")
        action_ids: set[str] = set()
        intents: set[str] = set()
        orders: set[int] = set()
        for action in self.recommended_actions:
            if not isinstance(action, NarrativeActionOption):
                raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, "recommended_actions must contain NarrativeActionOption")
            if action.action_id in action_ids:
                raise NarrativeTurnError(NarrativeTurnError.DUPLICATE_ACTION_ID, f"Duplicate action_id: {action.action_id}")
            action_ids.add(action.action_id)
            if action.intent in intents:
                raise NarrativeTurnError(NarrativeTurnError.DUPLICATE_ACTION_INTENT, f"Duplicate intent: {action.intent}")
            intents.add(action.intent)
            if action.deterministic_order in orders:
                raise NarrativeTurnError(NarrativeTurnError.INVALID_ACTION_ORDER, f"Duplicate deterministic_order: {action.deterministic_order}")
            orders.add(action.deterministic_order)
        if orders != {1, 2, 3}:
            raise NarrativeTurnError(NarrativeTurnError.INVALID_ACTION_ORDER, f"deterministic_order must be exactly 1, 2, 3: {orders}")
        if not isinstance(self.custom_action_policy, NarrativeCustomActionPolicy):
            raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, "custom_action_policy must be NarrativeCustomActionPolicy")

    def fingerprint(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "turn_id": self.turn_id,
            "project_id": self.scope.project_id,
            "timeline_id": self.scope.timeline_id,
            "branch_id": self.scope.branch_id,
            "chapter_id": self.chapter_id,
            "source_version_id": self.source_version_id,
            "parent_turn_id": self.parent_turn_id,
            "context_fingerprint": self.context_fingerprint,
            "planning_revision": self.planning_revision,
            "canon_revision": self.canon_revision,
            "created_at": self.created_at,
            "recommended_actions": [asdict(a) for a in self.recommended_actions],
            "custom_action_policy": asdict(self.custom_action_policy),
        }
        return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class NarrativeActionValidation:
    schema_version: str
    validation_id: str
    turn_id: str
    scope: NarrativeScope
    chapter_id: int
    action_source: ActionSource
    selected_action_id: str | None
    custom_action_text_hash: str | None
    status: ValidationStatus
    blocking_reasons: tuple[str, ...]
    cost_explanation: tuple[tuple[str, str], ...]
    risk_explanation: tuple[tuple[str, str], ...]
    checked_at: str
    context_fingerprint: str

    def __post_init__(self) -> None:
        if self.schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
            raise NarrativeTurnError(NarrativeTurnError.INVALID_SCHEMA_VERSION, f"Unsupported schema version: {self.schema_version}")
        _validate_id(self.validation_id, "validation_id")
        _validate_id(self.turn_id, "turn_id")
        if not isinstance(self.scope, NarrativeScope):
            raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, "scope must be NarrativeScope")
        _validate_int(self.chapter_id, "chapter_id")
        if not isinstance(self.action_source, ActionSource):
            raise NarrativeTurnError(NarrativeTurnError.INVALID_ENUM, f"Invalid action_source: {self.action_source}")
        if self.action_source == ActionSource.RECOMMENDED:
            if self.selected_action_id is None:
                raise NarrativeTurnError(NarrativeTurnError.VALIDATION_ACTION_XOR, "recommended action requires selected_action_id")
            if self.custom_action_text_hash is not None:
                raise NarrativeTurnError(NarrativeTurnError.VALIDATION_ACTION_XOR, "recommended action cannot have custom_action_text_hash")
            _validate_id(self.selected_action_id, "selected_action_id")
        else:
            if self.custom_action_text_hash is None:
                raise NarrativeTurnError(NarrativeTurnError.VALIDATION_ACTION_XOR, "custom action requires custom_action_text_hash")
            if self.selected_action_id is not None:
                raise NarrativeTurnError(NarrativeTurnError.VALIDATION_ACTION_XOR, "custom action cannot have selected_action_id")
            _validate_fingerprint(self.custom_action_text_hash, "custom_action_text_hash")
        if not isinstance(self.status, ValidationStatus):
            raise NarrativeTurnError(NarrativeTurnError.INVALID_ENUM, f"Invalid status: {self.status}")
        object.__setattr__(self, "blocking_reasons", _require_tuple(self.blocking_reasons, "blocking_reasons"))
        object.__setattr__(self, "cost_explanation", _require_tuple_of_tuples(self.cost_explanation, "cost_explanation"))
        object.__setattr__(self, "risk_explanation", _require_tuple_of_tuples(self.risk_explanation, "risk_explanation"))
        _validate_datetime(self.checked_at, "checked_at")
        _validate_fingerprint(self.context_fingerprint, "context_fingerprint")

    def fingerprint(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "validation_id": self.validation_id,
            "turn_id": self.turn_id,
            "project_id": self.scope.project_id,
            "timeline_id": self.scope.timeline_id,
            "branch_id": self.scope.branch_id,
            "chapter_id": self.chapter_id,
            "action_source": self.action_source.value,
            "selected_action_id": self.selected_action_id,
            "custom_action_text_hash": self.custom_action_text_hash,
            "status": self.status.value,
            "blocking_reasons": list(self.blocking_reasons),
            "cost_explanation": list(self.cost_explanation),
            "risk_explanation": list(self.risk_explanation),
            "checked_at": self.checked_at,
            "context_fingerprint": self.context_fingerprint,
        }
        return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class NarrativeTurnResult:
    schema_version: str
    turn_id: str
    scope: NarrativeScope
    chapter_id: int
    selected_action_id: str | None
    custom_action_text_hash: str | None
    result_status: ResultStatus
    event_summary: str
    state_delta_proposal: tuple[tuple[str, Any], ...]
    consequence_flags: tuple[str, ...]
    next_context_fingerprint: str
    execution_revision: str
    source_fingerprint: str
    confirmed_at: str
    operation_id: str

    def __post_init__(self) -> None:
        if self.schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
            raise NarrativeTurnError(NarrativeTurnError.INVALID_SCHEMA_VERSION, f"Unsupported schema version: {self.schema_version}")
        _validate_id(self.turn_id, "turn_id")
        if not isinstance(self.scope, NarrativeScope):
            raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, "scope must be NarrativeScope")
        _validate_int(self.chapter_id, "chapter_id")
        if self.selected_action_id is not None:
            _validate_id(self.selected_action_id, "selected_action_id")
        if self.custom_action_text_hash is not None:
            _validate_fingerprint(self.custom_action_text_hash, "custom_action_text_hash")
        if not isinstance(self.result_status, ResultStatus):
            raise NarrativeTurnError(NarrativeTurnError.INVALID_ENUM, f"Invalid result_status: {self.result_status}")
        _validate_non_empty_string(self.event_summary, "event_summary")
        object.__setattr__(self, "state_delta_proposal", _recursive_freeze(self.state_delta_proposal, "state_delta_proposal"))
        # After recursive freeze, ensure the top-level is a tuple-of-tuples.
        if not isinstance(self.state_delta_proposal, tuple):
            raise NarrativeTurnError(
                NarrativeTurnError.INVALID_TYPE,
                "state_delta_proposal must be a tuple of (key, value) pairs",
            )
        for item in self.state_delta_proposal:
            if not isinstance(item, tuple) or len(item) != 2:
                raise NarrativeTurnError(
                    NarrativeTurnError.INVALID_TYPE,
                    "state_delta_proposal each element must be a 2-tuple (key, value)",
                )
            if not isinstance(item[0], str) or not item[0]:
                raise NarrativeTurnError(
                    NarrativeTurnError.INVALID_FIELD,
                    "state_delta_proposal keys must be non-empty strings",
                )
        object.__setattr__(self, "consequence_flags", _require_tuple(self.consequence_flags, "consequence_flags"))
        _validate_fingerprint(self.next_context_fingerprint, "next_context_fingerprint")
        _validate_non_empty_string(self.execution_revision, "execution_revision")
        _validate_fingerprint(self.source_fingerprint, "source_fingerprint")
        _validate_datetime(self.confirmed_at, "confirmed_at")
        _validate_id(self.operation_id, "operation_id")

    def fingerprint(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "turn_id": self.turn_id,
            "project_id": self.scope.project_id,
            "timeline_id": self.scope.timeline_id,
            "branch_id": self.scope.branch_id,
            "chapter_id": self.chapter_id,
            "selected_action_id": self.selected_action_id,
            "custom_action_text_hash": self.custom_action_text_hash,
            "result_status": self.result_status.value,
            "event_summary": self.event_summary,
            "state_delta_proposal": list(self.state_delta_proposal),
            "consequence_flags": list(self.consequence_flags),
            "next_context_fingerprint": self.next_context_fingerprint,
            "execution_revision": self.execution_revision,
            "source_fingerprint": self.source_fingerprint,
            "confirmed_at": self.confirmed_at,
            "operation_id": self.operation_id,
        }
        return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class NarrativeBranchIdentity:
    """Immutable branch creation record — never overwritten."""

    schema_version: str
    branch_id: str
    project_id: str
    timeline_id: str
    parent_branch_id: str | None
    created_from_turn_id: str | None
    display_name: str
    created_at: str

    def __post_init__(self) -> None:
        if self.schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
            raise NarrativeTurnError(NarrativeTurnError.INVALID_SCHEMA_VERSION, f"Unsupported schema version: {self.schema_version}")
        _validate_id(self.branch_id, "branch_id")
        _validate_non_empty_string(self.project_id, "project_id")
        _validate_non_empty_string(self.timeline_id, "timeline_id")
        if self.parent_branch_id is not None:
            _validate_id(self.parent_branch_id, "parent_branch_id")
            if self.parent_branch_id == self.branch_id:
                raise NarrativeTurnError(NarrativeTurnError.BRANCH_CYCLE, "parent_branch_id cannot equal branch_id")
        if self.created_from_turn_id is not None:
            _validate_id(self.created_from_turn_id, "created_from_turn_id")
        _validate_non_empty_string(self.display_name, "display_name")
        _validate_datetime(self.created_at, "created_at")

    def fingerprint(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "branch_id": self.branch_id,
            "project_id": self.project_id,
            "timeline_id": self.timeline_id,
            "parent_branch_id": self.parent_branch_id,
            "created_from_turn_id": self.created_from_turn_id,
            "display_name": self.display_name,
            "created_at": self.created_at,
        }
        return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class NarrativeBranch:
    """Derived projection of branch identity + current lifecycle status.

    NOTE: ``lifecycle_status`` and ``archived_at`` are derived from the
    append-only lifecycle event journal, NOT stored in the immutable
    branch creation record.
    """

    schema_version: str
    branch_id: str
    project_id: str
    timeline_id: str
    parent_branch_id: str | None
    created_from_turn_id: str | None
    display_name: str
    lifecycle_status: BranchLifecycleStatus
    created_at: str
    archived_at: str | None

    def __post_init__(self) -> None:
        if self.schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
            raise NarrativeTurnError(NarrativeTurnError.INVALID_SCHEMA_VERSION, f"Unsupported schema version: {self.schema_version}")
        _validate_id(self.branch_id, "branch_id")
        _validate_non_empty_string(self.project_id, "project_id")
        _validate_non_empty_string(self.timeline_id, "timeline_id")
        if self.parent_branch_id is not None:
            _validate_id(self.parent_branch_id, "parent_branch_id")
            if self.parent_branch_id == self.branch_id:
                raise NarrativeTurnError(NarrativeTurnError.BRANCH_CYCLE, "parent_branch_id cannot equal branch_id")
        if self.created_from_turn_id is not None:
            _validate_id(self.created_from_turn_id, "created_from_turn_id")
        _validate_non_empty_string(self.display_name, "display_name")
        if not isinstance(self.lifecycle_status, BranchLifecycleStatus):
            raise NarrativeTurnError(NarrativeTurnError.INVALID_ENUM, f"Invalid lifecycle_status: {self.lifecycle_status}")
        _validate_datetime(self.created_at, "created_at")
        if self.lifecycle_status == BranchLifecycleStatus.ARCHIVED:
            if self.archived_at is None:
                raise NarrativeTurnError(NarrativeTurnError.BRANCH_LIFECYCLE_CONFLICT, "archived branch requires archived_at")
            _validate_datetime(self.archived_at, "archived_at")
        else:
            if self.archived_at is not None:
                raise NarrativeTurnError(NarrativeTurnError.BRANCH_LIFECYCLE_CONFLICT, "open branch cannot have archived_at")


@dataclass(frozen=True)
class BranchLifecycleEvent:
    """Append-only lifecycle transition event for a branch."""

    schema_version: str
    event_id: str
    sequence: int
    branch_id: str
    project_id: str
    timeline_id: str
    from_status: BranchLifecycleStatus
    to_status: BranchLifecycleStatus
    operation_id: str | None
    occurred_at: str
    previous_event_fingerprint: str | None
    record_fingerprint: str

    _LEGAL_LIFECYCLE_TRANSITIONS = frozenset({
        (BranchLifecycleStatus.OPEN, BranchLifecycleStatus.ARCHIVED),
        (BranchLifecycleStatus.ARCHIVED, BranchLifecycleStatus.OPEN),
    })

    def __post_init__(self) -> None:
        if self.schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
            raise NarrativeTurnError(NarrativeTurnError.INVALID_SCHEMA_VERSION, f"Unsupported schema version: {self.schema_version}")
        _validate_id(self.event_id, "event_id")
        _validate_int(self.sequence, "sequence", allow_zero=True)
        _validate_id(self.branch_id, "branch_id")
        _validate_non_empty_string(self.project_id, "project_id")
        _validate_non_empty_string(self.timeline_id, "timeline_id")
        if not isinstance(self.from_status, BranchLifecycleStatus):
            raise NarrativeTurnError(NarrativeTurnError.INVALID_ENUM, f"Invalid from_status: {self.from_status}")
        if not isinstance(self.to_status, BranchLifecycleStatus):
            raise NarrativeTurnError(NarrativeTurnError.INVALID_ENUM, f"Invalid to_status: {self.to_status}")
        if (self.from_status, self.to_status) not in self._LEGAL_LIFECYCLE_TRANSITIONS:
            raise NarrativeTurnError(
                NarrativeTurnError.BRANCH_LIFECYCLE_CONFLICT,
                f"Illegal lifecycle transition: {self.from_status.value} -> {self.to_status.value}",
            )
        if self.operation_id is not None:
            _validate_id(self.operation_id, "operation_id")
        _validate_datetime(self.occurred_at, "occurred_at")
        if self.previous_event_fingerprint is not None:
            _validate_fingerprint(self.previous_event_fingerprint, "previous_event_fingerprint")
        _validate_fingerprint(self.record_fingerprint, "record_fingerprint")

    def fingerprint(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "sequence": self.sequence,
            "branch_id": self.branch_id,
            "project_id": self.project_id,
            "timeline_id": self.timeline_id,
            "from_status": self.from_status.value,
            "to_status": self.to_status.value,
            "operation_id": self.operation_id,
            "occurred_at": self.occurred_at,
            "previous_event_fingerprint": self.previous_event_fingerprint,
            "record_fingerprint": self.record_fingerprint,
        }
        return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


class BranchOperationPhase(str, Enum):
    INTENT = "intent"
    REGISTRY_UPDATED = "registry_updated"
    LIFECYCLE_APPENDED = "lifecycle_appended"
    COMPLETED = "completed"


class BranchOperationType(str, Enum):
    ACTIVE_ARCHIVE_WITH_REPLACEMENT = "active_archive_with_replacement"


@dataclass(frozen=True)
class BranchOperationRecord:
    """Immutable record of a multi-phase branch operation.

    Supports recoverable active-archive-with-replacement by tracking
    the current phase so that a retry with the same ``operation_id``
    can resume or verify completion without double-writing.
    """

    schema_version: str
    operation_id: str
    project_id: str
    timeline_id: str
    operation_type: BranchOperationType
    target_branch_id: str
    replacement_branch_id: str
    expected_registry_revision: str
    initial_target_status: BranchLifecycleStatus
    phase: BranchOperationPhase
    resulting_registry_revision: str | None
    lifecycle_event_fingerprint: str | None
    payload_fingerprint: str
    created_at: str
    record_fingerprint: str

    def __post_init__(self) -> None:
        if self.schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
            raise NarrativeTurnError(NarrativeTurnError.INVALID_SCHEMA_VERSION, f"Unsupported schema version: {self.schema_version}")
        _validate_id(self.operation_id, "operation_id")
        _validate_non_empty_string(self.project_id, "project_id")
        _validate_non_empty_string(self.timeline_id, "timeline_id")
        if not isinstance(self.operation_type, BranchOperationType):
            raise NarrativeTurnError(NarrativeTurnError.INVALID_ENUM, f"Invalid operation_type: {self.operation_type}")
        _validate_id(self.target_branch_id, "target_branch_id")
        _validate_id(self.replacement_branch_id, "replacement_branch_id")
        _validate_non_empty_string(self.expected_registry_revision, "expected_registry_revision")
        if not isinstance(self.initial_target_status, BranchLifecycleStatus):
            raise NarrativeTurnError(NarrativeTurnError.INVALID_ENUM, f"Invalid initial_target_status: {self.initial_target_status}")
        if not isinstance(self.phase, BranchOperationPhase):
            raise NarrativeTurnError(NarrativeTurnError.INVALID_ENUM, f"Invalid phase: {self.phase}")
        if self.resulting_registry_revision is not None:
            _validate_non_empty_string(self.resulting_registry_revision, "resulting_registry_revision")
        if self.lifecycle_event_fingerprint is not None:
            _validate_fingerprint(self.lifecycle_event_fingerprint, "lifecycle_event_fingerprint")
        _validate_fingerprint(self.payload_fingerprint, "payload_fingerprint")
        _validate_datetime(self.created_at, "created_at")
        _validate_fingerprint(self.record_fingerprint, "record_fingerprint")

    def fingerprint(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "operation_id": self.operation_id,
            "project_id": self.project_id,
            "timeline_id": self.timeline_id,
            "operation_type": self.operation_type.value,
            "target_branch_id": self.target_branch_id,
            "replacement_branch_id": self.replacement_branch_id,
            "expected_registry_revision": self.expected_registry_revision,
            "initial_target_status": self.initial_target_status.value,
            "phase": self.phase.value,
            "resulting_registry_revision": self.resulting_registry_revision,
            "lifecycle_event_fingerprint": self.lifecycle_event_fingerprint,
            "payload_fingerprint": self.payload_fingerprint,
            "created_at": self.created_at,
            "record_fingerprint": self.record_fingerprint,
        }
        return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RegistryEvent:
    """Append-only registry event with deterministic sequence ordering.

    The current registry snapshot is fully rebuildable from the event journal.
    """

    schema_version: str
    event_id: str
    sequence: int
    project_id: str
    timeline_id: str
    event_type: str
    from_active_branch_id: str | None
    to_active_branch_id: str | None
    expected_revision: str
    resulting_revision: str
    operation_id: str | None
    occurred_at: str
    previous_event_id: str | None
    previous_event_fingerprint: str | None
    record_fingerprint: str

    def __post_init__(self) -> None:
        if self.schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
            raise NarrativeTurnError(NarrativeTurnError.INVALID_SCHEMA_VERSION, f"Unsupported schema version: {self.schema_version}")
        _validate_id(self.event_id, "event_id")
        _validate_int(self.sequence, "sequence", allow_zero=True)
        _validate_non_empty_string(self.project_id, "project_id")
        _validate_non_empty_string(self.timeline_id, "timeline_id")
        _validate_non_empty_string(self.event_type, "event_type")
        if self.from_active_branch_id is not None:
            _validate_id(self.from_active_branch_id, "from_active_branch_id")
        if self.to_active_branch_id is not None:
            _validate_id(self.to_active_branch_id, "to_active_branch_id")
        _validate_non_empty_string(self.expected_revision, "expected_revision")
        _validate_non_empty_string(self.resulting_revision, "resulting_revision")
        if self.operation_id is not None:
            _validate_id(self.operation_id, "operation_id")
        _validate_datetime(self.occurred_at, "occurred_at")
        if self.previous_event_id is not None:
            _validate_id(self.previous_event_id, "previous_event_id")
        if self.previous_event_fingerprint is not None:
            _validate_fingerprint(self.previous_event_fingerprint, "previous_event_fingerprint")
        _validate_fingerprint(self.record_fingerprint, "record_fingerprint")
        if self.sequence == 0 and self.previous_event_id is not None:
            raise NarrativeTurnError(
                NarrativeTurnError.REGISTRY_EVENT_CHAIN_CORRUPT,
                "first registry event (sequence=0) must have previous_event_id=None",
            )
        if self.sequence > 0 and self.previous_event_id is None:
            raise NarrativeTurnError(
                NarrativeTurnError.REGISTRY_EVENT_CHAIN_CORRUPT,
                f"non-first registry event (sequence={self.sequence}) must have previous_event_id",
            )

    def fingerprint(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "sequence": self.sequence,
            "project_id": self.project_id,
            "timeline_id": self.timeline_id,
            "event_type": self.event_type,
            "from_active_branch_id": self.from_active_branch_id,
            "to_active_branch_id": self.to_active_branch_id,
            "expected_revision": self.expected_revision,
            "resulting_revision": self.resulting_revision,
            "operation_id": self.operation_id,
            "occurred_at": self.occurred_at,
            "previous_event_id": self.previous_event_id,
            "previous_event_fingerprint": self.previous_event_fingerprint,
            "record_fingerprint": self.record_fingerprint,
        }
        return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class NarrativeTurnTransition:
    """Append-only lifecycle transition for a Turn.

    Ordering is deterministic via ``sequence`` (not ``occurred_at``).
    ``previous_transition_id`` and ``previous_transition_fingerprint`` form
    a singly-linked chain that must be validated on append.
    """

    schema_version: str
    transition_id: str
    turn_id: str
    scope: NarrativeScope
    from_state: TurnState
    to_state: TurnState
    reason_code: str
    operation_id: str | None
    occurred_at: str
    record_fingerprint: str
    sequence: int
    previous_transition_id: str | None
    previous_transition_fingerprint: str | None

    _LEGAL_TRANSITIONS = frozenset({
        (TurnState.PLANNED, TurnState.AWAITING_ACTION),
        (TurnState.PLANNED, TurnState.SUPERSEDED),
        (TurnState.AWAITING_ACTION, TurnState.VALIDATING),
        (TurnState.VALIDATING, TurnState.VALIDATED),
        (TurnState.VALIDATING, TurnState.BLOCKED),
        (TurnState.VALIDATING, TurnState.REQUIRES_CLARIFICATION),
        (TurnState.REQUIRES_CLARIFICATION, TurnState.AWAITING_ACTION),
        (TurnState.VALIDATED, TurnState.PREVIEWED),
        (TurnState.PREVIEWED, TurnState.CONFIRMED),
        (TurnState.CONFIRMED, TurnState.APPLIED_TO_BRANCH),
        (TurnState.APPLIED_TO_BRANCH, TurnState.INCLUDED_IN_CHAPTER),
        (TurnState.INCLUDED_IN_CHAPTER, TurnState.COMMITTED),
    })

    _TERMINAL_STATES = frozenset({TurnState.BLOCKED, TurnState.COMMITTED, TurnState.SUPERSEDED})

    def __post_init__(self) -> None:
        if self.schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
            raise NarrativeTurnError(NarrativeTurnError.INVALID_SCHEMA_VERSION, f"Unsupported schema version: {self.schema_version}")
        _validate_id(self.transition_id, "transition_id")
        _validate_id(self.turn_id, "turn_id")
        if not isinstance(self.scope, NarrativeScope):
            raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, "scope must be NarrativeScope")
        if not isinstance(self.from_state, TurnState):
            raise NarrativeTurnError(NarrativeTurnError.INVALID_ENUM, f"Invalid from_state: {self.from_state}")
        if not isinstance(self.to_state, TurnState):
            raise NarrativeTurnError(NarrativeTurnError.INVALID_ENUM, f"Invalid to_state: {self.to_state}")
        if (self.from_state, self.to_state) not in self._LEGAL_TRANSITIONS:
            raise NarrativeTurnError(NarrativeTurnError.ILLEGAL_TRANSITION, f"Illegal transition: {self.from_state.value} -> {self.to_state.value}")
        if self.from_state in self._TERMINAL_STATES:
            raise NarrativeTurnError(NarrativeTurnError.TERMINAL_STATE, f"Cannot transition from terminal state: {self.from_state.value}")
        _validate_non_empty_string(self.reason_code, "reason_code")
        if self.operation_id is not None:
            _validate_id(self.operation_id, "operation_id")
        _validate_datetime(self.occurred_at, "occurred_at")
        _validate_fingerprint(self.record_fingerprint, "record_fingerprint")
        _validate_int(self.sequence, "sequence", allow_zero=True)
        if self.previous_transition_id is not None:
            _validate_id(self.previous_transition_id, "previous_transition_id")
        if self.previous_transition_fingerprint is not None:
            _validate_fingerprint(self.previous_transition_fingerprint, "previous_transition_fingerprint")
        if self.sequence == 0 and self.previous_transition_id is not None:
            raise NarrativeTurnError(NarrativeTurnError.TRANSITION_PREVIOUS_MISMATCH, "first transition (sequence=0) must have previous_transition_id=None")
        if self.sequence > 0 and self.previous_transition_id is None:
            raise NarrativeTurnError(NarrativeTurnError.TRANSITION_PREVIOUS_MISMATCH, f"non-first transition (sequence={self.sequence}) must have previous_transition_id")

    def fingerprint(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "transition_id": self.transition_id,
            "turn_id": self.turn_id,
            "project_id": self.scope.project_id,
            "timeline_id": self.scope.timeline_id,
            "branch_id": self.scope.branch_id,
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "reason_code": self.reason_code,
            "operation_id": self.operation_id,
            "occurred_at": self.occurred_at,
            "record_fingerprint": self.record_fingerprint,
            "sequence": self.sequence,
            "previous_transition_id": self.previous_transition_id,
            "previous_transition_fingerprint": self.previous_transition_fingerprint,
        }
        return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(12)}"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()
