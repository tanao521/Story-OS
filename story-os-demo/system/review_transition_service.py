"""Durable request-changes transitions for pre-commit work versions.

This is deliberately separate from Canon revision authority and from the
0D8-A human decision log.  A transition records an explicit human request to
move from one exact work-version identity to another; it never creates or
inherits a decision.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.project_context import ProjectContext
from system.review_decision_service import (
    ReviewDecisionIdentity,
    ReviewDecisionInvalid,
    capture_identity_for_version,
    read_decision_state,
)


TRANSITION_SCHEMA_VERSION = "1.0"
TRANSITION_EVENTS = {"REQUESTED", "REVISION_CREATED"}
TRANSITION_STATUSES = {"REQUESTED", "REVISION_CREATED", "SUPERSEDED", "INVALID", "CONFLICTING"}


class ReviewTransitionError(Exception):
    """Base error for fail-closed transition operations."""


class ReviewTransitionConflict(ReviewTransitionError):
    """An operation or resulting version conflicts with existing authority."""


class ReviewTransitionInvalid(ReviewTransitionError):
    """A transition record or referenced work-version identity is invalid."""


class ReviewTransitionDrift(ReviewTransitionConflict):
    """The frozen source identity changed before the transition could persist."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _transition_dir(context: ProjectContext) -> Path:
    return context.root / "data" / "review_transitions"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewTransitionInvalid(f"Invalid transition record: {path}") from exc
    if not isinstance(value, dict):
        raise ReviewTransitionInvalid(f"Transition record must be an object: {path}")
    return value


