"""Read-only Simulator product state aggregation (Phase 0D5-B).

This module is intentionally a projection boundary.  It reads existing Turn,
Branch, Candidate, Commit, Vector-manifest, and Canon authorities and never
creates recovery records, indexes, registry snapshots, candidates, approvals,
commits, or vector data.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from core.contracts import HashGuard
from core.contracts.narrative_turn import NarrativeScope, TimelineContext, TurnState
from core.project_context import ProjectContext
from system.narrative_branch_lifecycle_service import BranchLifecycleService
from system.narrative_candidate_review_service import NarrativeCandidateReviewService
from system.narrative_chapter_compiler import CompilationScope
from system.narrative_turn_store import NarrativeTurnStore
from system.revision_service import RevisionService
from system.version_manager import list_versions, read_version_payload


_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_TERMINAL_PHASES = {"completed", "COMPLETE", "COMPLETED"}
_RECOVERY_CODES = {
    "turn": "TURN_RECOVERY_REQUIRED",
    "candidate": "CANDIDATE_RECOVERY_REQUIRED",
    "commit": "COMMIT_RECOVERY_REQUIRED",
}


class SimulatorLoopStateError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _safe_id(value: str, name: str) -> str:
    if not isinstance(value, str) or not value or _ID.fullmatch(value) is None:
        raise SimulatorLoopStateError("SCOPE_REQUIRED", f"{name} is required")
    return value


def _scope_dict(scope: NarrativeScope, chapter_id: int, source_version_id: str | None, canon_revision_id: str | None, source_fingerprint: str | None) -> dict[str, Any]:
    return {
        "project_id": scope.project_id,
        "timeline_id": scope.timeline_id,
        "chapter_id": chapter_id,
        "source_version_id": source_version_id,
        "source_fingerprint": source_fingerprint,
        "branch_id": scope.branch_id,
        "canon_revision_id": canon_revision_id,
    }


def _short(value: Any, length: int = 16) -> str | None:
    text = str(value) if value not in (None, "") else ""
    return text[:length] if text else None


def _safe_summary(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_safe_summary(item) for item in value]
    if isinstance(value, list):
        return [_safe_summary(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _safe_summary(v) for k, v in value.items() if not isinstance(v, Path)}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


@dataclass(frozen=True)
class BranchReadiness:
    branch_id: str
    lifecycle_status: str
    active: bool
    vector_readiness: str
    registry_revision: str
    blocking_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateSummary:
    candidate_id: str
    candidate_version_id: str
    chapter_id: int
    branch_id: str
    source_version_id: str | None
    included_turns: tuple[str, ...] = field(default_factory=tuple)
    fingerprint_summary: str | None = None
    freshness: str = "unknown"
    review_status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["included_turns"] = list(self.included_turns)
        return result


@dataclass(frozen=True)
class SimulatorLoopState:
    scope: dict[str, Any]
    current_stage: str
    branch: dict[str, Any]
    turn: dict[str, Any]
    candidate: dict[str, Any]
    commit: dict[str, Any]
    chapter_progression: dict[str, Any]
    recovery: dict[str, Any]
    approval: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "scope": _safe_summary(self.scope),
            "stage": self.current_stage,
            "current_stage": self.current_stage,
            "branch": _safe_summary(self.branch),
            "turn": _safe_summary(self.turn),
            "candidate": _safe_summary(self.candidate),
            "commit": _safe_summary(self.commit),
            "chapter_progression": _safe_summary(self.chapter_progression),
            "recovery": _safe_summary(self.recovery),
            "approval": _safe_summary(self.approval),
        }


class SimulatorLoopStateService:
    """Build a scoped, immutable-in-memory read model from existing authorities."""

    def __init__(self, context: ProjectContext, *, canonical_project_id: str | None = None):
        self.context = context
        self.storage_project_id = context.root.name
        self.project_id = canonical_project_id or self.storage_project_id
        self.turns = NarrativeTurnStore(context)
        self.branches = BranchLifecycleService(context)
        self.revisions = RevisionService(context)
        self.reviews = NarrativeCandidateReviewService(context)

    def _assert_scope(self, project_id: str, timeline_id: str, branch_id: str, chapter_id: int) -> NarrativeScope:
        _safe_id(project_id, "project_id")
        _safe_id(timeline_id, "timeline_id")
        _safe_id(branch_id, "branch_id")
        if project_id != self.project_id:
            raise SimulatorLoopStateError("PROJECT_NOT_FOUND", "Project does not match the active project context")
        if type(chapter_id) is not int or chapter_id < 1:
            raise SimulatorLoopStateError("SCOPE_REQUIRED", "chapter_id must be positive")
        return NarrativeScope(self.storage_project_id, timeline_id, branch_id)

    def _branch(self, scope: NarrativeScope) -> tuple[dict[str, Any], BranchReadiness]:
        result = self.branches.list_branches(scope.project_id, scope.timeline_id)
        branch = next((item for item in result.get("branches", []) if item.get("branch_id") == scope.branch_id), None)
        if branch is None:
            raise SimulatorLoopStateError("BRANCH_NOT_FOUND", "Branch is not available in this scope")
        registry_revision = str(result.get("registry_revision") or "0")
        lifecycle = str(branch.get("lifecycle_status") or "unknown")
        active = bool(branch.get("is_active"))
        manifest = None
        manifest_dir = self.context.data_dir / "chroma" / "manifests" / scope.timeline_id
        for candidate in sorted(manifest_dir.glob(f"{scope.branch_id}.json")) if manifest_dir.exists() else ():
            manifest = _read_json(candidate)
            break
        if manifest is None:
            readiness, reason = "not_ready", "VECTOR_MANIFEST_MISSING"
        else:
            manifest_ready = bool(manifest.get("vector_ready"))
            manifest_lifecycle = str(manifest.get("branch_lifecycle_status") or "")
            readiness = "ready" if manifest_ready and manifest_lifecycle == lifecycle else "not_ready"
            reason = None if readiness == "ready" else str(manifest.get("blocking_reason") or "VECTOR_SCOPE_NOT_READY")
        projection = {
            "active_branch_id": result.get("active_branch_id"),
            "active": active,
            "lifecycle_status": lifecycle,
            "display_name": branch.get("display_name"),
            "readiness": readiness,
            "registry_revision": registry_revision,
        }
        return projection, BranchReadiness(scope.branch_id, lifecycle, active, readiness, registry_revision, reason)

    def _source(self, chapter_id: int, requested: str | None) -> tuple[str | None, str | None]:
        versions = list_versions(chapter_id, self.context.data_dir)
        selected = versions.get("selected") if isinstance(versions.get("selected"), dict) else {}
        if requested:
            candidates = [item for kind in ("drafts", "edited", "manual") for item in versions.get(kind, []) if item.get("version_label") == requested]
            selected = candidates[0] if candidates else selected
        if selected:
            selected_label = str(selected.get("version_label") or "")
            resolved = next((item for kind in ("drafts", "edited", "manual") for item in versions.get(kind, []) if item.get("version_label") == selected_label), None)
            if resolved:
                selected = resolved
        if not selected:
            selected = next((items[-1] for kind in ("manual", "edited", "drafts") if (items := versions.get(kind)) and items), {})
        source_id = str(selected.get("version_label") or requested or "") or None
        try:
            payload = read_version_payload(selected) if selected else {}
            # A compiler-created Candidate may become the selected work
            # version.  Its authority-bound scope still names the source
            # version from which it was compiled; keep the read-model scope
            # stable for review/commit freshness checks.
            provenance = payload.get("narrative_compilation") if isinstance(payload.get("narrative_compilation"), dict) else {}
            candidate_scope = payload.get("candidate_scope") if isinstance(payload.get("candidate_scope"), dict) else provenance.get("scope", {})
            bound_source_id = str(candidate_scope.get("source_version_id") or "")
            if bound_source_id and bound_source_id != source_id:
                for kind in ("drafts", "edited", "manual"):
                    bound = next((item for item in versions.get(kind, []) if item.get("version_label") == bound_source_id), None)
                    if bound:
                        selected = bound
                        source_id = bound_source_id
                        payload = read_version_payload(bound)
                        break
            if not bound_source_id:
                for candidate in versions.get("manual", []):
                    try:
                        candidate_payload = read_version_payload(candidate)
                    except (OSError, ValueError, TypeError):
                        continue
                    candidate_provenance = candidate_payload.get("narrative_compilation") if isinstance(candidate_payload.get("narrative_compilation"), dict) else {}
                    candidate_bound = candidate_payload.get("candidate_scope") if isinstance(candidate_payload.get("candidate_scope"), dict) else candidate_provenance.get("scope", {})
                    candidate_source = str(candidate_bound.get("source_version_id") or "")
                    if candidate_source and candidate_source != source_id:
                        base = next((item for kind in ("drafts", "edited", "manual") for item in versions.get(kind, []) if item.get("version_label") == candidate_source), None)
                        if base:
                            selected = base
                            source_id = candidate_source
                            payload = read_version_payload(base)
                            break
            text = str(payload.get("manual_text") or payload.get("edited_text") or payload.get("draft_text") or "")
            return source_id, HashGuard.sha256_text(text) if text else None
        except (OSError, ValueError, TypeError):
            return source_id, None

    def _canon(self, chapter_id: int) -> dict[str, Any] | None:
        return self.revisions.read_active_canon(chapter_id)

    def _scoped_operation_records(self, directory: Path, scope: dict[str, Any], operation_type: str) -> list[tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]]:
        if not directory.exists():
            return []
        records = []
        for authority_path in sorted(directory.glob("*.json")):
            if authority_path.name.endswith((".phase.json", ".result.json")):
                continue
            authority = _read_json(authority_path)
            if not authority or authority.get("operation_type") not in (operation_type, None):
                continue
            raw_scope = authority.get("scope") if isinstance(authority.get("scope"), dict) else {}
            phase = _read_json(authority_path.with_suffix(".phase.json"))
            result = _read_json(authority_path.with_suffix(".result.json"))
            # Confirm results are durable TurnStore records keyed by turn_id,
            # not adjacent to the operation authority.  Recovery must consult
            # that authoritative result before declaring an unfinished retry.
            if result is None and operation_type == "confirm":
                result_root = self.context.data_dir / "narrative_turn" / "results"
                for result_path in result_root.glob("*/*/*.json") if result_root.exists() else ():
                    candidate_result = _read_json(result_path)
                    if candidate_result and candidate_result.get("operation_id") == authority.get("operation_id"):
                        result = candidate_result
                        break
            phase_scope = phase if isinstance(phase, dict) else {}
            effective_scope = {**raw_scope, **{key: phase_scope.get(key) for key in ("project_id", "timeline_id", "branch_id", "chapter_id") if phase_scope.get(key) is not None}}
            if any(effective_scope.get(key) is not None and effective_scope.get(key) != value for key, value in scope.items() if key in {"project_id", "timeline_id", "branch_id", "chapter_id"}):
                continue
            records.append((authority, phase, result))
        return records

    def _recovery(self, scope: dict[str, Any]) -> dict[str, Any]:
        checks = (
            ("turn", self.context.data_dir / "narrative_turn" / "operations", "confirm"),
            ("candidate", self.context.data_dir / "narrative_compile" / "operations", "compile"),
            ("commit", self.context.data_dir / "narrative_compile" / "commit_operations", "commit"),
        )
        pending: list[dict[str, Any]] = []
        for kind, directory, op_type in checks:
            for authority, phase, result in self._scoped_operation_records(directory, scope, op_type):
                phase_name = str((phase or {}).get("phase") or "")
                if phase is None or phase_name not in _TERMINAL_PHASES or result is None:
                    pending.append({"kind": kind, "code": _RECOVERY_CODES[kind], "operation_id": authority.get("operation_id"), "phase": phase_name or "unknown"})
        if pending:
            return {"status": pending[0]["code"], "pending": pending}
        return {"status": "READY_FOR_NEXT_ACTION", "pending": []}

    def _history_and_turns(self, scope_obj: NarrativeScope, chapter_id: int) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None]:
        plans: list[Any] = []
        for turn_id in self.turns.list_plans(scope_obj):
            plan = self.turns.get_plan(scope_obj, turn_id)
            if plan and plan.chapter_id == chapter_id:
                plans.append(plan)
        rows: list[dict[str, Any]] = []
        current: tuple[Any, Any, list[Any]] | None = None
        for plan in plans:
            transitions = self.turns.get_transitions(scope_obj, plan.turn_id)
            result = self.turns.get_result(scope_obj, plan.turn_id)
            if not transitions and result is None:
                continue
            latest = transitions[-1] if transitions else None
            if latest and latest.to_state not in {TurnState.COMMITTED, TurnState.SUPERSEDED}:
                if current is None or (latest.occurred_at, plan.turn_id) > (current[1].occurred_at if current[1] else "", current[0].turn_id):
                    current = (plan, latest, transitions)
            if result is None:
                continue
            action_summary = result.selected_action_id or ("custom action" if result.custom_action_text_hash else "unknown action")
            action = next((a.display_text for a in plan.recommended_actions if a.action_id == result.selected_action_id), None)
            rows.append({
                "turn_id": plan.turn_id,
                "sequence": 0,
                "action_summary": action or action_summary,
                "result_summary": result.event_summary,
                "state_delta_summary": _safe_summary(result.state_delta_proposal),
                "lifecycle": latest.to_state.value if latest else "confirmed",
                "candidate_link": None,
                "commit_link": None,
                "confirmed_at": result.confirmed_at,
            })
        rows.sort(key=lambda row: (str(row.get("confirmed_at") or ""), row["turn_id"]))
        for index, row in enumerate(rows, 1):
            row["sequence"] = index
        return rows, (current[0], current[1], current[2]) if current else None, plans[-1] if plans else None

    def _candidates(self, scope: dict[str, Any], chapter_id: int, current_canon: str | None, source_fp: str | None) -> list[CandidateSummary]:
        versions = list_versions(chapter_id, self.context.data_dir)
        compile_records = self._scoped_operation_records(self.context.data_dir / "narrative_compile" / "operations", scope, "compile")
        found: list[CandidateSummary] = []
        for item in [entry for kind in ("manual", "edited", "drafts") for entry in versions.get(kind, [])]:
            try:
                payload = read_version_payload(item)
            except (OSError, ValueError, TypeError):
                continue
            provenance = payload.get("narrative_compilation") if isinstance(payload.get("narrative_compilation"), dict) else {}
            candidate_scope = payload.get("candidate_scope") or provenance.get("scope")
            if not isinstance(candidate_scope, dict) or any(candidate_scope.get(k) != scope.get(k) for k in ("project_id", "timeline_id", "branch_id", "chapter_id")):
                continue
            candidate_id = str(payload.get("candidate_id") or provenance.get("candidate_id") or "")
            candidate_version_id = str(item.get("version_label") or "")
            if not candidate_id or not candidate_version_id:
                continue
            canon = str(payload.get("canon_revision_id") or candidate_scope.get("expected_canon_revision_id") or "")
            candidate_source_fp = str(payload.get("source_fingerprint") or "")
            freshness = "fresh"
            if current_canon and canon and current_canon != canon:
                freshness = "stale"
            elif source_fp and candidate_source_fp and source_fp != candidate_source_fp:
                freshness = "stale"
            included = tuple(str(x) for x in (provenance.get("ordered_turn_ids") or payload.get("included_turn_ids") or []))
            if not included:
                for authority, _phase, result in compile_records:
                    if (result or {}).get("candidate_version_id") == candidate_version_id or authority.get("candidate_version_id") == candidate_version_id:
                        included = tuple(str(x) for x in (authority.get("ordered_turn_ids") or []))
                        break
            review_status = "stale" if freshness == "stale" else "pending"
            try:
                review_scope = CompilationScope(
                    project_id=str(candidate_scope.get("project_id") or ""), timeline_id=str(candidate_scope.get("timeline_id") or ""),
                    branch_id=str(candidate_scope.get("branch_id") or ""), chapter_id=int(candidate_scope.get("chapter_id") or 0),
                    source_version_id=candidate_scope.get("source_version_id"), expected_source_fingerprint=payload.get("source_fingerprint") or candidate_scope.get("expected_source_fingerprint"),
                    expected_canon_revision_id=str(candidate_scope.get("expected_canon_revision_id") or payload.get("canon_revision_id") or ""),
                    expected_branch_registry_revision=str(candidate_scope.get("expected_branch_registry_revision") or ""),
                )
                review = self.reviews.review_for_candidate(review_scope, candidate_id)
                if review and freshness != "stale":
                    review_status = str(review.get("decision") or "pending")
            except Exception:
                review_status = "stale"
            found.append(CandidateSummary(candidate_id, candidate_version_id, chapter_id, str(scope["branch_id"]), payload.get("source_version_id") or candidate_scope.get("source_version_id"), included, _short(payload.get("candidate_fingerprint") or provenance.get("candidate_fingerprint")), freshness, review_status))
        found.sort(key=lambda item: item.candidate_version_id)
        return found

    def _commit(self, scope: dict[str, Any]) -> dict[str, Any]:
        records = self._scoped_operation_records(self.context.data_dir / "narrative_compile" / "commit_operations", scope, "commit")
        if not records:
            return {"status": "none", "operation_id": None, "durable_result": None, "canon_revision_id": None, "recovery_state": "none"}
        authority, phase, result = records[-1]
        phase_name = str((phase or {}).get("phase") or "")
        durable = None
        if isinstance(result, dict):
            durable = {key: result.get(key) for key in ("status", "commit_id", "canon_revision_id", "outcome_fingerprint") if key in result}
        status = str((result or {}).get("status") or phase_name or "pending")
        recovery = "required" if phase_name not in _TERMINAL_PHASES else "none"
        op_id = authority.get("operation_id")
        candidate_source = authority.get("candidate_source_version_id") or (result or {}).get("candidate_source_version_id")
        canon_rev = (result or {}).get("canon_revision_id")
        return {"status": status, "operation_id": op_id, "candidate_version_id": candidate_source, "durable_result": durable, "canon_revision_id": canon_rev, "recovery_state": recovery}

    def build(self, *, project_id: str, timeline_id: str, chapter_id: int, branch_id: str, source_version_id: str | None = None) -> SimulatorLoopState:
        scope_obj = self._assert_scope(project_id, timeline_id, branch_id, chapter_id)
        source_id, source_fp = self._source(chapter_id, source_version_id)
        canon = self._canon(chapter_id)
        canon_revision_id = str((canon or {}).get("canon_version_id") or (canon or {}).get("revision_id") or "") or None
        scope = _scope_dict(scope_obj, chapter_id, source_id, canon_revision_id, source_fp)
        product_scope = {**scope, "project_id": self.project_id}
        branch, branch_readiness = self._branch(scope_obj)
        branch_data = {**branch, "vector_readiness": branch_readiness.vector_readiness, "blocking_reason": branch_readiness.blocking_reason}
        recovery = self._recovery(product_scope)
        history, current, latest_plan = self._history_and_turns(scope_obj, chapter_id)
        candidates = self._candidates(product_scope, chapter_id, canon_revision_id, source_fp)
        commit = self._commit(product_scope)
        current_candidate = candidates[-1] if candidates else None
        if current_candidate:
            current_candidate = next((item for item in candidates if item.candidate_version_id == (commit.get("candidate_version_id") or current_candidate.candidate_version_id)), current_candidate)
        commit_completed = commit.get("status") in {"committed", "committed_with_warnings", "already_committed", "completed"}
        if commit_completed and current_candidate:
            current_candidate = replace(current_candidate, freshness="fresh", review_status="committed")
            candidates = [replace(item, freshness="fresh", review_status="committed") if item.candidate_version_id == current_candidate.candidate_version_id else item for item in candidates]
        current_turn = current[0] if current else latest_plan
        current_result = next((row for row in reversed(history) if current_turn and row["turn_id"] == current_turn.turn_id), None)
        turn_freshness = "unknown"
        if current_turn and current_result:
            result_obj = self.turns.get_result(scope_obj, current_turn.turn_id)
            if result_obj is not None and source_fp:
                turn_freshness = "fresh" if result_obj.source_fingerprint == source_fp else "stale"
            if current_turn.canon_revision and canon_revision_id:
                turn_freshness = "fresh" if current_turn.canon_revision == canon_revision_id else "stale"
        turn_data = {
            "current_turn": {"turn_id": current_turn.turn_id, "chapter_id": current_turn.chapter_id} if current_turn else None,
            "freshness": turn_freshness,
            "available_actions": [a.action_id for a in (current_turn.recommended_actions if current_turn else ())],
            "current_result": current_result,
            "history_summary": {"count": len(history), "last_turn_id": history[-1]["turn_id"] if history else None},
            "included_candidate": current_candidate.candidate_version_id if current_candidate and current_candidate.included_turns else None,
            "commit_status": commit["status"],
            "history": history,
        }
        review_status = current_candidate.review_status if current_candidate else "none"
        blocking = None if review_status == "approved" else ("CANDIDATE_PENDING_REVIEW" if review_status == "pending" else f"CANDIDATE_{review_status.upper()}")
        completed = commit_completed
        has_eligible_confirmed_turn = any(row.get("lifecycle") == TurnState.APPLIED_TO_BRANCH.value for row in history)
        if recovery["status"] != "READY_FOR_NEXT_ACTION":
            compile_blocking_reason = recovery["status"]
        elif not branch_readiness.active:
            compile_blocking_reason = "BRANCH_INACTIVE"
        elif branch_readiness.lifecycle_status == "archived":
            compile_blocking_reason = "BRANCH_ARCHIVED"
        elif branch_readiness.vector_readiness != "ready":
            compile_blocking_reason = branch_readiness.blocking_reason or "VECTOR_NOT_READY"
        elif completed:
            compile_blocking_reason = "CHAPTER_ALREADY_COMPLETE"
        elif current_candidate is not None:
            compile_blocking_reason = "CANDIDATE_ALREADY_CURRENT"
        elif not has_eligible_confirmed_turn:
            compile_blocking_reason = "NO_ELIGIBLE_CONFIRMED_TURNS"
        else:
            compile_blocking_reason = None
        candidate_data = {
            "candidate_list": [item.to_dict() for item in candidates],
            "current_candidate": current_candidate.to_dict() if current_candidate else None,
            "approval_status": review_status,
            "can_compile": compile_blocking_reason is None,
            "compile_blocking_reason": compile_blocking_reason,
        }
        chapter_data = {"current_chapter": chapter_id, "completed": completed, "next_chapter_available": (self.context.chapters_dir / f"chapter_{chapter_id + 1:03d}.md").exists(), "next_chapter_id": chapter_id + 1 if (self.context.chapters_dir / f"chapter_{chapter_id + 1:03d}.md").exists() else None}
        if not completed and (recovery["status"] != "READY_FOR_NEXT_ACTION" or turn_freshness == "stale" or any(item.freshness == "stale" for item in candidates)):
            stage = "BLOCKED"
        elif completed:
            stage = "COMPLETE"
        elif commit.get("status") not in {None, "none"}:
            stage = "COMMIT"
        elif current_candidate:
            stage = "REVIEW" if current_candidate.review_status in {"pending", "approved", "rejected"} else "CANDIDATE"
        elif current_turn:
            stage = "TURN"
        elif history:
            stage = "HISTORY"
        else:
            stage = "ENTRY"
        if not branch_readiness.active or branch_readiness.lifecycle_status == "archived":
            stage = "BLOCKED"
        return SimulatorLoopState(product_scope, stage, branch_data, turn_data, candidate_data, commit, chapter_data, recovery, {"status": review_status, "can_review": bool(current_candidate and current_candidate.freshness == "fresh"), "can_approve": bool(current_candidate and review_status == "pending" and current_candidate.freshness == "fresh"), "can_reject": bool(current_candidate and review_status == "pending" and current_candidate.freshness == "fresh"), "can_commit": bool(current_candidate and review_status == "approved" and current_candidate.freshness == "fresh"), "blocking_reason": blocking})
