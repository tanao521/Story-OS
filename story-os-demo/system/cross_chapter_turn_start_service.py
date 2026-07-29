"""Idempotent coordinator for starting a successor Chapter's first Turn."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from core.contracts.narrative_turn import NarrativeScope, TurnState, now_utc
from core.project_context import ProjectContext
from system.chapter_lifecycle_service import ChapterLifecycleService, _atomic_json
from system.cross_chapter_readiness_service import CrossChapterReadinessService, _fingerprint
from system.cross_chapter_scope import (
    AMBIGUOUS,
    CORRUPT,
    CURRENT,
    UNRELATED,
    ScopeTarget,
    classify_scope_fields,
)
from system.narrative_action_feasibility import NarrativeActionFeasibility
from system.narrative_branch_lifecycle_service import BranchLifecycleService
from system.narrative_turn_context import NarrativeTurnContextBinder
from system.narrative_turn_planner import NarrativeTurnPlanner
from system.narrative_turn_preview import NarrativeTurnPreviewService
from system.narrative_turn_service import NarrativeTurnService
from system.narrative_turn_store import NarrativeTurnStore


class CrossChapterTurnStartError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class CrossChapterTurnStartService:
    def __init__(self, context: ProjectContext,
                 *, fault_injector: Callable[[str], None] | None = None) -> None:
        self.context = context
        self.readiness = CrossChapterReadinessService(context)
        self.lifecycle = ChapterLifecycleService(context)
        self.branch_lifecycle = BranchLifecycleService(context)
        self.turns = NarrativeTurnStore(context)
        self.turn_service = NarrativeTurnService(context)
        self.operations = context.data_dir / "chapter_progression" / "operations"
        self.fault_injector = fault_injector

    def _fault(self, point: str) -> None:
        if self.fault_injector:
            self.fault_injector(point)

    def _path(self, operation_id: str, suffix: str = "") -> Path:
        if not operation_id or not operation_id.replace("_", "").replace("-", "").isalnum():
            raise CrossChapterTurnStartError("MALFORMED_REQUEST", "Invalid operation ID")
        path = self.operations / f"{operation_id}{suffix}.json"
        base, target = os.path.abspath(str(self.operations)), os.path.abspath(str(path))
        if os.path.commonpath([base, target]) != base:
            raise CrossChapterTurnStartError("MALFORMED_REQUEST", "Invalid operation ID")
        return path

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("record must be an object")
        return value

    def _phase(self, operation_id: str, phase: str, **extra: Any) -> None:
        _atomic_json(self._path(operation_id, ".phase"),
                     {"phase": phase, "updated_at": now_utc(), **extra})

    def _validate_terminal(self, operation_id: str, *, require_completed: bool = True) -> dict[str, Any] | None:
        """Validate historical start integrity without adopting current freshness."""
        try:
            claim = self._read(self._path(operation_id))
            phase = self._read(self._path(operation_id, ".phase"))
            result = self._read(self._path(operation_id, ".result"))
            request = claim["request"]
            if ((require_completed and phase.get("phase") != "completed")
                    or claim.get("operation_id") != operation_id
                    or result.get("operation_id") != operation_id
                    or result.get("project_id") != request["project_id"]
                    or result.get("timeline_id") != request["timeline_id"]
                    or result.get("branch_id") != request["branch_id"]
                    or result.get("previous_chapter_id") != request["previous_chapter_id"]
                    or result.get("successor_chapter_id") != request["successor_chapter_id"]
                    or result.get("readiness_fingerprint") != claim.get("authority_fingerprint")):
                return None
            body = dict(result)
            outcome = body.pop("outcome_fingerprint", None)
            if outcome != _fingerprint(body):
                return None
            scope = NarrativeScope(request["project_id"], request["timeline_id"], request["branch_id"])
            matching = []
            for turn_id in self.turns.list_plans(scope):
                plan = self.turns.get_plan(scope, turn_id)
                if plan and plan.chapter_id == request["successor_chapter_id"]:
                    matching.append(plan)
            if len(matching) != 1:
                return None
            plan = matching[0]
            if (plan.turn_id != result.get("turn_id")
                    or plan.fingerprint() != result.get("plan_fingerprint")):
                return None
            transitions = self.turns.get_transitions(scope, plan.turn_id)
            if not transitions:
                return None
            initial = transitions[0]
            if (initial.sequence != 0 or initial.from_state != TurnState.PLANNED
                    or initial.to_state != TurnState.AWAITING_ACTION
                    or initial.operation_id != operation_id
                    or initial.record_fingerprint != result.get("transition_fingerprint")):
                return None
            return result
        except (OSError, ValueError, KeyError, json.JSONDecodeError, Exception):
            return None

    def _terminal_or_raise(self, operation_id: str) -> dict[str, Any]:
        result = self._validate_terminal(operation_id)
        if result is None:
            raise CrossChapterTurnStartError(
                "CORRUPT_OPERATION", "Completed start operation integrity is invalid")
        return result

    def _validate_phase_effects(
        self,
        *,
        scope: NarrativeScope,
        phase: dict[str, Any],
        turn_id: Any,
        operation_id: str,
        successor_chapter_id: int,
        result_path: Path,
        expected_context_fingerprint: str | None,
    ) -> None:
        """Reject a durable phase whose promised effect is absent/corrupt."""
        phase_name = phase.get("phase")
        if phase_name not in {
            None,
            "claimed",
            "plan_published",
            "awaiting_action_transition_published",
            "result_published",
            "completed",
        }:
            raise CrossChapterTurnStartError(
                "CORRUPT_OPERATION", "Unknown durable start phase")
        requires_plan = phase_name in {
            "plan_published",
            "awaiting_action_transition_published",
            "result_published",
            "completed",
        }
        if not requires_plan:
            return
        if not isinstance(turn_id, str) or not turn_id:
            raise CrossChapterTurnStartError(
                "CORRUPT_OPERATION", "Durable phase has no bound Turn")
        plan = self.turns.get_plan(scope, turn_id)
        if (
            plan is None
            or plan.scope != scope
            or plan.chapter_id != successor_chapter_id
            or (
                expected_context_fingerprint is not None
                and plan.context_fingerprint != expected_context_fingerprint
            )
        ):
            raise CrossChapterTurnStartError(
                "CORRUPT_OPERATION", "Durable phase has no bound plan effect")
        if phase_name in {
            "awaiting_action_transition_published",
            "result_published",
            "completed",
        }:
            try:
                transitions = self.turns.get_transitions(scope, turn_id)
            except Exception as exc:
                raise CrossChapterTurnStartError(
                    "CORRUPT_OPERATION", "Durable phase transition journal is invalid") from exc
            if not transitions:
                raise CrossChapterTurnStartError(
                    "CORRUPT_OPERATION", "Durable phase has no transition effect")
            initial = transitions[0]
            if (
                initial.sequence != 0
                or initial.from_state != TurnState.PLANNED
                or initial.to_state != TurnState.AWAITING_ACTION
                or initial.operation_id != operation_id
                or (
                    phase.get("transition_fingerprint") is not None
                    and initial.record_fingerprint != phase.get("transition_fingerprint")
                )
            ):
                raise CrossChapterTurnStartError(
                    "CORRUPT_OPERATION", "Durable phase transition effect is invalid")
        if phase_name in {"result_published", "completed"} and not result_path.exists():
            raise CrossChapterTurnStartError(
                "CORRUPT_OPERATION", "Durable phase has no result effect")

    @staticmethod
    def _preview_payload(preview: Any) -> dict[str, Any]:
        return {
            "schema_version": preview.schema_version,
            "preview_id": preview.preview_id,
            "turn_id": preview.turn_id,
            "scope": {
                "project_id": preview.scope.project_id,
                "timeline_id": preview.scope.timeline_id,
                "branch_id": preview.scope.branch_id,
            },
            "chapter_id": preview.chapter_id,
            "context_fingerprint": preview.context_fingerprint,
            "preview_fingerprint": preview.preview_fingerprint,
            "action_source": preview.action_source,
            "selected_action_id": preview.selected_action_id,
            "custom_action_text_hash": preview.custom_action_text_hash,
            "validation_status": preview.validation_status.value,
            "expected_costs": [list(item) for item in preview.expected_costs],
            "expected_risks": [list(item) for item in preview.expected_risks],
            "likely_consequences": list(preview.likely_consequences),
            "evidence_codes": list(preview.evidence_codes),
            "limitations": list(preview.limitations),
            "generated_at": preview.generated_at,
        }

    def assert_branch_archive_safe(self, timeline_id: str, branch_id: str) -> None:
        if not self.operations.exists():
            return
        target = ScopeTarget(self.context.root.name, timeline_id, branch_id)
        basenames = {
            path.name[:-11] if path.name.endswith(".phase.json")
            else path.name[:-12] if path.name.endswith(".result.json")
            else path.stem
            for path in self.operations.glob("*.json")
        }
        for operation_id in basenames:
            claim_path = self._path(operation_id)
            phase_path = self._path(operation_id, ".phase")
            result_path = self._path(operation_id, ".result")
            records: dict[str, dict[str, Any]] = {}
            for kind, path in (("claim", claim_path), ("phase", phase_path), ("result", result_path)):
                if not path.exists():
                    continue
                try:
                    records[kind] = self._read(path)
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    raise CrossChapterTurnStartError(
                        "TURN_START_RECOVERY_REQUIRED", "Turn start authority is invalid") from exc
            claim = records.get("claim")
            request = claim.get("request", {}) if isinstance(claim, dict) else {}
            if claim is not None and not isinstance(request, dict):
                raise CrossChapterTurnStartError(
                    "TURN_START_RECOVERY_REQUIRED",
                    "Turn start authority is invalid")
            result = records.get("result")
            scope_fields = (
                {
                    "project_id": request.get("project_id"),
                    "timeline_id": request.get("timeline_id"),
                    "branch_id": request.get("branch_id"),
                    "previous_chapter_id": request.get("previous_chapter_id"),
                    "successor_chapter_id": request.get("successor_chapter_id"),
                }
                if claim is not None else {
                    key: result[key]
                    for key in (
                        "project_id", "timeline_id", "branch_id",
                        "previous_chapter_id", "successor_chapter_id",
                    )
                    if isinstance(result, dict) and key in result
                }
            )
            classification = classify_scope_fields(scope_fields, target, required=("project_id",))
            if classification == UNRELATED:
                continue
            if classification in (AMBIGUOUS, CORRUPT) or claim is None:
                raise CrossChapterTurnStartError(
                    "TURN_START_RECOVERY_REQUIRED",
                    "Turn start must be validated before archive")
            if self._validate_terminal(operation_id) is None:
                raise CrossChapterTurnStartError(
                    "TURN_START_RECOVERY_REQUIRED",
                    "Turn start must be validated before archive")

    def start_turn(self, *, operation_id: str, project_id: str, timeline_id: str,
                   branch_id: str, previous_chapter_id: int,
                   successor_chapter_id: int,
                   expected_readiness_fingerprint: str) -> dict[str, Any]:
        request = {
            "project_id": project_id, "timeline_id": timeline_id,
            "branch_id": branch_id, "previous_chapter_id": previous_chapter_id,
            "successor_chapter_id": successor_chapter_id,
            "expected_readiness_fingerprint": expected_readiness_fingerprint,
        }
        request_fp = _fingerprint(request)
        claim_path, result_path = self._path(operation_id), self._path(operation_id, ".result")

        def replay_if_complete() -> dict[str, Any] | None:
            if not claim_path.exists():
                return None
            try:
                claim = self._read(claim_path)
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                raise CrossChapterTurnStartError(
                    "CORRUPT_OPERATION", "Start operation claim is invalid") from exc
            if claim.get("request_fingerprint") != request_fp:
                raise CrossChapterTurnStartError(
                    "OPERATION_CONFLICT", "Operation ID is bound to another request")
            if not result_path.exists():
                return None
            try:
                result = self._read(result_path)
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                raise CrossChapterTurnStartError(
                    "CORRUPT_OPERATION", "Start operation result is invalid") from exc
            phase_path = self._path(operation_id, ".phase")
            try:
                phase = self._read(phase_path) if phase_path.exists() else {}
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                raise CrossChapterTurnStartError(
                    "CORRUPT_OPERATION", "Start operation phase is invalid") from exc
            if phase.get("phase") != "completed":
                if self._validate_terminal(operation_id, require_completed=False) is None:
                    raise CrossChapterTurnStartError(
                        "CORRUPT_OPERATION", "Result cannot repair completed phase")
                self._phase(operation_id, "completed", turn_id=result.get("turn_id"))
            return self._terminal_or_raise(operation_id)

        replay = replay_if_complete()
        if replay is not None:
            return replay
        with self.lifecycle.timeline_authority_lock(timeline_id), \
                self.branch_lifecycle._registry_lock(timeline_id), \
                self.lifecycle._operation_lock(f"{timeline_id}:turn-start:{operation_id}"), \
                self.turn_service._exclusive_lock(
                    "initial-turn",
                    f"{project_id}:{timeline_id}:{branch_id}:{successor_chapter_id}"):
            replay = replay_if_complete()
            if replay is not None:
                return replay
            if not claim_path.exists():
                ready = self.readiness.readiness(
                    project_id=project_id, timeline_id=timeline_id,
                    branch_id=branch_id, previous_chapter_id=previous_chapter_id)
                if not ready["ready_to_start_turn"]:
                    raise CrossChapterTurnStartError(
                        ready["readiness_code"], "Successor is not ready")
                if (ready["successor_chapter_id"] != successor_chapter_id
                        or ready["authority_fingerprint"] != expected_readiness_fingerprint):
                    raise CrossChapterTurnStartError(
                        "TURN_START_SOURCE_CHANGED", "Readiness authority changed")
                claim = {
                    "schema_version": "1.0", "operation_id": operation_id,
                    "operation_type": "start_successor_turn", "request": request,
                    "request_fingerprint": request_fp, "readiness_authority": ready,
                    "authority_fingerprint": ready["authority_fingerprint"],
                    "started_at": now_utc(),
                }
                claim["claim_fingerprint"] = _fingerprint(claim)
                _atomic_json(claim_path, claim)
                self._phase(operation_id, "claimed")
                self._fault("after_claim")
            else:
                try:
                    claim = self._read(claim_path)
                except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                    raise CrossChapterTurnStartError(
                        "CORRUPT_OPERATION", "Start operation claim is invalid") from exc
                if claim.get("request_fingerprint") != request_fp:
                    raise CrossChapterTurnStartError(
                        "OPERATION_CONFLICT", "Operation ID is bound to another request")

            phase_path = self._path(operation_id, ".phase")
            try:
                phase = self._read(phase_path) if phase_path.exists() else {}
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                raise CrossChapterTurnStartError(
                    "CORRUPT_OPERATION", "Start operation phase is invalid") from exc
            turn_id = phase.get("turn_id")
            fresh = self.readiness.readiness(
                project_id=project_id, timeline_id=timeline_id,
                branch_id=branch_id, previous_chapter_id=previous_chapter_id,
                ignore_start_operation_id=operation_id)
            if fresh["authority_fingerprint"] != claim["authority_fingerprint"]:
                if not (fresh["readiness_code"] == "TURN_ALREADY_STARTED"
                        and (turn_id is None or fresh.get("existing_turn_id") == turn_id)):
                    raise CrossChapterTurnStartError(
                        "TURN_START_SOURCE_CHANGED", "Start authority changed")
            scope = NarrativeScope(project_id, timeline_id, branch_id)
            snapshot = NarrativeTurnContextBinder(self.context).bind(
                scope, successor_chapter_id)
            if snapshot.context_fingerprint != claim["readiness_authority"]["planning_context_fingerprint"]:
                raise CrossChapterTurnStartError(
                    "TURN_START_SOURCE_CHANGED", "Turn context changed")
            try:
                plan = self.turns.get_plan(scope, turn_id) if turn_id else None
            except Exception as exc:
                raise CrossChapterTurnStartError(
                    "CORRUPT_OPERATION", "Start plan effect is invalid") from exc
            self._validate_phase_effects(
                scope=scope,
                phase=phase,
                turn_id=turn_id,
                operation_id=operation_id,
                successor_chapter_id=successor_chapter_id,
                result_path=result_path,
                expected_context_fingerprint=claim["readiness_authority"].get(
                    "planning_context_fingerprint"
                ),
            )
            if plan is None:
                plan = NarrativeTurnPlanner.build_plan(
                    snapshot, clock_now=claim["started_at"])
                other = []
                for item in self.turns.list_plans(scope):
                    existing = self.turns.get_plan(scope, item)
                    if existing and existing.chapter_id == successor_chapter_id:
                        other.append(item)
                if other and plan.turn_id not in other:
                    raise CrossChapterTurnStartError(
                        "TURN_ALREADY_STARTED", "Another initial Turn exists")
                if plan.turn_id not in other:
                    self.turns.append_plan(plan)
                turn_id = plan.turn_id
                self._fault("after_plan_effect")
                self._phase(operation_id, "plan_published", turn_id=turn_id)
                self._fault("after_plan_phase")
                self._fault("after_turn_delegate")
            self.turn_service._append_transition_safe(
                scope, turn_id, TurnState.PLANNED, TurnState.AWAITING_ACTION,
                "cross_chapter_turn_started", operation_id)
            transitions = self.turns.get_transitions(scope, turn_id)
            if (not transitions or transitions[0].sequence != 0
                    or transitions[0].from_state != TurnState.PLANNED
                    or transitions[0].to_state != TurnState.AWAITING_ACTION
                    or transitions[0].operation_id != operation_id):
                raise CrossChapterTurnStartError(
                    "CORRUPT_OPERATION", "Initial transition integrity is invalid")
            initial_transition = transitions[0]
            self._fault("after_transition_effect")
            self._phase(operation_id, "awaiting_action_transition_published", turn_id=turn_id,
                        transition_fingerprint=initial_transition.record_fingerprint)
            self._fault("after_transition_phase")
            action = plan.recommended_actions[0]
            validation = NarrativeActionFeasibility.validate_recommended(
                snapshot, action, turn_id, clock_now=claim["started_at"])
            preview = NarrativeTurnPreviewService.preview_recommended(
                plan=plan, action=action, validation=validation,
                snapshot=snapshot, clock_now=claim["started_at"])
            result = {
                "schema_version": "1.0", "operation_id": operation_id,
                "operation_type": "start_successor_turn",
                "project_id": project_id, "timeline_id": timeline_id,
                "branch_id": branch_id,
                "previous_chapter_id": previous_chapter_id,
                "successor_chapter_id": successor_chapter_id,
                "chapter_lifecycle_operation_id":
                    claim["readiness_authority"]["chapter_lifecycle_operation_id"],
                "readiness_fingerprint": claim["authority_fingerprint"],
                "turn_id": turn_id, "turn_status": TurnState.AWAITING_ACTION.value,
                "plan_fingerprint": plan.fingerprint(),
                "transition_fingerprint": initial_transition.record_fingerprint,
                "preview": self._preview_payload(preview),
                "completed_at": now_utc(), "warnings": [],
            }
            result["outcome_fingerprint"] = _fingerprint(result)
            _atomic_json(result_path, result)
            self._fault("after_result")
            self._phase(operation_id, "result_published", turn_id=turn_id,
                        transition_fingerprint=initial_transition.record_fingerprint)
            self._fault("after_result_phase")
            self._phase(operation_id, "completed", turn_id=turn_id)
            self._fault("after_completed_phase")
            return result
