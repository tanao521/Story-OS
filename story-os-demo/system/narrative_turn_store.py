"""Append-only store for Narrative Turn records and transition journal.

Phase 0D4-A-FIX-RC: separates immutable publication from mutable projection,
adds transition sequence ordering, and project-root operation authority.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from core.contracts.narrative_turn import (
    ActionSource,
    ActionType,
    NarrativeActionOption,
    NarrativeActionValidation,
    NarrativeCustomActionPolicy,
    NarrativeTurnError,
    NarrativeTurnPlan,
    NarrativeTurnResult,
    NarrativeTurnTransition,
    NarrativeScope,
    ResultStatus,
    TurnState,
    ValidationStatus,
    new_id,
    now_utc,
)
from core.project_context import ProjectContext


_PATH_COMPONENT_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_path_component(value: str, component_name: str) -> None:
    if not isinstance(value, str) or _PATH_COMPONENT_PATTERN.fullmatch(value) is None:
        raise NarrativeTurnError(NarrativeTurnError.INVALID_ID, f"Invalid {component_name}: {value!r}")


def _validate_path_containment(base: Path, target: Path) -> None:
    """Reject path traversal using resolve() (not string prefix checks)."""
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
    """Atomic create-if-absent publication for immutable records.

    Semantics:
    - Target absent: atomically create (tempfile + fsync + os.link).
    - Target present with identical content: idempotent success (no write).
    - Target present with different content: IMMUTABLE_RECORD_EXISTS collision.
    - Any OSError (fsync failure, link failure, permission): fail-closed.
    - Never overwrites an existing target.
    - Never leaves a partial target.
    - Temp file is in the same directory as the target (required for os.link).
    - Temp file is always cleaned up in finally.

    Platform durability note: on Windows NTFS, directory entry persistence
    after file fsync is not guaranteed; callers that require cross-process
    durability must additionally fsync the parent directory (not done here
    because the journal is rebuildable from append-only events and the
    authoritative event log).
    """
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
            # Write/fsync failure: fail-closed. No target file is created
            # because os.link is never reached. Temp file is cleaned up in
            # finally.
            raise NarrativeTurnError(
                NarrativeTurnError.INVALID_FIELD,
                f"Atomic immutable publication failed during write/fsync: {exc}",
            ) from exc
        try:
            os.link(str(temp_path), str(target_path))
        except FileExistsError:
            # Target exists. Determine idempotent replay vs. collision.
            try:
                existing_text = target_path.read_text(encoding="utf-8")
            except OSError as exc:
                raise NarrativeTurnError(
                    NarrativeTurnError.INVALID_FIELD,
                    "Failed to read existing immutable record",
                ) from exc
            if existing_text == payload_text:
                # Idempotent replay — successful no-op.
                return
            raise NarrativeTurnError(
                NarrativeTurnError.IMMUTABLE_RECORD_EXISTS,
                f"Immutable record already exists with different content: {target_path.name}",
            )
        except OSError as exc:
            # os.link failed for a non-FileExists reason (permissions, media,
            # unsupported platform). Fail closed — never fall back to write.
            raise NarrativeTurnError(
                NarrativeTurnError.INVALID_FIELD,
                f"Atomic immutable publication failed: {exc}",
            ) from exc
    finally:
        # ALWAYS clean up the temp file. On a successful os.link, the temp
        # name and the target name are two directory entries for the same
        # inode; deleting the temp name does not affect the target. On
        # failure or idempotent replay, the temp file is orphaned and must
        # be removed to avoid polluting the record directory.
        try:
            temp_path.unlink()
        except OSError:
            pass


def _atomic_write_json(target_path: Path, data: dict[str, Any]) -> None:
    """Atomic replace for mutable projections ONLY (registry snapshot, head cache).

    Never use this for immutable records. Immutable records must use
    ``_publish_immutable_json`` so that create-if-absent semantics are
    enforced and idempotent replay is detected.
    """
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


class NarrativeTurnStore:
    def __init__(self, project_context: ProjectContext) -> None:
        self._project_root = project_context.data_dir
        project_id = project_context.root.name
        _validate_path_component(project_id, "project_id")
        self._project_id = project_id

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------
    def _scope_base_path(self, scope: NarrativeScope) -> Path:
        _validate_path_component(scope.timeline_id, "timeline_id")
        _validate_path_component(scope.branch_id, "branch_id")
        path = self._project_root / "narrative_turns" / scope.timeline_id / scope.branch_id
        _validate_path_containment(self._project_root, path)
        return path

    def _plans_path(self, scope: NarrativeScope) -> Path:
        return self._scope_base_path(scope) / "plans"

    def _validations_path(self, scope: NarrativeScope) -> Path:
        return self._scope_base_path(scope) / "validations"

    def _results_path(self, scope: NarrativeScope) -> Path:
        return self._scope_base_path(scope) / "results"

    def _transitions_path(self, scope: NarrativeScope) -> Path:
        return self._scope_base_path(scope) / "transitions"

    def _scope_operations_path(self, scope: NarrativeScope) -> Path:
        """Branch-local operation index (NOT authoritative; rebuildable)."""
        return self._scope_base_path(scope) / "operations"

    def _operation_authority_path(self, operation_id: str) -> Path:
        """Project-root operation authority — authoritative for collision detection."""
        _validate_path_component(operation_id, "operation_id")
        path = self._project_root / "narrative_turn_operations" / f"{operation_id}.json"
        _validate_path_containment(self._project_root, path)
        return path

    # ------------------------------------------------------------------
    # Plan
    # ------------------------------------------------------------------
    def append_plan(self, plan: NarrativeTurnPlan) -> None:
        if plan.scope.project_id != self._project_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "project_id mismatch")
        plan_path = self._plans_path(plan.scope) / f"{plan.turn_id}.json"
        payload = self._plan_payload(plan)
        try:
            _publish_immutable_json(plan_path, payload)
        except NarrativeTurnError as exc:
            if exc.code == NarrativeTurnError.IMMUTABLE_RECORD_EXISTS:
                raise NarrativeTurnError(
                    NarrativeTurnError.INVALID_FIELD,
                    "Plan already exists",
                ) from exc
            raise

    def _plan_payload(self, plan: NarrativeTurnPlan) -> dict[str, Any]:
        return {
            "schema_version": plan.schema_version,
            "turn_id": plan.turn_id,
            "project_id": plan.scope.project_id,
            "timeline_id": plan.scope.timeline_id,
            "branch_id": plan.scope.branch_id,
            "chapter_id": plan.chapter_id,
            "source_version_id": plan.source_version_id,
            "parent_turn_id": plan.parent_turn_id,
            "context_fingerprint": plan.context_fingerprint,
            "planning_revision": plan.planning_revision,
            "canon_revision": plan.canon_revision,
            "created_at": plan.created_at,
            "recommended_actions": [
                {
                    "action_id": a.action_id,
                    "action_type": a.action_type.value,
                    "display_text": a.display_text,
                    "intent": a.intent,
                    "expected_costs": [list(pair) for pair in a.expected_costs],
                    "expected_risks": [list(pair) for pair in a.expected_risks],
                    "required_conditions": list(a.required_conditions),
                    "unavailable_reasons": list(a.unavailable_reasons),
                    "provenance": a.provenance,
                    "deterministic_order": a.deterministic_order,
                }
                for a in plan.recommended_actions
            ],
            "custom_action_policy": {
                "max_length": plan.custom_action_policy.max_length,
                "forbidden_patterns": list(plan.custom_action_policy.forbidden_patterns),
                "feasibility_pipeline": list(plan.custom_action_policy.feasibility_pipeline),
            },
            "fingerprint": plan.fingerprint(),
        }

    def get_plan(self, scope: NarrativeScope, turn_id: str) -> NarrativeTurnPlan | None:
        if scope.project_id != self._project_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "project_id mismatch")
        _validate_path_component(turn_id, "turn_id")
        plan_path = self._plans_path(scope) / f"{turn_id}.json"
        if not plan_path.exists():
            return None
        data = _load_json(plan_path)
        actions = []
        for a in data["recommended_actions"]:
            actions.append(NarrativeActionOption(
                action_id=a["action_id"],
                action_type=ActionType(a["action_type"]),
                display_text=a["display_text"],
                intent=a["intent"],
                expected_costs=tuple(tuple(pair) for pair in a["expected_costs"]),
                expected_risks=tuple(tuple(pair) for pair in a["expected_risks"]),
                required_conditions=tuple(a["required_conditions"]),
                unavailable_reasons=tuple(a["unavailable_reasons"]),
                provenance=a["provenance"],
                deterministic_order=a["deterministic_order"],
            ))
        return NarrativeTurnPlan(
            schema_version=data["schema_version"],
            turn_id=data["turn_id"],
            scope=NarrativeScope(
                project_id=data["project_id"],
                timeline_id=data["timeline_id"],
                branch_id=data["branch_id"],
            ),
            chapter_id=data["chapter_id"],
            source_version_id=data.get("source_version_id"),
            parent_turn_id=data.get("parent_turn_id"),
            context_fingerprint=data["context_fingerprint"],
            planning_revision=data["planning_revision"],
            canon_revision=data.get("canon_revision"),
            created_at=data["created_at"],
            recommended_actions=tuple(actions),
            custom_action_policy=NarrativeCustomActionPolicy(
                max_length=data["custom_action_policy"]["max_length"],
                forbidden_patterns=tuple(data["custom_action_policy"]["forbidden_patterns"]),
                feasibility_pipeline=tuple(data["custom_action_policy"]["feasibility_pipeline"]),
            ),
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def append_validation(self, validation: NarrativeActionValidation) -> None:
        if validation.scope.project_id != self._project_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "project_id mismatch")
        validation_path = self._validations_path(validation.scope) / f"{validation.validation_id}.json"
        payload = {
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
        try:
            _publish_immutable_json(validation_path, payload)
        except NarrativeTurnError as exc:
            if exc.code == NarrativeTurnError.IMMUTABLE_RECORD_EXISTS:
                raise NarrativeTurnError(
                    NarrativeTurnError.INVALID_FIELD,
                    "Validation already exists",
                ) from exc
            raise

    def get_validation(self, scope: NarrativeScope, validation_id: str) -> NarrativeActionValidation | None:
        if scope.project_id != self._project_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "project_id mismatch")
        _validate_path_component(validation_id, "validation_id")
        validation_path = self._validations_path(scope) / f"{validation_id}.json"
        if not validation_path.exists():
            return None
        data = _load_json(validation_path)
        return NarrativeActionValidation(
            schema_version=data["schema_version"],
            validation_id=data["validation_id"],
            turn_id=data["turn_id"],
            scope=NarrativeScope(
                project_id=data["project_id"],
                timeline_id=data["timeline_id"],
                branch_id=data["branch_id"],
            ),
            chapter_id=data["chapter_id"],
            action_source=ActionSource(data["action_source"]),
            selected_action_id=data.get("selected_action_id"),
            custom_action_text_hash=data.get("custom_action_text_hash"),
            status=ValidationStatus(data["status"]),
            blocking_reasons=tuple(data["blocking_reasons"]),
            cost_explanation=tuple(tuple(pair) for pair in data["cost_explanation"]),
            risk_explanation=tuple(tuple(pair) for pair in data["risk_explanation"]),
            checked_at=data["checked_at"],
            context_fingerprint=data["context_fingerprint"],
        )

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------
    def append_result(self, result: NarrativeTurnResult) -> None:
        if result.scope.project_id != self._project_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "project_id mismatch")
        result_path = self._results_path(result.scope) / f"{result.turn_id}.json"
        payload = {
            "schema_version": result.schema_version,
            "turn_id": result.turn_id,
            "project_id": result.scope.project_id,
            "timeline_id": result.scope.timeline_id,
            "branch_id": result.scope.branch_id,
            "chapter_id": result.chapter_id,
            "selected_action_id": result.selected_action_id,
            "custom_action_text_hash": result.custom_action_text_hash,
            "result_status": result.result_status.value,
            "event_summary": result.event_summary,
            "state_delta_proposal": [list(pair) for pair in result.state_delta_proposal],
            "consequence_flags": list(result.consequence_flags),
            "next_context_fingerprint": result.next_context_fingerprint,
            "execution_revision": result.execution_revision,
            "source_fingerprint": result.source_fingerprint,
            "confirmed_at": result.confirmed_at,
            "operation_id": result.operation_id,
            "fingerprint": result.fingerprint(),
        }
        try:
            _publish_immutable_json(result_path, payload)
        except NarrativeTurnError as exc:
            if exc.code == NarrativeTurnError.IMMUTABLE_RECORD_EXISTS:
                raise NarrativeTurnError(
                    NarrativeTurnError.INVALID_FIELD,
                    "Result already exists",
                ) from exc
            raise

    def get_result(self, scope: NarrativeScope, turn_id: str) -> NarrativeTurnResult | None:
        if scope.project_id != self._project_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "project_id mismatch")
        _validate_path_component(turn_id, "turn_id")
        result_path = self._results_path(scope) / f"{turn_id}.json"
        if not result_path.exists():
            return None
        data = _load_json(result_path)
        return NarrativeTurnResult(
            schema_version=data["schema_version"],
            turn_id=data["turn_id"],
            scope=NarrativeScope(
                project_id=data["project_id"],
                timeline_id=data["timeline_id"],
                branch_id=data["branch_id"],
            ),
            chapter_id=data["chapter_id"],
            selected_action_id=data.get("selected_action_id"),
            custom_action_text_hash=data.get("custom_action_text_hash"),
            result_status=ResultStatus(data["result_status"]),
            event_summary=data["event_summary"],
            state_delta_proposal=tuple(tuple(pair) for pair in data["state_delta_proposal"]),
            consequence_flags=tuple(data["consequence_flags"]),
            next_context_fingerprint=data["next_context_fingerprint"],
            execution_revision=data["execution_revision"],
            source_fingerprint=data["source_fingerprint"],
            confirmed_at=data["confirmed_at"],
            operation_id=data["operation_id"],
        )

    # ------------------------------------------------------------------
    # Transition journal (sequence-ordered, append-only)
    # ------------------------------------------------------------------
    def append_transition(self, transition: NarrativeTurnTransition) -> None:
        if transition.scope.project_id != self._project_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "project_id mismatch")

        # Read the existing journal once for idempotency and sequence validation.
        existing = self.get_transitions(transition.scope, transition.turn_id)

        # Idempotent replay check — same transition_id with identical content
        # is a no-op; same transition_id with different content is a collision.
        for existing_trans in existing:
            if existing_trans.transition_id == transition.transition_id:
                if existing_trans.fingerprint() == transition.fingerprint():
                    return
                raise NarrativeTurnError(
                    NarrativeTurnError.TRANSITION_COLLISION,
                    f"Transition {transition.transition_id} already exists with different content",
                )

        # Validate deterministic sequence ordering against the existing journal.
        expected_sequence = len(existing)
        if transition.sequence != expected_sequence:
            raise NarrativeTurnError(
                NarrativeTurnError.TRANSITION_SEQUENCE_COLLISION,
                f"Transition sequence collision: expected {expected_sequence}, got {transition.sequence}",
            )
        if existing:
            last = existing[-1]
            if transition.previous_transition_id != last.transition_id:
                raise NarrativeTurnError(
                    NarrativeTurnError.TRANSITION_PREVIOUS_MISMATCH,
                    "previous_transition_id does not match the last transition",
                )
            if transition.previous_transition_fingerprint != last.record_fingerprint:
                raise NarrativeTurnError(
                    NarrativeTurnError.TRANSITION_PREVIOUS_MISMATCH,
                    "previous_transition_fingerprint does not match the last transition",
                )
            # Stale from_state check — must equal the last transition's to_state.
            if transition.from_state != last.to_state:
                raise NarrativeTurnError(
                    NarrativeTurnError.TRANSITION_STALE_FROM_STATE,
                    "from_state does not match the current journal head",
                )
        else:
            if transition.previous_transition_id is not None:
                raise NarrativeTurnError(
                    NarrativeTurnError.TRANSITION_PREVIOUS_MISMATCH,
                    "first transition must have previous_transition_id=None",
                )
            if transition.previous_transition_fingerprint is not None:
                raise NarrativeTurnError(
                    NarrativeTurnError.TRANSITION_PREVIOUS_MISMATCH,
                    "first transition must have previous_transition_fingerprint=None",
                )

        transitions_dir = self._transitions_path(transition.scope) / transition.turn_id
        transitions_dir.mkdir(parents=True, exist_ok=True)
        # Sequence-only filename ensures concurrent first-wins: two threads
        # racing to append at the same sequence collide on the same path,
        # and _publish_immutable_json atomically resolves idempotent vs. collision.
        transition_path = transitions_dir / f"{transition.sequence:08d}.json"
        payload = {
            "schema_version": transition.schema_version,
            "transition_id": transition.transition_id,
            "turn_id": transition.turn_id,
            "project_id": transition.scope.project_id,
            "timeline_id": transition.scope.timeline_id,
            "branch_id": transition.scope.branch_id,
            "from_state": transition.from_state.value,
            "to_state": transition.to_state.value,
            "reason_code": transition.reason_code,
            "operation_id": transition.operation_id,
            "occurred_at": transition.occurred_at,
            "record_fingerprint": transition.record_fingerprint,
            "sequence": transition.sequence,
            "previous_transition_id": transition.previous_transition_id,
            "previous_transition_fingerprint": transition.previous_transition_fingerprint,
            "fingerprint": transition.fingerprint(),
        }
        try:
            _publish_immutable_json(transition_path, payload)
        except NarrativeTurnError as exc:
            if exc.code == NarrativeTurnError.IMMUTABLE_RECORD_EXISTS:
                # Another concurrent writer won this sequence slot with
                # different content. Surface as a transition collision so the
                # caller knows to re-read the journal and retry.
                raise NarrativeTurnError(
                    NarrativeTurnError.TRANSITION_COLLISION,
                    "Concurrent transition write won this sequence slot",
                ) from exc
            raise

    def get_transitions(self, scope: NarrativeScope, turn_id: str) -> list[NarrativeTurnTransition]:
        if scope.project_id != self._project_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "project_id mismatch")
        _validate_path_component(turn_id, "turn_id")
        transitions_path = self._transitions_path(scope) / turn_id
        if not transitions_path.exists():
            return []
        records: list[dict[str, Any]] = []
        for entry in sorted(transitions_path.iterdir()):
            if entry.suffix != ".json":
                continue
            data = _load_json(entry)
            records.append(data)
        # Deterministic ordering by sequence (NOT occurred_at).
        records.sort(key=lambda r: r["sequence"])
        # Verify chain integrity on read — fail-closed on any break.
        previous_id: str | None = None
        previous_fp: str | None = None
        expected_seq = 0
        for record in records:
            if record["sequence"] != expected_seq:
                raise NarrativeTurnError(
                    NarrativeTurnError.TRANSITION_SEQUENCE_COLLISION,
                    f"Journal sequence gap/duplicate at {expected_seq}",
                )
            if record.get("previous_transition_id") != previous_id:
                raise NarrativeTurnError(
                    NarrativeTurnError.TRANSITION_PREVIOUS_MISMATCH,
                    "Journal previous_transition_id chain broken",
                )
            if record.get("previous_transition_fingerprint") != previous_fp:
                raise NarrativeTurnError(
                    NarrativeTurnError.TRANSITION_PREVIOUS_MISMATCH,
                    "Journal previous_transition_fingerprint chain broken",
                )
            previous_id = record["transition_id"]
            previous_fp = record["record_fingerprint"]
            expected_seq += 1
        return [
            NarrativeTurnTransition(
                schema_version=r["schema_version"],
                transition_id=r["transition_id"],
                turn_id=r["turn_id"],
                scope=NarrativeScope(
                    project_id=r["project_id"],
                    timeline_id=r["timeline_id"],
                    branch_id=r["branch_id"],
                ),
                from_state=TurnState(r["from_state"]),
                to_state=TurnState(r["to_state"]),
                reason_code=r["reason_code"],
                operation_id=r.get("operation_id"),
                occurred_at=r["occurred_at"],
                record_fingerprint=r["record_fingerprint"],
                sequence=r["sequence"],
                previous_transition_id=r.get("previous_transition_id"),
                previous_transition_fingerprint=r.get("previous_transition_fingerprint"),
            )
            for r in records
        ]

    def get_current_state(self, scope: NarrativeScope, turn_id: str) -> TurnState:
        transitions = self.get_transitions(scope, turn_id)
        if not transitions:
            return TurnState.PLANNED
        return transitions[-1].to_state

    def list_plans(self, scope: NarrativeScope) -> list[str]:
        if scope.project_id != self._project_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "project_id mismatch")
        plans_path = self._plans_path(scope)
        if not plans_path.exists():
            return []
        return sorted(entry.stem for entry in plans_path.iterdir() if entry.suffix == ".json")

    # ------------------------------------------------------------------
    # Operation authority (project-root, cross-scope collision detection)
    # ------------------------------------------------------------------
    def record_operation(
        self,
        scope: NarrativeScope,
        operation_id: str,
        turn_id: str,
        record_type: str,
        record_fingerprint: str,
    ) -> None:
        """Record an operation at project-root authority.

        Collision rules (cross-branch / cross-timeline / cross-turn safe):
        - Same operation_id + identical scope/turn/type/fingerprint → idempotent replay.
        - Same operation_id + any differing binding field → OPERATION_COLLISION.
        - Project isolation is provided by ProjectContext root; project_id is
          still stored on the record and verified on read.
        """
        if scope.project_id != self._project_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "project_id mismatch")
        _validate_path_component(operation_id, "operation_id")
        _validate_path_component(turn_id, "turn_id")

        authority_path = self._operation_authority_path(operation_id)
        payload = {
            "operation_id": operation_id,
            "project_id": scope.project_id,
            "timeline_id": scope.timeline_id,
            "branch_id": scope.branch_id,
            "turn_id": turn_id,
            "operation_type": record_type,
            "payload_fingerprint": record_fingerprint,
            # Relative path only — never persist absolute paths.
            "result_record_path": f"narrative_turns/{scope.timeline_id}/{scope.branch_id}/{record_type}/{turn_id}.json",
            "created_at": now_utc(),
        }
        try:
            _publish_immutable_json(authority_path, payload)
        except NarrativeTurnError as exc:
            if exc.code != NarrativeTurnError.IMMUTABLE_RECORD_EXISTS:
                raise
            existing = _load_json(authority_path)
            if (
                existing.get("project_id") == payload["project_id"]
                and existing.get("timeline_id") == payload["timeline_id"]
                and existing.get("branch_id") == payload["branch_id"]
                and existing.get("turn_id") == payload["turn_id"]
                and existing.get("operation_type") == payload["operation_type"]
                and existing.get("payload_fingerprint") == payload["payload_fingerprint"]
            ):
                # Idempotent replay — success.
                return
            raise NarrativeTurnError(
                NarrativeTurnError.OPERATION_COLLISION,
                f"Operation collision: operation_id={operation_id} already bound to a different scope/turn/type/fingerprint",
            ) from exc

        # Also write a branch-local index entry for fast lookup. This index is
        # a mutable-derived projection (rebuildable from project-root authority)
        # so it uses _atomic_write_json and stores only relative paths.
        index_path = self._scope_operations_path(scope) / f"{operation_id}.json"
        index_payload = {
            "operation_id": operation_id,
            "turn_id": turn_id,
            "operation_type": record_type,
            "payload_fingerprint": record_fingerprint,
            "authority_path": f"narrative_turn_operations/{operation_id}.json",
            "recorded_at": now_utc(),
        }
        if not index_path.exists():
            _atomic_write_json(index_path, index_payload)

    def get_operation(self, scope: NarrativeScope, operation_id: str) -> dict[str, Any] | None:
        """Read from project-root authority (not the branch-local index)."""
        if scope.project_id != self._project_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "project_id mismatch")
        _validate_path_component(operation_id, "operation_id")
        authority_path = self._operation_authority_path(operation_id)
        if not authority_path.exists():
            return None
        record = _load_json(authority_path)
        # Verify the operation belongs to this scope (project_id is enforced
        # by directory isolation; timeline_id and branch_id are scope filters).
        if record.get("project_id") != scope.project_id:
            raise NarrativeTurnError(
                NarrativeTurnError.SCOPE_MISMATCH,
                "operation project_id does not match current scope",
            )
        return record
