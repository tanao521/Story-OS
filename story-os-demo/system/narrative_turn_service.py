"""Transactional Narrative Turn Confirmation Service.

Phase 0D4-D: implements confirm with idempotent operation replay,
first-writer-wins concurrency arbitration, branch-local event journal,
branch-state projection with CAS, and forward recovery protocol.

Security boundaries (enforced as 0 for non-test writes):
- No Provider calls
- No Canon writes
- No Chroma writes
- No global NarrativeMemory migration
- No branch lifecycle mutation
- Custom action raw text never persisted — only hash travels to records
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from core.contracts.narrative_turn import (
    ActionSource,
    NarrativeActionValidation,
    NarrativeScope,
    NarrativeTurnError,
    NarrativeTurnPlan,
    NarrativeTurnResult,
    NarrativeTurnTransition,
    ResultStatus,
    SCHEMA_VERSION,
    TurnState,
    ValidationStatus,
    new_id,
    now_utc,
)
from core.project_context import ProjectContext
from system.narrative_action_feasibility import (
    NarrativeActionFeasibility,
    NormalizedCustomAction,
    normalize_custom_action,
)
from system.narrative_turn_context import (
    NarrativeTurnContextBinder,
    NarrativeTurnContextSnapshot,
    _stable_fingerprint,
)
from system.narrative_turn_planner import NarrativeTurnPlanner
from system.narrative_turn_preview import NarrativeTurnPreviewService
from system.narrative_turn_store import NarrativeTurnStore


_PATH_COMPONENT_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_SEQUENCE_FILENAME_PATTERN = re.compile(r"^\d{8}\.json$")


def _validate_path_component(value: str, component_name: str) -> None:
    if not isinstance(value, str) or _PATH_COMPONENT_PATTERN.fullmatch(value) is None:
        raise NarrativeTurnError(NarrativeTurnError.INVALID_ID, f"Invalid {component_name}: {value!r}")


def _validate_path_containment(base: Path, target: Path) -> None:
    try:
        resolved_base = base.resolve()
        resolved_target = target.resolve()
    except OSError as exc:
        raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, "Path resolution failed") from exc
    try:
        resolved_target.relative_to(resolved_base)
    except ValueError as exc:
        raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, "Path traversal detected") from exc


def _canonical_json(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, indent=2)


def _publish_immutable_json(target_path: Path, data: dict[str, Any]) -> None:
    parent = target_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    payload_text = _canonical_json(data)

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{target_path.name}.",
        suffix=".tmp",
        dir=str(parent),
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload_text)
                f.flush()
                os.fsync(f.fileno())
        except OSError as exc:
            raise NarrativeTurnError(
                NarrativeTurnError.INVALID_FIELD,
                f"Atomic immutable publication failed during write/fsync: {exc}",
            ) from exc
        try:
            os.link(str(temp_path), str(target_path))
        except FileExistsError:
            try:
                existing_text = target_path.read_text(encoding="utf-8")
            except OSError as exc:
                raise NarrativeTurnError(
                    NarrativeTurnError.INVALID_FIELD,
                    "Failed to read existing immutable record",
                ) from exc
            if existing_text == payload_text:
                return
            raise NarrativeTurnError(
                NarrativeTurnError.IMMUTABLE_RECORD_EXISTS,
                f"Immutable record already exists with different content: {target_path.name}",
            )
        except OSError as exc:
            raise NarrativeTurnError(
                NarrativeTurnError.INVALID_FIELD,
                f"Atomic immutable publication failed: {exc}",
            ) from exc
    finally:
        try:
            temp_path.unlink()
        except OSError:
            pass


def _atomic_write_json(target_path: Path, data: dict[str, Any]) -> None:
    parent = target_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{target_path.name}.",
        suffix=".tmp",
        dir=str(parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, sort_keys=True, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_name, str(target_path))
    except OSError as exc:
        raise NarrativeTurnError(
            NarrativeTurnError.INVALID_FIELD,
            f"Atomic write failed: {exc}",
        ) from exc
    finally:
        try:
            os.unlink(temp_name)
        except OSError:
            pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, "Corrupt JSON") from exc
    except OSError as exc:
        raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, "Failed to read file") from exc


def _compute_event_fingerprint(payload: dict[str, Any]) -> str:
    fp_payload = {k: v for k, v in payload.items() if k != "record_fingerprint"}
    return sha256(
        json.dumps(fp_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


class ConfirmOperationPhase(str):
    PRECHECK_COMPLETE = "precheck_complete"
    RESULT_CLAIMED = "result_claimed"
    TURN_CHAIN_PERSISTED = "turn_chain_persisted"
    CONFIRMED_TRANSITION_APPENDED = "confirmed_transition_appended"
    BRANCH_EVENT_APPENDED = "branch_event_appended"
    STATE_PROJECTED = "state_projected"
    APPLIED_TRANSITION_APPENDED = "applied_transition_appended"
    COMPLETED = "completed"


@dataclass(frozen=True)
class ConfirmResult:
    result: NarrativeTurnResult
    idempotent_replay: bool
    recovery_performed: bool
    branch_state_revision: str
    final_phase: str


class NarrativeTurnService:
    """Transactional Narrative Turn confirmation service.

    Implements:
    - Idempotent operation replay via operation_id
    - First-writer-wins concurrency via immutable Result claim
    - Full legal transition chain (planned -> ... -> applied_to_branch)
    - Branch-local append-only event journal
    - Branch-state projection with CAS (compare-and-swap)
    - Forward recovery protocol with phase markers
    """

    def __init__(self, project_context: ProjectContext) -> None:
        self._project_root = project_context.data_dir
        project_id = project_context.root.name
        _validate_path_component(project_id, "project_id")
        self._project_id = project_id
        self._turn_store = NarrativeTurnStore(project_context)
        self._context_binder = NarrativeTurnContextBinder(project_context)
        self._project_context = project_context

    def _branch_events_path(self, scope: NarrativeScope) -> Path:
        _validate_path_component(scope.timeline_id, "timeline_id")
        _validate_path_component(scope.branch_id, "branch_id")
        path = self._project_root / "narrative_turns" / scope.timeline_id / scope.branch_id / "branch_events"
        _validate_path_containment(self._project_root, path)
        return path

    def _branch_state_path(self, scope: NarrativeScope) -> Path:
        _validate_path_component(scope.timeline_id, "timeline_id")
        _validate_path_component(scope.branch_id, "branch_id")
        path = self._project_context.narrative_state_dir / scope.timeline_id / scope.branch_id / "current.json"
        _validate_path_containment(self._project_root, path)
        return path

    def _operation_phase_path(self, operation_id: str) -> Path:
        _validate_path_component(operation_id, "operation_id")
        path = self._project_root / "narrative_turn_operations" / f"{operation_id}_phase.json"
        _validate_path_containment(self._project_root, path)
        return path

    def _read_operation_phase(self, operation_id: str) -> dict[str, Any] | None:
        path = self._operation_phase_path(operation_id)
        if not path.exists():
            return None
        return _load_json(path)

    def _write_operation_phase(
        self,
        operation_id: str,
        phase: str,
        scope: NarrativeScope,
        turn_id: str,
        result_fingerprint: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        path = self._operation_phase_path(operation_id)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "operation_id": operation_id,
            "project_id": scope.project_id,
            "timeline_id": scope.timeline_id,
            "branch_id": scope.branch_id,
            "turn_id": turn_id,
            "phase": phase,
            "result_fingerprint": result_fingerprint,
            "updated_at": now_utc(),
        }
        if extra:
            payload.update(extra)
        _atomic_write_json(path, payload)

    def _read_branch_events(self, scope: NarrativeScope) -> list[dict[str, Any]]:
        events_path = self._branch_events_path(scope)
        if not events_path.exists():
            return []
        records: list[dict[str, Any]] = []
        for entry in sorted(events_path.iterdir()):
            if entry.suffix != ".json":
                continue
            if not _SEQUENCE_FILENAME_PATTERN.fullmatch(entry.name):
                raise NarrativeTurnError(
                    NarrativeTurnError.LIFECYCLE_EVENT_CHAIN_CORRUPT,
                    f"Invalid branch event filename: {entry.name}",
                )
            records.append(_load_json(entry))
        records.sort(key=lambda r: r["sequence"])
        previous_fp: str | None = None
        expected_seq = 0
        for record in records:
            if record["sequence"] != expected_seq:
                raise NarrativeTurnError(
                    NarrativeTurnError.LIFECYCLE_EVENT_CHAIN_CORRUPT,
                    f"Branch event sequence gap/duplicate at {expected_seq}",
                )
            if record.get("previous_event_fingerprint") != previous_fp:
                raise NarrativeTurnError(
                    NarrativeTurnError.LIFECYCLE_EVENT_CHAIN_CORRUPT,
                    "Branch event previous_event_fingerprint chain broken",
                )
            previous_fp = record["record_fingerprint"]
            expected_seq += 1
        return records

    def _append_branch_event(
        self,
        scope: NarrativeScope,
        turn_id: str,
        result_fingerprint: str,
        operation_id: str,
    ) -> dict[str, Any]:
        existing = self._read_branch_events(scope)
        for evt in existing:
            if evt["operation_id"] == operation_id and evt["turn_id"] == turn_id:
                return evt

        sequence = len(existing)
        if existing:
            last = existing[-1]
            previous_event_id = last["event_id"]
            previous_event_fingerprint = last["record_fingerprint"]
        else:
            previous_event_id = None
            previous_event_fingerprint = None

        event_id = new_id("bevt")
        occurred_at = now_utc()
        payload = {
            "schema_version": SCHEMA_VERSION,
            "event_id": event_id,
            "sequence": sequence,
            "scope": {
                "project_id": scope.project_id,
                "timeline_id": scope.timeline_id,
                "branch_id": scope.branch_id,
            },
            "turn_id": turn_id,
            "result_fingerprint": result_fingerprint,
            "operation_id": operation_id,
            "previous_event_id": previous_event_id,
            "previous_event_fingerprint": previous_event_fingerprint,
            "occurred_at": occurred_at,
        }
        record_fingerprint = _compute_event_fingerprint(payload)
        payload["record_fingerprint"] = record_fingerprint

        events_path = self._branch_events_path(scope)
        events_path.mkdir(parents=True, exist_ok=True)
        event_path = events_path / f"{sequence:08d}.json"
        _publish_immutable_json(event_path, payload)
        return payload

    def _read_branch_state(self, scope: NarrativeScope) -> tuple[str | None, dict[str, Any] | None]:
        state_path = self._branch_state_path(scope)
        if not state_path.exists():
            return None, None
        data = _load_json(state_path)
        revision = data.get("revision")
        return revision, data

    def _apply_state_delta(
        self,
        current_state: dict[str, Any] | None,
        state_delta_proposal: tuple[tuple[str, Any], ...],
    ) -> dict[str, Any]:
        result = dict(current_state) if current_state else {}
        for key, value in state_delta_proposal:
            if isinstance(value, tuple):
                if value and isinstance(value[0], tuple) and len(value[0]) == 2:
                    result[key] = dict((k, v) for k, v in value)
                else:
                    result[key] = list(value)
            else:
                result[key] = value
        return result

    def _project_state(
        self,
        scope: NarrativeScope,
        turn_id: str,
        event_sequence: int,
        result_fingerprint: str,
        state_delta_proposal: tuple[tuple[str, Any], ...],
        expected_revision: str | None,
    ) -> str:
        state_path = self._branch_state_path(scope)
        state_path.parent.mkdir(parents=True, exist_ok=True)

        current_rev, current_state = self._read_branch_state(scope)

        if current_rev != expected_revision:
            raise NarrativeTurnError(
                NarrativeTurnError.BRANCH_OPERATION_STALE_REVISION,
                "Branch state revision conflict",
            )

        new_state = self._apply_state_delta(current_state, state_delta_proposal)

        new_state["project_id"] = scope.project_id
        new_state["timeline_id"] = scope.timeline_id
        new_state["branch_id"] = scope.branch_id
        new_state["last_applied_turn_id"] = turn_id
        new_state["last_event_sequence"] = event_sequence
        new_state["last_result_fingerprint"] = result_fingerprint
        new_state["updated_at"] = now_utc()

        new_revision = _stable_fingerprint(new_state)
        new_state["revision"] = new_revision

        backup_path = state_path.with_suffix(".bak")
        try:
            if state_path.exists():
                os.replace(str(state_path), str(backup_path))
            _atomic_write_json(state_path, new_state)
            return new_revision
        except NarrativeTurnError:
            if backup_path.exists():
                try:
                    os.replace(str(backup_path), str(state_path))
                except OSError:
                    pass
            raise

    def _build_result(
        self,
        plan: NarrativeTurnPlan,
        validation: NarrativeActionValidation,
        snapshot: NarrativeTurnContextSnapshot,
        operation_id: str,
        clock_now: str,
    ) -> NarrativeTurnResult:
        if validation.status == ValidationStatus.ALLOWED:
            result_status = ResultStatus.SUCCESS
        elif validation.status == ValidationStatus.ALLOWED_WITH_COST:
            result_status = ResultStatus.PARTIAL
        else:
            raise NarrativeTurnError(
                NarrativeTurnError.INVALID_FIELD,
                f"Cannot confirm action with status: {validation.status.value}",
            )

        if validation.action_source == ActionSource.RECOMMENDED:
            selected_action_id = validation.selected_action_id
            custom_action_text_hash = None
            action = next(
                (a for a in plan.recommended_actions if a.action_id == selected_action_id),
                None,
            )
            if action is None:
                raise NarrativeTurnError(
                    NarrativeTurnError.ACTION_INVALID,
                    "Selected action not found in plan",
                )
            summary_intent = action.intent
        else:
            selected_action_id = None
            custom_action_text_hash = validation.custom_action_text_hash
            summary_intent = f"custom_{custom_action_text_hash[:16]}" if custom_action_text_hash else "custom_action"

        event_summary = f"Turn {plan.turn_id}: {result_status.value} - {summary_intent}"

        consequence_flags: list[str] = []
        for cost_kind, cost_level in validation.cost_explanation:
            consequence_flags.append(f"cost_{cost_kind}_{cost_level}")
        for risk_kind, risk_level in validation.risk_explanation:
            consequence_flags.append(f"risk_{risk_kind}_{risk_level}")

        state_delta_proposal_list: list[tuple[str, Any]] = []
        state_delta_proposal_list.append(("last_turn_id", plan.turn_id))
        state_delta_proposal_list.append(("last_result_status", result_status.value))
        state_delta_proposal_list.append(("last_action_source", validation.action_source.value))
        if selected_action_id:
            state_delta_proposal_list.append(("last_selected_action_id", selected_action_id))
        if custom_action_text_hash:
            state_delta_proposal_list.append(("last_custom_action_hash", custom_action_text_hash))

        state_delta_proposal = tuple(state_delta_proposal_list)

        next_context_fp_input = {
            "previous_context_fingerprint": snapshot.context_fingerprint,
            "turn_id": plan.turn_id,
            "result_status": result_status.value,
            "state_delta_fingerprint": _stable_fingerprint(state_delta_proposal),
        }
        next_context_fingerprint = _stable_fingerprint(next_context_fp_input)

        return NarrativeTurnResult(
            schema_version=SCHEMA_VERSION,
            turn_id=plan.turn_id,
            scope=plan.scope,
            chapter_id=plan.chapter_id,
            selected_action_id=selected_action_id,
            custom_action_text_hash=custom_action_text_hash,
            result_status=result_status,
            event_summary=event_summary,
            state_delta_proposal=state_delta_proposal,
            consequence_flags=tuple(consequence_flags),
            next_context_fingerprint=next_context_fingerprint,
            execution_revision=f"exec_{plan.turn_id[:16]}",
            source_fingerprint=snapshot.source_fingerprint,
            confirmed_at=clock_now,
            operation_id=operation_id,
        )

    def _append_transition_safe(
        self,
        scope: NarrativeScope,
        turn_id: str,
        from_state: TurnState,
        to_state: TurnState,
        reason_code: str,
        operation_id: str,
    ) -> bool:
        try:
            existing = self._turn_store.get_transitions(scope, turn_id)
        except NarrativeTurnError:
            existing = []

        current_state = existing[-1].to_state if existing else TurnState.PLANNED

        if current_state == to_state:
            return False

        if current_state != from_state:
            raise NarrativeTurnError(
                NarrativeTurnError.ILLEGAL_TRANSITION,
                f"Cannot transition from {from_state.value} when current is {current_state.value}",
            )

        sequence = len(existing)
        previous_transition_id = existing[-1].transition_id if existing else None
        previous_transition_fingerprint = existing[-1].record_fingerprint if existing else None

        transition_id = new_id("trans")
        occurred_at = now_utc()

        record_fp_input = {
            "schema_version": SCHEMA_VERSION,
            "transition_id": transition_id,
            "turn_id": turn_id,
            "project_id": scope.project_id,
            "timeline_id": scope.timeline_id,
            "branch_id": scope.branch_id,
            "from_state": from_state.value,
            "to_state": to_state.value,
            "reason_code": reason_code,
            "operation_id": operation_id,
            "occurred_at": occurred_at,
            "sequence": sequence,
            "previous_transition_id": previous_transition_id,
            "previous_transition_fingerprint": previous_transition_fingerprint,
        }
        record_fingerprint = _compute_event_fingerprint(record_fp_input)

        transition = NarrativeTurnTransition(
            schema_version=SCHEMA_VERSION,
            transition_id=transition_id,
            turn_id=turn_id,
            scope=scope,
            from_state=from_state,
            to_state=to_state,
            reason_code=reason_code,
            operation_id=operation_id,
            occurred_at=occurred_at,
            record_fingerprint=record_fingerprint,
            sequence=sequence,
            previous_transition_id=previous_transition_id,
            previous_transition_fingerprint=previous_transition_fingerprint,
        )

        try:
            self._turn_store.append_transition(transition)
            return True
        except NarrativeTurnError as exc:
            if exc.code == NarrativeTurnError.TRANSITION_COLLISION:
                return False
            raise

    def confirm_turn(
        self,
        *,
        operation_id: str,
        scope: NarrativeScope,
        chapter_id: int,
        source_version_id: str | None,
        expected_context_fingerprint: str | None,
        expected_turn_id: str | None,
        expected_validation_id: str | None,
        expected_preview_fingerprint: str | None,
        action_source: str,
        selected_action_id: str | None = None,
        custom_action_text: str | None = None,
    ) -> ConfirmResult:
        """Confirm a narrative turn with full transactional semantics.

        Implements idempotent replay, first-writer-wins concurrency,
        full transition chain, branch event journal, state projection,
        and forward recovery.
        """
        if scope.project_id != self._project_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "project_id mismatch")

        _validate_path_component(operation_id, "operation_id")

        custom_raw_text: str | None = None
        try:
            existing_op = self._turn_store.get_operation(scope, operation_id)
            existing_phase = self._read_operation_phase(operation_id)

            if existing_op is not None:
                if (
                    existing_op.get("timeline_id") != scope.timeline_id
                    or existing_op.get("branch_id") != scope.branch_id
                    or existing_op.get("turn_id") != (existing_phase.get("turn_id") if existing_phase else None)
                ):
                    existing_turn = existing_op.get("turn_id")
                    if existing_turn and existing_op.get("operation_type") == "result":
                        if (
                            existing_op.get("timeline_id") != scope.timeline_id
                            or existing_op.get("branch_id") != scope.branch_id
                        ):
                            raise NarrativeTurnError(
                                NarrativeTurnError.OPERATION_COLLISION,
                                "Operation already bound to a different scope",
                            )

            if existing_phase is not None:
                return self._resume_confirmation(
                    operation_id=operation_id,
                    scope=scope,
                    phase_record=existing_phase,
                )

            snapshot = self._context_binder.bind(
                scope,
                chapter_id,
                source_version_id=source_version_id,
            )

            if not snapshot.branch_open:
                raise NarrativeTurnError(
                    NarrativeTurnError.BRANCH_LIFECYCLE_CONFLICT,
                    "Branch is archived",
                )
            if not snapshot.branch_is_active:
                raise NarrativeTurnError(
                    NarrativeTurnError.BRANCH_NOT_ACTIVE,
                    "Branch is not active",
                )

            if expected_context_fingerprint is not None and expected_context_fingerprint != snapshot.context_fingerprint:
                raise NarrativeTurnError(
                    NarrativeTurnError.INVALID_FIELD,
                    "Context fingerprint mismatch",
                )

            plan = NarrativeTurnPlanner.build_plan(
                snapshot,
                parent_turn_id=None,
                clock_now=now_utc(),
            )

            if expected_turn_id is not None and expected_turn_id != plan.turn_id:
                raise NarrativeTurnError(
                    NarrativeTurnError.INVALID_FIELD,
                    "Turn ID mismatch",
                )

            if action_source == "recommended":
                if not selected_action_id:
                    raise NarrativeTurnError(
                        NarrativeTurnError.VALIDATION_ACTION_XOR,
                        "selected_action_id required for recommended action",
                    )
                action = next(
                    (a for a in plan.recommended_actions if a.action_id == selected_action_id),
                    None,
                )
                if action is None:
                    raise NarrativeTurnError(
                        NarrativeTurnError.ACTION_INVALID,
                        "Selected action not found",
                    )
                validation = NarrativeActionFeasibility.validate_recommended(
                    snapshot,
                    action,
                    plan.turn_id,
                    clock_now=now_utc(),
                )
                normalized_custom = None
            else:
                if not custom_action_text:
                    raise NarrativeTurnError(
                        NarrativeTurnError.VALIDATION_ACTION_XOR,
                        "custom_action_text required for custom action",
                    )
                custom_raw_text = custom_action_text
                normalized_custom = normalize_custom_action(custom_action_text)
                validation = NarrativeActionFeasibility.validate_custom(
                    snapshot,
                    normalized_custom,
                    plan.turn_id,
                    clock_now=now_utc(),
                )

            if validation.status not in (ValidationStatus.ALLOWED, ValidationStatus.ALLOWED_WITH_COST):
                raise NarrativeTurnError(
                    NarrativeTurnError.INVALID_FIELD,
                    f"Cannot confirm action with status: {validation.status.value}",
                )

            if expected_validation_id is not None and expected_validation_id != validation.validation_id:
                raise NarrativeTurnError(
                    NarrativeTurnError.INVALID_FIELD,
                    "Validation ID mismatch",
                )

            try:
                if action_source == "recommended":
                    preview = NarrativeTurnPreviewService.preview_recommended(
                        plan=plan,
                        action=action,
                        validation=validation,
                        snapshot=snapshot,
                        clock_now=now_utc(),
                    )
                else:
                    preview = NarrativeTurnPreviewService.preview_custom(
                        plan=plan,
                        validation=validation,
                        snapshot=snapshot,
                        clock_now=now_utc(),
                    )
            except NarrativeTurnError:
                preview = None

            if expected_preview_fingerprint is not None and preview is not None:
                if expected_preview_fingerprint != preview.preview_fingerprint:
                    raise NarrativeTurnError(
                        NarrativeTurnError.INVALID_FIELD,
                        "Preview fingerprint mismatch",
                    )

            clock_now = now_utc()
            result = self._build_result(
                plan=plan,
                validation=validation,
                snapshot=snapshot,
                operation_id=operation_id,
                clock_now=clock_now,
            )

            result_fp = result.fingerprint()

            self._write_operation_phase(
                operation_id,
                ConfirmOperationPhase.PRECHECK_COMPLETE,
                scope,
                plan.turn_id,
                result_fp,
            )

            try:
                self._turn_store.append_result(result)
                self._turn_store.record_operation(
                    scope,
                    operation_id,
                    plan.turn_id,
                    "result",
                    result_fp,
                )
            except NarrativeTurnError as exc:
                if exc.code == NarrativeTurnError.INVALID_FIELD:
                    existing_result = self._turn_store.get_result(scope, plan.turn_id)
                    if existing_result is not None:
                        if existing_result.operation_id != operation_id:
                            raise NarrativeTurnError(
                                NarrativeTurnError.OPERATION_COLLISION,
                                "Turn already confirmed by a different operation",
                            ) from exc
                        result_fp = existing_result.fingerprint()
                    else:
                        raise
                elif exc.code == NarrativeTurnError.OPERATION_COLLISION:
                    existing_result = self._turn_store.get_result(scope, plan.turn_id)
                    if existing_result is not None and existing_result.operation_id == operation_id:
                        result_fp = existing_result.fingerprint()
                    else:
                        raise
                else:
                    raise

            self._write_operation_phase(
                operation_id,
                ConfirmOperationPhase.RESULT_CLAIMED,
                scope,
                plan.turn_id,
                result_fp,
            )

            try:
                self._turn_store.append_plan(plan)
            except NarrativeTurnError as exc:
                if exc.code != NarrativeTurnError.INVALID_FIELD:
                    raise

            self._append_transition_safe(
                scope, plan.turn_id,
                TurnState.PLANNED, TurnState.AWAITING_ACTION,
                "plan_published", operation_id,
            )
            self._append_transition_safe(
                scope, plan.turn_id,
                TurnState.AWAITING_ACTION, TurnState.VALIDATING,
                "action_selected", operation_id,
            )

            try:
                self._turn_store.append_validation(validation)
            except NarrativeTurnError as exc:
                if exc.code != NarrativeTurnError.INVALID_FIELD:
                    raise

            self._append_transition_safe(
                scope, plan.turn_id,
                TurnState.VALIDATING, TurnState.VALIDATED,
                "validation_passed", operation_id,
            )
            self._append_transition_safe(
                scope, plan.turn_id,
                TurnState.VALIDATED, TurnState.PREVIEWED,
                "preview_generated", operation_id,
            )

            self._write_operation_phase(
                operation_id,
                ConfirmOperationPhase.TURN_CHAIN_PERSISTED,
                scope,
                plan.turn_id,
                result_fp,
            )

            self._append_transition_safe(
                scope, plan.turn_id,
                TurnState.PREVIEWED, TurnState.CONFIRMED,
                "user_confirmed", operation_id,
            )

            self._write_operation_phase(
                operation_id,
                ConfirmOperationPhase.CONFIRMED_TRANSITION_APPENDED,
                scope,
                plan.turn_id,
                result_fp,
            )

            try:
                event = self._append_branch_event(
                    scope, plan.turn_id, result_fp, operation_id
                )
            except NarrativeTurnError as exc:
                if exc.code == NarrativeTurnError.IMMUTABLE_RECORD_EXISTS:
                    events = self._read_branch_events(scope)
                    event = events[-1] if events else None
                    if event is None:
                        raise
                else:
                    raise

            event_sequence = event["sequence"]

            self._write_operation_phase(
                operation_id,
                ConfirmOperationPhase.BRANCH_EVENT_APPENDED,
                scope,
                plan.turn_id,
                result_fp,
                {"event_sequence": event_sequence},
            )

            current_state_rev, _ = self._read_branch_state(scope)
            new_revision = self._project_state(
                scope,
                turn_id=plan.turn_id,
                event_sequence=event_sequence,
                result_fingerprint=result_fp,
                state_delta_proposal=result.state_delta_proposal,
                expected_revision=current_state_rev,
            )

            self._write_operation_phase(
                operation_id,
                ConfirmOperationPhase.STATE_PROJECTED,
                scope,
                plan.turn_id,
                result_fp,
                {
                    "event_sequence": event_sequence,
                    "branch_state_revision": new_revision,
                },
            )

            self._append_transition_safe(
                scope, plan.turn_id,
                TurnState.CONFIRMED, TurnState.APPLIED_TO_BRANCH,
                "state_projected", operation_id,
            )

            self._write_operation_phase(
                operation_id,
                ConfirmOperationPhase.APPLIED_TRANSITION_APPENDED,
                scope,
                plan.turn_id,
                result_fp,
                {
                    "event_sequence": event_sequence,
                    "branch_state_revision": new_revision,
                },
            )

            self._write_operation_phase(
                operation_id,
                ConfirmOperationPhase.COMPLETED,
                scope,
                plan.turn_id,
                result_fp,
                {
                    "event_sequence": event_sequence,
                    "branch_state_revision": new_revision,
                },
            )

            final_result = self._turn_store.get_result(scope, plan.turn_id)
            if final_result is None:
                raise NarrativeTurnError(
                    NarrativeTurnError.INVALID_FIELD,
                    "Result not found after confirmation",
                )

            return ConfirmResult(
                result=final_result,
                idempotent_replay=False,
                recovery_performed=False,
                branch_state_revision=new_revision,
                final_phase=ConfirmOperationPhase.COMPLETED,
            )
        finally:
            custom_raw_text = None

    def _resume_confirmation(
        self,
        *,
        operation_id: str,
        scope: NarrativeScope,
        phase_record: dict[str, Any],
    ) -> ConfirmResult:
        turn_id = phase_record["turn_id"]
        result_fp = phase_record["result_fingerprint"]
        current_phase = phase_record["phase"]

        if phase_record.get("project_id") != scope.project_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "project_id mismatch")
        if phase_record.get("timeline_id") != scope.timeline_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "timeline_id mismatch")
        if phase_record.get("branch_id") != scope.branch_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "branch_id mismatch")

        result = self._turn_store.get_result(scope, turn_id)
        if result is None:
            raise NarrativeTurnError(
                NarrativeTurnError.INVALID_FIELD,
                "Result not found during recovery",
            )

        if result.fingerprint() != result_fp:
            raise NarrativeTurnError(
                NarrativeTurnError.OPERATION_COLLISION,
                "Result fingerprint mismatch during recovery",
            )

        recovery_performed = current_phase != ConfirmOperationPhase.COMPLETED

        if current_phase == ConfirmOperationPhase.COMPLETED:
            return ConfirmResult(
                result=result,
                idempotent_replay=True,
                recovery_performed=False,
                branch_state_revision=phase_record.get("branch_state_revision", ""),
                final_phase=ConfirmOperationPhase.COMPLETED,
            )

        event_sequence = phase_record.get("event_sequence")
        branch_state_revision = phase_record.get("branch_state_revision", "")

        if current_phase in (
            ConfirmOperationPhase.PRECHECK_COMPLETE,
            ConfirmOperationPhase.RESULT_CLAIMED,
            ConfirmOperationPhase.TURN_CHAIN_PERSISTED,
            ConfirmOperationPhase.CONFIRMED_TRANSITION_APPENDED,
        ):
            try:
                event = self._append_branch_event(scope, turn_id, result_fp, operation_id)
                event_sequence = event["sequence"]
            except NarrativeTurnError as exc:
                if exc.code == NarrativeTurnError.IMMUTABLE_RECORD_EXISTS:
                    events = self._read_branch_events(scope)
                    for evt in events:
                        if evt["operation_id"] == operation_id:
                            event_sequence = evt["sequence"]
                            break
                    if event_sequence is None:
                        if events:
                            event_sequence = events[-1]["sequence"]
                else:
                    raise

            self._write_operation_phase(
                operation_id,
                ConfirmOperationPhase.BRANCH_EVENT_APPENDED,
                scope,
                turn_id,
                result_fp,
                {"event_sequence": event_sequence},
            )
            current_phase = ConfirmOperationPhase.BRANCH_EVENT_APPENDED

        if current_phase == ConfirmOperationPhase.BRANCH_EVENT_APPENDED:
            if event_sequence is None:
                events = self._read_branch_events(scope)
                for evt in events:
                    if evt["operation_id"] == operation_id:
                        event_sequence = evt["sequence"]
                        break

            current_state_rev, _ = self._read_branch_state(scope)
            try:
                new_revision = self._project_state(
                    scope,
                    turn_id=turn_id,
                    event_sequence=event_sequence if event_sequence is not None else 0,
                    result_fingerprint=result_fp,
                    state_delta_proposal=result.state_delta_proposal,
                    expected_revision=current_state_rev,
                )
            except NarrativeTurnError as exc:
                if exc.code == NarrativeTurnError.BRANCH_OPERATION_STALE_REVISION:
                    _, current_state = self._read_branch_state(scope)
                    if current_state and current_state.get("last_result_fingerprint") == result_fp:
                        new_revision = current_state.get("revision", "")
                    else:
                        raise
                else:
                    raise

            branch_state_revision = new_revision
            self._write_operation_phase(
                operation_id,
                ConfirmOperationPhase.STATE_PROJECTED,
                scope,
                turn_id,
                result_fp,
                {
                    "event_sequence": event_sequence,
                    "branch_state_revision": new_revision,
                },
            )
            current_phase = ConfirmOperationPhase.STATE_PROJECTED

        if current_phase == ConfirmOperationPhase.STATE_PROJECTED:
            self._append_transition_safe(
                scope, turn_id,
                TurnState.CONFIRMED, TurnState.APPLIED_TO_BRANCH,
                "state_projected", operation_id,
            )
            self._write_operation_phase(
                operation_id,
                ConfirmOperationPhase.APPLIED_TRANSITION_APPENDED,
                scope,
                turn_id,
                result_fp,
                {
                    "event_sequence": event_sequence,
                    "branch_state_revision": branch_state_revision,
                },
            )
            current_phase = ConfirmOperationPhase.APPLIED_TRANSITION_APPENDED

        if current_phase == ConfirmOperationPhase.APPLIED_TRANSITION_APPENDED:
            self._write_operation_phase(
                operation_id,
                ConfirmOperationPhase.COMPLETED,
                scope,
                turn_id,
                result_fp,
                {
                    "event_sequence": event_sequence,
                    "branch_state_revision": branch_state_revision,
                },
            )
            current_phase = ConfirmOperationPhase.COMPLETED

        return ConfirmResult(
            result=result,
            idempotent_replay=True,
            recovery_performed=recovery_performed,
            branch_state_revision=branch_state_revision or "",
            final_phase=current_phase,
        )
