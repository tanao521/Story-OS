"""HTTP Wire DTO adapter for Narrative Turn read-only endpoints.

Phase 0D4-C: converts Python domain contracts (frozen dataclasses with
tuple-of-pairs and enums) into JSON-serializable Wire DTOs that contain
only JSON primitives, objects, and arrays.

Security:
- Never exposes Python method names, absolute paths, raw exceptions,
  tracebacks, or Provider information.
- Never echoes custom action raw text — only the SHA-256 hash.
- Tuples of pairs are converted to arrays of objects with explicit
  ``key`` / ``level`` fields; enums are converted to their string value.
- The DTO is a plain dict ready for ``json.dumps``; no dataclass
  accessors are exposed to the browser.
"""
from __future__ import annotations

from typing import Any

from core.contracts.narrative_turn import (
    ActionSource,
    NarrativeActionOption,
    NarrativeActionValidation,
    NarrativeScope,
    NarrativeTurnPlan,
    NarrativeTurnResult,
    ValidationStatus,
)
from core.contracts.narrative_turn_preview import NarrativeTurnPreview
from system.narrative_turn_context import NarrativeTurnContextSnapshot
from system.narrative_turn_service import ConfirmResult


# ---------------------------------------------------------------------------
# Primitive helpers — never leak Python internals
# ---------------------------------------------------------------------------

def _costs_risks_to_array(
    pairs: tuple[tuple[str, str], ...] | None,
) -> list[dict[str, str]]:
    """Convert a tuple-of-pairs into an array of {key, level} objects."""
    if not pairs:
        return []
    result: list[dict[str, str]] = []
    for pair in pairs:
        if isinstance(pair, (tuple, list)) and len(pair) == 2:
            key = str(pair[0]) if pair[0] is not None else ""
            level = str(pair[1]) if pair[1] is not None else ""
            result.append({"key": key, "level": level})
    return result


def _strings_to_array(items: tuple[str, ...] | list[str] | None) -> list[str]:
    if not items:
        return []
    return [str(item) for item in items if item is not None]


def _scope_to_dict(scope: NarrativeScope) -> dict[str, str]:
    return {
        "project_id": scope.project_id,
        "timeline_id": scope.timeline_id,
        "branch_id": scope.branch_id,
    }


def _branch_state_value(snapshot: NarrativeTurnContextSnapshot) -> str:
    """Derive the narrative_state_data dimension from snapshot limitations.

    Returns one of: ``available``, ``unavailable``, ``scope_mismatch``,
    ``invalid``.
    """
    limitations = set(snapshot.limitations)
    if "BRANCH_STATE_INVALID" in limitations:
        return "invalid"
    if "BRANCH_STATE_SCOPE_MISMATCH" in limitations:
        return "scope_mismatch"
    if "BRANCH_STATE_UNAVAILABLE" in limitations or not snapshot.branch_state_revision:
        return "unavailable"
    return "available"


