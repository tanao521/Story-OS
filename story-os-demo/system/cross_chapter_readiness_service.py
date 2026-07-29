"""Pure-read cross-chapter readiness projection for Phase 0D6-B."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from core.contracts.narrative_turn import BranchLifecycleStatus, NarrativeScope, NarrativeTurnError, TimelineContext
from core.project_context import ProjectContext
from system.chapter_lifecycle_service import ChapterLifecycleService
from system.narrative_branch_store import NarrativeBranchStore
from system.narrative_turn_context import NarrativeTurnContextBinder
from system.narrative_turn_store import NarrativeTurnStore
from system.cross_chapter_scope import (
    AMBIGUOUS,
    CORRUPT,
    CURRENT,
    UNRELATED,
    ScopeTarget,
    classify_scope_fields,
)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("authority must be an object")
    return value


class CrossChapterReadinessService:
    """Aggregate sealed durable facts without creating or repairing anything."""

    def __init__(self, context: ProjectContext) -> None:
        self.context = context
        self.project_id = context.root.name or "default"
        self.lifecycle = ChapterLifecycleService(context)
        self.branches = NarrativeBranchStore(context)
        self.turns = NarrativeTurnStore(context)

    def _blocked(self, code: str, project_id: str, timeline_id: str,
                 branch_id: str | None, previous_chapter_id: int | None,
                 successor_chapter_id: int | None = None,
                 lifecycle_operation_id: str | None = None,
                 existing_turn_id: str | None = None,
                 existing_turn_status: str | None = None) -> dict[str, Any]:
        payload = {
            "project_id": project_id, "timeline_id": timeline_id,
            "branch_id": branch_id, "previous_chapter_id": previous_chapter_id,
            "successor_chapter_id": successor_chapter_id,
            "readiness_code": code, "ready_to_start_turn": False,
            "blocking_reasons": [code],
            "chapter_lifecycle_operation_id": lifecycle_operation_id,
            "existing_turn_id": existing_turn_id,
            "existing_turn_status": existing_turn_status,
            "branch_revision": None, "branch_authority_fingerprint": None,
            "planning_revision": None, "planning_context_fingerprint": None,
            "selected_source_version_id": None, "source_fingerprint": None,
            "canon_revision": None,
        }
        payload["authority_fingerprint"] = _fingerprint(payload)
        return payload

    def _lifecycle_bundles(
        self, previous: int, timeline: str, branch_id: str, resolver_successor: int | None
    ) -> tuple[list[tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]], bool, bool, bool]:
        """Collect and validate lifecycle bundles; never select by directory order.

        Returns (valid_completed, incomplete, conflict, corrupt).  A basename is
        the only permitted association for a legacy phase record because the
        sealed phase schema has no operation_id field.
        """
        root = self.context.data_dir / "chapter_lifecycle" / "operations"
        if not root.exists():
            return [], False, False, False
        names: set[str] = set()
        for path in root.glob("*.json"):
            if path.name.endswith(".phase.json"):
                names.add(path.name[:-11])
            elif path.name.endswith(".result.json"):
                names.add(path.name[:-12])
            elif not path.name.endswith(".staging.json"):
                names.add(path.stem)
        complete: list[tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]] = []
        incomplete = conflict = corrupt = False
        target = ScopeTarget(
            project_id=self.project_id,
            timeline_id=timeline,
            branch_id=branch_id,
            previous_chapter_id=previous,
            successor_chapter_id=resolver_successor,
        )
        for operation_id in names:
            path = root / f"{operation_id}.json"
            phase_path = root / f"{operation_id}.phase.json"
            result_path = root / f"{operation_id}.result.json"
            if not path.exists():
                # Result-only records from another provable scope are ignored;
                # phase-only or unscoped records remain fail-closed.
                artifact_scope = AMBIGUOUS
                for artifact_path in (result_path, phase_path):
                    if not artifact_path.exists():
                        continue
                    try:
                        artifact = _read_object(artifact_path)
                    except (OSError, ValueError, TypeError, json.JSONDecodeError):
                        artifact_scope = CORRUPT
                        break
                    fields = {
                        key: artifact[key]
                        for key in (
                            "project_id", "timeline_id", "branch_id",
                            "previous_chapter_id", "successor_chapter_id",
                        )
                        if key in artifact
                    }
                    artifact_scope = classify_scope_fields(
                        fields, target, required=("project_id",)
                    )
                    if artifact_scope != AMBIGUOUS:
                        break
                if artifact_scope == UNRELATED:
                    continue
                corrupt = True
                continue
            try:
                claim = _read_object(path)
                request = claim.get("request", {})
                if not isinstance(request, dict):
                    corrupt = True
                    continue
                branch_claim = request.get("branch_authority", {})
                if not isinstance(branch_claim, dict):
                    corrupt = True
                    continue
                claim_fields = {
                    "project_id": claim.get("project_id"),
                    "timeline_id": request.get("timeline_id"),
                    "branch_id": branch_claim.get("active_branch_id"),
                    "previous_chapter_id": request.get("current_chapter_id"),
                    "successor_chapter_id": request.get("next_chapter_id"),
                }
                claim_scope = classify_scope_fields(
                    claim_fields, target,
                    required=(
                        "project_id", "timeline_id", "branch_id",
                        "previous_chapter_id", "successor_chapter_id",
                    ),
                )
                if claim_scope == UNRELATED:
                    continue
                if claim_scope in (AMBIGUOUS, CORRUPT):
                    corrupt = True
                    continue
                if (claim.get("project_id") != self.project_id
                        or request.get("timeline_id") != timeline
                        or int(request.get("current_chapter_id", 0) or 0) != previous):
                    corrupt = True
                    continue
                bound_branch = request.get("branch_authority", {}).get("active_branch_id")
                if bound_branch != branch_id:
                    conflict = True
                    continue
                if claim.get("operation_type") != "create_next_chapter" or claim.get("request_fingerprint") != _fingerprint(request):
                    corrupt = True
                    continue
                if not phase_path.exists() or not result_path.exists():
                    incomplete = True
                    continue
                result = _read_object(result_path)
                phase = _read_object(phase_path)
                for artifact in (phase, result):
                    scope_keys = {
                        key: artifact[key]
                        for key in (
                            "project_id", "timeline_id", "branch_id",
                            "previous_chapter_id", "successor_chapter_id",
                        )
                        if key in artifact
                    }
                    if scope_keys and classify_scope_fields(
                        scope_keys, target, required=("project_id",)
                    ) != CURRENT:
                        corrupt = True
                        break
                if corrupt:
                    continue
                if phase.get("phase") != "completed":
                    incomplete = True
                    continue
                if (result.get("operation_id") != operation_id
                        or result.get("operation_type") != "create_next_chapter"
                        or result.get("project_id") != self.project_id
                        or int(result.get("chapter_id", 0) or 0) != int(request.get("next_chapter_id", 0) or 0)):
                    corrupt = True
                    continue
                expected = result.get("outcome_fingerprint")
                body = dict(result)
                body.pop("outcome_fingerprint", None)
                if expected != _fingerprint(body):
                    corrupt = True
                    continue
                if resolver_successor is None or int(request.get("next_chapter_id", 0) or 0) != resolver_successor:
                    conflict = True
                    continue
                complete.append((operation_id, claim, phase, result))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                corrupt = True
        if len(complete) > 1:
            conflict = True
        return complete, incomplete, conflict, corrupt

    def readiness(self, *, project_id: str, timeline_id: str = "main",
                  branch_id: str | None = None,
                  previous_chapter_id: int | None = None,
                  ignore_start_operation_id: str | None = None) -> dict[str, Any]:
        blocked = lambda code, **kw: self._blocked(
            code, project_id, timeline_id, kw.pop("branch_id", branch_id),
            kw.pop("previous_chapter_id", previous_chapter_id), **kw)
        if project_id != self.project_id:
            return blocked("BLOCKED_SCOPE_MISMATCH")
        if timeline_id != "main":
            return blocked("BLOCKED_TIMELINE_UNSUPPORTED")
        if previous_chapter_id is None:
            state = self.lifecycle._read_state_projection()
            previous_chapter_id = int(state.get("current_chapter", 0) or 0)
        if previous_chapter_id <= 0:
            return blocked("BLOCKED_PREVIOUS_CHAPTER_NOT_COMPLETE",
                           previous_chapter_id=None)
        try:
            _commit, completion_authority = self.lifecycle._completion_authority(previous_chapter_id)
        except Exception as exc:
            code = ("BLOCKED_COMPLETION_RECOVERY_REQUIRED"
                    if getattr(exc, "code", "") == "COMMIT_RECOVERY_REQUIRED"
                    else "BLOCKED_PREVIOUS_CHAPTER_NOT_COMPLETE")
            return blocked(code, previous_chapter_id=previous_chapter_id)
        try:
            registry, branch_authority = self.lifecycle._branch_authority(timeline_id)
        except Exception as exc:
            code = ("BLOCKED_BRANCH_ARCHIVED" if getattr(exc, "code", "") == "BRANCH_ARCHIVED"
                    else "BLOCKED_CORRUPT_AUTHORITY")
            return blocked(code, previous_chapter_id=previous_chapter_id)
        active = branch_authority.get("active_branch_id")
        if branch_id is not None and branch_id != active:
            return blocked("BLOCKED_BRANCH_NOT_ACTIVE",
                           previous_chapter_id=previous_chapter_id)
        branch_id = str(active or "")
        if not branch_id:
            return blocked("BLOCKED_BRANCH_NOT_ACTIVE", branch_id=None,
                           previous_chapter_id=previous_chapter_id)
        try:
            branch = self.branches.get_branch(TimelineContext(project_id, timeline_id), branch_id)
            if branch is None:
                raise ValueError
            if branch.lifecycle_status == BranchLifecycleStatus.ARCHIVED:
                return blocked("BLOCKED_BRANCH_ARCHIVED", branch_id=branch_id,
                               previous_chapter_id=previous_chapter_id)
        except Exception:
            return blocked("BLOCKED_CORRUPT_AUTHORITY", branch_id=branch_id,
                           previous_chapter_id=previous_chapter_id)
        start_ops = self.context.data_dir / "chapter_progression" / "operations"
        if start_ops.exists():
            for path in sorted(start_ops.glob("*.json")):
                if path.name.endswith((".phase.json", ".result.json")):
                    continue
                if path.stem == ignore_start_operation_id:
                    continue
                try:
                    request = _read_object(path).get("request", {})
                except (OSError, ValueError, json.JSONDecodeError):
                    return blocked("BLOCKED_CORRUPT_AUTHORITY", branch_id=branch_id,
                                   previous_chapter_id=previous_chapter_id)
                if (request.get("timeline_id") == timeline_id
                        and request.get("branch_id") == branch_id
                        and request.get("previous_chapter_id") == previous_chapter_id
                        and not path.with_name(f"{path.stem}.result.json").exists()):
                    return blocked("BLOCKED_TURN_START_INCOMPLETE", branch_id=branch_id,
                                   previous_chapter_id=previous_chapter_id)

        resolved = self.lifecycle.resolve_next_chapter(
            project_id=project_id, timeline_id=timeline_id,
            current_chapter_id=previous_chapter_id)
        resolver_successor = (int(resolved.get("next_chapter_id", 0) or 0)
                              if resolved.get("status") == "NEXT_CHAPTER_AVAILABLE" else None)
        complete, incomplete, conflict, corrupt = self._lifecycle_bundles(
            previous_chapter_id, timeline_id, branch_id, resolver_successor)
        if conflict:
            return blocked("BLOCKED_LIFECYCLE_CONFLICT", branch_id=branch_id,
                           previous_chapter_id=previous_chapter_id)
        if corrupt:
            return blocked("BLOCKED_CORRUPT_AUTHORITY", branch_id=branch_id,
                           previous_chapter_id=previous_chapter_id)
        if len(complete) != 1:
            code = "BLOCKED_LIFECYCLE_INCOMPLETE" if incomplete else "BLOCKED_LIFECYCLE_NOT_CREATED"
            return blocked(code, branch_id=branch_id,
                           previous_chapter_id=previous_chapter_id)
        op_id, claim, _phase, result = complete[0]
        successor = int(claim["request"]["next_chapter_id"])
        lifecycle_request = claim["request"]
        if lifecycle_request.get("completion_authority") != completion_authority:
            return blocked("BLOCKED_COMPLETION_RECOVERY_REQUIRED", branch_id=branch_id,
                           previous_chapter_id=previous_chapter_id,
                           successor_chapter_id=successor, lifecycle_operation_id=op_id)
        if lifecycle_request.get("branch_authority") != branch_authority:
            return blocked("BLOCKED_BRANCH_AUTHORITY_CHANGED", branch_id=branch_id,
                           previous_chapter_id=previous_chapter_id,
                           successor_chapter_id=successor, lifecycle_operation_id=op_id)
        try:
            planning_authority = self.lifecycle._planning_authority()
        except Exception:
            return blocked("BLOCKED_PLANNING_MISSING", branch_id=branch_id,
                           previous_chapter_id=previous_chapter_id,
                           successor_chapter_id=successor, lifecycle_operation_id=op_id)
        if lifecycle_request.get("planning_authority") != planning_authority:
            return blocked("BLOCKED_PLANNING_STALE", branch_id=branch_id,
                           previous_chapter_id=previous_chapter_id,
                           successor_chapter_id=successor, lifecycle_operation_id=op_id)
        if resolved.get("status") != "NEXT_CHAPTER_AVAILABLE" or resolver_successor != successor:
            code = ("BLOCKED_SUCCESSOR_ASSETS_INCOMPLETE"
                    if resolved.get("status") == "NEXT_CHAPTER_RECOVERY_REQUIRED"
                    else "BLOCKED_SUCCESSOR_NOT_VISIBLE")
            return blocked(code, branch_id=branch_id,
                           previous_chapter_id=previous_chapter_id,
                           successor_chapter_id=successor,
                           lifecycle_operation_id=op_id)
        scope = NarrativeScope(project_id, timeline_id, branch_id)
        try:
            snapshot = NarrativeTurnContextBinder(self.context).bind(scope, successor)
        except (NarrativeTurnError, OSError, ValueError):
            return blocked("BLOCKED_SOURCE_MISSING", branch_id=branch_id,
                           previous_chapter_id=previous_chapter_id,
                           successor_chapter_id=successor,
                           lifecycle_operation_id=op_id)
        if not snapshot.branch_is_active or not snapshot.branch_open:
            return blocked("BLOCKED_BRANCH_NOT_ACTIVE" if not snapshot.branch_is_active else
                           "BLOCKED_BRANCH_ARCHIVED", branch_id=branch_id,
                           previous_chapter_id=previous_chapter_id,
                           successor_chapter_id=successor,
                           lifecycle_operation_id=op_id)
        try:
            existing = []
            for turn_id in self.turns.list_plans(scope):
                plan = self.turns.get_plan(scope, turn_id)
                if plan and plan.chapter_id == successor:
                    existing.append((turn_id, self.turns.get_current_state(scope, turn_id).value))
        except NarrativeTurnError:
            return blocked("BLOCKED_CORRUPT_AUTHORITY", branch_id=branch_id,
                           previous_chapter_id=previous_chapter_id,
                           successor_chapter_id=successor,
                           lifecycle_operation_id=op_id)
        if existing:
            if len(existing) != 1:
                return blocked("BLOCKED_EXISTING_TURN_CORRUPT", branch_id=branch_id,
                               previous_chapter_id=previous_chapter_id,
                               successor_chapter_id=successor,
                               lifecycle_operation_id=op_id)
            turn_id, status = sorted(existing)[0]
            return blocked("TURN_ALREADY_STARTED", branch_id=branch_id,
                           previous_chapter_id=previous_chapter_id,
                           successor_chapter_id=successor,
                           lifecycle_operation_id=op_id,
                           existing_turn_id=turn_id,
                           existing_turn_status=status)
        authority = {
            "project_id": project_id, "timeline_id": timeline_id,
            "branch_id": branch_id, "previous_chapter_id": previous_chapter_id,
            "successor_chapter_id": successor,
            "chapter_lifecycle_operation_id": op_id,
            "chapter_lifecycle_result_fingerprint": _fingerprint(result),
            "branch_revision": branch_authority.get("revision"),
            "branch_authority_fingerprint": _fingerprint(registry),
            "planning_revision": snapshot.planning_revision,
            "planning_context_fingerprint": snapshot.context_fingerprint,
            "selected_source_version_id": snapshot.source_version_id,
            "source_fingerprint": snapshot.source_fingerprint,
            "canon_revision": snapshot.canon_revision,
        }
        return {**authority, "readiness_code": "READY_TO_START_TURN",
                "ready_to_start_turn": True, "blocking_reasons": [],
                "authority_fingerprint": _fingerprint(authority),
                "existing_turn_id": None, "existing_turn_status": None}
