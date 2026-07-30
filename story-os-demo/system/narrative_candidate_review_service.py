"""Durable, first-writer-wins authority for Candidate review decisions.

Candidate versions remain immutable work versions.  This service is the sole
authority for a human review decision and is deliberately separate from both
the compiler and ChapterCommitService.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from core.contracts.narrative_turn import TimelineContext, now_utc
from core.contracts import HashGuard
from core.project_context import ProjectContext
from system.narrative_branch_store import NarrativeBranchStore
from system.narrative_chapter_compiler import CompilationScope, NarrativeCompilationError
from system.revision_service import RevisionService
from system.version_manager import list_versions, read_version_payload


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, ensure_ascii=False, indent=2)
            handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try: os.unlink(temporary)
        except OSError: pass


def _immutable(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded); handle.flush(); os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
            return value
        except FileExistsError:
            existing = _read(path)
            if not existing:
                raise NarrativeCompilationError("REVIEW_CHAIN_INVALID", "Review authority is corrupt.")
            return existing
    finally:
        try: os.unlink(temporary)
        except OSError: pass


class NarrativeCandidateReviewService:
    """Review decisions and the read-only commit gate for Candidate versions."""

    schema_version = "1.0"

    def __init__(self, context: ProjectContext, canonical_project_id: str | None = None):
        self.context = context
        self.canonical_project_id = canonical_project_id or context.root.name
        self.storage_project_id = context.root.name
        self.branches = NarrativeBranchStore(context)
        self.revisions = RevisionService(context)
        self._fault_injector = None

    @property
    def _root(self) -> Path:
        return self.context.data_dir / "narrative_candidate_review"

    def _fault(self, point: str) -> None:
        if self._fault_injector:
            self._fault_injector(point)

    def _candidate(self, scope: CompilationScope, candidate_id: str, candidate_version_id: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for kind in ("manual", "edited", "drafts"):
            for item in list_versions(scope.chapter_id, self.context.data_dir).get(kind, []):
                if candidate_version_id and item.get("version_label") != candidate_version_id:
                    continue
                try: payload = read_version_payload(item)
                except (OSError, ValueError, TypeError): continue
                provenance = payload.get("narrative_compilation") if isinstance(payload.get("narrative_compilation"), dict) else {}
                if str(payload.get("candidate_id") or provenance.get("candidate_id") or "") == candidate_id:
                    matches.append((item, payload))
        if len(matches) != 1:
            raise NarrativeCompilationError("CANDIDATE_COLLISION", "Candidate is unavailable or ambiguous.")
        return matches[0]

    def _fresh(self, scope: CompilationScope, candidate_id: str, candidate_version_id: str | None = None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        item, payload = self._candidate(scope, candidate_id, candidate_version_id)
        provenance = payload.get("narrative_compilation") if isinstance(payload.get("narrative_compilation"), dict) else {}
        candidate_scope = payload.get("candidate_scope") or provenance.get("scope")
        if candidate_scope != asdict(scope):
            raise NarrativeCompilationError("CANDIDATE_COLLISION", "Candidate scope does not match request.")
        fingerprint = str(payload.get("candidate_fingerprint") or provenance.get("candidate_fingerprint") or "")
        if not fingerprint:
            raise NarrativeCompilationError("CANDIDATE_COLLISION", "Candidate fingerprint is missing.")
        candidate_state = str(payload.get("review_status") or provenance.get("review_status") or "pending").lower()
        if candidate_state == "superseded":
            raise NarrativeCompilationError("CANDIDATE_SUPERSEDED", "Candidate has been superseded.")
        if candidate_state == "committed":
            raise NarrativeCompilationError("CANDIDATE_ALREADY_COMMITTED", "Candidate has already been committed.")
        candidate_source_version = str(payload.get("source_version_id") or candidate_scope.get("source_version_id") or "")
        candidate_source_fingerprint = str(payload.get("source_fingerprint") or candidate_scope.get("expected_source_fingerprint") or "")
        if candidate_source_version != str(scope.source_version_id or ""):
            raise NarrativeCompilationError("SOURCE_VERSION_STALE", "Candidate source version no longer matches scope.")
        if candidate_source_fingerprint != str(scope.expected_source_fingerprint or ""):
            raise NarrativeCompilationError("SOURCE_VERSION_STALE", "Candidate source fingerprint no longer matches scope.")
        # Bind review freshness to the current source bytes as well as the
        # metadata copied into the immutable Candidate payload.  Empty legacy
        # fixtures have no source catalog; a real project does, and in that
        # case a missing or changed source fails closed.
        versions = list_versions(scope.chapter_id, self.context.data_dir)
        source_matches = [
            entry for kind in ("drafts", "edited", "manual")
            for entry in versions.get(kind, [])
            if entry.get("version_label") == scope.source_version_id
        ]
        if source_matches:
            source_payload = read_version_payload(source_matches[0])
            source_text = str(source_payload.get("manual_text") or source_payload.get("edited_text") or source_payload.get("draft_text") or "")
            if HashGuard.sha256_text(source_text) != str(scope.expected_source_fingerprint or ""):
                raise NarrativeCompilationError("SOURCE_VERSION_STALE", "Source fingerprint changed.")
        elif any(versions.get(kind) for kind in ("drafts", "edited", "manual")):
            raise NarrativeCompilationError("SOURCE_VERSION_STALE", "Source version is unavailable.")
        timeline = TimelineContext(self.storage_project_id, scope.timeline_id)
        branch = self.branches.get_branch(timeline, scope.branch_id)
        if branch is None or branch.lifecycle_status.value == "archived":
            raise NarrativeCompilationError("BRANCH_ARCHIVED", "Candidate branch is not available.")
        if self.branches.get_registry_revision(timeline) != scope.expected_branch_registry_revision:
            raise NarrativeCompilationError("SOURCE_VERSION_STALE", "Branch registry revision changed.")
        active = self.revisions.read_active_canon(scope.chapter_id)
        active_id = str((active or {}).get("canon_version_id") or (active or {}).get("revision_id") or "")
        if active_id and active_id != scope.expected_canon_revision_id:
            raise NarrativeCompilationError("CANON_REVISION_STALE", "Expected Canon revision is no longer active.")
        return item, payload, {"candidate_fingerprint": fingerprint, "candidate_version_id": str(item.get("version_label") or ""), "active_canon_revision_id": active_id or scope.expected_canon_revision_id}

    def _authority(self, operation_id: str, request: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
        if not operation_id or "/" in operation_id or "\\" in operation_id:
            raise NarrativeCompilationError("REVIEW_SCOPE_REQUIRED", "operation_id is required.")
        path = self._root / "operations" / f"{operation_id}.json"
        record = {"schema_version": self.schema_version, "operation_id": operation_id, "operation_type": "candidate_review", **request, "created_at": now_utc()}
        record["record_fingerprint"] = _sha(record)
        existing = _immutable(path, record)
        if existing.get("canonical_request_fingerprint") != record["canonical_request_fingerprint"]:
            raise NarrativeCompilationError("REVIEW_OPERATION_CONFLICT", "operation_id is bound to another review request.")
        return path, existing

    def review_candidate(self, *, operation_id: str, scope: CompilationScope, candidate_id: str, candidate_version_id: str | None, decision: str, reviewer_id: str, reason: str = "") -> dict[str, Any]:
        scope.validate(self.context, self.canonical_project_id)
        decision = str(decision).lower()
        if decision not in {"approved", "rejected"} or not reviewer_id.strip() or not candidate_id:
            raise NarrativeCompilationError("REVIEW_SCOPE_REQUIRED", "candidate, reviewer identity, and approved/rejected decision are required.")
        existing_path = self._root / "operations" / f"{operation_id}.json"
        existing = _read(existing_path)
        if existing:
            if (existing.get("scope") != asdict(scope) or existing.get("candidate_id") != candidate_id
                    or (candidate_version_id is not None and existing.get("candidate_version_id") != candidate_version_id)
                    or existing.get("decision") != decision or existing.get("reviewer_id") != reviewer_id
                    or existing.get("reason", "") != reason):
                raise NarrativeCompilationError("REVIEW_OPERATION_CONFLICT", "operation_id is bound to another review request.")
            stored_result = _read(existing_path.with_suffix(".result.json"))
            if stored_result:
                self._validate_review_chain(scope, candidate_id, stored_result=stored_result)
                self._complete_recovered_operation(existing_path, existing)
                return {**stored_result, "replayed": True}
        snapshot_item, snapshot_payload = self._candidate(scope, candidate_id, candidate_version_id)
        snapshot_provenance = snapshot_payload.get("narrative_compilation") if isinstance(snapshot_payload.get("narrative_compilation"), dict) else {}
        snapshot_scope = snapshot_payload.get("candidate_scope") or snapshot_provenance.get("scope")
        snapshot_fingerprint = str(snapshot_payload.get("candidate_fingerprint") or snapshot_provenance.get("candidate_fingerprint") or "")
        if snapshot_scope != asdict(scope) or not snapshot_fingerprint:
            raise NarrativeCompilationError("CANDIDATE_COLLISION", "Candidate scope or fingerprint is invalid.")
        snapshot_version_id = str(snapshot_item.get("version_label") or "")
        request = {"scope": asdict(scope), "candidate_id": candidate_id, "candidate_version_id": snapshot_version_id, "candidate_fingerprint": snapshot_fingerprint, "decision": decision, "reviewer_id": reviewer_id, "reason": reason, "canonical_request_fingerprint": _sha({"scope": asdict(scope), "candidate_id": candidate_id, "candidate_version_id": snapshot_version_id, "candidate_fingerprint": snapshot_fingerprint, "decision": decision, "reviewer_id": reviewer_id, "reason": reason})}
        authority_path, authority = self._authority(operation_id, request)
        phase_path = authority_path.with_suffix(".phase.json")
        if not phase_path.exists():
            _atomic(phase_path, {"operation_id": operation_id, "phase": "OPERATION_CLAIMED", "scope": asdict(scope), "updated_at": now_utc()})
        self._fault("after_authority_claim")
        _atomic(phase_path, {"operation_id": operation_id, "phase": "CANDIDATE_SNAPSHOTTED", "scope": asdict(scope), "candidate_version_id": snapshot_version_id, "candidate_fingerprint": snapshot_fingerprint, "updated_at": now_utc()})
        self._fault("after_candidate_snapshot")
        result_path = authority_path.with_suffix(".result.json")
        result = _read(result_path)
        if result:
            if result.get("scope") != asdict(scope) or result.get("canonical_request_fingerprint") != authority.get("canonical_request_fingerprint"):
                raise NarrativeCompilationError("REVIEW_CHAIN_INVALID", "Durable review result does not match authority.")
            self._validate_review_chain(scope, candidate_id, stored_result=result)
            self._complete_recovered_operation(authority_path, authority)
            return {**result, "replayed": True}
        # Freshness is intentionally re-checked immediately before decision publication.
        _item, _payload, live = self._fresh(scope, candidate_id, candidate_version_id)
        _atomic(phase_path, {"operation_id": operation_id, "phase": "FRESHNESS_VALIDATED", "scope": asdict(scope), "candidate_version_id": live["candidate_version_id"], "candidate_fingerprint": live["candidate_fingerprint"], "updated_at": now_utc()})
        self._fault("after_first_freshness_validation")
        # The hook above models the review/supersede and review/archive race;
        # this second read is the publication fence.
        _item, _payload, live = self._fresh(scope, candidate_id, candidate_version_id)
        self._fault("before_decision_publish")
        decision_path = self._root / "decisions" / f"{candidate_id}.json"
        review = {"schema_version": self.schema_version, "review_id": f"review_{operation_id}", "operation_id": operation_id, "scope": asdict(scope), "project_id": scope.project_id, "timeline_id": scope.timeline_id, "branch_id": scope.branch_id, "chapter_id": scope.chapter_id, "candidate_id": candidate_id, "candidate_version_id": live["candidate_version_id"], "candidate_fingerprint": live["candidate_fingerprint"], "source_version_id": scope.source_version_id, "source_fingerprint": scope.expected_source_fingerprint, "expected_canon_revision_id": scope.expected_canon_revision_id, "expected_branch_registry_revision": scope.expected_branch_registry_revision, "decision": decision, "reviewer_id": reviewer_id, "reason": reason, "decided_at": now_utc(), "canonical_request_fingerprint": authority["canonical_request_fingerprint"]}
        review["outcome_fingerprint"] = _sha({k: review[k] for k in ("review_id", "candidate_id", "candidate_fingerprint", "decision", "reviewer_id", "canonical_request_fingerprint")})
        published = _immutable(decision_path, review)
        self._fault("after_review_decision_publication")
        self._fault("after_decision_publish")
        if published.get("operation_id") != operation_id:
            code = "REVIEW_DECISION_CONFLICT" if published.get("decision") != decision else "REVIEW_ALREADY_DECIDED"
            raise NarrativeCompilationError(code, "Candidate already has an immutable review decision.")
        result = {k: published[k] for k in ("review_id", "operation_id", "scope", "candidate_id", "candidate_version_id", "candidate_fingerprint", "decision", "reviewer_id", "reason", "decided_at", "canonical_request_fingerprint", "outcome_fingerprint")}
        _atomic(result_path, result)
        _atomic(phase_path, {"operation_id": operation_id, "phase": "RESULT_PUBLISHED", "scope": asdict(scope), "review_id": published["review_id"], "updated_at": now_utc()})
        self._fault("after_durable_result_publication")
        self._fault("after_result_publish")
        self._fault("before_completed_phase_marker")
        _atomic(phase_path, {"operation_id": operation_id, "phase": "COMPLETED", "scope": asdict(scope), "updated_at": now_utc()})
        return {**result, "replayed": False}

    def _complete_recovered_operation(self, authority_path: Path, authority: dict[str, Any]) -> None:
        phase_path = authority_path.with_suffix(".phase.json")
        phase = _read(phase_path)
        if phase and (phase.get("operation_id") != authority.get("operation_id") or phase.get("scope") != authority.get("scope")):
            raise NarrativeCompilationError("REVIEW_CHAIN_INVALID", "Review phase scope is invalid.")
        if phase.get("phase") != "COMPLETED":
            self._fault("before_completed_phase_marker")
            _atomic(phase_path, {"operation_id": authority["operation_id"], "phase": "COMPLETED", "scope": authority["scope"], "updated_at": now_utc()})

    def _validate_review_chain(self, scope: CompilationScope, candidate_id: str, *, stored_result: dict[str, Any] | None = None) -> dict[str, Any]:
        decision = _read(self._root / "decisions" / f"{candidate_id}.json")
        if not decision or decision.get("scope") != asdict(scope) or decision.get("candidate_id") != candidate_id:
            raise NarrativeCompilationError("REVIEW_CHAIN_INVALID", "Review decision chain is invalid.")
        authority = _read(self._root / "operations" / f"{decision.get('operation_id')}.json")
        if not authority or authority.get("operation_type") != "candidate_review":
            raise NarrativeCompilationError("REVIEW_CHAIN_INVALID", "Review authority chain is invalid.")
        if authority.get("scope") != asdict(scope) or authority.get("candidate_id") != candidate_id or authority.get("canonical_request_fingerprint") != decision.get("canonical_request_fingerprint"):
            raise NarrativeCompilationError("REVIEW_CHAIN_INVALID", "Review authority chain is invalid.")
        expected_outcome = _sha({k: decision.get(k) for k in ("review_id", "candidate_id", "candidate_fingerprint", "decision", "reviewer_id", "canonical_request_fingerprint")})
        if decision.get("outcome_fingerprint") != expected_outcome or decision.get("decision") not in {"approved", "rejected"}:
            raise NarrativeCompilationError("REVIEW_CHAIN_INVALID", "Review decision chain is invalid.")
        result = stored_result or _read(self._root / "operations" / f"{authority.get('operation_id')}.result.json")
        if result and (result.get("scope") != asdict(scope) or result.get("operation_id") != decision.get("operation_id")
                       or result.get("canonical_request_fingerprint") != decision.get("canonical_request_fingerprint")
                       or result.get("decision") != decision.get("decision")):
            raise NarrativeCompilationError("REVIEW_CHAIN_INVALID", "Review result chain is invalid.")
        return decision

    def review_for_candidate(self, scope: CompilationScope, candidate_id: str) -> dict[str, Any] | None:
        record = _read(self._root / "decisions" / f"{candidate_id}.json")
        if not record: return None
        self._validate_review_chain(scope, candidate_id)
        return record

    def assert_commit_approved(self, *, scope: CompilationScope, candidate_id: str, candidate_version_id: str, candidate_fingerprint: str) -> dict[str, Any]:
        # Re-read all authorities; a stored approval is only usable while fresh.
        self._fresh(scope, candidate_id, candidate_version_id)
        review = self.review_for_candidate(scope, candidate_id)
        if not review:
            raise NarrativeCompilationError("CANDIDATE_NOT_APPROVED", "Candidate requires durable human approval.")
        if review.get("candidate_version_id") != candidate_version_id or review.get("candidate_fingerprint") != candidate_fingerprint:
            raise NarrativeCompilationError("CANDIDATE_REVIEW_STALE", "Candidate review does not match candidate authority.")
        if review.get("decision") != "approved":
            raise NarrativeCompilationError("CANDIDATE_NOT_APPROVED", "Candidate review did not approve commit.")
        return review