def _situation_block(snapshot: NarrativeTurnContextSnapshot) -> dict[str, Any]:
    """Build the situation object for ContextWireDTO.

    All Python accessor calls happen here (server-side only). The result
    is a plain dict of JSON primitives, arrays, and objects.
    """
    chapter_plan = snapshot.chapter_plan_dict() or {}
    narrative_state = snapshot.narrative_state_dict() or {}
    world_data = snapshot.world_data_dict() or {}
    character_data = snapshot.character_data_dict() or {}
    rolling_window = snapshot.rolling_window_dict() or {}
    dependencies = snapshot.dependencies_dict() or {}
    planning = snapshot.planning_data_dict() or {}

    chapter_goal: str | None = None
    if isinstance(chapter_plan, dict):
        goal = chapter_plan.get("goal") or chapter_plan.get("chapter_goal")
        if goal:
            chapter_goal = str(goal)

    active_conflicts: list[str] = []
    conflicts_src = (
        narrative_state.get("active_conflicts")
        if isinstance(narrative_state, dict)
        else None
    )
    if conflicts_src is None and isinstance(planning, dict):
        conflicts_src = planning.get("conflicts")
    if isinstance(conflicts_src, list):
        for c in conflicts_src:
            if isinstance(c, dict):
                title = c.get("title") or c.get("id")
                if title:
                    active_conflicts.append(str(title))
            elif isinstance(c, str):
                active_conflicts.append(c)

    characters: list[str] = []
    if isinstance(character_data, dict):
        for key in ("main_characters", "supporting_characters"):
            lst = character_data.get(key)
            if isinstance(lst, list):
                for ch in lst:
                    if isinstance(ch, dict):
                        name = ch.get("name") or ch.get("id")
                        if name:
                            characters.append(str(name))

    locations: list[str] = []
    if isinstance(world_data, dict):
        locs = world_data.get("locations")
        if isinstance(locs, list):
            for loc in locs:
                if isinstance(loc, dict):
                    name = loc.get("name") or loc.get("location_name") or loc.get("id")
                    if name:
                        locations.append(str(name))

    resources: list[str] = []
    if isinstance(world_data, dict):
        res = world_data.get("resources")
        if isinstance(res, dict):
            resources = list(str(k) for k in res.keys() if k)
        elif isinstance(res, list):
            for r in res:
                if isinstance(r, dict):
                    name = r.get("name") or r.get("id")
                    if name:
                        resources.append(str(name))
                elif isinstance(r, str):
                    resources.append(r)

    world_rules: list[str] = []
    if isinstance(world_data, dict):
        core = world_data.get("core_rules")
        if isinstance(core, list):
            for rule in core:
                if isinstance(rule, dict):
                    text = rule.get("rule") or rule.get("id")
                    if text:
                        world_rules.append(str(text))
                elif isinstance(rule, str):
                    world_rules.append(rule)
        taboos = world_data.get("taboos_or_limits")
        if isinstance(taboos, list):
            for t in taboos:
                if isinstance(t, str):
                    world_rules.append(t)

    open_threads: list[str] = []
    if isinstance(rolling_window, dict):
        threads = rolling_window.get("open_threads") or rolling_window.get("threads")
        if isinstance(threads, list):
            for t in threads:
                if isinstance(t, dict):
                    tid = t.get("thread_id") or t.get("id") or t.get("title")
                    if tid:
                        open_threads.append(str(tid))
                elif isinstance(t, str):
                    open_threads.append(t)
    if not open_threads and isinstance(planning, dict):
        threads = planning.get("plot_threads")
        if isinstance(threads, list):
            for t in threads:
                if isinstance(t, dict):
                    status = str(t.get("status", "")).lower()
                    if status in ("active", "open", "unresolved"):
                        tid = t.get("thread_id") or t.get("id") or t.get("title")
                        if tid:
                            open_threads.append(str(tid))

    time_window: str | None = None
    if isinstance(narrative_state, dict):
        tw = narrative_state.get("time_window") or narrative_state.get("time_of_day")
        if tw:
            time_window = str(tw)

    deps_list: list[str] = []
    if isinstance(dependencies, dict):
        blocking = dependencies.get("blocking_dependencies")
        if isinstance(blocking, list):
            for d in blocking:
                if isinstance(d, dict):
                    label = d.get("id") or d.get("label") or d.get("node_id")
                    if label:
                        deps_list.append(str(label))

    return {
        "chapter_goal": chapter_goal,
        "active_conflicts": active_conflicts,
        "characters": characters,
        "locations": locations,
        "resources": resources,
        "world_rules": world_rules,
        "open_threads": open_threads,
        "time_window": time_window,
        "dependencies": deps_list,
    }


# ---------------------------------------------------------------------------
# Public DTO builders
# ---------------------------------------------------------------------------

def build_context_wire_dto(snapshot: NarrativeTurnContextSnapshot) -> dict[str, Any]:
    """Convert a NarrativeTurnContextSnapshot into ContextWireDTO.

    The output contains only JSON primitives, objects, and arrays. No
    Python method names, frozen tuple-of-pairs, enums, or Path objects
    are exposed.
    """
    return {
        "schema_version": snapshot.schema_version,
        "scope": _scope_to_dict(snapshot.scope),
        "chapter_id": snapshot.chapter_id,
        "source_version_id": snapshot.source_version_id,
        "context_fingerprint": snapshot.context_fingerprint,
        "branch_state_revision": snapshot.branch_state_revision,
        "canon_revision": snapshot.canon_revision,
        "planner_revision": snapshot.planner_revision,
        "branch": {
            "lifecycle": "open" if snapshot.branch_open else "archived",
            "activity": "active" if snapshot.branch_is_active else "inactive",
            "narrative_state_data": _branch_state_value(snapshot),
        },
        "situation": _situation_block(snapshot),
        "evidence_codes": _strings_to_array(snapshot.evidence_codes),
        "limitations": _strings_to_array(snapshot.limitations),
    }


def build_plan_wire_dto(plan: NarrativeTurnPlan) -> dict[str, Any]:
    """Convert a NarrativeTurnPlan into PlanWireDTO."""
    actions: list[dict[str, Any]] = []
    for action in plan.recommended_actions:
        actions.append(_action_option_to_dict(action))
    return {
        "schema_version": plan.schema_version,
        "turn_id": plan.turn_id,
        "scope": _scope_to_dict(plan.scope),
        "chapter_id": plan.chapter_id,
        "source_version_id": plan.source_version_id,
        "context_fingerprint": plan.context_fingerprint,
        "planner_revision": plan.planning_revision,
        "canon_revision": plan.canon_revision,
        "recommended_actions": actions,
        "custom_action_policy": {
            "max_length": plan.custom_action_policy.max_length,
            "forbidden_patterns": _strings_to_array(
                plan.custom_action_policy.forbidden_patterns
            ),
            "feasibility_pipeline": _strings_to_array(
                plan.custom_action_policy.feasibility_pipeline
            ),
        },
    }


def _action_option_to_dict(action: NarrativeActionOption) -> dict[str, Any]:
    return {
        "action_id": action.action_id,
        "action_type": action.action_type.value,
        "display_text": action.display_text,
        "intent": action.intent,
        "expected_costs": _costs_risks_to_array(action.expected_costs),
        "expected_risks": _costs_risks_to_array(action.expected_risks),
        "required_conditions": _strings_to_array(action.required_conditions),
        "unavailable_reasons": _strings_to_array(action.unavailable_reasons),
        "provenance": action.provenance,
        "deterministic_order": action.deterministic_order,
    }


