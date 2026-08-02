"""Fail-closed approval-to-Commit authority validation for Phase 0D8-C.

This module is intentionally a small boundary around the existing Canon/Commit
pipeline.  It resolves one exact work-version identity, revalidates the
immutable human decision and the final selected pointer, and returns a frozen
provenance payload for the Commit record.  It never changes selection,
decisions, evidence, or lineage.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.project_context import ProjectContext
from system.review_decision_service import (
    ReviewDecisionIdentity,
    capture_identity,
    list_decisions,
    read_decision_state,
)
from system.review_transition_service import transition_state_for_version
from system.version_manager import list_versions


class CommitAuthorityError(RuntimeError):
    """A deterministic fail-closed approval-to-Commit rejection."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ApprovedCommitAuthority:
    identity: ReviewDecisionIdentity
    decision_id: str
    decision_type: str
    decision_status: str
    decided_at: str
    validated_at: str
    transition_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": asdict(self.identity),
            "decision_id": self.decision_id,
            "decision_type": self.decision_type,
            "decision_status": self.decision_status,
            "decided_at": self.decided_at,
            "validated_at": self.validated_at,
            "transition_id": self.transition_id,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def identity_from_payload(payload: ReviewDecisionIdentity | dict[str, Any]) -> ReviewDecisionIdentity:
    if isinstance(payload, ReviewDecisionIdentity):
        return payload
    if not isinstance(payload, dict):
        raise CommitAuthorityError("COMMIT_SOURCE_MISMATCH", "Commit source identity is missing.")
    try:
        return ReviewDecisionIdentity(
            project_id=str(payload["project_id"]),
            timeline_id=str(payload["timeline_id"]),
            branch_id=str(payload["branch_id"]),
            chapter_id=int(payload["chapter_id"]),
            source_type=str(payload["source_type"]),
            source_version_id=str(payload["source_version_id"]),
            content_fingerprint=str(payload["content_fingerprint"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CommitAuthorityError("COMMIT_SOURCE_MISMATCH", "Commit source identity is incomplete.") from exc


def _source_path(context: ProjectContext, identity: ReviewDecisionIdentity) -> Path | None:
    root = context.root / "data"
    pattern = re.compile(rf"^chapter_{identity.chapter_id:03d}_{re.escape(identity.source_type)}_v\d{{3}}\.json$")
    for directory in ("drafts", "edited", "manual"):
        folder = root / directory
        if not folder.exists():
            continue
        for path in sorted(folder.glob(f"chapter_{identity.chapter_id:03d}_{identity.source_type}_v*.json")):
            if not pattern.match(path.name):
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if str(payload.get("version_label") or "") == identity.source_version_id:
                return path
    return None


def _decision_by_id(context: ProjectContext, decision_id: str | None) -> dict[str, Any] | None:
    if not decision_id:
        return None
    try:
        for record in list_decisions(context):
            if str(record.get("decision_id") or "") == str(decision_id):
                return record
    except Exception as exc:
        raise CommitAuthorityError("APPROVAL_INVALID", "Approval decision history is unreadable.") from exc
    return None


def _raise_for_decision_state(state: dict[str, Any], identity: ReviewDecisionIdentity) -> None:
    status = str(state.get("status") or "MISSING").upper()
    mapping = {
        "MISSING": "APPROVAL_MISSING",
        "STALE": "APPROVAL_STALE",
        "INVALID": "APPROVAL_INVALID",
        "CONFLICTING": "APPROVAL_CONFLICTING",
    }
    if status in mapping:
        raise CommitAuthorityError(mapping[status], f"Approval for {identity.source_version_id} is {status}.")


def validate_approved_commit(
    context: ProjectContext,
    approved_identity: ReviewDecisionIdentity | dict[str, Any],
    *,
    decision_id: str | None = None,
) -> ApprovedCommitAuthority:
    """Revalidate exact approval, source content, scope, and final selection.

    The final selected pointer is intentionally part of the contract: approved
    identity == explicit commit identity == selected identity at the final
    gate.  No fallback to latest/current selection is allowed.
    """
    identity = identity_from_payload(approved_identity)
    if identity.project_id != context.root.name:
        raise CommitAuthorityError("COMMIT_SCOPE_MISMATCH", "Approval belongs to another project.")
    if identity.timeline_id != "main" or not identity.branch_id:
        raise CommitAuthorityError("COMMIT_SCOPE_MISMATCH", "Commit scope is not supported by this boundary.")
    if identity.source_type not in {"draft", "edited", "manual"} or identity.chapter_id < 1:
        raise CommitAuthorityError("COMMIT_SOURCE_MISMATCH", "Commit source type or chapter is invalid.")

    source_path = _source_path(context, identity)
    if source_path is None:
        raise CommitAuthorityError("COMMIT_SOURCE_MISMATCH", "The exact approved work version no longer exists.")
    current = capture_identity(context, {
        "chapter_id": identity.chapter_id,
        "source_type": identity.source_type,
        "version_label": identity.source_version_id,
        "json_path": source_path,
    })
    if current.project_id != identity.project_id or current.timeline_id != identity.timeline_id or current.branch_id != identity.branch_id or current.chapter_id != identity.chapter_id:
        raise CommitAuthorityError("COMMIT_SCOPE_MISMATCH", "Commit source scope differs from approval scope.")
    if current.source_type != identity.source_type or current.source_version_id != identity.source_version_id:
        raise CommitAuthorityError("COMMIT_SOURCE_MISMATCH", "Commit source differs from approved source version.")
    if current.content_fingerprint != identity.content_fingerprint:
        raise CommitAuthorityError("APPROVAL_FINGERPRINT_MISMATCH", "Approved content fingerprint no longer matches.")

    state = read_decision_state(context, identity)
    _raise_for_decision_state(state, identity)
    decision = state.get("decision") if isinstance(state.get("decision"), dict) else None
    if not decision:
        raise CommitAuthorityError("APPROVAL_MISSING", "No current approval decision exists for this version.")
    if str(decision.get("decision_type") or "").upper() != "APPROVED":
        if str(decision.get("decision_type") or "").upper() == "REJECTED":
            raise CommitAuthorityError("APPROVAL_REJECTED", "The exact work version was rejected.")
        raise CommitAuthorityError("APPROVAL_INVALID", "The exact work version is not approved.")
    if decision_id and str(decision.get("decision_id") or "") != str(decision_id):
        historical = _decision_by_id(context, decision_id)
        if historical and historical.get("identity", {}).get("content_fingerprint") != identity.content_fingerprint:
            raise CommitAuthorityError("APPROVAL_FINGERPRINT_MISMATCH", "Decision fingerprint differs from Commit source.")
        raise CommitAuthorityError("APPROVAL_VERSION_MISMATCH", "Commit decision identity differs from current approval.")

    versions = list_versions(identity.chapter_id, context.data_dir)
    selected = versions.get("selected") if isinstance(versions.get("selected"), dict) else None
    selected_label = str(selected.get("version_label") or "") if selected else ""
    if selected and not selected_label:
        selected_label = f"{selected.get('source_type', '')}_v{int(selected.get('version', 0) or 0):03d}"
    if not selected or str(selected.get("source_type") or "") != identity.source_type or selected_label != identity.source_version_id:
        raise CommitAuthorityError("COMMIT_SELECTION_DRIFT", "The selected version no longer matches the approved Commit source.")
    selected_path = Path(str(selected.get("json_path") or ""))
    if not selected_path.is_file():
        collection = "drafts" if identity.source_type == "draft" else identity.source_type
        selected_path = Path(str(next((item.get("json_path") for item in versions.get(collection, []) if str(item.get("version_label") or selected_label) == selected_label), "")))
    if not selected_path.is_file():
        raise CommitAuthorityError("COMMIT_SELECTION_DRIFT", "The selected approved source is unavailable.")
    selected_identity = capture_identity(context, {
        "chapter_id": identity.chapter_id,
        "source_type": identity.source_type,
        "version_label": identity.source_version_id,
        "json_path": selected_path,
    })
    if selected_identity != identity:
        raise CommitAuthorityError("COMMIT_SELECTION_DRIFT", "Selected source identity or fingerprint drifted.")

    try:
        transition = transition_state_for_version(context, identity)
    except Exception as exc:
        raise CommitAuthorityError("APPROVAL_INVALID", "Revision lineage authority is unreadable.") from exc
    if str(transition.get("status") or "").upper() == "INVALID":
        raise CommitAuthorityError("APPROVAL_INVALID", "Revision lineage is invalid or conflicting.")
    if bool(transition.get("re_review_required")):
        raise CommitAuthorityError("APPROVAL_STALE", "This revision requires a fresh review before Commit.")

    transition_record = transition.get("transition") if isinstance(transition.get("transition"), dict) else {}
    return ApprovedCommitAuthority(
        identity=identity,
        decision_id=str(decision.get("decision_id") or ""),
        decision_type="APPROVED",
        decision_status="CURRENT",
        decided_at=str(decision.get("decided_at") or ""),
        validated_at=_now(),
        transition_id=str(transition_record.get("transition_id") or "") or None,
    )
