"""Deterministic confirmed-Turn compilation and ChapterCommit wiring.

This module intentionally keeps compilation (a work-version write) separate
from the existing ChapterCommitService.  Turn records are never rewritten;
only their append-only transition journals are advanced.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.contracts import HashGuard, ProjectRef
from core.contracts.adoption_contract import AdoptionRequest
from core.contracts.narrative_turn import (
    NarrativeScope, NarrativeTurnTransition, TurnState, SCHEMA_VERSION, new_id, now_utc,
    TimelineContext,
)
from core.contracts.revision_contract import RevisionCandidate
from core.project_context import ProjectContext
from system.narrative_branch_store import NarrativeBranchStore
from system.narrative_turn_store import NarrativeTurnStore
from system.version_manager import read_version_payload, list_versions, get_next_version_number
from system.version_writer_facade import VersionWriterFacade
from system.chapter_commit_service import ChapterCommitService, PostCommitPolicy, CommitStatus
from system.revision_service import RevisionService, CanonVersionNotFoundError
from system.vector_index_schema import VectorScope


class NarrativeCompilationError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class CompilationScope:
    project_id: str
    timeline_id: str
    branch_id: str
    chapter_id: int
    source_version_id: str | None
    expected_source_fingerprint: str | None
    expected_canon_revision_id: str
    expected_branch_registry_revision: str

    def validate(self, context: ProjectContext, canonical_project_id: str | None = None) -> None:
        values = (self.project_id, self.timeline_id, self.branch_id, self.expected_canon_revision_id, self.expected_branch_registry_revision)
        if any(not isinstance(v, str) or not v.strip() for v in values) or self.chapter_id < 1:
            raise NarrativeCompilationError("COMPILATION_SCOPE_REQUIRED", "Complete compilation scope is required.")
        if not self.source_version_id and not self.expected_source_fingerprint:
            raise NarrativeCompilationError("COMPILATION_SCOPE_REQUIRED", "source_version_id or expected_source_fingerprint is required.")
        if self.project_id != (canonical_project_id or context.root.name):
            raise NarrativeCompilationError("COMPILATION_SCOPE_REQUIRED", "project_id does not match the project context.")

    def scope(self) -> NarrativeScope:
        return NarrativeScope(self.project_id, self.timeline_id, self.branch_id)


def _sha(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, ensure_ascii=False, indent=2)
            handle.flush(); os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        try: os.unlink(name)
        except OSError: pass


def _publish_immutable_json(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Create authority once; concurrent identical writers reuse it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text); handle.flush(); os.fsync(handle.fileno())
        try:
            os.link(name, path)
            return payload
        except FileExistsError:
            existing = json.loads(path.read_text(encoding="utf-8"))
            return existing
    finally:
        try: os.unlink(name)
        except OSError: pass


class NarrativeChapterCompiler:
    compiler_revision = "0D4-F.1"

    def __init__(self, context: ProjectContext, canonical_project_id: str | None = None):
        self.context = context
        self.canonical_project_id = canonical_project_id or context.root.name
        self.storage_project_id = context.root.name
        self.turns = NarrativeTurnStore(context)
        self.branches = NarrativeBranchStore(context)
        self._fault_injector = None

    @property
    def _root(self) -> Path:
        return self.context.data_dir / "narrative_compile" / "operations"

    def _fault(self, point: str) -> None:
        if self._fault_injector:
            self._fault_injector(point)

    def _storage_scope(self, scope: CompilationScope) -> NarrativeScope:
        return NarrativeScope(self.storage_project_id, scope.timeline_id, scope.branch_id)

    def _authority(self, operation_id: str, request: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
        if not operation_id or "/" in operation_id or "\\" in operation_id:
            raise NarrativeCompilationError("COMPILATION_SCOPE_REQUIRED", "operation_id is required.")
        path = self._root / f"{operation_id}.json"
        record = {
            "schema_version": "1.0", "operation_id": operation_id, "operation_type": "compile",
            **request, "created_at": now_utc(),
        }
        record["record_fingerprint"] = _sha(record)
        if path.exists():
            try: existing = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc: raise NarrativeCompilationError("COMPILATION_OPERATION_CONFLICT", "Corrupt compile authority.") from exc
            if existing.get("canonical_request_fingerprint") != record.get("canonical_request_fingerprint"):
                raise NarrativeCompilationError("COMPILATION_OPERATION_CONFLICT", "operation_id is bound to another request.")
            return path, existing
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent), text=True)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(record, handle, sort_keys=True, ensure_ascii=False, indent=2); handle.flush(); os.fsync(handle.fileno())
            os.link(name, path)
            os.unlink(name)
        except FileExistsError:
            try: os.unlink(name)
            except OSError: pass
            return self._authority(operation_id, request)
        return path, record

    def _phase(self, path: Path, phase: str, **extra: Any) -> None:
        _atomic_json(path.with_suffix(".phase.json"), {"operation_id": path.stem, "phase": phase, **extra, "updated_at": now_utc()})

    def _result_path(self, authority_path: Path) -> Path:
        return authority_path.with_suffix(".result.json")

    def _read_result(self, authority_path: Path) -> dict[str, Any]:
        path = self._result_path(authority_path)
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def _validate_result_scope(self, result: dict[str, Any], scope: CompilationScope, request_fp: str | None = None) -> None:
        if not result:
            return
        if result.get("scope") and result.get("scope") != asdict(scope):
            raise NarrativeCompilationError("COMPILATION_OPERATION_CONFLICT", "Durable result scope does not match the request.")
        if request_fp and result.get("canonical_request_fingerprint") and result.get("canonical_request_fingerprint") != request_fp:
            raise NarrativeCompilationError("COMPILATION_OPERATION_CONFLICT", "Durable result request fingerprint does not match authority.")

    def _branch_check(self, scope: CompilationScope) -> None:
        timeline = TimelineContext(self.storage_project_id, scope.timeline_id)
        branch = self.branches.get_branch(timeline, scope.branch_id)
        if branch is None: raise NarrativeCompilationError("BRANCH_NOT_ACTIVE", "Branch does not exist.")
        if branch.lifecycle_status.value == "archived": raise NarrativeCompilationError("BRANCH_ARCHIVED", "Archived branches cannot compile.")
        if self.branches.get_active_branch_id(timeline) != scope.branch_id: raise NarrativeCompilationError("BRANCH_NOT_ACTIVE", "Branch is not active.")
        if self.branches.get_registry_revision(timeline) != scope.expected_branch_registry_revision:
            raise NarrativeCompilationError("SOURCE_VERSION_STALE", "Branch registry revision changed.")
        # If a canon authority exists, the caller must pin its active revision.
        # Empty chapters may legitimately have no canon yet.
        try:
            active = RevisionService(self.context).active_canon(scope.chapter_id)
        except CanonVersionNotFoundError:
            active = None
        if active and str(active.get("canon_version_id") or active.get("revision_id") or "") != scope.expected_canon_revision_id:
            raise NarrativeCompilationError("CANON_REVISION_STALE", "Expected Canon revision is no longer active.")

    def _source(self, scope: CompilationScope) -> tuple[str, str, str, int]:
        versions = list_versions(scope.chapter_id, self.context.data_dir)
        selected = versions.get("selected") if isinstance(versions.get("selected"), dict) else {}
        info = selected or (versions.get("manual") or versions.get("edited") or versions.get("drafts") or [{}])[-1]
        if scope.source_version_id:
            matches = [item for kind in ("drafts", "edited", "manual") for item in versions.get(kind, []) if item.get("version_label") == scope.source_version_id]
            if not matches: raise NarrativeCompilationError("SOURCE_VERSION_STALE", "Source version no longer exists.")
            info = matches[0]
        if not info: raise NarrativeCompilationError("SOURCE_VERSION_STALE", "Source version is unavailable.")
        payload = read_version_payload(info)
        text = str(payload.get("manual_text") or payload.get("edited_text") or payload.get("draft_text") or "")
        fingerprint = HashGuard.sha256_text(text)
        if scope.expected_source_fingerprint and fingerprint != scope.expected_source_fingerprint:
            raise NarrativeCompilationError("SOURCE_VERSION_STALE", "Source fingerprint changed.")
        return str(info.get("version_label") or scope.source_version_id or ""), fingerprint, text, int(info.get("version", 1) or 1)

    def _eligible(self, scope: CompilationScope, *, allow_included: bool = False) -> list[tuple[str, Any, list[Any], Any]]:
        found = []
        storage_scope = self._storage_scope(scope)
        for plan_id in self.turns.list_plans(storage_scope):
            plan = self.turns.get_plan(storage_scope, plan_id)
            if plan is None:
                continue
            if plan.chapter_id != scope.chapter_id or plan.source_version_id != scope.source_version_id and scope.source_version_id:
                continue
            try:
                transitions = self.turns.get_transitions(storage_scope, plan.turn_id)
            except Exception as exc:
                raise NarrativeCompilationError("TURN_CHAIN_INVALID", "Turn transition chain is invalid.") from exc
            if not transitions: continue
            if any(t.to_state in {TurnState.SUPERSEDED, TurnState.BLOCKED} for t in transitions): continue
            states = [t.to_state for t in transitions]
            if TurnState.CONFIRMED not in states or TurnState.APPLIED_TO_BRANCH not in states:
                continue
            if TurnState.INCLUDED_IN_CHAPTER in states or TurnState.COMMITTED in states:
                if allow_included and TurnState.COMMITTED not in states:
                    result = self.turns.get_result(storage_scope, plan.turn_id)
                    if result is not None:
                        applied = next((t for t in transitions if t.to_state == TurnState.APPLIED_TO_BRANCH), transitions[-1])
                        found.append((plan.turn_id, plan, transitions, result, applied.sequence))
                    continue
                raise NarrativeCompilationError("TURN_ALREADY_INCLUDED", f"Turn {plan.turn_id} is already included.")
            result = self.turns.get_result(storage_scope, plan.turn_id)
            if result is None: continue
            applied = next(t for t in transitions if t.to_state == TurnState.APPLIED_TO_BRANCH)
            found.append((plan.turn_id, plan, transitions, result, applied.sequence))
        if not found: raise NarrativeCompilationError("NO_ELIGIBLE_TURNS", "No eligible confirmed Turns were found.")
        found.sort(key=lambda item: (item[4], item[0]))
        return found

    def compile_candidate(self, *, operation_id: str, scope: CompilationScope) -> dict[str, Any]:
        scope.validate(self.context, self.canonical_project_id); self._branch_check(scope)
        source_id, source_fp, base_text, source_version = self._source(scope)
        existing_authority_path = self._root / f"{operation_id}.json"
        existing_phase_path = existing_authority_path.with_suffix(".phase.json")
        if existing_authority_path.exists() and existing_phase_path.exists():
            try:
                prior_authority = json.loads(existing_authority_path.read_text(encoding="utf-8"))
                prior_phase = json.loads(existing_phase_path.read_text(encoding="utf-8"))
                prior_result = self._read_result(existing_authority_path)
                self._validate_result_scope(prior_result, scope, prior_authority.get("canonical_request_fingerprint"))
                if prior_phase.get("scope") and prior_phase.get("scope") != asdict(scope):
                    raise NarrativeCompilationError("COMPILATION_OPERATION_CONFLICT", "Compile phase scope does not match request.")
                if prior_phase.get("phase") == "COMPLETED" and prior_result.get("candidate_version_id"):
                    return self._candidate_result({**prior_authority, **prior_result})
            except (OSError, ValueError, TypeError):
                pass
        allow_included = existing_authority_path.exists()
        eligible = self._eligible(scope, allow_included=allow_included)
        snippets = [str(item[3].event_summary or "").strip() for item in eligible]
        if not any(snippets): raise NarrativeCompilationError("TURN_CONTENT_NOT_COMPILABLE", "Persisted Turn results contain no compilable text.")
        turn_ids = [item[0] for item in eligible]; result_fps = [item[3].fingerprint() for item in eligible]
        candidate_fp = _sha({"project_id": scope.project_id, "timeline_id": scope.timeline_id, "branch_id": scope.branch_id, "chapter_id": scope.chapter_id, "base_source_version_id": source_id, "base_source_fingerprint": source_fp, "canon_revision_id": scope.expected_canon_revision_id, "ordered_turn_ids": turn_ids, "ordered_result_fingerprints": result_fps, "compiler_revision": self.compiler_revision})
        request = {"scope": asdict(scope), "ordered_turn_ids": turn_ids, "turn_set_fingerprint": _sha(turn_ids), "base_source_fingerprint": source_fp, "canon_revision_id": scope.expected_canon_revision_id, "canonical_request_fingerprint": _sha({"scope": asdict(scope), "turn_ids": turn_ids, "source": source_fp, "candidate_fingerprint": candidate_fp})}
        authority_path, authority = self._authority(operation_id, request); self._phase(authority_path, "OPERATION_CLAIMED", scope=asdict(scope)); self._fault("after_authority_claim")
        phase_path = authority_path
        prior_result = self._read_result(authority_path)
        self._validate_result_scope(prior_result, scope, authority.get("canonical_request_fingerprint"))
        if prior_result.get("candidate_fingerprint") == candidate_fp and prior_result.get("candidate_version_id"):
            self._append_included(scope, operation_id, eligible)
            self._phase(phase_path, "INCLUDED_TRANSITIONS_APPENDED", scope=asdict(scope)); self._phase(phase_path, "COMPLETED", scope=asdict(scope))
            return self._candidate_result({**authority, **prior_result})
        # Recovery after the version write but before authority publication:
        # discover the immutable candidate by fingerprint and reuse it.
        for item in list_versions(scope.chapter_id, self.context.data_dir).get("manual", []):
            try:
                existing_payload = read_version_payload(item)
            except (OSError, ValueError, TypeError):
                continue
            provenance = existing_payload.get("narrative_compilation") if isinstance(existing_payload.get("narrative_compilation"), dict) else {}
            if provenance.get("candidate_fingerprint") == candidate_fp:
                recovery_result = {"scope": asdict(scope), "canonical_request_fingerprint": request["canonical_request_fingerprint"], "candidate_version_id": item.get("version_label"), "candidate_id": provenance.get("candidate_id"), "candidate_fingerprint": candidate_fp, "outcome_fingerprint": _sha({"candidate_version_id": item.get("version_label"), "candidate_fingerprint": candidate_fp})}
                _atomic_json(self._result_path(authority_path), recovery_result)
                self._append_included(scope, operation_id, eligible)
                self._phase(phase_path, "INCLUDED_TRANSITIONS_APPENDED", scope=asdict(scope)); self._phase(phase_path, "COMPLETED", scope=asdict(scope))
                return self._candidate_result({**authority, **recovery_result})
        self._phase(phase_path, "TURNS_SNAPSHOTTED", scope=asdict(scope), turn_ids=turn_ids); self._fault("after_turn_snapshot")
        content = base_text + "\n\n" + "\n\n".join(f"[Turn {tid}]\n{summary}" for tid, summary in zip(turn_ids, snippets))
        candidate_id = f"chapter_{scope.chapter_id:03d}_candidate_{candidate_fp[:16]}"
        rev = RevisionCandidate(candidate_id=candidate_id, revision_id=f"narrative_compile_{operation_id}", source_hash=source_fp, candidate_hash=HashGuard.sha256_text(content), change_type="turn_compilation", status="qualified")
        index = list_versions(scope.chapter_id, self.context.data_dir); expected_revision = int(index.get("selection_revision", 1) or 1)
        adoption = AdoptionRequest(operation_id=f"{operation_id}_version", preview_id=candidate_id, candidate_id=candidate_id, author_confirm=True, review_reason="confirmed Turn compilation candidate; human review required", expected_revision=expected_revision)
        payload = {"manual_version": "2.3", "chapter_id": scope.chapter_id, "chapter_title": f"Chapter {scope.chapter_id}", "status": "manual", "version": get_next_version_number(scope.chapter_id, "manual", self.context.data_dir), "version_label": "", "manual_text": content, "created_at": now_utc(), "updated_at": now_utc(), "review_status": "pending", "candidate_id": candidate_id, "candidate_fingerprint": candidate_fp, "candidate_scope": asdict(scope), "source_version_id": source_id, "source_fingerprint": source_fp, "canon_revision_id": scope.expected_canon_revision_id}
        payload["version_label"] = f"manual_v{payload['version']:03d}"
        result = VersionWriterFacade(self.context).create_work_version(project=ProjectRef.from_context(self.context), chapter_id=scope.chapter_id, source_type="manual", source_version=source_version, chapter_title=payload["chapter_title"], candidate_text=content, candidate=rev, adoption=adoption, provenance_kind="narrative_compilation", provenance={"candidate_id": candidate_id, "candidate_fingerprint": candidate_fp, "review_status": "pending", "scope": asdict(scope)})
        self._phase(phase_path, "CANDIDATE_WRITTEN", scope=asdict(scope), candidate_version_id=result.version_id, candidate_fingerprint=candidate_fp); self._fault("after_candidate_write")
        # Add candidate metadata to the durable manual payload through the existing writer path is intentionally avoided;
        # the facade payload already carries provenance and review remains pending.
        result_record = {"scope": asdict(scope), "canonical_request_fingerprint": request["canonical_request_fingerprint"], "candidate_version_id": result.version_id, "candidate_id": candidate_id, "candidate_fingerprint": candidate_fp, "content_fingerprint": HashGuard.sha256_text(content), "outcome_fingerprint": _sha({"candidate_version_id": result.version_id, "candidate_fingerprint": candidate_fp, "content_fingerprint": HashGuard.sha256_text(content)})}
        _atomic_json(self._result_path(authority_path), result_record)
        self._append_included(scope, operation_id, eligible); self._phase(phase_path, "INCLUDED_TRANSITIONS_APPENDED", scope=asdict(scope)); self._fault("after_all_included_transitions")
        self._fault("before_completed_marker")
        self._phase(phase_path, "COMPLETED", scope=asdict(scope)); return self._candidate_result(authority)

    def _append_included(self, scope: CompilationScope, operation_id: str, eligible: list[Any]) -> None:
        for turn_id, _plan, transitions, _result, _seq in eligible:
            if any(t.to_state == TurnState.INCLUDED_IN_CHAPTER for t in transitions): continue
            last = transitions[-1]
            record_fp = _sha({"operation_id": operation_id, "turn_id": turn_id, "to_state": "included_in_chapter"})
            self.turns.append_transition(NarrativeTurnTransition(SCHEMA_VERSION, new_id("trn"), turn_id, self._storage_scope(scope), last.to_state, TurnState.INCLUDED_IN_CHAPTER, "candidate_compiled", operation_id, now_utc(), record_fp, len(transitions), last.transition_id, last.record_fingerprint))
            self._fault("after_first_included_transition")

    def _candidate_result(self, authority: dict[str, Any]) -> dict[str, Any]:
        if not authority.get("candidate_version_id") and authority.get("operation_id"):
            authority = {**authority, **self._read_result(self._root / f"{authority['operation_id']}.json")}
        return {"operation_id": authority["operation_id"], "candidate_id": authority.get("candidate_id"), "candidate_version_id": authority.get("candidate_version_id"), "candidate_fingerprint": authority.get("candidate_fingerprint"), "review_status": "pending", "scope": authority.get("scope"), "replayed": bool(authority.get("candidate_version_id"))}


class NarrativeChapterCommitService:
    """Commit only approved candidates through ChapterCommitService."""
    def __init__(self, context: ProjectContext, canonical_project_id: str | None = None):
        self.context = context
        self.canonical_project_id = canonical_project_id or context.root.name
        self.compiler = NarrativeChapterCompiler(context, canonical_project_id=self.canonical_project_id)
        self.turns = self.compiler.turns
        self._commit_calls: dict[str, Any] = {}
        self._fault_injector = None

    def _fault(self, point: str) -> None:
        if self._fault_injector:
            self._fault_injector(point)

    def commit_candidate(self, *, operation_id: str, scope: CompilationScope, candidate_version_id: str, ordered_turn_ids: list[str] | None = None) -> dict[str, Any]:
        scope.validate(self.context, self.canonical_project_id)
        versions = list_versions(scope.chapter_id, self.context.data_dir); matches = [x for k in ("manual", "edited", "drafts") for x in versions.get(k, []) if x.get("version_label") == candidate_version_id]
        if not matches: raise NarrativeCompilationError("CANDIDATE_COLLISION", "Candidate version does not exist.")
        payload = read_version_payload(matches[0]); provenance = payload.get("narrative_compilation") if isinstance(payload.get("narrative_compilation"), dict) else {}
        candidate_fp = str(payload.get("candidate_fingerprint") or provenance.get("candidate_fingerprint") or "")
        if not candidate_fp: raise NarrativeCompilationError("CANDIDATE_COLLISION", "Candidate metadata is incomplete.")
        candidate_scope = payload.get("candidate_scope") or provenance.get("scope")
        if candidate_scope and candidate_scope != asdict(scope): raise NarrativeCompilationError("CANDIDATE_COLLISION", "Candidate scope does not match commit scope.")
        candidate_id = str(payload.get("candidate_id") or provenance.get("candidate_id") or "")
        if not candidate_id: raise NarrativeCompilationError("CANDIDATE_COLLISION", "Candidate identity is incomplete.")
        authority = {"schema_version": "1.0", "operation_id": operation_id, "operation_type": "commit", "scope": asdict(scope), "candidate_source_version_id": candidate_version_id, "candidate_fingerprint": candidate_fp, "ordered_turn_ids": ordered_turn_ids or [], "expected_canon_revision_id": scope.expected_canon_revision_id, "canonical_request_fingerprint": _sha({"scope": asdict(scope), "candidate": candidate_version_id, "fingerprint": candidate_fp})}
        root = self.context.data_dir / "narrative_compile" / "commit_operations"; path = root / f"{operation_id}.json"; root.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing.get("canonical_request_fingerprint") != authority["canonical_request_fingerprint"]: raise NarrativeCompilationError("COMMIT_OPERATION_CONFLICT", "operation_id is bound to another commit request.")
            authority = existing
        else:
            authority["created_at"] = now_utc(); authority["record_fingerprint"] = _sha(authority); authority = _publish_immutable_json(path, authority)
        phase = path.with_suffix(".phase.json")
        if not phase.exists():
            _atomic_json(phase, {"operation_id": operation_id, "phase": "OPERATION_CLAIMED", "scope": asdict(scope), "updated_at": now_utc()})
        self._fault("after_authority_claim")
        phase_record = json.loads(phase.read_text(encoding="utf-8")) if phase.exists() else {}
        commit_result_path = path.with_suffix(".result.json")
        durable_result = json.loads(commit_result_path.read_text(encoding="utf-8")) if commit_result_path.exists() else {}
        if durable_result.get("scope") and durable_result.get("scope") != asdict(scope): raise NarrativeCompilationError("COMMIT_OPERATION_CONFLICT", "Durable commit result scope does not match request.")
        if durable_result.get("canonical_request_fingerprint") and durable_result.get("canonical_request_fingerprint") != authority.get("canonical_request_fingerprint"): raise NarrativeCompilationError("COMMIT_OPERATION_CONFLICT", "Durable commit result request fingerprint does not match authority.")
        if phase_record.get("scope") and phase_record.get("scope") != asdict(scope): raise NarrativeCompilationError("COMMIT_OPERATION_CONFLICT", "Commit phase scope does not match request.")
        recovered_durable_result = bool(durable_result.get("commit_id") and durable_result.get("status") in {status.value for status in (CommitStatus.COMMITTED, CommitStatus.ALREADY_COMMITTED, CommitStatus.COMMITTED_WITH_WARNINGS)})
        if recovered_durable_result and phase_record.get("phase") == "COMPLETED":
            return {"operation_id": operation_id, "status": durable_result["status"], "candidate_version_id": candidate_version_id, "replayed": True, **durable_result}
        # A completed commit result is returned above before this gate.  Every
        # new ChapterCommitService invocation must re-read durable review
        # authority; mutable candidate payloads are never an approval source.
        if not recovered_durable_result:
            self.compiler._branch_check(scope)
            from system.narrative_candidate_review_service import NarrativeCandidateReviewService
            NarrativeCandidateReviewService(
                self.context, canonical_project_id=self.canonical_project_id
            ).assert_commit_approved(
                scope=scope, candidate_id=candidate_id, candidate_version_id=candidate_version_id,
                candidate_fingerprint=candidate_fp,
            )
        if phase_record.get("phase") not in {"CANDIDATE_VERIFIED", "CHAPTER_COMMIT_SUCCEEDED", "COMMITTED_TRANSITIONS_APPENDED"}:
            _atomic_json(phase, {"operation_id": operation_id, "phase": "CANDIDATE_VERIFIED", "scope": asdict(scope), "updated_at": now_utc()})
        self._fault("after_candidate_verification")
        if phase_record.get("phase") == "CHAPTER_COMMIT_SUCCEEDED" and durable_result.get("commit_id"):
            result = type("RecoveredCommitResult", (), {"status": CommitStatus(durable_result["status"]), "commit_id": durable_result["commit_id"], "canon_revision_id": durable_result.get("canon_revision_id")})()
        elif durable_result.get("commit_id"):
            result = type("RecoveredCommitResult", (), {"status": CommitStatus(durable_result["status"]), "commit_id": durable_result["commit_id"], "canon_revision_id": durable_result.get("canon_revision_id")})()
        elif operation_id not in self._commit_calls and not recovered_durable_result:
            self._fault("before_chapter_commit")
            vector_scope = VectorScope(scope.project_id, scope.timeline_id, scope.branch_id, scope.expected_canon_revision_id)
            # ChapterCommitService's established explicit-source contract uses
            # the persisted filename; preserve the public candidate label in
            # the operation authority while passing that filename through.
            self.compiler._branch_check(scope)
            commit_source_id = Path(str(matches[0].get("json_path") or candidate_version_id)).name
            result = ChapterCommitService(self.context).commit_chapter(scope.chapter_id, source_version_id=commit_source_id, post_commit_policy=PostCommitPolicy.FULL, vector_scope=vector_scope)
            self._commit_calls[operation_id] = result
        elif recovered_durable_result:
            result = type("RecoveredCommitResult", (), {"status": CommitStatus(durable_result["status"]), "commit_id": durable_result["commit_id"], "canon_revision_id": durable_result.get("canon_revision_id")})()
        else: result = self._commit_calls[operation_id]
        if result.status not in {CommitStatus.COMMITTED, CommitStatus.ALREADY_COMMITTED, CommitStatus.COMMITTED_WITH_WARNINGS}: raise NarrativeCompilationError("COMMIT_RECOVERY_REQUIRED", "Chapter commit did not complete.")
        durable_result = {"scope": asdict(scope), "canonical_request_fingerprint": authority["canonical_request_fingerprint"], "status": result.status.value, "commit_id": result.commit_id, "canon_revision_id": result.canon_revision_id, "outcome_fingerprint": _sha({"commit_id": result.commit_id, "status": result.status.value, "canon_revision_id": result.canon_revision_id})}
        _atomic_json(commit_result_path, durable_result)
        self._fault("after_chapter_commit_success")
        _atomic_json(phase, {"operation_id": operation_id, "phase": "CHAPTER_COMMIT_SUCCEEDED", "scope": asdict(scope), "commit_id": result.commit_id, "updated_at": now_utc()})
        for turn_id in ordered_turn_ids or authority.get("ordered_turn_ids") or []:
            scope_obj = self.compiler._storage_scope(scope); transitions = self.turns.get_transitions(scope_obj, turn_id)
            if not transitions or transitions[-1].to_state == TurnState.COMMITTED: continue
            last = transitions[-1]
            if last.to_state != TurnState.INCLUDED_IN_CHAPTER: continue
            self.turns.append_transition(NarrativeTurnTransition(SCHEMA_VERSION, new_id("trn"), turn_id, scope_obj, TurnState.INCLUDED_IN_CHAPTER, TurnState.COMMITTED, "chapter_committed", operation_id, now_utc(), _sha({"turn": turn_id, "op": operation_id, "state": "committed"}), len(transitions), last.transition_id, last.record_fingerprint))
            self._fault("after_first_committed_transition")
        self._fault("after_all_committed_transitions")
        _atomic_json(phase, {"operation_id": operation_id, "phase": "COMMITTED_TRANSITIONS_APPENDED", "scope": asdict(scope), "updated_at": now_utc()}); self._fault("before_completed_marker"); _atomic_json(phase, {"operation_id": operation_id, "phase": "COMPLETED", "scope": asdict(scope), "updated_at": now_utc()})
        return {"operation_id": operation_id, "status": result.status.value, "candidate_version_id": candidate_version_id, "commit_id": result.commit_id, "canon_revision_id": result.canon_revision_id}