def _identity_from_payload(raw: Any) -> ReviewDecisionIdentity:
    if not isinstance(raw, dict):
        raise ReviewTransitionInvalid("Missing transition identity")
    try:
        identity = ReviewDecisionIdentity(
            project_id=str(raw["project_id"]),
            timeline_id=str(raw["timeline_id"]),
            branch_id=str(raw["branch_id"]),
            chapter_id=int(raw["chapter_id"]),
            source_type=str(raw["source_type"]),
            source_version_id=str(raw["source_version_id"]),
            content_fingerprint=str(raw["content_fingerprint"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ReviewTransitionInvalid("Incomplete transition identity") from exc
    if (
        identity.chapter_id < 1
        or identity.source_type not in {"draft", "edited", "manual"}
        or not identity.project_id
        or not identity.timeline_id
        or not identity.branch_id
        or not identity.source_version_id
        or len(identity.content_fingerprint) != 64
        or any(char not in "0123456789abcdef" for char in identity.content_fingerprint.lower())
    ):
        raise ReviewTransitionInvalid("Invalid transition identity")
    return identity


def _identity_payload(identity: ReviewDecisionIdentity) -> dict[str, Any]:
    return asdict(identity)


def _event_path(context: ProjectContext, transition_id: str, event: str, event_id: str) -> Path:
    return _transition_dir(context) / f"{transition_id}__{event.lower()}__{event_id}.json"


def _validate_event(record: dict[str, Any]) -> tuple[str, str, ReviewDecisionIdentity, ReviewDecisionIdentity | None]:
    if record.get("schema_version") != TRANSITION_SCHEMA_VERSION:
        raise ReviewTransitionInvalid("Invalid transition schema")
    transition_id = str(record.get("transition_id") or "")
    operation_id = str(record.get("operation_id") or "")
    event = str(record.get("event") or "").upper()
    if not transition_id or not operation_id or event not in TRANSITION_EVENTS or not str(record.get("event_at") or ""):
        raise ReviewTransitionInvalid("Incomplete transition event")
    source = _identity_from_payload(record.get("source_identity"))
    result_raw = record.get("result_identity")
    result = _identity_from_payload(result_raw) if result_raw is not None else None
    if event == "REQUESTED" and result is not None:
        raise ReviewTransitionInvalid("REQUESTED event cannot contain a result identity")
    if event == "REVISION_CREATED" and result is None:
        raise ReviewTransitionInvalid("REVISION_CREATED event requires a result identity")
    return transition_id, operation_id, source, result


def _events(context: ProjectContext) -> list[dict[str, Any]]:
    directory = _transition_dir(context)
    if not directory.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        record = _read_json(path)
        _validate_event(record)
        records.append(record)
    return records


def _fold_events(context: ProjectContext) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in _events(context):
        grouped.setdefault(str(record["transition_id"]), []).append(record)
    states: list[dict[str, Any]] = []
    for transition_id, records in grouped.items():
        records.sort(key=lambda item: (
            str(item.get("event_at", "")),
            0 if str(item.get("event", "")).upper() == "REQUESTED" else 1,
            str(item.get("event_id", "")),
        ))
        first = records[0]
        _, operation_id, source, _ = _validate_event(first)
        status = "REQUESTED"
        result: ReviewDecisionIdentity | None = None
        conflict = False
        for record in records:
            _, event_operation, event_source, event_result = _validate_event(record)
            if event_operation != operation_id or event_source != source:
                conflict = True
                continue
            event = str(record["event"]).upper()
            if event == "REQUESTED":
                if status != "REQUESTED":
                    conflict = True
            elif event == "REVISION_CREATED":
                if status == "REVISION_CREATED" and event_result != result:
                    conflict = True
                elif event_result is not None:
                    status = "REVISION_CREATED"
                    result = event_result
        if conflict:
            status = "CONFLICTING"
        states.append({
            "transition_id": transition_id,
            "operation_id": operation_id,
            "status": status,
            "source_identity": _identity_payload(source),
            "result_identity": _identity_payload(result) if result else None,
            "request": {
                "actor": str(first.get("actor") or "user"),
                "note": str(first.get("note") or ""),
                "requested_at": str(first.get("event_at") or ""),
                "consulted_evidence": first.get("consulted_evidence"),
            },
            "history": records,
        })
    return sorted(states, key=lambda item: (str(item.get("request", {}).get("requested_at", "")), str(item["transition_id"])))


def list_transition_states(context: ProjectContext) -> list[dict[str, Any]]:
    """Read all transition states; malformed append-only data fails closed."""
    try:
        return _fold_events(context)
    except ReviewTransitionInvalid:
        raise


def _write_event(context: ProjectContext, record: dict[str, Any]) -> None:
    event_id = str(record["event_id"])
    path = _event_path(context, str(record["transition_id"]), str(record["event"]).lower(), event_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ReviewTransitionConflict("Transition event identity collision")
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _current_identity(context: ProjectContext, identity: ReviewDecisionIdentity) -> ReviewDecisionIdentity:
    try:
        return capture_identity_for_version(context, identity.chapter_id, identity.source_type, int(identity.source_version_id.rsplit("_v", 1)[-1]))
    except (ReviewDecisionInvalid, ValueError, IndexError) as exc:
        raise ReviewTransitionInvalid("Frozen source version cannot be resolved") from exc


def _exact_version_path(context: ProjectContext, identity: ReviewDecisionIdentity) -> Path:
    version_label = identity.source_version_id
    for directory in ("drafts", "edited", "manual"):
        root = context.root / "data" / directory
        if not root.exists():
            continue
        for path in sorted(root.glob("*.json")):
            try:
                payload = _read_json(path)
            except ReviewTransitionInvalid:
                continue
            if (
                int(payload.get("chapter_id", 0) or 0) == identity.chapter_id
                and str(payload.get("version_label") or "") == version_label
            ):
                return path
    raise ReviewTransitionInvalid("Exact version file cannot be resolved")


def request_changes(
    context: ProjectContext,
    identity: ReviewDecisionIdentity,
    *,
    operation_id: str,
    actor: str = "user",
    note: str = "",
    consulted_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze and persist a request-changes event for one exact source version."""
    operation_id = str(operation_id or "").strip()
    if not operation_id:
        raise ReviewTransitionInvalid("operation_id is required")
    if _current_identity(context, identity) != identity:
        raise ReviewTransitionDrift("Frozen source identity changed before request persistence")
    states = list_transition_states(context)
    for state in states:
        if state["operation_id"] == operation_id:
            if state["source_identity"] != _identity_payload(identity):
                raise ReviewTransitionConflict("Operation identity conflicts with an existing transition")
            return {**state, "replayed": True}
        if state["status"] in {"REQUESTED", "REVISION_CREATED"} and state["source_identity"] == _identity_payload(identity):
            raise ReviewTransitionConflict("An active request-changes transition already exists for this exact version")
    transition_id = f"review_transition_{uuid.uuid4().hex}"
    event = {
        "schema_version": TRANSITION_SCHEMA_VERSION,
        "event_id": f"transition_event_{uuid.uuid4().hex}",
        "transition_id": transition_id,
        "operation_id": operation_id,
        "event": "REQUESTED",
        "event_at": _now(),
        "actor": str(actor or "user"),
        "note": str(note or "")[:2000],
        "consulted_evidence": dict(consulted_evidence) if isinstance(consulted_evidence, dict) else None,
        "source_identity": _identity_payload(identity),
    }
    _write_event(context, event)
    return {
        "transition_id": transition_id,
        "operation_id": operation_id,
        "status": "REQUESTED",
        "source_identity": _identity_payload(identity),
        "result_identity": None,
        "request": {"actor": event["actor"], "note": event["note"], "requested_at": event["event_at"], "consulted_evidence": event["consulted_evidence"]},
        "history": [event],
        "replayed": False,
    }


def get_transition(context: ProjectContext, transition_id: str) -> dict[str, Any]:
    for state in list_transition_states(context):
        if state["transition_id"] == str(transition_id):
            return state
    raise ReviewTransitionInvalid("Transition not found")


def attach_revision(
    context: ProjectContext,
    transition_id: str,
    result_identity: ReviewDecisionIdentity,
) -> dict[str, Any]:
    """Attach a newly-created Y to an existing frozen X transition."""
    state = get_transition(context, transition_id)
    if state["status"] == "REVISION_CREATED":
        if state.get("result_identity") == _identity_payload(result_identity):
            return {**state, "replayed": True}
        raise ReviewTransitionConflict("Transition already has a different resulting version")
    if state["status"] != "REQUESTED":
        raise ReviewTransitionConflict("Transition is not attachable")
    source = _identity_from_payload(state["source_identity"])
    if _current_identity(context, source) != source:
        raise ReviewTransitionDrift("Frozen source identity changed before revision attachment")
    current_result = _current_identity(context, result_identity)
    if current_result != result_identity:
        raise ReviewTransitionDrift("Resulting version changed before lineage attachment")
    if result_identity.scope_key[:4] != source.scope_key[:4]:
        raise ReviewTransitionConflict("Resulting version is outside the source scope")
    if result_identity == source or result_identity.content_fingerprint == source.content_fingerprint:
        raise ReviewTransitionConflict("Revision must be a distinct version with distinct content")
    result_payload = _read_json(_exact_version_path(context, result_identity))
    if str(result_payload.get("revision_transition_id") or "") != str(transition_id):
        raise ReviewTransitionConflict("Resulting version is not explicitly created for this transition")
    recorded_source = result_payload.get("revision_source_identity")
    if not isinstance(recorded_source, dict) or recorded_source != state["source_identity"]:
        raise ReviewTransitionConflict("Resulting version source lineage does not match frozen X")
    for other in list_transition_states(context):
        if other["transition_id"] != transition_id and other.get("result_identity") == _identity_payload(result_identity):
            raise ReviewTransitionConflict("Another transition already claims this resulting version")
    event = {
        "schema_version": TRANSITION_SCHEMA_VERSION,
        "event_id": f"transition_event_{uuid.uuid4().hex}",
        "transition_id": str(transition_id),
        "operation_id": state["operation_id"],
        "event": "REVISION_CREATED",
        "event_at": _now(),
        "source_identity": _identity_payload(source),
        "result_identity": _identity_payload(result_identity),
    }
    _write_event(context, event)
    return {
        **state,
        "status": "REVISION_CREATED",
        "result_identity": _identity_payload(result_identity),
        "history": [*state.get("history", []), event],
        "replayed": False,
    }


def transition_state_for_version(context: ProjectContext, identity: ReviewDecisionIdentity) -> dict[str, Any]:
    """Return lineage plus derived fresh-review state for an exact version."""
    states = list_transition_states(context)
    matches = [
        state for state in states
        if state.get("source_identity") == _identity_payload(identity)
        or state.get("result_identity") == _identity_payload(identity)
    ]
    if any(state["status"] in {"INVALID", "CONFLICTING"} for state in matches):
        return {"status": "INVALID", "transition": None, "re_review_required": False}
    transition = next((state for state in reversed(matches) if state["status"] in {"REQUESTED", "REVISION_CREATED"}), None)
    decision = read_decision_state(context, identity)
    is_revision_target = bool(transition and transition.get("result_identity") == _identity_payload(identity))
    re_review_required = is_revision_target and decision.get("status") != "CURRENT"
    return {
        "status": transition["status"] if transition else "MISSING",
        "transition": transition,
        "re_review_required": re_review_required,
        "decision_state": decision.get("status"),
        "is_revision_target": is_revision_target,
    }