def build_validation_wire_dto(
    validation: NarrativeActionValidation,
) -> dict[str, Any]:
    """Convert a NarrativeActionValidation into ValidationWireDTO.

    Never echoes the custom action raw text — only the SHA-256 hash.
    """
    return {
        "schema_version": validation.schema_version,
        "validation_id": validation.validation_id,
        "turn_id": validation.turn_id,
        "scope": _scope_to_dict(validation.scope),
        "chapter_id": validation.chapter_id,
        "context_fingerprint": validation.context_fingerprint,
        "action_source": validation.action_source.value,
        "selected_action_id": validation.selected_action_id,
        "custom_action_text_hash": validation.custom_action_text_hash,
        "status": validation.status.value,
        "blocking_reasons": _strings_to_array(validation.blocking_reasons),
        "cost_explanation": _costs_risks_to_array(validation.cost_explanation),
        "risk_explanation": _costs_risks_to_array(validation.risk_explanation),
        "checked_at": validation.checked_at,
    }


def build_preview_wire_dto(preview: NarrativeTurnPreview) -> dict[str, Any]:
    """Convert a NarrativeTurnPreview into PreviewWireDTO.

    Never echoes the custom action raw text — only the SHA-256 hash.
    """
    return {
        "schema_version": preview.schema_version,
        "preview_id": preview.preview_id,
        "turn_id": preview.turn_id,
        "scope": _scope_to_dict(preview.scope),
        "chapter_id": preview.chapter_id,
        "context_fingerprint": preview.context_fingerprint,
        "preview_fingerprint": preview.preview_fingerprint,
        "action_source": preview.action_source,
        "selected_action_id": preview.selected_action_id,
        "custom_action_text_hash": preview.custom_action_text_hash,
        "validation_status": preview.validation_status.value,
        "reason_codes": _strings_to_array(preview.evidence_codes),
        "expected_costs": _costs_risks_to_array(preview.expected_costs),
        "expected_risks": _costs_risks_to_array(preview.expected_risks),
        "likely_consequences": _strings_to_array(preview.likely_consequences),
        "evidence_codes": _strings_to_array(preview.evidence_codes),
        "limitations": _strings_to_array(preview.limitations),
        "generated_at": preview.generated_at,
    }


def build_confirm_result_wire_dto(confirm_result: ConfirmResult) -> dict[str, Any]:
    """Convert a ConfirmResult into ConfirmResponseWireDTO.

    Never exposes raw custom action text, internal state delta,
    absolute paths, operation phase internals, or tracebacks.
    """
    result = confirm_result.result
    return {
        "schema_version": result.schema_version,
        "operation_id": result.operation_id,
        "idempotent_replay": confirm_result.idempotent_replay,
        "recovery_performed": confirm_result.recovery_performed,
        "turn_state": confirm_result.final_phase,
        "result": {
            "turn_id": result.turn_id,
            "scope": _scope_to_dict(result.scope),
            "chapter_id": result.chapter_id,
            "selected_action_id": result.selected_action_id,
            "custom_action_text_hash": result.custom_action_text_hash,
            "result_status": result.result_status.value,
            "event_summary": result.event_summary,
            "consequence_flags": _strings_to_array(result.consequence_flags),
            "next_context_fingerprint": result.next_context_fingerprint,
            "execution_revision": result.execution_revision,
            "source_fingerprint": result.source_fingerprint,
            "confirmed_at": result.confirmed_at,
        },
        "branch_state_revision": confirm_result.branch_state_revision,
    }


def error_envelope(code: str, message: str, request_id: str | None = None) -> dict[str, Any]:
    """Build the unified error envelope.

    The envelope never includes raw exceptions, tracebacks, absolute
    paths, custom action raw text, or Provider information.
    """
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
        }
    }


# ---------------------------------------------------------------------------
# Security boundary — verify a DTO contains only JSON primitives
# ---------------------------------------------------------------------------

_JSON_PRIMITIVES = (type(None), bool, int, str)


def assert_json_safe(value: Any, *, path: str = "$") -> None:
    """Recursively assert that a value is JSON-safe.

    Allows: None, bool, int, str, list, dict.
    Rejects: float NaN/Infinity, tuple (must be list), set, bytes,
    Path, datetime, custom objects.

    Floats are accepted only when finite; this mirrors the strict
    canonical serialization used by the context binder.
    """
    import math

    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise TypeError(f"{path}: NaN/Infinity float is not JSON-safe")
        return
    if isinstance(value, list):
        for i, item in enumerate(value):
            assert_json_safe(item, path=f"{path}[{i}]")
        return
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise TypeError(f"{path}.<key>: non-string key {type(k).__name__}")
            assert_json_safe(v, path=f"{path}.{k}")
        return
    raise TypeError(f"{path}: {type(value).__name__} is not JSON-safe")
