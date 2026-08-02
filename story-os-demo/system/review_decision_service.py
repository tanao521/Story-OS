"""Immutable, exact-work-version human review decisions.

Assembly/quality evidence is deliberately not consulted here.  This module is
the human-decision authority boundary for pre-commit work versions; Commit
eligibility remains outside 0D8-A.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.project_context import ProjectContext


DECISION_TYPES = {"APPROVED", "REJECTED"}
SOURCE_TYPES = {"draft", "edited", "manual"}
DECISION_STATES = {"CURRENT", "STALE", "MISSING", "INVALID", "CONFLICTING"}
SCHEMA_VERSION = "1.0"


class ReviewDecisionError(Exception):
    """Base error for fail-closed decision operations."""


class ReviewDecisionConflict(ReviewDecisionError):
    """The frozen decision identity no longer matches source authority."""


class ReviewDecisionInvalid(ReviewDecisionError):
    """A decision payload or requested decision is invalid."""


@dataclass(frozen=True)
class ReviewDecisionIdentity:
    project_id: str
    timeline_id: str
    branch_id: str
    chapter_id: int
    source_type: str
    source_version_id: str
    content_fingerprint: str

    @property
    def scope_key(self) -> tuple[str, str, str, int, str]:
        return (self.project_id, self.timeline_id, self.branch_id, self.chapter_id, self.source_type)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def content_fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewDecisionInvalid(f"Invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ReviewDecisionInvalid(f"Decision payload must be an object: {path}")
    return value


def _source_text(path: Path, payload: dict[str, Any]) -> str:
    field = next((name for name in ("manual_text", "edited_text", "draft_text", "content") if name in payload), None)
    if field is None:
        raise ReviewDecisionInvalid(f"Version payload has no text field: {path}")
    return str(payload.get(field) or "")


def _registry(context: ProjectContext) -> dict[str, Any]:
    path = context.root / "data" / "branches" / "main" / "registry.json"
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _version_path(context: ProjectContext, target: dict[str, Any]) -> Path:
    raw = Path(str(target.get("json_path") or ""))
    return raw if raw.is_absolute() else context.root / raw


def capture_identity(context: ProjectContext, target: dict[str, Any]) -> ReviewDecisionIdentity:
    """Capture a frozen exact-version identity from the authoritative file."""
    path = _version_path(context, target)
    if not path.exists():
        raise ReviewDecisionInvalid(f"Version file does not exist: {path}")
    payload = _read_json(path)
    source_type = str(target.get("source_type") or "")
    version = int(target.get("version", payload.get("version", 0)) or 0)
    version_id = str(target.get("version_label") or payload.get("version_label") or f"{source_type}_v{version:03d}")
    if source_type not in SOURCE_TYPES or version < 1 or not version_id:
        raise ReviewDecisionInvalid("Version identity is incomplete")
    registry = _registry(context)
    branch_id = str(registry.get("active_branch_id") or "main")
    return ReviewDecisionIdentity(
        project_id=str(context.root.name),
        timeline_id="main",
        branch_id=branch_id,
        chapter_id=int(target.get("chapter_id", payload.get("chapter_id", 0)) or 0),
        source_type=source_type,
        source_version_id=version_id,
        content_fingerprint=content_fingerprint(_source_text(path, payload)),
    )


def capture_identity_for_version(
    context: ProjectContext, chapter_id: int, source_type: str, version: int
) -> ReviewDecisionIdentity:
    """Capture an exact version without consulting the selected pointer."""
    label = f"{source_type}_v{int(version):03d}"
    root = context.root / "data"
    for directory in ("drafts", "edited", "manual"):
        path = root / directory / f"chapter_{int(chapter_id):03d}_{label}.json"
        if path.exists():
            return capture_identity(context, {
                "chapter_id": int(chapter_id), "source_type": source_type,
                "version": int(version), "version_label": label, "json_path": path,
            })
    raise ReviewDecisionInvalid("Exact work version does not exist")


def _identity_payload(identity: ReviewDecisionIdentity) -> dict[str, Any]:
    return asdict(identity)


def _decision_dir(context: ProjectContext) -> Path:
    return context.root / "data" / "review_decisions"


def _record_identity(record: dict[str, Any]) -> ReviewDecisionIdentity:
    raw = record.get("identity")
    if not isinstance(raw, dict):
        raise ReviewDecisionInvalid("Missing decision identity")
    required = ("project_id", "timeline_id", "branch_id", "chapter_id", "source_type", "source_version_id", "content_fingerprint")
    if any(key not in raw for key in required):
        raise ReviewDecisionInvalid("Incomplete decision identity")
    identity = ReviewDecisionIdentity(
        project_id=str(raw["project_id"]), timeline_id=str(raw["timeline_id"]), branch_id=str(raw["branch_id"]),
        chapter_id=int(raw["chapter_id"]), source_type=str(raw["source_type"]),
        source_version_id=str(raw["source_version_id"]), content_fingerprint=str(raw["content_fingerprint"]),
    )
    if (
        not identity.project_id or not identity.timeline_id or not identity.branch_id
        or identity.chapter_id < 1 or identity.source_type not in SOURCE_TYPES
        or not identity.source_version_id
        or len(identity.content_fingerprint) != 64
        or any(char not in "0123456789abcdef" for char in identity.content_fingerprint.lower())
    ):
        raise ReviewDecisionInvalid("Invalid decision identity")
    return identity


def _validate_record(record: dict[str, Any]) -> ReviewDecisionIdentity:
    if record.get("schema_version") != SCHEMA_VERSION or not str(record.get("decision_id") or ""):
        raise ReviewDecisionInvalid("Invalid decision schema")
    if str(record.get("decision_type") or "").upper() not in DECISION_TYPES:
        raise ReviewDecisionInvalid("Invalid decision type")
    if not str(record.get("decided_at") or ""):
        raise ReviewDecisionInvalid("Missing decision timestamp")
    return _record_identity(record)


def create_decision(
    context: ProjectContext,
    identity: ReviewDecisionIdentity,
    decision_type: str,
    *,
    actor: str = "user",
    note: str = "",
    consulted_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist one immutable decision after revalidating the frozen identity."""
    normalized = str(decision_type or "").upper()
    if normalized not in DECISION_TYPES:
        raise ReviewDecisionInvalid("Only APPROVED and REJECTED are supported in 0D8-A")
    target = {
        "chapter_id": identity.chapter_id,
        "source_type": identity.source_type,
        "version_label": identity.source_version_id,
        "json_path": _find_version_path(context, identity),
    }
    current = capture_identity(context, target)
    if current != identity:
        raise ReviewDecisionConflict("Frozen review identity no longer matches current version content")
    record = {
        "schema_version": SCHEMA_VERSION,
        "decision_id": f"review_decision_{uuid.uuid4().hex}",
        "identity": _identity_payload(identity),
        "decision_type": normalized,
        "decided_at": _now(),
        "actor": str(actor or "user"),
        "note": str(note or "")[:2000],
        "consulted_evidence": dict(consulted_evidence) if isinstance(consulted_evidence, dict) else None,
    }
    path = _decision_dir(context) / f"{record['decision_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ReviewDecisionConflict("Decision identity collision")
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def _find_version_path(context: ProjectContext, identity: ReviewDecisionIdentity) -> str:
    root = context.root / "data"
    for directory in ("drafts", "edited", "manual"):
        for path in sorted((root / directory).glob("*.json")) if (root / directory).exists() else ():
            try:
                payload = _read_json(path)
            except ReviewDecisionInvalid:
                continue
            label = str(payload.get("version_label") or "")
            if label == identity.source_version_id and int(payload.get("chapter_id", 0) or 0) == identity.chapter_id:
                return path.as_posix()
    raise ReviewDecisionInvalid("Exact version file cannot be resolved")


