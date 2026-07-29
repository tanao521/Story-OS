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
import time
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

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
    branch_state_content_revision,
    context_fingerprint_for,
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
        resolved_base = os.path.normcase(os.path.abspath(str(base.resolve())))
        resolved_target = os.path.normcase(os.path.abspath(str(target.resolve())))
    except OSError as exc:
        raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, "Path resolution failed") from exc
    if resolved_base.startswith("\\\\?\\"):
        resolved_base = resolved_base[4:]
    if resolved_target.startswith("\\\\?\\"):
        resolved_target = resolved_target[4:]
    try:
        contained = os.path.commonpath((resolved_base, resolved_target)) == resolved_base
    except ValueError:
        contained = False
    if not contained:
        raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, "Path traversal detected")


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


def _state_content_revision(state: dict[str, Any]) -> str:
    """Compatibility alias for the Binder's canonical revision authority."""
    return branch_state_content_revision(state)


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

    def __init__(
        self,
        project_context: ProjectContext,
        *,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self._project_root = project_context.data_dir
        project_id = project_context.root.name
        _validate_path_component(project_id, "project_id")
        self._project_id = project_id
        self._turn_store = NarrativeTurnStore(project_context)
        self._context_binder = NarrativeTurnContextBinder(project_context)
        self._project_context = project_context
        self._fault_injector = fault_injector

    def _fault(self, point: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(point)

    def _branch_events_path(self, scope: NarrativeScope) -> Path:
        _validate_path_component(scope.timeline_id, "timeline_id")
        _validate_path_component(scope.branch_id, "branch_id")
        path = self._project_root / "narrative_turn" / "events" / scope.timeline_id / scope.branch_id
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
        path = self._project_root / "narrative_turn" / "operations" / f"{operation_id}.phase.json"
        _validate_path_containment(self._project_root, path)
        return path

    def _operation_authority_path(self, operation_id: str) -> Path:
        _validate_path_component(operation_id, "operation_id")
        path = self._project_root / "narrative_turn" / "operations" / f"{operation_id}.json"
        _validate_path_containment(self._project_root, path)
        return path

    def _claim_operation(
        self,
        operation_id: str,
        scope: NarrativeScope,
        request_fingerprint: str,
    ) -> None:
        path = self._operation_authority_path(operation_id)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "operation_id": operation_id,
            "scope": {
                "project_id": scope.project_id,
                "timeline_id": scope.timeline_id,
                "branch_id": scope.branch_id,
            },
            "request_fingerprint": request_fingerprint,
        }
        try:
            _publish_immutable_json(path, payload)
        except NarrativeTurnError as exc:
            if exc.code != NarrativeTurnError.IMMUTABLE_RECORD_EXISTS:
                raise
            existing = _load_json(path)
            if existing != payload:
                raise NarrativeTurnError(
                    NarrativeTurnError.OPERATION_COLLISION,
                    "Operation ID is already bound to a different request or scope",
                ) from exc

    def _lock_path(self, lock_kind: str, lock_key: str) -> Path:
        digest = sha256(lock_key.encode("utf-8")).hexdigest()
        path = self._project_root / "narrative_turn" / ".locks" / f"{lock_kind}-{digest}.lock"
        _validate_path_containment(self._project_root, path)
        return path

    @contextmanager
    def _exclusive_lock(self, lock_kind: str, lock_key: str, timeout: float = 15.0):
        """Cross-service/process arbitration using atomic directory creation."""
        lock_path = self._lock_path(lock_kind, lock_key)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + timeout
        while True:
            try:
                lock_path.mkdir()
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise NarrativeTurnError(
                        NarrativeTurnError.CONFIRM_RECOVERY_REQUIRED,
                        "Timed out waiting for confirmation arbitration",
                    )
                time.sleep(0.01)
        try:
            yield
        finally:
            try:
                lock_path.rmdir()
            except OSError:
                pass

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
        existing = self._read_operation_phase(operation_id)
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
        if existing is not None:
            for preserved_key in ("request_fingerprint", "recovery_bundle"):
                if preserved_key in existing:
                    payload[preserved_key] = existing[preserved_key]
        if extra:
            payload.update(extra)
        _atomic_write_json(path, payload)

    @staticmethod
    def _validation_payload(validation: NarrativeActionValidation) -> dict[str, Any]:
        return {
            "schema_version": validation.schema_version,
            "validation_id": validation.validation_id,
            "turn_id": validation.turn_id,
            "project_id": validation.scope.project_id,
            "timeline_id": validation.scope.timeline_id,
            "branch_id": validation.scope.branch_id,
            "chapter_id": validation.chapter_id,
            "action_source": validation.action_source.value,
            "selected_action_id": validation.selected_action_id,
            "custom_action_text_hash": validation.custom_action_text_hash,
            "status": validation.status.value,
            "blocking_reasons": list(validation.blocking_reasons),
            "cost_explanation": [list(pair) for pair in validation.cost_explanation],
            "risk_explanation": [list(pair) for pair in validation.risk_explanation],
            "checked_at": validation.checked_at,
            "context_fingerprint": validation.context_fingerprint,
            "fingerprint": validation.fingerprint(),
        }

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
        lock_key = f"{scope.project_id}:{scope.timeline_id}:{scope.branch_id}"
        with self._exclusive_lock("branch-event", lock_key):
            return self._append_branch_event_unlocked(
                scope, turn_id, result_fingerprint, operation_id
            )

    def _append_branch_event_unlocked(
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
        applied_at: str | None = None,
    ) -> str:
        lock_key = f"{scope.project_id}:{scope.timeline_id}:{scope.branch_id}"
        with self._exclusive_lock("branch-state", lock_key):
            current_revision, current_state = self._read_branch_state(scope)
            if (
                current_state is not None
                and current_state.get("schema_version") == SCHEMA_VERSION
                and isinstance(current_state.get("applied_result_fingerprints"), list)
                and current_revision is not None
                and current_revision != _state_content_revision(current_state)
            ):
                raise NarrativeTurnError(
                    NarrativeTurnError.BRANCH_OPERATION_STALE_REVISION,
                    "Branch state revision integrity check failed",
                )
            return self._project_state_unlocked(
                scope,
                turn_id,
                event_sequence,
                result_fingerprint,
                state_delta_proposal,
                current_revision,
                applied_at or now_utc(),
            )

    def _project_state_unlocked(
        self,
        scope: NarrativeScope,
        turn_id: str,
        event_sequence: int,
        result_fingerprint: str,
        state_delta_proposal: tuple[tuple[str, Any], ...],
        expected_revision: str | None,
        applied_at: str,
    ) -> str:
        state_path = self._branch_state_path(scope)
        state_path.parent.mkdir(parents=True, exist_ok=True)

        current_rev, current_state = self._read_branch_state(scope)

        if current_state is not None:
            if (
                current_state.get("schema_version") == SCHEMA_VERSION
                and isinstance(current_state.get("applied_result_fingerprints"), list)
                and current_rev != _state_content_revision(current_state)
            ):
                raise NarrativeTurnError(
                    NarrativeTurnError.CONFIRM_RECOVERY_REQUIRED,
                    "Branch state revision integrity check failed",
                )
            applied = current_state.get("applied_result_fingerprints", [])
            if isinstance(applied, list) and result_fingerprint in applied:
                return str(current_state.get("revision") or current_rev or "")

        if current_rev != expected_revision:
            raise NarrativeTurnError(
                NarrativeTurnError.BRANCH_OPERATION_STALE_REVISION,
                "Branch state revision conflict",
            )

        new_state = self._apply_state_delta(current_state, state_delta_proposal)

        new_state.pop("revision", None)
        new_state["schema_version"] = SCHEMA_VERSION
        new_state["project_id"] = scope.project_id
        new_state["timeline_id"] = scope.timeline_id
        new_state["branch_id"] = scope.branch_id
        new_state["last_applied_turn_id"] = turn_id
        new_state["last_event_sequence"] = event_sequence
        new_state["last_result_fingerprint"] = result_fingerprint
        prior_applied = current_state.get("applied_result_fingerprints", []) if current_state else []
        applied_fingerprints = list(prior_applied) if isinstance(prior_applied, list) else []
        if result_fingerprint not in applied_fingerprints:
            applied_fingerprints.append(result_fingerprint)
        new_state["applied_result_fingerprints"] = applied_fingerprints
        new_state["updated_at"] = applied_at

        new_revision = _state_content_revision(new_state)
        new_state["revision"] = new_revision

        backup_path = state_path.with_suffix(".bak")
        try:
            self._fault("before_projection_replace")
            if state_path.exists():
                os.replace(str(state_path), str(backup_path))
            _atomic_write_json(state_path, new_state)
            self._fault("after_projection_replace")
            return new_revision
        except NarrativeTurnError:
            if backup_path.exists():
                try:
                    os.replace(str(backup_path), str(state_path))
                except OSError:
                    pass
            raise

    def _append_event_and_project(
        self,
        scope: NarrativeScope,
        result: NarrativeTurnResult,
        result_fingerprint: str,
        operation_id: str,
        *,
        inject_faults: bool,
    ) -> tuple[dict[str, Any], str]:
        """Serialize branch event allocation and state application as one unit."""
        lock_key = f"{scope.project_id}:{scope.timeline_id}:{scope.branch_id}"
        with self._exclusive_lock("branch-transaction", lock_key):
            event = self._append_branch_event_unlocked(
                scope, result.turn_id, result_fingerprint, operation_id
            )
            if inject_faults:
                self._fault("after_branch_event_append")
            current_revision, _ = self._read_branch_state(scope)
            revision = self._project_state_unlocked(
                scope,
                result.turn_id,
                event["sequence"],
                result_fingerprint,
                result.state_delta_proposal,
                current_revision,
                result.confirmed_at,
            )
            return event, revision

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
        projected_state = self._apply_state_delta(snapshot.narrative_state_dict(), state_delta_proposal)
        projected_state["schema_version"] = SCHEMA_VERSION
        projected_state["project_id"] = plan.scope.project_id
        projected_state["timeline_id"] = plan.scope.timeline_id
        projected_state["branch_id"] = plan.scope.branch_id
        projected_revision = _state_content_revision(projected_state)
        next_context_fingerprint = context_fingerprint_for(
            snapshot, branch_state_revision=projected_revision
        )

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
                refreshed = self._turn_store.get_transitions(scope, turn_id)
                if refreshed:
                    winner = refreshed[-1]
                    if (
                        winner.from_state == from_state
                        and winner.to_state == to_state
                        and winner.reason_code == reason_code
                        and winner.operation_id == operation_id
                    ):
                        return False
                raise NarrativeTurnError(
                    NarrativeTurnError.CONFIRM_RECOVERY_REQUIRED,
                    "Transition sequence was claimed by a different semantic transition",
                ) from exc
            raise

    def _restore_turn_chain(
        self,
        scope: NarrativeScope,
        turn_id: str,
        operation_id: str,
        phase_record: dict[str, Any],
    ) -> bool:
        """Verify durable Plan/Validation/transitions and safely fill omissions."""
        repaired = False
        bundle = phase_record.get("recovery_bundle")
        if not isinstance(bundle, dict):
            raise NarrativeTurnError(
                NarrativeTurnError.CONFIRM_RECOVERY_REQUIRED,
                "Recovery bundle is missing",
            )
        plan_payload = bundle.get("plan")
        validation_payload = bundle.get("validation")
        if not isinstance(plan_payload, dict) or not isinstance(validation_payload, dict):
            raise NarrativeTurnError(
                NarrativeTurnError.CONFIRM_RECOVERY_REQUIRED,
                "Recovery bundle is incomplete",
            )
        expected_scope = (scope.project_id, scope.timeline_id, scope.branch_id)
        for payload in (plan_payload, validation_payload):
            actual_scope = (
                payload.get("project_id"),
                payload.get("timeline_id"),
                payload.get("branch_id"),
            )
            if actual_scope != expected_scope or payload.get("turn_id") != turn_id:
                raise NarrativeTurnError(
                    NarrativeTurnError.CONFIRM_RECOVERY_REQUIRED,
                    "Recovery bundle scope or turn mismatch",
                )

        plan = self._turn_store.get_plan(scope, turn_id)
        if plan is None:
            plan_path = self._turn_store._plans_path(scope) / f"{turn_id}.json"
            _publish_immutable_json(plan_path, plan_payload)
            repaired = True

        validation_id = validation_payload.get("validation_id")
        if not isinstance(validation_id, str):
            raise NarrativeTurnError(
                NarrativeTurnError.CONFIRM_RECOVERY_REQUIRED,
                "Recovery validation ID is invalid",
            )
        validation = self._turn_store.get_validation(scope, validation_id)
        if validation is None:
            validation_path = self._turn_store._validations_path(scope) / f"{validation_id}.json"
            _publish_immutable_json(validation_path, validation_payload)
            repaired = True

        transitions = (
            (TurnState.PLANNED, TurnState.AWAITING_ACTION, "plan_published"),
            (TurnState.AWAITING_ACTION, TurnState.VALIDATING, "action_selected"),
            (TurnState.VALIDATING, TurnState.VALIDATED, "validation_passed"),
            (TurnState.VALIDATED, TurnState.PREVIEWED, "preview_generated"),
            (TurnState.PREVIEWED, TurnState.CONFIRMED, "user_confirmed"),
        )
        state_order = {
            TurnState.PLANNED: 0,
            TurnState.AWAITING_ACTION: 1,
            TurnState.VALIDATING: 2,
            TurnState.VALIDATED: 3,
            TurnState.PREVIEWED: 4,
            TurnState.CONFIRMED: 5,
            TurnState.APPLIED_TO_BRANCH: 6,
        }
        for from_state, to_state, reason in transitions:
            current = self._turn_store.get_current_state(scope, turn_id)
            if state_order[current] >= state_order[to_state]:
                continue
            changed = self._append_transition_safe(
                scope, turn_id, from_state, to_state, reason, operation_id
            )
            repaired = changed or repaired
        return repaired

    def confirm_turn(
        self,
        **kwargs: Any,
    ) -> ConfirmResult:
        operation_id = kwargs.get("operation_id")
        scope = kwargs.get("scope")
        chapter_id = kwargs.get("chapter_id")
        if not isinstance(operation_id, str):
            raise NarrativeTurnError(NarrativeTurnError.INVALID_ID, "Invalid operation_id")
        if not isinstance(scope, NarrativeScope):
            raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, "Invalid scope")
        if type(chapter_id) is not int or chapter_id <= 0:
            raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, "Invalid chapter_id")
        lock_key = f"{scope.project_id}:{operation_id}"
        initial_key = f"{scope.project_id}:{scope.timeline_id}:{scope.branch_id}:{chapter_id}"
        with self._exclusive_lock("initial-turn", initial_key), self._exclusive_lock("operation", lock_key):
            return self._confirm_turn_unlocked(**kwargs)

    def _confirm_turn_unlocked(
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
        request_custom_hash: str | None = None
        if action_source == "custom" and isinstance(custom_action_text, str):
            request_custom_hash = normalize_custom_action(custom_action_text).text_hash
        request_fingerprint = _stable_fingerprint(
            {
                "project_id": scope.project_id,
                "timeline_id": scope.timeline_id,
                "branch_id": scope.branch_id,
                "chapter_id": chapter_id,
                "source_version_id": source_version_id,
                "expected_context_fingerprint": expected_context_fingerprint,
                "expected_turn_id": expected_turn_id,
                "expected_validation_id": expected_validation_id,
                "expected_preview_fingerprint": expected_preview_fingerprint,
                "action_source": action_source,
                "selected_action_id": selected_action_id,
                "custom_action_text_hash": request_custom_hash,
            }
        )
        self._claim_operation(operation_id, scope, request_fingerprint)

        custom_raw_text: str | None = None
        try:
            existing_phase = self._read_operation_phase(operation_id)

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

            # The component-local initial-turn lock serializes the two
            # prechecks.  A losing writer can therefore observe the winner's
            # projected state before it reaches immutable-result arbitration.
            # Preserve the established first-writer contract by recognizing
            # that durable fact before deriving/validating the next plan.
            last_turn_id = snapshot.narrative_state_dict().get("last_turn_id")
            if isinstance(last_turn_id, str):
                confirmed_result = self._turn_store.get_result(scope, last_turn_id)
                if (
                    confirmed_result is not None
                    and confirmed_result.chapter_id == chapter_id
                    and confirmed_result.operation_id != operation_id
                ):
                    raise NarrativeTurnError(
                        NarrativeTurnError.TURN_ALREADY_CONFIRMED,
                        "Turn already confirmed by a different operation",
                    )

            if expected_context_fingerprint is not None and expected_context_fingerprint != snapshot.context_fingerprint:
                raise NarrativeTurnError(
                    NarrativeTurnError.CONTEXT_STALE,
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
                    NarrativeTurnError.VALIDATION_STALE,
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

            if expected_preview_fingerprint is not None:
                if preview is None or expected_preview_fingerprint != preview.preview_fingerprint:
                    raise NarrativeTurnError(
                        NarrativeTurnError.PREVIEW_STALE,
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
                {
                    "request_fingerprint": request_fingerprint,
                    "recovery_bundle": {
                        "plan": self._turn_store._plan_payload(plan),
                        "validation": self._validation_payload(validation),
                    },
                },
            )

            try:
                self._turn_store.append_result(result)
                self._fault("after_result_publish")
            except NarrativeTurnError as exc:
                if exc.code == NarrativeTurnError.INVALID_FIELD:
                    existing_result = self._turn_store.get_result(scope, plan.turn_id)
                    if existing_result is not None:
                        if existing_result.operation_id != operation_id:
                            raise NarrativeTurnError(
                                NarrativeTurnError.TURN_ALREADY_CONFIRMED,
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
                self._fault("after_plan_append")
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
                self._fault("after_validation_append")
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
            self._fault("after_previewed_transition")

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
            self._fault("after_confirmed_transition")

            self._write_operation_phase(
                operation_id,
                ConfirmOperationPhase.CONFIRMED_TRANSITION_APPENDED,
                scope,
                plan.turn_id,
                result_fp,
            )

            event, new_revision = self._append_event_and_project(
                scope,
                result,
                result_fp,
                operation_id,
                inject_faults=True,
            )
            event_sequence = event["sequence"]

            self._write_operation_phase(
                operation_id,
                ConfirmOperationPhase.BRANCH_EVENT_APPENDED,
                scope,
                plan.turn_id,
                result_fp,
                {"event_sequence": event_sequence},
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
            self._fault("after_applied_transition")

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

            self._fault("before_completed_marker")
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

        repaired = self._restore_turn_chain(
            scope, turn_id, operation_id, phase_record
        )

        matching_events = [
            event
            for event in self._read_branch_events(scope)
            if event.get("operation_id") == operation_id
            and event.get("turn_id") == turn_id
            and event.get("result_fingerprint") == result_fp
        ]
        if len(matching_events) > 1:
            raise NarrativeTurnError(
                NarrativeTurnError.CONFIRM_RECOVERY_REQUIRED,
                "Duplicate branch events found during recovery",
            )
        had_event = bool(matching_events)
        current_state_rev, current_state = self._read_branch_state(scope)
        applied = (
            current_state.get("applied_result_fingerprints", [])
            if isinstance(current_state, dict)
            else []
        )
        had_projection = isinstance(applied, list) and result_fp in applied
        event, branch_state_revision = self._append_event_and_project(
            scope,
            result,
            result_fp,
            operation_id,
            inject_faults=False,
        )
        repaired = repaired or not had_event or not had_projection
        event_sequence = event["sequence"]
        self._write_operation_phase(
            operation_id,
            ConfirmOperationPhase.BRANCH_EVENT_APPENDED,
            scope,
            turn_id,
            result_fp,
            {"event_sequence": event_sequence},
        )

        self._write_operation_phase(
            operation_id,
            ConfirmOperationPhase.STATE_PROJECTED,
            scope,
            turn_id,
            result_fp,
            {
                "event_sequence": event_sequence,
                "branch_state_revision": branch_state_revision,
            },
        )

        current_turn_state = self._turn_store.get_current_state(scope, turn_id)
        if current_turn_state == TurnState.CONFIRMED:
            changed = self._append_transition_safe(
                scope,
                turn_id,
                TurnState.CONFIRMED,
                TurnState.APPLIED_TO_BRANCH,
                "state_projected",
                operation_id,
            )
            repaired = changed or repaired
        elif current_turn_state != TurnState.APPLIED_TO_BRANCH:
            raise NarrativeTurnError(
                NarrativeTurnError.CONFIRM_RECOVERY_REQUIRED,
                "Transition chain is not recoverable",
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

        return ConfirmResult(
            result=result,
            idempotent_replay=True,
            recovery_performed=repaired or current_phase != ConfirmOperationPhase.COMPLETED,
            branch_state_revision=branch_state_revision,
            final_phase=ConfirmOperationPhase.COMPLETED,
        )