def list_decisions(context: ProjectContext) -> list[dict[str, Any]]:
    directory = _decision_dir(context)
    if not directory.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        records.append(_read_json(path))
    return records


def read_decision_state(context: ProjectContext, identity: ReviewDecisionIdentity) -> dict[str, Any]:
    """Return a fail-closed read model for one exact identity."""
    exact: list[dict[str, Any]] = []
    related: list[dict[str, Any]] = []
    invalid = False
    integrity_error: str | None = None
    directory = _decision_dir(context)
    records: list[dict[str, Any]] = []
    if directory.exists():
        for path in sorted(directory.glob("*.json")):
            try:
                record = _read_json(path)
                if str(record.get("decision_id") or "") != path.stem:
                    invalid = True
                    integrity_error = "APPROVAL_DECISION_ID_MISMATCH"
                records.append(record)
            except ReviewDecisionInvalid:
                invalid = True
    for record in records:
        try:
            record_identity = _validate_record(record)
        except ReviewDecisionInvalid:
            invalid = True
            continue
        if record_identity == identity:
            exact.append(record)
        elif record_identity.scope_key == identity.scope_key:
            related.append(record)
    if invalid:
        # Any unreadable record makes the read model unsafe to interpret.  Do
        # not let a valid-looking exact record mask a corrupt append-only log.
        return {
            "status": "INVALID",
            "error_code": integrity_error or "APPROVAL_INVALID",
            "decision": None,
            "history": exact + related,
        }
    types = {str(item.get("decision_type", "")).upper() for item in exact}
    if len(types) > 1:
        return {"status": "CONFLICTING", "decision": None, "history": exact + related}
    if exact:
        latest = sorted(exact, key=lambda item: str(item.get("decided_at", "")))[-1]
        return {"status": "CURRENT", "decision": latest, "history": exact + related}
    if related:
        return {"status": "STALE", "decision": None, "history": related}
    return {"status": "MISSING", "decision": None, "history": []}
