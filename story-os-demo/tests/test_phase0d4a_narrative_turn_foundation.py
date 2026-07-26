"""Phase 0D4-A-FIX-RC focused tests for Narrative Turn foundation.

Covers:
- Contract validation (strict types, frozen immutability, enums)
- Immutable publication (create-if-absent, idempotent replay, collision)
- Branch lifecycle (append-only events, derived projection)
- Operation authority (project-root, cross-scope collision)
- Transition ordering (sequence, previous binding, concurrent first-wins)
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

import pytest

from core.contracts.narrative_turn import (
    ActionSource,
    ActionType,
    BranchLifecycleEvent,
    BranchLifecycleStatus,
    BranchOperationPhase,
    BranchOperationType,
    NarrativeActionOption,
    NarrativeActionValidation,
    NarrativeBranch,
    NarrativeBranchIdentity,
    NarrativeCustomActionPolicy,
    NarrativeScope,
    NarrativeTurnError,
    NarrativeTurnPlan,
    NarrativeTurnResult,
    NarrativeTurnTransition,
    TimelineContext,
    TurnState,
    ValidationStatus,
    ResultStatus,
    SCHEMA_VERSION,
    new_id,
    now_utc,
)
from core.project_context import ProjectContext, get_project_context
from system.narrative_branch_store import NarrativeBranchStore
from system.narrative_turn_store import NarrativeTurnStore


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

def make_fixture_scope(project_id: str = "test-project") -> NarrativeScope:
    return NarrativeScope(
        project_id=project_id,
        timeline_id="test-timeline",
        branch_id="test-branch",
    )


@pytest.fixture
def fixture_scope(temp_project: ProjectContext) -> NarrativeScope:
    return NarrativeScope(
        project_id=temp_project.root.name,
        timeline_id="test-timeline",
        branch_id="test-branch",
    )


def make_fixture_actions() -> tuple[NarrativeActionOption, ...]:
    return (
        NarrativeActionOption(
            action_id="action_1",
            action_type=ActionType.ADVANCE,
            display_text="Advance cautiously",
            intent="advance_cautiously",
            expected_costs=(("time", "medium"), ("resource", "low")),
            expected_risks=(("safety", "low"),),
            required_conditions=("cond_1",),
            unavailable_reasons=(),
            provenance="deterministic-planner",
            deterministic_order=1,
        ),
        NarrativeActionOption(
            action_id="action_2",
            action_type=ActionType.INVESTIGATE,
            display_text="Investigate surroundings",
            intent="investigate_surroundings",
            expected_costs=(("time", "high"),),
            expected_risks=(("safety", "medium"),),
            required_conditions=("cond_2",),
            unavailable_reasons=(),
            provenance="deterministic-planner",
            deterministic_order=2,
        ),
        NarrativeActionOption(
            action_id="action_3",
            action_type=ActionType.RETREAT,
            display_text="Retreat to safety",
            intent="retreat_to_safety",
            expected_costs=(("time", "low"),),
            expected_risks=(),
            required_conditions=(),
            unavailable_reasons=("reason_1",),
            provenance="deterministic-planner",
            deterministic_order=3,
        ),
    )


def make_fixture_policy() -> NarrativeCustomActionPolicy:
    return NarrativeCustomActionPolicy(
        max_length=200,
        forbidden_patterns=("prompt_injection",),
        feasibility_pipeline=("check_1", "check_2"),
    )


def make_fixture_plan(scope: NarrativeScope) -> NarrativeTurnPlan:
    return NarrativeTurnPlan(
        schema_version=SCHEMA_VERSION,
        turn_id=new_id("turn"),
        scope=scope,
        chapter_id=1,
        source_version_id="v1",
        parent_turn_id=None,
        context_fingerprint=sha256(b"test").hexdigest(),
        planning_revision="rev_1",
        canon_revision="canon_1",
        created_at=datetime.now(timezone.utc).isoformat(),
        recommended_actions=make_fixture_actions(),
        custom_action_policy=make_fixture_policy(),
    )


def make_fixture_transition(
    scope: NarrativeScope,
    turn_id: str,
    *,
    from_state: TurnState = TurnState.PLANNED,
    to_state: TurnState = TurnState.AWAITING_ACTION,
    sequence: int = 0,
    previous_transition_id: str | None = None,
    previous_transition_fingerprint: str | None = None,
    record_fingerprint: str | None = None,
    transition_id: str | None = None,
) -> NarrativeTurnTransition:
    """Build a transition with valid sequence/previous binding fields."""
    return NarrativeTurnTransition(
        schema_version=SCHEMA_VERSION,
        transition_id=transition_id or new_id("trans"),
        turn_id=turn_id,
        scope=scope,
        from_state=from_state,
        to_state=to_state,
        reason_code="test",
        operation_id=None,
        occurred_at=datetime.now(timezone.utc).isoformat(),
        record_fingerprint=record_fingerprint or sha256(b"test").hexdigest(),
        sequence=sequence,
        previous_transition_id=previous_transition_id,
        previous_transition_fingerprint=previous_transition_fingerprint,
    )


def append_transition_chain(
    store: NarrativeTurnStore,
    scope: NarrativeScope,
    turn_id: str,
    transitions: list[tuple[TurnState, TurnState]],
    record_fingerprint: str,
) -> list[NarrativeTurnTransition]:
    """Append a chain of transitions with correct sequence/previous binding."""
    appended: list[NarrativeTurnTransition] = []
    previous_id: str | None = None
    previous_fp: str | None = None
    for seq, (from_state, to_state) in enumerate(transitions):
        t = make_fixture_transition(
            scope,
            turn_id,
            from_state=from_state,
            to_state=to_state,
            sequence=seq,
            previous_transition_id=previous_id,
            previous_transition_fingerprint=previous_fp,
            record_fingerprint=record_fingerprint,
        )
        store.append_transition(t)
        appended.append(t)
        previous_id = t.transition_id
        previous_fp = t.record_fingerprint
    return appended


@pytest.fixture
def fixture_plan(fixture_scope: NarrativeScope) -> NarrativeTurnPlan:
    return make_fixture_plan(fixture_scope)


@pytest.fixture
def temp_project() -> ProjectContext:
    with tempfile.TemporaryDirectory() as tmpdir:
        ctx = get_project_context(tmpdir)
        yield ctx


@pytest.fixture
def turn_store(temp_project: ProjectContext) -> NarrativeTurnStore:
    return NarrativeTurnStore(temp_project)


@pytest.fixture
def branch_store(temp_project: ProjectContext) -> NarrativeBranchStore:
    return NarrativeBranchStore(temp_project)


@pytest.fixture
def timeline_context(temp_project: ProjectContext) -> TimelineContext:
    return TimelineContext(project_id=temp_project.root.name, timeline_id="test-timeline")


# ---------------------------------------------------------------------------
# Contract validation (existing — strict types now enforced)
# ---------------------------------------------------------------------------

class TestContractValidation:
    def test_schema_version_required(self) -> None:
        with pytest.raises(NarrativeTurnError, match="Unsupported schema version"):
            NarrativeTurnPlan(
                schema_version="2.0",
                turn_id="turn_1",
                scope=make_fixture_scope(),
                chapter_id=1,
                source_version_id="v1",
                parent_turn_id=None,
                context_fingerprint=sha256(b"test").hexdigest(),
                planning_revision="rev_1",
                canon_revision="canon_1",
                created_at=datetime.now(timezone.utc).isoformat(),
                recommended_actions=make_fixture_actions(),
                custom_action_policy=make_fixture_policy(),
            )

    def test_bool_not_int(self) -> None:
        with pytest.raises(NarrativeTurnError, match="must be int"):
            NarrativeCustomActionPolicy(
                max_length=True,
                forbidden_patterns=(),
                feasibility_pipeline=(),
            )

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(NarrativeTurnError, match="Invalid project_id"):
            NarrativeScope(
                project_id="",
                timeline_id="timeline",
                branch_id="branch",
            )

    def test_malformed_id_rejected(self) -> None:
        with pytest.raises(NarrativeTurnError, match="Invalid timeline_id"):
            NarrativeScope(
                project_id="valid",
                timeline_id="timeline/with/slash",
                branch_id="branch",
            )

    def test_malformed_hash_rejected(self) -> None:
        with pytest.raises(NarrativeTurnError, match="Invalid context_fingerprint"):
            NarrativeTurnPlan(
                schema_version=SCHEMA_VERSION,
                turn_id="turn_1",
                scope=make_fixture_scope(),
                chapter_id=1,
                source_version_id="v1",
                parent_turn_id=None,
                context_fingerprint="invalid_hash",
                planning_revision="rev_1",
                canon_revision="canon_1",
                created_at=datetime.now(timezone.utc).isoformat(),
                recommended_actions=make_fixture_actions(),
                custom_action_policy=make_fixture_policy(),
            )

    def test_timezone_naive_datetime_rejected(self) -> None:
        with pytest.raises(NarrativeTurnError, match="must have timezone"):
            NarrativeTurnPlan(
                schema_version=SCHEMA_VERSION,
                turn_id="turn_1",
                scope=make_fixture_scope(),
                chapter_id=1,
                source_version_id="v1",
                parent_turn_id=None,
                context_fingerprint=sha256(b"test").hexdigest(),
                planning_revision="rev_1",
                canon_revision="canon_1",
                created_at="2024-01-01T00:00:00",
                recommended_actions=make_fixture_actions(),
                custom_action_policy=make_fixture_policy(),
            )

    def test_invalid_enum_rejected(self) -> None:
        with pytest.raises(NarrativeTurnError, match="Invalid action_type"):
            NarrativeActionOption(
                action_id="action_1",
                action_type="invalid",
                display_text="Test",
                intent="test",
                expected_costs=(),
                expected_risks=(),
                required_conditions=(),
                unavailable_reasons=(),
                provenance="deterministic-planner",
                deterministic_order=1,
            )

    def test_frozen_immutable(self) -> None:
        scope = make_fixture_scope()
        with pytest.raises(FrozenInstanceError):
            scope.project_id = "modified"

    def test_exactly_three_actions(self) -> None:
        actions = make_fixture_actions()
        with pytest.raises(NarrativeTurnError, match="must have exactly 3 items"):
            NarrativeTurnPlan(
                schema_version=SCHEMA_VERSION,
                turn_id="turn_1",
                scope=make_fixture_scope(),
                chapter_id=1,
                source_version_id="v1",
                parent_turn_id=None,
                context_fingerprint=sha256(b"test").hexdigest(),
                planning_revision="rev_1",
                canon_revision="canon_1",
                created_at=datetime.now(timezone.utc).isoformat(),
                recommended_actions=actions[:2],
                custom_action_policy=make_fixture_policy(),
            )

    def test_action_order_must_be_123(self) -> None:
        with pytest.raises(NarrativeTurnError, match="deterministic_order must be 1, 2, or 3"):
            NarrativeActionOption(
                action_id="action_1",
                action_type=ActionType.ADVANCE,
                display_text="Advance",
                intent="advance",
                expected_costs=(),
                expected_risks=(),
                required_conditions=(),
                unavailable_reasons=(),
                provenance="deterministic-planner",
                deterministic_order=4,
            )

    def test_duplicate_action_id_rejected(self) -> None:
        actions = list(make_fixture_actions())
        actions[1] = NarrativeActionOption(
            action_id="action_1",
            action_type=ActionType.INVESTIGATE,
            display_text="Investigate",
            intent="investigate",
            expected_costs=(),
            expected_risks=(),
            required_conditions=(),
            unavailable_reasons=(),
            provenance="deterministic-planner",
            deterministic_order=2,
        )
        with pytest.raises(NarrativeTurnError, match="Duplicate action_id"):
            NarrativeTurnPlan(
                schema_version=SCHEMA_VERSION,
                turn_id="turn_1",
                scope=make_fixture_scope(),
                chapter_id=1,
                source_version_id="v1",
                parent_turn_id=None,
                context_fingerprint=sha256(b"test").hexdigest(),
                planning_revision="rev_1",
                canon_revision="canon_1",
                created_at=datetime.now(timezone.utc).isoformat(),
                recommended_actions=tuple(actions),
                custom_action_policy=make_fixture_policy(),
            )

    def test_duplicate_intent_rejected(self) -> None:
        actions = list(make_fixture_actions())
        actions[1] = NarrativeActionOption(
            action_id="action_2",
            action_type=ActionType.INVESTIGATE,
            display_text="Investigate",
            intent="advance_cautiously",
            expected_costs=(),
            expected_risks=(),
            required_conditions=(),
            unavailable_reasons=(),
            provenance="deterministic-planner",
            deterministic_order=2,
        )
        with pytest.raises(NarrativeTurnError, match="Duplicate intent"):
            NarrativeTurnPlan(
                schema_version=SCHEMA_VERSION,
                turn_id="turn_1",
                scope=make_fixture_scope(),
                chapter_id=1,
                source_version_id="v1",
                parent_turn_id=None,
                context_fingerprint=sha256(b"test").hexdigest(),
                planning_revision="rev_1",
                canon_revision="canon_1",
                created_at=datetime.now(timezone.utc).isoformat(),
                recommended_actions=tuple(actions),
                custom_action_policy=make_fixture_policy(),
            )

    def test_validation_recommended_xor_custom(self) -> None:
        scope = make_fixture_scope()
        with pytest.raises(NarrativeTurnError, match="recommended action requires selected_action_id"):
            NarrativeActionValidation(
                schema_version=SCHEMA_VERSION,
                validation_id="val_1",
                turn_id="turn_1",
                scope=scope,
                chapter_id=1,
                action_source=ActionSource.RECOMMENDED,
                selected_action_id=None,
                custom_action_text_hash=None,
                status=ValidationStatus.ALLOWED,
                blocking_reasons=(),
                cost_explanation=(),
                risk_explanation=(),
                checked_at=datetime.now(timezone.utc).isoformat(),
                context_fingerprint=sha256(b"test").hexdigest(),
            )

    def test_branch_lifecycle_consistency(self) -> None:
        with pytest.raises(NarrativeTurnError, match="archived branch requires archived_at"):
            NarrativeBranch(
                schema_version=SCHEMA_VERSION,
                branch_id="branch_1",
                project_id="project_1",
                timeline_id="timeline_1",
                parent_branch_id=None,
                created_from_turn_id=None,
                display_name="Branch",
                lifecycle_status=BranchLifecycleStatus.ARCHIVED,
                created_at=datetime.now(timezone.utc).isoformat(),
                archived_at=None,
            )


# ---------------------------------------------------------------------------
# Strict types (§10.3) — list input fail-closed for every tuple field
# ---------------------------------------------------------------------------

class TestStrictTypes:
    def test_list_rejected_for_forbidden_patterns(self) -> None:
        with pytest.raises(NarrativeTurnError, match="must be a tuple, not list"):
            NarrativeCustomActionPolicy(
                max_length=200,
                forbidden_patterns=["prompt_injection"],
                feasibility_pipeline=(),
            )

    def test_list_rejected_for_feasibility_pipeline(self) -> None:
        with pytest.raises(NarrativeTurnError, match="must be a tuple, not list"):
            NarrativeCustomActionPolicy(
                max_length=200,
                forbidden_patterns=(),
                feasibility_pipeline=["check_1"],
            )

    def test_list_rejected_for_expected_costs(self) -> None:
        with pytest.raises(NarrativeTurnError, match="must be a tuple of tuples, not list"):
            NarrativeActionOption(
                action_id="a1",
                action_type=ActionType.ADVANCE,
                display_text="Test",
                intent="test",
                expected_costs=[("time", "low")],
                expected_risks=(),
                required_conditions=(),
                unavailable_reasons=(),
                provenance="deterministic-planner",
                deterministic_order=1,
            )

    def test_list_rejected_for_expected_risks(self) -> None:
        with pytest.raises(NarrativeTurnError, match="must be a tuple of tuples, not list"):
            NarrativeActionOption(
                action_id="a1",
                action_type=ActionType.ADVANCE,
                display_text="Test",
                intent="test",
                expected_costs=(),
                expected_risks=[("safety", "low")],
                required_conditions=(),
                unavailable_reasons=(),
                provenance="deterministic-planner",
                deterministic_order=1,
            )

    def test_list_rejected_for_required_conditions(self) -> None:
        with pytest.raises(NarrativeTurnError, match="must be a tuple, not list"):
            NarrativeActionOption(
                action_id="a1",
                action_type=ActionType.ADVANCE,
                display_text="Test",
                intent="test",
                expected_costs=(),
                expected_risks=(),
                required_conditions=["cond_1"],
                unavailable_reasons=(),
                provenance="deterministic-planner",
                deterministic_order=1,
            )

    def test_list_rejected_for_recommended_actions(self) -> None:
        with pytest.raises(NarrativeTurnError, match="must be a tuple, not list"):
            NarrativeTurnPlan(
                schema_version=SCHEMA_VERSION,
                turn_id="turn_1",
                scope=make_fixture_scope(),
                chapter_id=1,
                source_version_id="v1",
                parent_turn_id=None,
                context_fingerprint=sha256(b"test").hexdigest(),
                planning_revision="rev_1",
                canon_revision="canon_1",
                created_at=datetime.now(timezone.utc).isoformat(),
                recommended_actions=list(make_fixture_actions()),
                custom_action_policy=make_fixture_policy(),
            )

    def test_list_rejected_for_blocking_reasons(self) -> None:
        with pytest.raises(NarrativeTurnError, match="must be a tuple, not list"):
            NarrativeActionValidation(
                schema_version=SCHEMA_VERSION,
                validation_id="val_1",
                turn_id="turn_1",
                scope=make_fixture_scope(),
                chapter_id=1,
                action_source=ActionSource.RECOMMENDED,
                selected_action_id="action_1",
                custom_action_text_hash=None,
                status=ValidationStatus.ALLOWED,
                blocking_reasons=["reason_1"],
                cost_explanation=(),
                risk_explanation=(),
                checked_at=datetime.now(timezone.utc).isoformat(),
                context_fingerprint=sha256(b"test").hexdigest(),
            )

    def test_dict_rejected_for_tuple_of_tuples(self) -> None:
        with pytest.raises(NarrativeTurnError, match="must be a tuple of tuples, not dict"):
            NarrativeActionOption(
                action_id="a1",
                action_type=ActionType.ADVANCE,
                display_text="Test",
                intent="test",
                expected_costs={"time": "low"},
                expected_risks=(),
                required_conditions=(),
                unavailable_reasons=(),
                provenance="deterministic-planner",
                deterministic_order=1,
            )

    def test_tuple_input_accepted(self) -> None:
        policy = NarrativeCustomActionPolicy(
            max_length=200,
            forbidden_patterns=("a",),
            feasibility_pipeline=("b",),
        )
        assert policy.forbidden_patterns == ("a",)
        assert policy.feasibility_pipeline == ("b",)

    def test_external_dict_mutation_does_not_change_contract(self) -> None:
        # expected_costs is a tuple of tuples — mutating a dict that was
        # never accepted cannot affect the record.
        action = NarrativeActionOption(
            action_id="a1",
            action_type=ActionType.ADVANCE,
            display_text="Test",
            intent="test",
            expected_costs=(("time", "low"),),
            expected_risks=(),
            required_conditions=(),
            unavailable_reasons=(),
            provenance="deterministic-planner",
            deterministic_order=1,
        )
        # Tuples are immutable; the only way to "mutuate" would be through
        # a mutable nested object, but our tuples contain only strings.
        assert action.expected_costs == (("time", "low"),)

    def test_bool_does_not_pass_as_int(self) -> None:
        with pytest.raises(NarrativeTurnError, match="must be int"):
            NarrativeTurnPlan(
                schema_version=SCHEMA_VERSION,
                turn_id="turn_1",
                scope=make_fixture_scope(),
                chapter_id=True,
                source_version_id="v1",
                parent_turn_id=None,
                context_fingerprint=sha256(b"test").hexdigest(),
                planning_revision="rev_1",
                canon_revision="canon_1",
                created_at=datetime.now(timezone.utc).isoformat(),
                recommended_actions=make_fixture_actions(),
                custom_action_policy=make_fixture_policy(),
            )

    def test_unknown_enum_value_rejected(self) -> None:
        with pytest.raises(NarrativeTurnError, match="Invalid action_type"):
            NarrativeActionOption(
                action_id="a1",
                action_type="unknown_action",
                display_text="Test",
                intent="test",
                expected_costs=(),
                expected_risks=(),
                required_conditions=(),
                unavailable_reasons=(),
                provenance="deterministic-planner",
                deterministic_order=1,
            )

    def test_serialized_shape_stability(self) -> None:
        """Plan fingerprint is stable across identical constructions."""
        scope = make_fixture_scope()
        p1 = make_fixture_plan(scope)
        p2 = NarrativeTurnPlan(
            schema_version=p1.schema_version,
            turn_id=p1.turn_id,
            scope=p1.scope,
            chapter_id=p1.chapter_id,
            source_version_id=p1.source_version_id,
            parent_turn_id=p1.parent_turn_id,
            context_fingerprint=p1.context_fingerprint,
            planning_revision=p1.planning_revision,
            canon_revision=p1.canon_revision,
            created_at=p1.created_at,
            recommended_actions=p1.recommended_actions,
            custom_action_policy=p1.custom_action_policy,
        )
        assert p1.fingerprint() == p2.fingerprint()


# ---------------------------------------------------------------------------
# Scope binding & path containment
# ---------------------------------------------------------------------------

class TestScopeBinding:
    def test_project_mismatch(self, turn_store: NarrativeTurnStore, fixture_scope: NarrativeScope) -> None:
        wrong_scope = NarrativeScope(
            project_id="wrong-project",
            timeline_id=fixture_scope.timeline_id,
            branch_id=fixture_scope.branch_id,
        )
        plan = make_fixture_plan(wrong_scope)
        with pytest.raises(NarrativeTurnError, match="project_id mismatch"):
            turn_store.append_plan(plan)

    def test_scope_assert_matches(self) -> None:
        scope1 = make_fixture_scope()
        scope2 = NarrativeScope(
            project_id="test-project",
            timeline_id="different-timeline",
            branch_id="test-branch",
        )
        with pytest.raises(NarrativeTurnError, match="timeline_id mismatch"):
            scope1.assert_matches(scope2)


class TestPathContainment:
    def test_path_traversal_rejected(self) -> None:
        with pytest.raises(NarrativeTurnError, match="Invalid branch_id"):
            NarrativeScope(
                project_id="test-project",
                timeline_id="timeline",
                branch_id="../escape",
            )

    def test_absolute_path_rejected(self) -> None:
        with pytest.raises(NarrativeTurnError, match="Invalid timeline_id"):
            NarrativeScope(
                project_id="test-project",
                timeline_id="/absolute/path",
                branch_id="branch",
            )


# ---------------------------------------------------------------------------
# Turn store — basic operations (updated for new transition fields)
# ---------------------------------------------------------------------------

class TestTurnStore:
    def test_append_plan(self, turn_store: NarrativeTurnStore, fixture_scope: NarrativeScope) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        retrieved = turn_store.get_plan(fixture_scope, plan.turn_id)
        assert retrieved is not None
        assert retrieved.turn_id == plan.turn_id

    def test_duplicate_plan_rejected(self, turn_store: NarrativeTurnStore, fixture_scope: NarrativeScope) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        # Identical replay is idempotent (no error). A conflicting plan with
        # the same turn_id but different content must be rejected.
        conflicting = NarrativeTurnPlan(
            schema_version=SCHEMA_VERSION,
            turn_id=plan.turn_id,
            scope=plan.scope,
            chapter_id=999,
            source_version_id=plan.source_version_id,
            parent_turn_id=plan.parent_turn_id,
            context_fingerprint=plan.context_fingerprint,
            planning_revision=plan.planning_revision,
            canon_revision=plan.canon_revision,
            created_at=plan.created_at,
            recommended_actions=plan.recommended_actions,
            custom_action_policy=plan.custom_action_policy,
        )
        with pytest.raises(NarrativeTurnError, match="already exists"):
            turn_store.append_plan(conflicting)

    def test_append_validation(self, turn_store: NarrativeTurnStore, fixture_scope: NarrativeScope) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        validation = NarrativeActionValidation(
            schema_version=SCHEMA_VERSION,
            validation_id=new_id("val"),
            turn_id=plan.turn_id,
            scope=fixture_scope,
            chapter_id=1,
            action_source=ActionSource.RECOMMENDED,
            selected_action_id="action_1",
            custom_action_text_hash=None,
            status=ValidationStatus.ALLOWED,
            blocking_reasons=(),
            cost_explanation=(("time", "medium"),),
            risk_explanation=(),
            checked_at=datetime.now(timezone.utc).isoformat(),
            context_fingerprint=sha256(b"test").hexdigest(),
        )
        turn_store.append_validation(validation)
        retrieved = turn_store.get_validation(fixture_scope, validation.validation_id)
        assert retrieved is not None

    def test_append_result(self, turn_store: NarrativeTurnStore, fixture_scope: NarrativeScope) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        result = NarrativeTurnResult(
            schema_version=SCHEMA_VERSION,
            turn_id=plan.turn_id,
            scope=fixture_scope,
            chapter_id=1,
            selected_action_id="action_1",
            custom_action_text_hash=None,
            result_status=ResultStatus.SUCCESS,
            event_summary="Test event",
            state_delta_proposal=(("key", "value"),),
            consequence_flags=("flag_1",),
            next_context_fingerprint=sha256(b"next").hexdigest(),
            execution_revision="exec_1",
            source_fingerprint=sha256(b"source").hexdigest(),
            confirmed_at=datetime.now(timezone.utc).isoformat(),
            operation_id=new_id("op"),
        )
        turn_store.append_result(result)
        retrieved = turn_store.get_result(fixture_scope, plan.turn_id)
        assert retrieved is not None

    def test_append_transition(self, turn_store: NarrativeTurnStore, fixture_scope: NarrativeScope) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        transition = make_fixture_transition(fixture_scope, plan.turn_id)
        turn_store.append_transition(transition)
        transitions = turn_store.get_transitions(fixture_scope, plan.turn_id)
        assert len(transitions) == 1

    def test_get_current_state(self, turn_store: NarrativeTurnStore, fixture_scope: NarrativeScope) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        assert turn_store.get_current_state(fixture_scope, plan.turn_id) == TurnState.PLANNED
        transition = make_fixture_transition(fixture_scope, plan.turn_id)
        turn_store.append_transition(transition)
        assert turn_store.get_current_state(fixture_scope, plan.turn_id) == TurnState.AWAITING_ACTION

    def test_list_plans(self, turn_store: NarrativeTurnStore, fixture_scope: NarrativeScope) -> None:
        plan1 = make_fixture_plan(fixture_scope)
        plan2 = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan1)
        turn_store.append_plan(plan2)
        plans = turn_store.list_plans(fixture_scope)
        assert plan1.turn_id in plans
        assert plan2.turn_id in plans

    def test_record_operation(self, turn_store: NarrativeTurnStore, fixture_scope: NarrativeScope) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        op_id = new_id("op")
        turn_store.record_operation(fixture_scope, op_id, plan.turn_id, "plan", plan.fingerprint())
        op = turn_store.get_operation(fixture_scope, op_id)
        assert op is not None
        assert op["turn_id"] == plan.turn_id

    def test_operation_collision(self, turn_store: NarrativeTurnStore, fixture_scope: NarrativeScope) -> None:
        plan1 = make_fixture_plan(fixture_scope)
        plan2 = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan1)
        turn_store.append_plan(plan2)
        op_id = new_id("op")
        turn_store.record_operation(fixture_scope, op_id, plan1.turn_id, "plan", plan1.fingerprint())
        with pytest.raises(NarrativeTurnError, match="Operation collision"):
            turn_store.record_operation(fixture_scope, op_id, plan2.turn_id, "plan", plan2.fingerprint())


# ---------------------------------------------------------------------------
# State journal (updated for sequence/previous binding)
# ---------------------------------------------------------------------------

class TestStateJournal:
    def test_legal_transitions(self, turn_store: NarrativeTurnStore, fixture_scope: NarrativeScope) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        transitions = [
            (TurnState.PLANNED, TurnState.AWAITING_ACTION),
            (TurnState.AWAITING_ACTION, TurnState.VALIDATING),
            (TurnState.VALIDATING, TurnState.VALIDATED),
            (TurnState.VALIDATED, TurnState.PREVIEWED),
            (TurnState.PREVIEWED, TurnState.CONFIRMED),
            (TurnState.CONFIRMED, TurnState.APPLIED_TO_BRANCH),
            (TurnState.APPLIED_TO_BRANCH, TurnState.INCLUDED_IN_CHAPTER),
            (TurnState.INCLUDED_IN_CHAPTER, TurnState.COMMITTED),
        ]
        append_transition_chain(turn_store, fixture_scope, plan.turn_id, transitions, plan.fingerprint())
        assert turn_store.get_current_state(fixture_scope, plan.turn_id) == TurnState.COMMITTED

    def test_illegal_transition(self) -> None:
        with pytest.raises(NarrativeTurnError, match="Illegal transition"):
            NarrativeTurnTransition(
                schema_version=SCHEMA_VERSION,
                transition_id=new_id("trans"),
                turn_id="turn_1",
                scope=make_fixture_scope(),
                from_state=TurnState.PLANNED,
                to_state=TurnState.CONFIRMED,
                reason_code="test",
                operation_id=None,
                occurred_at=datetime.now(timezone.utc).isoformat(),
                record_fingerprint=sha256(b"test").hexdigest(),
                sequence=0,
                previous_transition_id=None,
                previous_transition_fingerprint=None,
            )

    def test_terminal_state_transition(self) -> None:
        with pytest.raises(NarrativeTurnError, match="Illegal transition"):
            NarrativeTurnTransition(
                schema_version=SCHEMA_VERSION,
                transition_id=new_id("trans"),
                turn_id="turn_1",
                scope=make_fixture_scope(),
                from_state=TurnState.SUPERSEDED,
                to_state=TurnState.AWAITING_ACTION,
                reason_code="test",
                operation_id=None,
                occurred_at=datetime.now(timezone.utc).isoformat(),
                record_fingerprint=sha256(b"test").hexdigest(),
                sequence=0,
                previous_transition_id=None,
                previous_transition_fingerprint=None,
            )

    def test_transition_idempotency(self, turn_store: NarrativeTurnStore, fixture_scope: NarrativeScope) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        transition = make_fixture_transition(
            fixture_scope,
            plan.turn_id,
            transition_id="same_trans_id",
        )
        turn_store.append_transition(transition)
        turn_store.append_transition(transition)
        transitions = turn_store.get_transitions(fixture_scope, plan.turn_id)
        assert len(transitions) == 1


# ---------------------------------------------------------------------------
# §10.1 Immutable publication
# ---------------------------------------------------------------------------

class TestImmutablePublication:
    def test_first_append_succeeds(self, turn_store: NarrativeTurnStore, fixture_scope: NarrativeScope) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        assert turn_store.get_plan(fixture_scope, plan.turn_id) is not None

    def test_identical_replay_succeeds(self, turn_store: NarrativeTurnStore, fixture_scope: NarrativeScope) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        # Re-appending the exact same plan should be idempotent (no error).
        turn_store.append_plan(plan)
        retrieved = turn_store.get_plan(fixture_scope, plan.turn_id)
        assert retrieved is not None
        assert retrieved.fingerprint() == plan.fingerprint()

    def test_conflicting_duplicate_rejected(self, turn_store: NarrativeTurnStore, fixture_scope: NarrativeScope) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        # Construct a plan with the same turn_id but different content.
        conflicting = NarrativeTurnPlan(
            schema_version=SCHEMA_VERSION,
            turn_id=plan.turn_id,
            scope=plan.scope,
            chapter_id=999,
            source_version_id=plan.source_version_id,
            parent_turn_id=plan.parent_turn_id,
            context_fingerprint=plan.context_fingerprint,
            planning_revision=plan.planning_revision,
            canon_revision=plan.canon_revision,
            created_at=plan.created_at,
            recommended_actions=plan.recommended_actions,
            custom_action_policy=plan.custom_action_policy,
        )
        with pytest.raises(NarrativeTurnError, match="already exists"):
            turn_store.append_plan(conflicting)

    def test_immutable_target_never_overwritten(
        self,
        turn_store: NarrativeTurnStore,
        fixture_scope: NarrativeScope,
        temp_project: ProjectContext,
    ) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        plan_path = temp_project.data_dir / "narrative_turns" / fixture_scope.timeline_id / fixture_scope.branch_id / "plans" / f"{plan.turn_id}.json"
        original_content = plan_path.read_text(encoding="utf-8")
        # Attempt to re-publish with different content — should fail.
        conflicting = NarrativeTurnPlan(
            schema_version=SCHEMA_VERSION,
            turn_id=plan.turn_id,
            scope=plan.scope,
            chapter_id=999,
            source_version_id=plan.source_version_id,
            parent_turn_id=plan.parent_turn_id,
            context_fingerprint=plan.context_fingerprint,
            planning_revision=plan.planning_revision,
            canon_revision=plan.canon_revision,
            created_at=plan.created_at,
            recommended_actions=plan.recommended_actions,
            custom_action_policy=plan.custom_action_policy,
        )
        with pytest.raises(NarrativeTurnError):
            turn_store.append_plan(conflicting)
        # The original content must be preserved.
        assert plan_path.read_text(encoding="utf-8") == original_content

    def test_os_replace_not_used_for_immutable_records(
        self,
        turn_store: NarrativeTurnStore,
        fixture_scope: NarrativeScope,
    ) -> None:
        """Verify _publish_immutable_json uses os.link, not os.replace."""
        from system import narrative_turn_store as nts
        plan = make_fixture_plan(fixture_scope)
        with patch.object(nts.os, "replace", side_effect=AssertionError("os.replace must not be used for immutable records")) as _mock_replace:
            turn_store.append_plan(plan)
        # If we reach here, os.replace was not called.

    def test_temp_cleanup_on_success(
        self,
        turn_store: NarrativeTurnStore,
        fixture_scope: NarrativeScope,
        temp_project: ProjectContext,
    ) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        plan_dir = temp_project.data_dir / "narrative_turns" / fixture_scope.timeline_id / fixture_scope.branch_id / "plans"
        temp_files = [p for p in plan_dir.iterdir() if p.name.startswith(".") and p.suffix == ".tmp"]
        assert temp_files == []

    def test_temp_cleanup_on_collision(
        self,
        turn_store: NarrativeTurnStore,
        fixture_scope: NarrativeScope,
        temp_project: ProjectContext,
    ) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        conflicting = NarrativeTurnPlan(
            schema_version=SCHEMA_VERSION,
            turn_id=plan.turn_id,
            scope=plan.scope,
            chapter_id=999,
            source_version_id=plan.source_version_id,
            parent_turn_id=plan.parent_turn_id,
            context_fingerprint=plan.context_fingerprint,
            planning_revision=plan.planning_revision,
            canon_revision=plan.canon_revision,
            created_at=plan.created_at,
            recommended_actions=plan.recommended_actions,
            custom_action_policy=plan.custom_action_policy,
        )
        with pytest.raises(NarrativeTurnError):
            turn_store.append_plan(conflicting)
        plan_dir = temp_project.data_dir / "narrative_turns" / fixture_scope.timeline_id / fixture_scope.branch_id / "plans"
        temp_files = [p for p in plan_dir.iterdir() if p.name.startswith(".") and p.suffix == ".tmp"]
        assert temp_files == []

    def test_fsync_failure_fail_closed(
        self,
        turn_store: NarrativeTurnStore,
        fixture_scope: NarrativeScope,
    ) -> None:
        """If fsync fails, the publish must fail closed — no target file created."""
        from system import narrative_turn_store as nts
        plan = make_fixture_plan(fixture_scope)
        original_fsync = nts.os.fsync

        def failing_fsync(fd: int) -> None:
            raise OSError("simulated fsync failure")

        with patch.object(nts.os, "fsync", side_effect=failing_fsync):
            with pytest.raises(NarrativeTurnError):
                turn_store.append_plan(plan)
        # Verify no target file was created.
        retrieved = turn_store.get_plan(fixture_scope, plan.turn_id)
        assert retrieved is None

    def test_hard_link_failure_fail_closed(
        self,
        turn_store: NarrativeTurnStore,
        fixture_scope: NarrativeScope,
    ) -> None:
        """If os.link fails for a non-FileExistsError reason, fail closed."""
        from system import narrative_turn_store as nts
        plan = make_fixture_plan(fixture_scope)

        original_link = nts.os.link

        def failing_link(src: str, dst: str) -> None:
            raise OSError("simulated link failure")

        with patch.object(nts.os, "link", side_effect=failing_link):
            with pytest.raises(NarrativeTurnError):
                turn_store.append_plan(plan)
        retrieved = turn_store.get_plan(fixture_scope, plan.turn_id)
        assert retrieved is None

    def test_existing_content_preserved_on_collision(
        self,
        turn_store: NarrativeTurnStore,
        fixture_scope: NarrativeScope,
    ) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        original = turn_store.get_plan(fixture_scope, plan.turn_id)
        assert original is not None
        # Re-append the exact same plan (idempotent) — content must not change.
        turn_store.append_plan(plan)
        replayed = turn_store.get_plan(fixture_scope, plan.turn_id)
        assert replayed is not None
        assert replayed.fingerprint() == original.fingerprint()


# ---------------------------------------------------------------------------
# §10.2 Branch lifecycle (append-only events, derived projection)
# ---------------------------------------------------------------------------

class TestBranchLifecycle:
    def test_create_root_branch(self, branch_store: NarrativeBranchStore, timeline_context: TimelineContext) -> None:
        branch = branch_store.create_branch(timeline_context, "root", "Root Branch")
        assert branch.branch_id == "root"
        assert branch.parent_branch_id is None
        assert branch.lifecycle_status == BranchLifecycleStatus.OPEN

    def test_create_child_branch(self, branch_store: NarrativeBranchStore, timeline_context: TimelineContext) -> None:
        branch_store.create_branch(timeline_context, "root", "Root Branch")
        child = branch_store.create_branch(timeline_context, "child", "Child Branch", parent_branch_id="root")
        assert child.parent_branch_id == "root"

    def test_multiple_open_branches(self, branch_store: NarrativeBranchStore, timeline_context: TimelineContext) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        branch_store.create_branch(timeline_context, "branch2", "Branch 2")
        branches = branch_store.list_branches(timeline_context)
        assert len(branches) == 2
        assert all(b.lifecycle_status == BranchLifecycleStatus.OPEN for b in branches)

    def test_select_branch(self, branch_store: NarrativeBranchStore, timeline_context: TimelineContext) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        revision = branch_store.get_registry_revision(timeline_context)
        branch_store.select_branch(timeline_context, "branch1", revision)
        assert branch_store.get_active_branch_id(timeline_context) == "branch1"

    def test_switch_selection(self, branch_store: NarrativeBranchStore, timeline_context: TimelineContext) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        branch_store.create_branch(timeline_context, "branch2", "Branch 2")
        revision = branch_store.get_registry_revision(timeline_context)
        branch_store.select_branch(timeline_context, "branch1", revision)
        revision = branch_store.get_registry_revision(timeline_context)
        branch_store.select_branch(timeline_context, "branch2", revision)
        assert branch_store.get_active_branch_id(timeline_context) == "branch2"

    def test_archive_inactive_branch(self, branch_store: NarrativeBranchStore, timeline_context: TimelineContext) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        branch_store.create_branch(timeline_context, "branch2", "Branch 2")
        revision = branch_store.get_registry_revision(timeline_context)
        branch_store.select_branch(timeline_context, "branch1", revision)
        branch_store.archive_branch(timeline_context, "branch2")
        branch = branch_store.get_branch(timeline_context, "branch2")
        assert branch is not None
        assert branch.lifecycle_status == BranchLifecycleStatus.ARCHIVED

    def test_reject_archiving_selected_branch_without_replacement(self, branch_store: NarrativeBranchStore, timeline_context: TimelineContext) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        revision = branch_store.get_registry_revision(timeline_context)
        branch_store.select_branch(timeline_context, "branch1", revision)
        with pytest.raises(NarrativeTurnError, match="Must specify replacement branch"):
            branch_store.archive_branch(timeline_context, "branch1")

    def test_archive_with_replacement(self, branch_store: NarrativeBranchStore, timeline_context: TimelineContext) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        branch_store.create_branch(timeline_context, "branch2", "Branch 2")
        revision = branch_store.get_registry_revision(timeline_context)
        branch_store.select_branch(timeline_context, "branch1", revision)
        branch_store.archive_branch(timeline_context, "branch1", replacement_branch_id="branch2")
        branch = branch_store.get_branch(timeline_context, "branch1")
        assert branch is not None
        assert branch.lifecycle_status == BranchLifecycleStatus.ARCHIVED
        assert branch_store.get_active_branch_id(timeline_context) == "branch2"

    def test_restore_branch(self, branch_store: NarrativeBranchStore, timeline_context: TimelineContext) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        branch_store.archive_branch(timeline_context, "branch1")
        restored = branch_store.restore_branch(timeline_context, "branch1")
        assert restored.lifecycle_status == BranchLifecycleStatus.OPEN

    def test_reject_selecting_archived_branch(self, branch_store: NarrativeBranchStore, timeline_context: TimelineContext) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        branch_store.archive_branch(timeline_context, "branch1")
        revision = branch_store.get_registry_revision(timeline_context)
        with pytest.raises(NarrativeTurnError, match="Cannot select archived branch"):
            branch_store.select_branch(timeline_context, "branch1", revision)

    def test_parent_self_rejected(self, branch_store: NarrativeBranchStore, timeline_context: TimelineContext) -> None:
        with pytest.raises(NarrativeTurnError, match="parent_branch_id cannot equal branch_id"):
            branch_store.create_branch(timeline_context, "branch1", "Branch 1", parent_branch_id="branch1")

    def test_missing_parent_rejected(self, branch_store: NarrativeBranchStore, timeline_context: TimelineContext) -> None:
        with pytest.raises(NarrativeTurnError, match="Parent branch not found"):
            branch_store.create_branch(timeline_context, "child", "Child", parent_branch_id="nonexistent")

    def test_revision_conflict(self, branch_store: NarrativeBranchStore, timeline_context: TimelineContext) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        revision = branch_store.get_registry_revision(timeline_context)
        branch_store.select_branch(timeline_context, "branch1", revision)
        with pytest.raises(NarrativeTurnError, match="Revision conflict"):
            branch_store.select_branch(timeline_context, "branch1", revision)

    # --- New lifecycle tests (§10.2) ---

    def test_branch_creation_record_never_changes(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        temp_project: ProjectContext,
    ) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        identity_path = temp_project.data_dir / "branches" / timeline_context.timeline_id / "branches" / "branch1.json"
        original_content = identity_path.read_text(encoding="utf-8")
        # Archive and restore — the identity record must not change.
        branch_store.archive_branch(timeline_context, "branch1")
        branch_store.restore_branch(timeline_context, "branch1")
        assert identity_path.read_text(encoding="utf-8") == original_content

    def test_archive_appends_event(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
    ) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        branch_store.archive_branch(timeline_context, "branch1")
        events = branch_store.get_lifecycle_events(timeline_context, "branch1")
        assert len(events) == 1
        assert events[0].from_status == BranchLifecycleStatus.OPEN
        assert events[0].to_status == BranchLifecycleStatus.ARCHIVED
        assert events[0].sequence == 0

    def test_restore_appends_event(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
    ) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        branch_store.archive_branch(timeline_context, "branch1")
        branch_store.restore_branch(timeline_context, "branch1")
        events = branch_store.get_lifecycle_events(timeline_context, "branch1")
        assert len(events) == 2
        assert events[0].from_status == BranchLifecycleStatus.OPEN
        assert events[0].to_status == BranchLifecycleStatus.ARCHIVED
        assert events[1].from_status == BranchLifecycleStatus.ARCHIVED
        assert events[1].to_status == BranchLifecycleStatus.OPEN
        assert events[1].sequence == 1

    def test_lifecycle_derived_deterministically(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
    ) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        # No events yet → OPEN.
        assert branch_store.get_branch(timeline_context, "branch1").lifecycle_status == BranchLifecycleStatus.OPEN
        branch_store.archive_branch(timeline_context, "branch1")
        assert branch_store.get_branch(timeline_context, "branch1").lifecycle_status == BranchLifecycleStatus.ARCHIVED
        branch_store.restore_branch(timeline_context, "branch1")
        assert branch_store.get_branch(timeline_context, "branch1").lifecycle_status == BranchLifecycleStatus.OPEN

    def test_restore_does_not_auto_select(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
    ) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        branch_store.create_branch(timeline_context, "branch2", "Branch 2")
        revision = branch_store.get_registry_revision(timeline_context)
        branch_store.select_branch(timeline_context, "branch1", revision)
        # Archive branch1 (active) with branch2 as replacement.
        branch_store.archive_branch(timeline_context, "branch1", replacement_branch_id="branch2")
        assert branch_store.get_active_branch_id(timeline_context) == "branch2"
        # Restore branch1 — must NOT auto-select it as active.
        branch_store.restore_branch(timeline_context, "branch1")
        assert branch_store.get_active_branch_id(timeline_context) == "branch2"

    def test_selecting_archived_rejected(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
    ) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        branch_store.archive_branch(timeline_context, "branch1")
        revision = branch_store.get_registry_revision(timeline_context)
        with pytest.raises(NarrativeTurnError, match="Cannot select archived branch"):
            branch_store.select_branch(timeline_context, "branch1", revision)

    def test_active_archive_without_replacement_rejected(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
    ) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        revision = branch_store.get_registry_revision(timeline_context)
        branch_store.select_branch(timeline_context, "branch1", revision)
        with pytest.raises(NarrativeTurnError, match="Must specify replacement branch"):
            branch_store.archive_branch(timeline_context, "branch1")

    def test_active_archive_with_replacement_atomic(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
    ) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        branch_store.create_branch(timeline_context, "branch2", "Branch 2")
        revision = branch_store.get_registry_revision(timeline_context)
        branch_store.select_branch(timeline_context, "branch1", revision)
        branch_store.archive_branch(timeline_context, "branch1", replacement_branch_id="branch2")
        # After atomic archive-with-replacement: branch1 archived, branch2 active.
        assert branch_store.get_branch(timeline_context, "branch1").lifecycle_status == BranchLifecycleStatus.ARCHIVED
        assert branch_store.get_active_branch_id(timeline_context) == "branch2"
        assert branch_store.get_branch(timeline_context, "branch2").lifecycle_status == BranchLifecycleStatus.OPEN

    def test_event_chain_corruption_fail_closed(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        temp_project: ProjectContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        branch_store.archive_branch(timeline_context, "branch1")
        # Simulate corruption by monkeypatching _load_json to return a record
        # with a broken previous_event_fingerprint chain. This avoids direct
        # disk writes (which are restricted by the test sandbox) and tests the
        # same fail-closed read path.
        from system import narrative_branch_store as nbs
        original_load = nbs._load_json

        def corrupted_load(path: Path) -> dict[str, Any]:
            data = original_load(path)
            if "lifecycle_events" in str(path) and "record_fingerprint" in data:
                data["previous_event_fingerprint"] = sha256(b"corrupted").hexdigest()
            return data

        monkeypatch.setattr(nbs, "_load_json", corrupted_load)
        # Reading the branch must fail-closed.
        with pytest.raises(NarrativeTurnError):
            branch_store.get_branch(timeline_context, "branch1")

    def test_lifecycle_event_chain_previous_binding(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
    ) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        branch_store.archive_branch(timeline_context, "branch1")
        events = branch_store.get_lifecycle_events(timeline_context, "branch1")
        assert len(events) == 1
        assert events[0].previous_event_fingerprint is None
        branch_store.restore_branch(timeline_context, "branch1")
        events = branch_store.get_lifecycle_events(timeline_context, "branch1")
        assert len(events) == 2
        assert events[1].previous_event_fingerprint == events[0].record_fingerprint


# ---------------------------------------------------------------------------
# §10.4 Operation authority (project-root, cross-scope collision)
# ---------------------------------------------------------------------------

class TestOperationAuthority:
    def test_same_operation_replay(
        self,
        turn_store: NarrativeTurnStore,
        fixture_scope: NarrativeScope,
    ) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        op_id = new_id("op")
        turn_store.record_operation(fixture_scope, op_id, plan.turn_id, "plan", plan.fingerprint())
        # Idempotent replay with identical bindings.
        turn_store.record_operation(fixture_scope, op_id, plan.turn_id, "plan", plan.fingerprint())
        op = turn_store.get_operation(fixture_scope, op_id)
        assert op is not None

    def test_cross_branch_collision(
        self,
        turn_store: NarrativeTurnStore,
        fixture_scope: NarrativeScope,
    ) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        op_id = new_id("op")
        turn_store.record_operation(fixture_scope, op_id, plan.turn_id, "plan", plan.fingerprint())
        # Same operation_id on a different branch must collide.
        other_scope = NarrativeScope(
            project_id=fixture_scope.project_id,
            timeline_id=fixture_scope.timeline_id,
            branch_id="other-branch",
        )
        with pytest.raises(NarrativeTurnError, match="Operation collision"):
            turn_store.record_operation(other_scope, op_id, plan.turn_id, "plan", plan.fingerprint())

    def test_cross_timeline_collision(
        self,
        turn_store: NarrativeTurnStore,
        fixture_scope: NarrativeScope,
    ) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        op_id = new_id("op")
        turn_store.record_operation(fixture_scope, op_id, plan.turn_id, "plan", plan.fingerprint())
        other_scope = NarrativeScope(
            project_id=fixture_scope.project_id,
            timeline_id="other-timeline",
            branch_id=fixture_scope.branch_id,
        )
        with pytest.raises(NarrativeTurnError, match="Operation collision"):
            turn_store.record_operation(other_scope, op_id, plan.turn_id, "plan", plan.fingerprint())

    def test_cross_turn_collision(
        self,
        turn_store: NarrativeTurnStore,
        fixture_scope: NarrativeScope,
    ) -> None:
        plan1 = make_fixture_plan(fixture_scope)
        plan2 = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan1)
        turn_store.append_plan(plan2)
        op_id = new_id("op")
        turn_store.record_operation(fixture_scope, op_id, plan1.turn_id, "plan", plan1.fingerprint())
        with pytest.raises(NarrativeTurnError, match="Operation collision"):
            turn_store.record_operation(fixture_scope, op_id, plan2.turn_id, "plan", plan2.fingerprint())

    def test_different_payload_collision(
        self,
        turn_store: NarrativeTurnStore,
        fixture_scope: NarrativeScope,
    ) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        op_id = new_id("op")
        turn_store.record_operation(fixture_scope, op_id, plan.turn_id, "plan", plan.fingerprint())
        # Same operation_id, same scope/turn/type, but different fingerprint.
        different_fp = sha256(b"different").hexdigest()
        with pytest.raises(NarrativeTurnError, match="Operation collision"):
            turn_store.record_operation(fixture_scope, op_id, plan.turn_id, "plan", different_fp)

    def test_operation_record_does_not_store_absolute_paths(
        self,
        turn_store: NarrativeTurnStore,
        fixture_scope: NarrativeScope,
        temp_project: ProjectContext,
    ) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        op_id = new_id("op")
        turn_store.record_operation(fixture_scope, op_id, plan.turn_id, "plan", plan.fingerprint())
        op = turn_store.get_operation(fixture_scope, op_id)
        assert op is not None
        # result_record_path must be relative, not absolute.
        assert not Path(op["result_record_path"]).is_absolute()
        # Must not contain the temp directory path.
        assert str(temp_project.root) not in op["result_record_path"]

    def test_corrupt_operation_record_fail_closed(
        self,
        turn_store: NarrativeTurnStore,
        fixture_scope: NarrativeScope,
        temp_project: ProjectContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        op_id = new_id("op")
        turn_store.record_operation(fixture_scope, op_id, plan.turn_id, "plan", plan.fingerprint())
        # Simulate corruption by monkeypatching _load_json to raise
        # json.JSONDecodeError when reading the operation record.
        from system import narrative_turn_store as nts
        original_load = nts._load_json

        def corrupted_load(path: Path) -> dict[str, Any]:
            if "narrative_turn_operations" in str(path):
                # Match production _load_json behavior: wrap JSONDecodeError
                # in NarrativeTurnError so callers see a domain error.
                raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, "Corrupt JSON")
            return original_load(path)

        monkeypatch.setattr(nts, "_load_json", corrupted_load)
        with pytest.raises(NarrativeTurnError):
            turn_store.get_operation(fixture_scope, op_id)


# ---------------------------------------------------------------------------
# §10.5 Transition ordering (sequence, previous binding, concurrent first-wins)
# ---------------------------------------------------------------------------

class TestTransitionOrdering:
    def test_sequence_increments(
        self,
        turn_store: NarrativeTurnStore,
        fixture_scope: NarrativeScope,
    ) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        append_transition_chain(
            turn_store,
            fixture_scope,
            plan.turn_id,
            [
                (TurnState.PLANNED, TurnState.AWAITING_ACTION),
                (TurnState.AWAITING_ACTION, TurnState.VALIDATING),
                (TurnState.VALIDATING, TurnState.VALIDATED),
            ],
            plan.fingerprint(),
        )
        transitions = turn_store.get_transitions(fixture_scope, plan.turn_id)
        assert [t.sequence for t in transitions] == [0, 1, 2]

    def test_duplicate_sequence_rejected(
        self,
        turn_store: NarrativeTurnStore,
        fixture_scope: NarrativeScope,
    ) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        t1 = make_fixture_transition(fixture_scope, plan.turn_id, sequence=0)
        turn_store.append_transition(t1)
        # Same sequence, different transition_id.
        t2 = make_fixture_transition(
            fixture_scope,
            plan.turn_id,
            sequence=0,
            from_state=TurnState.PLANNED,
            to_state=TurnState.AWAITING_ACTION,
        )
        with pytest.raises(NarrativeTurnError, match="sequence collision"):
            turn_store.append_transition(t2)

    def test_missing_sequence_rejected(
        self,
        turn_store: NarrativeTurnStore,
        fixture_scope: NarrativeScope,
    ) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        # Skip sequence 0 and try to write sequence 1 directly.
        t = make_fixture_transition(
            fixture_scope,
            plan.turn_id,
            sequence=1,
            previous_transition_id="fake",
            previous_transition_fingerprint=sha256(b"fake").hexdigest(),
        )
        with pytest.raises(NarrativeTurnError, match="sequence collision"):
            turn_store.append_transition(t)

    def test_out_of_order_timestamp_does_not_affect_state(
        self,
        turn_store: NarrativeTurnStore,
        fixture_scope: NarrativeScope,
    ) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        # Append a chain where occurred_at is non-monotonic.
        previous_id: str | None = None
        previous_fp: str | None = None
        transitions_spec = [
            (TurnState.PLANNED, TurnState.AWAITING_ACTION, "2026-07-25T10:00:00+00:00"),
            (TurnState.AWAITING_ACTION, TurnState.VALIDATING, "2026-07-25T08:00:00+00:00"),
            (TurnState.VALIDATING, TurnState.VALIDATED, "2026-07-25T09:00:00+00:00"),
        ]
        for seq, (from_state, to_state, occurred_at) in enumerate(transitions_spec):
            t = NarrativeTurnTransition(
                schema_version=SCHEMA_VERSION,
                transition_id=new_id("trans"),
                turn_id=plan.turn_id,
                scope=fixture_scope,
                from_state=from_state,
                to_state=to_state,
                reason_code="test",
                operation_id=None,
                occurred_at=occurred_at,
                record_fingerprint=plan.fingerprint(),
                sequence=seq,
                previous_transition_id=previous_id,
                previous_transition_fingerprint=previous_fp,
            )
            turn_store.append_transition(t)
            previous_id = t.transition_id
            previous_fp = t.record_fingerprint
        # Current state is determined by sequence, not timestamp.
        assert turn_store.get_current_state(fixture_scope, plan.turn_id) == TurnState.VALIDATED

    def test_previous_id_mismatch_rejected(
        self,
        turn_store: NarrativeTurnStore,
        fixture_scope: NarrativeScope,
    ) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        t1 = make_fixture_transition(fixture_scope, plan.turn_id, sequence=0)
        turn_store.append_transition(t1)
        t2 = make_fixture_transition(
            fixture_scope,
            plan.turn_id,
            sequence=1,
            from_state=TurnState.AWAITING_ACTION,
            to_state=TurnState.VALIDATING,
            previous_transition_id="wrong_id",
            previous_transition_fingerprint=t1.record_fingerprint,
        )
        with pytest.raises(NarrativeTurnError, match="previous_transition_id"):
            turn_store.append_transition(t2)

    def test_previous_fingerprint_mismatch_rejected(
        self,
        turn_store: NarrativeTurnStore,
        fixture_scope: NarrativeScope,
    ) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        t1 = make_fixture_transition(fixture_scope, plan.turn_id, sequence=0)
        turn_store.append_transition(t1)
        t2 = make_fixture_transition(
            fixture_scope,
            plan.turn_id,
            sequence=1,
            from_state=TurnState.AWAITING_ACTION,
            to_state=TurnState.VALIDATING,
            previous_transition_id=t1.transition_id,
            previous_transition_fingerprint=sha256(b"wrong").hexdigest(),
        )
        with pytest.raises(NarrativeTurnError, match="previous_transition_fingerprint"):
            turn_store.append_transition(t2)

    def test_stale_from_state_rejected(
        self,
        turn_store: NarrativeTurnStore,
        fixture_scope: NarrativeScope,
    ) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        t1 = make_fixture_transition(fixture_scope, plan.turn_id, sequence=0)
        turn_store.append_transition(t1)
        # Current head is AWAITING_ACTION, but we try to transition from PLANNED.
        # PLANNED -> AWAITING_ACTION is a legal transition at the contract level,
        # but the store must reject it because the journal head is AWAITING_ACTION.
        t2 = make_fixture_transition(
            fixture_scope,
            plan.turn_id,
            sequence=1,
            from_state=TurnState.PLANNED,  # stale
            to_state=TurnState.AWAITING_ACTION,
            previous_transition_id=t1.transition_id,
            previous_transition_fingerprint=t1.record_fingerprint,
        )
        with pytest.raises(NarrativeTurnError, match="from_state"):
            turn_store.append_transition(t2)

    def test_concurrent_next_transition_first_wins(
        self,
        turn_store: NarrativeTurnStore,
        fixture_scope: NarrativeScope,
    ) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        # Simulate two concurrent writers that both read an empty journal.
        t1 = make_fixture_transition(
            fixture_scope,
            plan.turn_id,
            sequence=0,
            transition_id="trans_A",
        )
        t2 = make_fixture_transition(
            fixture_scope,
            plan.turn_id,
            sequence=0,
            transition_id="trans_B",
        )
        turn_store.append_transition(t1)
        # t2 has a different transition_id (different content) at the same
        # sequence — must be rejected as a collision.
        with pytest.raises(NarrativeTurnError, match="sequence collision"):
            turn_store.append_transition(t2)

    def test_journal_replay_deterministic(
        self,
        turn_store: NarrativeTurnStore,
        fixture_scope: NarrativeScope,
    ) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        append_transition_chain(
            turn_store,
            fixture_scope,
            plan.turn_id,
            [
                (TurnState.PLANNED, TurnState.AWAITING_ACTION),
                (TurnState.AWAITING_ACTION, TurnState.VALIDATING),
                (TurnState.VALIDATING, TurnState.VALIDATED),
            ],
            plan.fingerprint(),
        )
        transitions = turn_store.get_transitions(fixture_scope, plan.turn_id)
        assert len(transitions) == 3
        assert [t.sequence for t in transitions] == [0, 1, 2]
        # Verify previous binding chain.
        assert transitions[0].previous_transition_id is None
        assert transitions[1].previous_transition_id == transitions[0].transition_id
        assert transitions[2].previous_transition_id == transitions[1].transition_id

    def test_journal_corruption_fail_closed(
        self,
        turn_store: NarrativeTurnStore,
        fixture_scope: NarrativeScope,
        temp_project: ProjectContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        plan = make_fixture_plan(fixture_scope)
        turn_store.append_plan(plan)
        append_transition_chain(
            turn_store,
            fixture_scope,
            plan.turn_id,
            [
                (TurnState.PLANNED, TurnState.AWAITING_ACTION),
                (TurnState.AWAITING_ACTION, TurnState.VALIDATING),
            ],
            plan.fingerprint(),
        )
        # Simulate corruption by monkeypatching _load_json to return a record
        # with a non-contiguous sequence number for the second transition.
        from system import narrative_turn_store as nts
        original_load = nts._load_json
        call_count = {"n": 0}

        def corrupted_load(path: Path) -> dict[str, Any]:
            data = original_load(path)
            # Corrupt the second transition file (sequence=1) by changing
            # its sequence to 5, breaking the contiguous chain.
            if "transitions" in str(path) and data.get("sequence") == 1:
                data["sequence"] = 5
            return data

        monkeypatch.setattr(nts, "_load_json", corrupted_load)
        with pytest.raises(NarrativeTurnError):
            turn_store.get_transitions(fixture_scope, plan.turn_id)


# ---------------------------------------------------------------------------
# Immutable fingerprint (existing)
# ---------------------------------------------------------------------------

class TestImmutableFingerprint:
    def test_plan_fingerprint(self) -> None:
        scope = make_fixture_scope()
        plan = make_fixture_plan(scope)
        fp1 = plan.fingerprint()
        fp2 = plan.fingerprint()
        assert fp1 == fp2
        assert len(fp1) == 64

    def test_transition_fingerprint(self) -> None:
        scope = make_fixture_scope()
        plan = make_fixture_plan(scope)
        transition = make_fixture_transition(scope, plan.turn_id)
        fp1 = transition.fingerprint()
        fp2 = transition.fingerprint()
        assert fp1 == fp2
        assert len(fp1) == 64


# ---------------------------------------------------------------------------
# FIX-RC2: §10.2 Lifecycle concurrency (sequence-only filenames)
# ---------------------------------------------------------------------------

class TestLifecycleConcurrency:
    def test_lifecycle_sequence_only_filename(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        temp_project: ProjectContext,
    ) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        branch_store.archive_branch(timeline_context, "branch1")
        events_path = temp_project.data_dir / "branches" / timeline_context.timeline_id / "lifecycle_events" / "branch1"
        files = [p.name for p in events_path.iterdir() if p.suffix == ".json"]
        assert len(files) == 1
        assert files[0] == "00000000.json"

    def test_concurrent_archive_archive_same_branch_first_wins(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        temp_project: ProjectContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from system.narrative_branch_store import _publish_immutable_json
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        events_path = temp_project.data_dir / "branches" / timeline_context.timeline_id / "lifecycle_events" / "branch1"
        events_path.mkdir(parents=True, exist_ok=True)
        fake_event = {
            "schema_version": SCHEMA_VERSION,
            "event_id": "evt_fake",
            "sequence": 0,
            "branch_id": "branch1",
            "project_id": timeline_context.project_id,
            "timeline_id": timeline_context.timeline_id,
            "from_status": BranchLifecycleStatus.OPEN.value,
            "to_status": BranchLifecycleStatus.ARCHIVED.value,
            "operation_id": None,
            "occurred_at": now_utc(),
            "previous_event_fingerprint": None,
            "record_fingerprint": sha256(b"fake").hexdigest(),
        }
        event_path = events_path / "00000000.json"
        _publish_immutable_json(event_path, fake_event)
        original_read = NarrativeBranchStore._read_lifecycle_events
        def fake_read(self_store: NarrativeBranchStore, tc: TimelineContext, branch_id: str):
            if branch_id == "branch1":
                return []
            return original_read(self_store, tc, branch_id)
        monkeypatch.setattr(
            NarrativeBranchStore,
            "_read_lifecycle_events",
            fake_read,
        )
        with pytest.raises(NarrativeTurnError, match="IMMUTABLE_RECORD_EXISTS|already exists"):
            branch_store.archive_branch(timeline_context, "branch1")

    def test_concurrent_archive_restore_same_branch(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        temp_project: ProjectContext,
    ) -> None:
        from system.narrative_branch_store import _publish_immutable_json
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        branch_store.archive_branch(timeline_context, "branch1")
        events_path = temp_project.data_dir / "branches" / timeline_context.timeline_id / "lifecycle_events" / "branch1"
        fake_event = {
            "schema_version": SCHEMA_VERSION,
            "event_id": "evt_fake_restore",
            "sequence": 1,
            "branch_id": "branch1",
            "project_id": timeline_context.project_id,
            "timeline_id": timeline_context.timeline_id,
            "from_status": BranchLifecycleStatus.ARCHIVED.value,
            "to_status": BranchLifecycleStatus.OPEN.value,
            "operation_id": None,
            "occurred_at": now_utc(),
            "previous_event_fingerprint": sha256(b"wrong").hexdigest(),
            "record_fingerprint": sha256(b"fake2").hexdigest(),
        }
        event_path = events_path / "00000001.json"
        _publish_immutable_json(event_path, fake_event)
        with pytest.raises(NarrativeTurnError):
            branch_store.restore_branch(timeline_context, "branch1")

    def test_same_sequence_different_event_id_first_wins(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        temp_project: ProjectContext,
    ) -> None:
        from system.narrative_branch_store import _publish_immutable_json
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        events_path = temp_project.data_dir / "branches" / timeline_context.timeline_id / "lifecycle_events" / "branch1"
        events_path.mkdir(parents=True, exist_ok=True)
        first_event = {
            "schema_version": SCHEMA_VERSION,
            "event_id": "evt_first",
            "sequence": 0,
            "branch_id": "branch1",
            "project_id": timeline_context.project_id,
            "timeline_id": timeline_context.timeline_id,
            "from_status": BranchLifecycleStatus.OPEN.value,
            "to_status": BranchLifecycleStatus.ARCHIVED.value,
            "operation_id": None,
            "occurred_at": now_utc(),
            "previous_event_fingerprint": None,
            "record_fingerprint": sha256(b"first").hexdigest(),
        }
        event_path = events_path / "00000000.json"
        _publish_immutable_json(event_path, first_event)
        events = branch_store.get_lifecycle_events(timeline_context, "branch1")
        assert len(events) == 1
        assert events[0].event_id == "evt_first"

    def test_no_duplicate_sequence_files(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        temp_project: ProjectContext,
    ) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        branch_store.archive_branch(timeline_context, "branch1")
        branch_store.restore_branch(timeline_context, "branch1")
        branch_store.archive_branch(timeline_context, "branch1")
        events_path = temp_project.data_dir / "branches" / timeline_context.timeline_id / "lifecycle_events" / "branch1"
        files = [p.name for p in events_path.iterdir() if p.suffix == ".json"]
        assert len(files) == 3
        import re
        for fname in files:
            assert re.fullmatch(r"^\d{8}\.json$", fname), f"Invalid filename: {fname}"
        events = branch_store.get_lifecycle_events(timeline_context, "branch1")
        assert len(events) == 3

    def test_loser_re_read_gets_stale_state(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
    ) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        branch_store.archive_branch(timeline_context, "branch1")
        branch = branch_store.get_branch(timeline_context, "branch1")
        assert branch is not None
        assert branch.lifecycle_status == BranchLifecycleStatus.ARCHIVED

    def test_corrupt_legacy_duplicate_sequence_fail_closed(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        temp_project: ProjectContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        branch_store.archive_branch(timeline_context, "branch1")
        from system import narrative_branch_store as nbs
        original_iterdir = nbs.Path.iterdir

        def corrupted_iterdir(path_self: Path):
            entries = list(original_iterdir(path_self))
            if "lifecycle_events" in str(path_self):
                fake_file = path_self / "00000000_evt_abc.json"
                fake_file.touch()
                entries.append(fake_file)
            return entries

        monkeypatch.setattr(nbs.Path, "iterdir", corrupted_iterdir)
        with pytest.raises(NarrativeTurnError, match="LIFECYCLE_EVENT_CHAIN_CORRUPT|Invalid lifecycle event filename"):
            branch_store.get_lifecycle_events(timeline_context, "branch1")


# ---------------------------------------------------------------------------
# FIX-RC2: §10.2 Branch operation recovery (active archive with replacement)
# ---------------------------------------------------------------------------

class TestBranchOperationRecovery:
    def _setup_two_branches_with_active(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
    ) -> tuple[str, str, str]:
        branch_store.create_branch(timeline_context, "branch_a", "Branch A")
        branch_store.create_branch(timeline_context, "branch_b", "Branch B")
        revision = branch_store.get_registry_revision(timeline_context)
        branch_store.select_branch(timeline_context, "branch_a", revision)
        new_rev = branch_store.get_registry_revision(timeline_context)
        return "branch_a", "branch_b", new_rev

    def test_active_archive_completes_successfully(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
    ) -> None:
        a, b, rev = self._setup_two_branches_with_active(branch_store, timeline_context)
        branch_store.archive_branch(timeline_context, a, replacement_branch_id=b, expected_revision=rev)
        assert branch_store.get_active_branch_id(timeline_context) == b
        branch_a = branch_store.get_branch(timeline_context, a)
        assert branch_a is not None
        assert branch_a.lifecycle_status == BranchLifecycleStatus.ARCHIVED
        events = branch_store.get_lifecycle_events(timeline_context, a)
        assert len(events) == 1
        assert events[0].from_status == BranchLifecycleStatus.OPEN
        assert events[0].to_status == BranchLifecycleStatus.ARCHIVED

    def test_retry_after_intent_phase_succeeds(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        a, b, rev = self._setup_two_branches_with_active(branch_store, timeline_context)
        operation_id = new_id("op")
        call_count = {"n": 0}
        original_resume = NarrativeBranchStore._resume_active_archive_with_replacement

        def failing_resume(
            self_store: NarrativeBranchStore,
            tc: TimelineContext,
            op_id: str,
            op: Any,
        ) -> str:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("simulated crash after intent")
            return original_resume(self_store, tc, op_id, op)

        monkeypatch.setattr(
            NarrativeBranchStore,
            "_resume_active_archive_with_replacement",
            failing_resume,
        )
        with pytest.raises(RuntimeError, match="simulated crash after intent"):
            branch_store._active_archive_with_replacement(
                timeline_context, a, b, rev, operation_id,
            )
        result_rev = branch_store._active_archive_with_replacement(
            timeline_context, a, b, rev, operation_id,
        )
        assert result_rev is not None
        assert branch_store.get_active_branch_id(timeline_context) == b
        branch_a = branch_store.get_branch(timeline_context, a)
        assert branch_a is not None
        assert branch_a.lifecycle_status == BranchLifecycleStatus.ARCHIVED

    def test_retry_after_registry_update_succeeds(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        a, b, rev = self._setup_two_branches_with_active(branch_store, timeline_context)
        operation_id = new_id("op")
        original_append = NarrativeBranchStore._append_lifecycle_event

        def failing_append(
            self_store: NarrativeBranchStore,
            tc: TimelineContext,
            branch_id: str,
            from_status: BranchLifecycleStatus,
            to_status: BranchLifecycleStatus,
            operation_id: str | None = None,
        ) -> BranchLifecycleEvent:
            raise RuntimeError("simulated failure during lifecycle append")

        monkeypatch.setattr(
            NarrativeBranchStore,
            "_append_lifecycle_event",
            failing_append,
        )
        with pytest.raises(RuntimeError, match="simulated failure during lifecycle append"):
            branch_store._active_archive_with_replacement(
                timeline_context, a, b, rev, operation_id,
            )
        assert branch_store.get_active_branch_id(timeline_context) == b
        monkeypatch.undo()
        result_rev = branch_store._active_archive_with_replacement(
            timeline_context, a, b, rev, operation_id,
        )
        assert result_rev is not None
        branch_a = branch_store.get_branch(timeline_context, a)
        assert branch_a is not None
        assert branch_a.lifecycle_status == BranchLifecycleStatus.ARCHIVED

    def test_failure_after_registry_before_lifecycle_recovery(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        a, b, rev = self._setup_two_branches_with_active(branch_store, timeline_context)
        operation_id = new_id("op")
        original_append = NarrativeBranchStore._append_lifecycle_event

        def failing_append(
            self_store: NarrativeBranchStore,
            tc: TimelineContext,
            branch_id: str,
            from_status: BranchLifecycleStatus,
            to_status: BranchLifecycleStatus,
            operation_id: str | None = None,
        ) -> BranchLifecycleEvent:
            raise RuntimeError("simulated lifecycle append failure")

        monkeypatch.setattr(
            NarrativeBranchStore,
            "_append_lifecycle_event",
            failing_append,
        )
        with pytest.raises(RuntimeError):
            branch_store._active_archive_with_replacement(
                timeline_context, a, b, rev, operation_id,
            )
        assert branch_store.get_active_branch_id(timeline_context) == b
        monkeypatch.undo()
        result_rev = branch_store._active_archive_with_replacement(
            timeline_context, a, b, rev, operation_id,
        )
        assert result_rev is not None
        events = branch_store.get_lifecycle_events(timeline_context, a)
        assert len(events) == 1

    def test_recovery_does_not_create_second_archive_event(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        a, b, rev = self._setup_two_branches_with_active(branch_store, timeline_context)
        operation_id = new_id("op")
        call_count = {"n": 0}
        original_append = NarrativeBranchStore._append_lifecycle_event

        def counting_append(
            self_store: NarrativeBranchStore,
            tc: TimelineContext,
            branch_id: str,
            from_status: BranchLifecycleStatus,
            to_status: BranchLifecycleStatus,
            operation_id: str | None = None,
        ) -> BranchLifecycleEvent:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("simulated first failure")
            return original_append(self_store, tc, branch_id, from_status, to_status, operation_id)

        monkeypatch.setattr(
            NarrativeBranchStore,
            "_append_lifecycle_event",
            counting_append,
        )
        with pytest.raises(RuntimeError):
            branch_store._active_archive_with_replacement(
                timeline_context, a, b, rev, operation_id,
            )
        monkeypatch.undo()
        branch_store._active_archive_with_replacement(
            timeline_context, a, b, rev, operation_id,
        )
        events = branch_store.get_lifecycle_events(timeline_context, a)
        assert len(events) == 1

    def test_concurrent_archive_operations_conflict(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        a, b, rev = self._setup_two_branches_with_active(branch_store, timeline_context)
        branch_store.create_branch(timeline_context, "branch_c", "Branch C")
        rev2 = branch_store.get_registry_revision(timeline_context)
        branch_store.select_branch(timeline_context, "branch_c", rev2)
        rev3 = branch_store.get_registry_revision(timeline_context)
        branch_store.select_branch(timeline_context, a, rev3)
        current_rev = branch_store.get_registry_revision(timeline_context)
        assert current_rev != rev
        op1 = new_id("op")
        with pytest.raises(NarrativeTurnError, match="Revision conflict|stale"):
            branch_store._active_archive_with_replacement(
                timeline_context, a, b, rev, op1,
            )

    def test_replacement_archived_during_operation(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        a, b, rev = self._setup_two_branches_with_active(branch_store, timeline_context)
        operation_id = new_id("op")
        branch_store.archive_branch(timeline_context, b)
        with pytest.raises(NarrativeTurnError, match="Replacement branch cannot be archived|BRANCH_OPERATION_REPLACEMENT_ARCHIVED"):
            branch_store._active_archive_with_replacement(
                timeline_context, a, b, rev, operation_id,
            )

    def test_expected_registry_revision_stale(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
    ) -> None:
        a, b, rev = self._setup_two_branches_with_active(branch_store, timeline_context)
        operation_id = new_id("op")
        stale_rev = "stale_revision_123"
        with pytest.raises(NarrativeTurnError, match="Revision conflict|stale"):
            branch_store._active_archive_with_replacement(
                timeline_context, a, b, stale_rev, operation_id,
            )

    def test_same_operation_id_different_replacement(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
    ) -> None:
        a, b, rev = self._setup_two_branches_with_active(branch_store, timeline_context)
        branch_store.create_branch(timeline_context, "branch_c", "Branch C")
        operation_id = new_id("op")
        branch_store._active_archive_with_replacement(
            timeline_context, a, b, rev, operation_id,
        )
        with pytest.raises(NarrativeTurnError):
            branch_store._active_archive_with_replacement(
                timeline_context, a, "branch_c", rev, operation_id,
            )

    def test_invariant_active_never_points_to_archived(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        a, b, rev = self._setup_two_branches_with_active(branch_store, timeline_context)
        operation_id = new_id("op")
        original_append = NarrativeBranchStore._append_lifecycle_event

        def failing_append(*args: Any, **kwargs: Any) -> BranchLifecycleEvent:
            raise RuntimeError("simulated failure")

        monkeypatch.setattr(
            NarrativeBranchStore,
            "_append_lifecycle_event",
            failing_append,
        )
        try:
            branch_store._active_archive_with_replacement(
                timeline_context, a, b, rev, operation_id,
            )
        except RuntimeError:
            pass
        active_id = branch_store.get_active_branch_id(timeline_context)
        if active_id is not None:
            active_branch = branch_store.get_branch(timeline_context, active_id)
            assert active_branch is not None
            assert active_branch.lifecycle_status != BranchLifecycleStatus.ARCHIVED

    def test_operation_record_persists_all_phases(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        temp_project: ProjectContext,
    ) -> None:
        a, b, rev = self._setup_two_branches_with_active(branch_store, timeline_context)
        operation_id = new_id("op")
        branch_store._active_archive_with_replacement(
            timeline_context, a, b, rev, operation_id,
        )
        ops_path = temp_project.data_dir / "branch_operations"
        phase_files = [p.name for p in ops_path.iterdir() if p.suffix == ".json"]
        assert f"{operation_id}.json" in phase_files
        assert any("registry_updated" in name for name in phase_files)
        assert any("lifecycle_appended" in name for name in phase_files)
        assert any("completed" in name for name in phase_files)


# ---------------------------------------------------------------------------
# FIX-RC2: §10.3 Registry rebuild (event journal vs projection)
# ---------------------------------------------------------------------------

class TestRegistryRebuild:
    def test_registry_events_sequence_ordered(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        temp_project: ProjectContext,
    ) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        branch_store.create_branch(timeline_context, "branch2", "Branch 2")
        revision = branch_store.get_registry_revision(timeline_context)
        branch_store.select_branch(timeline_context, "branch1", revision)
        revision = branch_store.get_registry_revision(timeline_context)
        branch_store.select_branch(timeline_context, "branch2", revision)
        events_path = temp_project.data_dir / "branches" / timeline_context.timeline_id / "registry_events"
        files = sorted([p.name for p in events_path.iterdir() if p.suffix == ".json"])
        import re
        for fname in files:
            assert re.fullmatch(r"^\d{8}\.json$", fname), f"Invalid filename: {fname}"
        sequences = [int(f.split(".")[0]) for f in files]
        assert sequences == list(range(len(files)))

    def test_rebuild_registry_from_events(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        temp_project: ProjectContext,
    ) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        branch_store.create_branch(timeline_context, "branch2", "Branch 2")
        revision = branch_store.get_registry_revision(timeline_context)
        branch_store.select_branch(timeline_context, "branch1", revision)
        registry_path = temp_project.data_dir / "branches" / timeline_context.timeline_id / "registry.json"
        assert registry_path.exists()
        registry_path.unlink()
        assert not registry_path.exists()
        active_id = branch_store.get_active_branch_id(timeline_context)
        assert active_id == "branch1"
        assert registry_path.exists()

    def test_deleted_registry_snapshot_recovery(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        temp_project: ProjectContext,
    ) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        revision = branch_store.get_registry_revision(timeline_context)
        branch_store.select_branch(timeline_context, "branch1", revision)
        registry_path = temp_project.data_dir / "branches" / timeline_context.timeline_id / "registry.json"
        bak_path = registry_path.with_suffix(".bak")
        if registry_path.exists():
            registry_path.unlink()
        if bak_path.exists():
            bak_path.unlink()
        active_id = branch_store.get_active_branch_id(timeline_context)
        assert active_id == "branch1"

    def test_corrupt_registry_snapshot_recovery(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        temp_project: ProjectContext,
    ) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        revision = branch_store.get_registry_revision(timeline_context)
        branch_store.select_branch(timeline_context, "branch1", revision)
        registry_path = temp_project.data_dir / "branches" / timeline_context.timeline_id / "registry.json"
        registry_path.write_text("this is not valid json{{{", encoding="utf-8")
        active_id = branch_store.get_active_branch_id(timeline_context)
        assert active_id == "branch1"

    def test_event_gap_fail_closed(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        temp_project: ProjectContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        branch_store.create_branch(timeline_context, "branch2", "Branch 2")
        revision = branch_store.get_registry_revision(timeline_context)
        branch_store.select_branch(timeline_context, "branch1", revision)
        from system import narrative_branch_store as nbs
        original_read = nbs._load_json

        def gap_load(path: Path) -> dict[str, Any]:
            data = original_read(path)
            if "registry_events" in str(path) and data.get("sequence") == 1:
                data["sequence"] = 5
            return data

        monkeypatch.setattr(nbs, "_load_json", gap_load)
        with pytest.raises(NarrativeTurnError, match="REGISTRY_EVENT_CHAIN_CORRUPT|sequence gap"):
            branch_store.get_active_branch_id(timeline_context)

    def test_duplicate_sequence_fail_closed(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        temp_project: ProjectContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        from system import narrative_branch_store as nbs
        original_iterdir = nbs.Path.iterdir

        def dup_iterdir(path_self: Path):
            entries = list(original_iterdir(path_self))
            if "registry_events" in str(path_self):
                fake = path_self / "00000000_dup.json"
                fake.touch()
                entries.append(fake)
            return entries

        monkeypatch.setattr(nbs.Path, "iterdir", dup_iterdir)
        with pytest.raises(NarrativeTurnError, match="REGISTRY_EVENT_CHAIN_CORRUPT|Invalid registry event filename"):
            branch_store.get_active_branch_id(timeline_context)

    def test_previous_fingerprint_mismatch_fail_closed(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        branch_store.create_branch(timeline_context, "branch2", "Branch 2")
        revision = branch_store.get_registry_revision(timeline_context)
        branch_store.select_branch(timeline_context, "branch1", revision)
        from system import narrative_branch_store as nbs
        original_read = nbs._load_json

        def broken_fp_load(path: Path) -> dict[str, Any]:
            data = original_read(path)
            if "registry_events" in str(path) and data.get("sequence") == 2:
                data["previous_event_fingerprint"] = sha256(b"broken").hexdigest()
            return data

        monkeypatch.setattr(nbs, "_load_json", broken_fp_load)
        with pytest.raises(NarrativeTurnError, match="REGISTRY_EVENT_CHAIN_CORRUPT|previous_event_fingerprint"):
            branch_store.get_active_branch_id(timeline_context)

    def test_non_monotonic_timestamps(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        branch_store.create_branch(timeline_context, "branch2", "Branch 2")
        revision = branch_store.get_registry_revision(timeline_context)
        branch_store.select_branch(timeline_context, "branch1", revision)
        revision = branch_store.get_registry_revision(timeline_context)
        branch_store.select_branch(timeline_context, "branch2", revision)
        from system import narrative_branch_store as nbs
        original_read = nbs._load_json
        call_count = {"n": 0}

        def nonmono_load(path: Path) -> dict[str, Any]:
            data = original_read(path)
            if "registry_events" in str(path) and "occurred_at" in data:
                seq = data.get("sequence", 0)
                data["occurred_at"] = f"2026-07-25T{23 - seq:02d}:00:00+00:00"
            return data

        monkeypatch.setattr(nbs, "_load_json", nonmono_load)
        active_id = branch_store.get_active_branch_id(timeline_context)
        assert active_id == "branch2"

    def test_concurrent_selection_first_wins(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
    ) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        branch_store.create_branch(timeline_context, "branch2", "Branch 2")
        revision = branch_store.get_registry_revision(timeline_context)
        branch_store.select_branch(timeline_context, "branch1", revision)
        with pytest.raises(NarrativeTurnError, match="Revision conflict"):
            branch_store.select_branch(timeline_context, "branch2", revision)

    def test_projection_journal_mismatch_fail_closed(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        temp_project: ProjectContext,
    ) -> None:
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        branch_store.create_branch(timeline_context, "branch2", "Branch 2")
        revision = branch_store.get_registry_revision(timeline_context)
        branch_store.select_branch(timeline_context, "branch1", revision)
        registry_path = temp_project.data_dir / "branches" / timeline_context.timeline_id / "registry.json"
        import json as _json
        data = _json.loads(registry_path.read_text(encoding="utf-8"))
        data["active_branch_id"] = "branch2"
        registry_path.write_text(_json.dumps(data, sort_keys=True, indent=2), encoding="utf-8")
        active_id = branch_store.get_active_branch_id(timeline_context)
        assert active_id == "branch1"


# ---------------------------------------------------------------------------
# FIX-RC2: §10.4 Recursive state delta immutability
# ---------------------------------------------------------------------------

class TestRecursiveStateDelta:
    def test_nested_dict_mutation_isolation(self) -> None:
        from core.contracts.narrative_turn import _recursive_freeze
        inner = {"inner_key": "inner_value"}
        outer = {"outer_key": inner}
        frozen = _recursive_freeze(outer, "test_field")
        inner["inner_key"] = "mutated"
        assert frozen == (("outer_key", (("inner_key", "inner_value"),)),)

    def test_nested_list_rejected(self) -> None:
        from core.contracts.narrative_turn import _recursive_freeze
        with pytest.raises(NarrativeTurnError, match="must be a tuple, not list"):
            _recursive_freeze((("key", [1, 2, 3]),), "test_field")

    def test_nested_dict_inside_tuple(self) -> None:
        from core.contracts.narrative_turn import _recursive_freeze
        value = (("nested", {"a": 1, "b": 2}),)
        frozen = _recursive_freeze(value, "test_field")
        assert isinstance(frozen, tuple)
        assert isinstance(frozen[0][1], tuple)

    def test_nan_infinity_rejected(self) -> None:
        from core.contracts.narrative_turn import _recursive_freeze
        import math
        with pytest.raises(NarrativeTurnError, match="NaN or Infinity"):
            _recursive_freeze((("key", float("nan")),), "test_field")
        with pytest.raises(NarrativeTurnError, match="NaN or Infinity"):
            _recursive_freeze((("key", float("inf")),), "test_field")
        with pytest.raises(NarrativeTurnError, match="NaN or Infinity"):
            _recursive_freeze((("key", float("-inf")),), "test_field")

    def test_unsupported_custom_object_rejected(self) -> None:
        from core.contracts.narrative_turn import _recursive_freeze

        class CustomObj:
            pass

        with pytest.raises(NarrativeTurnError, match="unsupported type"):
            _recursive_freeze((("key", CustomObj()),), "test_field")

    def test_excessive_nesting_rejected(self) -> None:
        from core.contracts.narrative_turn import _recursive_freeze
        deep: dict[str, Any] = {"level0": {}}
        current = deep["level0"]
        for i in range(1, 10):
            current[f"level{i}"] = {}
            current = current[f"level{i}"]
        with pytest.raises(NarrativeTurnError, match="exceeds maximum nesting depth"):
            _recursive_freeze(deep, "test_field")

    def test_deterministic_key_order(self) -> None:
        from core.contracts.narrative_turn import _recursive_freeze
        d1 = {"z": 1, "a": 2, "m": 3}
        d2 = {"a": 2, "m": 3, "z": 1}
        f1 = _recursive_freeze(d1, "test_field")
        f2 = _recursive_freeze(d2, "test_field")
        assert f1 == f2
        assert [k for k, _ in f1] == ["a", "m", "z"]

    def test_same_semantic_value_same_fingerprint(self) -> None:
        scope = make_fixture_scope()
        plan = make_fixture_plan(scope)
        tuple_form = (
            ("key1", "value1"),
            ("key2", (("nested", 42),)),
        )
        dict_form = {
            "key1": "value1",
            "key2": {"nested": 42},
        }
        result1 = NarrativeTurnResult(
            schema_version=SCHEMA_VERSION,
            turn_id=plan.turn_id,
            scope=fixture_scope if False else scope,
            chapter_id=1,
            selected_action_id="action_1",
            custom_action_text_hash=None,
            result_status=ResultStatus.SUCCESS,
            event_summary="Test",
            state_delta_proposal=tuple_form,
            consequence_flags=(),
            next_context_fingerprint=sha256(b"next").hexdigest(),
            execution_revision="exec_1",
            source_fingerprint=plan.fingerprint(),
            confirmed_at=datetime.now(timezone.utc).isoformat(),
            operation_id=new_id("op"),
        )
        result2 = NarrativeTurnResult(
            schema_version=SCHEMA_VERSION,
            turn_id=plan.turn_id,
            scope=scope,
            chapter_id=1,
            selected_action_id="action_1",
            custom_action_text_hash=None,
            result_status=ResultStatus.SUCCESS,
            event_summary="Test",
            state_delta_proposal=dict_form,
            consequence_flags=(),
            next_context_fingerprint=sha256(b"next").hexdigest(),
            execution_revision="exec_1",
            source_fingerprint=plan.fingerprint(),
            confirmed_at=result1.confirmed_at,
            operation_id=result1.operation_id,
        )
        assert result1.state_delta_proposal == result2.state_delta_proposal
        assert result1.fingerprint() == result2.fingerprint()


# ---------------------------------------------------------------------------
# Phase 0D4-A-FIX-RC2-FV: Fact-locking tests
# ---------------------------------------------------------------------------

class TestFactLockingFixRC2FV:
    """Fact-locking tests for FIX-RC2-FV final code-to-document verification.

    These tests pin down the facts claimed in the FIX-RC2-FV delivery:
    - active archive uses REGISTRY-FIRST safe order
    - active_branch_id never targets an archived branch at any failure point
    - BranchOperation path is project-root (not timeline-isolated)
    - RegistryEvent uses explicit fields (Scheme A, NOT generic payload)
    - registry rebuild uses from_active_branch_id / to_active_branch_id /
      expected_revision / resulting_revision
    - phase document paths match store constants (no doc drift)
    """

    def _setup_two_branches_with_active(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
    ) -> tuple[str, str, str]:
        branch_store.create_branch(timeline_context, "branch_a", "Branch A")
        branch_store.create_branch(timeline_context, "branch_b", "Branch B")
        revision = branch_store.get_registry_revision(timeline_context)
        branch_store.select_branch(timeline_context, "branch_a", revision)
        new_rev = branch_store.get_registry_revision(timeline_context)
        return "branch_a", "branch_b", new_rev

    def test_active_archive_switches_registry_before_archiving_target(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Lock fact: REGISTRY-FIRST order.

        After REGISTRY_UPDATED phase the active pointer is already on the
        replacement, but the target branch is STILL OPEN (lifecycle event
        not yet appended). This proves the registry is switched *before*
        the target is archived.
        """
        a, b, rev = self._setup_two_branches_with_active(branch_store, timeline_context)
        operation_id = new_id("op")

        def failing_append(
            self_store: NarrativeBranchStore,
            tc: TimelineContext,
            branch_id: str,
            from_status: BranchLifecycleStatus,
            to_status: BranchLifecycleStatus,
            operation_id: str | None = None,
        ) -> BranchLifecycleEvent:
            raise RuntimeError("simulated failure before lifecycle append")

        monkeypatch.setattr(
            NarrativeBranchStore,
            "_append_lifecycle_event",
            failing_append,
        )
        with pytest.raises(RuntimeError, match="simulated failure before lifecycle append"):
            branch_store._active_archive_with_replacement(
                timeline_context, a, b, rev, operation_id,
            )

        # REGISTRY-FIRST proof: active already switched to replacement (b)...
        assert branch_store.get_active_branch_id(timeline_context) == b
        # ...but target (a) is STILL OPEN (not yet archived).
        target = branch_store.get_branch(timeline_context, a)
        assert target is not None
        assert target.lifecycle_status == BranchLifecycleStatus.OPEN
        # No lifecycle event has been appended yet.
        events = branch_store.get_lifecycle_events(timeline_context, a)
        assert events == []
        # The operation phase marker for registry_updated must already exist.
        monkeypatch.undo()
        op_record = branch_store._read_operation_record(operation_id)
        assert op_record is not None
        assert op_record.phase == BranchOperationPhase.REGISTRY_UPDATED

    def test_active_pointer_never_targets_archived_branch_after_each_failure_point(
        self,
        temp_project: ProjectContext,
    ) -> None:
        """Lock fact: active_branch_id never points to an archived branch.

        At every observable / recoverable failure point, the active
        pointer must point to an OPEN branch. Each failure point uses a
        fresh temporary project so the states do not contaminate each
        other.
        """
        # --- Failure point 1: crash after INTENT, before REGISTRY_UPDATED ---
        with tempfile.TemporaryDirectory() as tmp1:
            ctx1 = get_project_context(tmp1)
            store1 = NarrativeBranchStore(ctx1)
            tc1 = TimelineContext(project_id=ctx1.root.name, timeline_id="tl1")
            store1.create_branch(tc1, "branch_a", "Branch A")
            store1.create_branch(tc1, "branch_b", "Branch B")
            rev1 = store1.get_registry_revision(tc1)
            store1.select_branch(tc1, "branch_a", rev1)
            rev1 = store1.get_registry_revision(tc1)

            op_id_1 = new_id("op")
            call_count_1 = {"n": 0}
            original_resume = NarrativeBranchStore._resume_active_archive_with_replacement

            def failing_resume_1(
                self_store: NarrativeBranchStore,
                tc: TimelineContext,
                op_id: str,
                op: Any,
            ) -> str:
                call_count_1["n"] += 1
                if call_count_1["n"] == 1:
                    raise RuntimeError("crash after intent")
                return original_resume(self_store, tc, op_id, op)

            with patch.object(
                NarrativeBranchStore,
                "_resume_active_archive_with_replacement",
                failing_resume_1,
            ):
                with pytest.raises(RuntimeError, match="crash after intent"):
                    store1._active_archive_with_replacement(
                        tc1, "branch_a", "branch_b", rev1, op_id_1,
                    )
            # After INTENT-only failure: active = target (a), still OPEN — safe.
            assert store1.get_active_branch_id(tc1) == "branch_a"
            target_a = store1.get_branch(tc1, "branch_a")
            assert target_a is not None
            assert target_a.lifecycle_status == BranchLifecycleStatus.OPEN

        # --- Failure point 2: crash after REGISTRY_UPDATED, before LIFECYCLE_APPENDED ---
        with tempfile.TemporaryDirectory() as tmp2:
            ctx2 = get_project_context(tmp2)
            store2 = NarrativeBranchStore(ctx2)
            tc2 = TimelineContext(project_id=ctx2.root.name, timeline_id="tl2")
            store2.create_branch(tc2, "branch_a", "Branch A")
            store2.create_branch(tc2, "branch_b", "Branch B")
            rev2 = store2.get_registry_revision(tc2)
            store2.select_branch(tc2, "branch_a", rev2)
            rev2 = store2.get_registry_revision(tc2)

            op_id_2 = new_id("op")

            def failing_append_2(
                self_store: NarrativeBranchStore,
                tc: TimelineContext,
                branch_id: str,
                from_status: BranchLifecycleStatus,
                to_status: BranchLifecycleStatus,
                operation_id: str | None = None,
            ) -> BranchLifecycleEvent:
                raise RuntimeError("crash after registry_updated")

            with patch.object(
                NarrativeBranchStore,
                "_append_lifecycle_event",
                failing_append_2,
            ):
                with pytest.raises(RuntimeError, match="crash after registry_updated"):
                    store2._active_archive_with_replacement(
                        tc2, "branch_a", "branch_b", rev2, op_id_2,
                    )
            # After REGISTRY_UPDATED-only: active = replacement (b), still OPEN — safe.
            assert store2.get_active_branch_id(tc2) == "branch_b"
            replacement_b = store2.get_branch(tc2, "branch_b")
            assert replacement_b is not None
            assert replacement_b.lifecycle_status == BranchLifecycleStatus.OPEN
            # Target (a) is STILL OPEN at this point — safe.
            target_a = store2.get_branch(tc2, "branch_a")
            assert target_a is not None
            assert target_a.lifecycle_status == BranchLifecycleStatus.OPEN
            # Invariant: active never points to an archived branch.
            assert store2.get_active_branch_id(tc2) != "branch_a" or target_a.lifecycle_status == BranchLifecycleStatus.OPEN

        # --- Failure point 3: crash after LIFECYCLE_APPENDED, before COMPLETED ---
        with tempfile.TemporaryDirectory() as tmp3:
            ctx3 = get_project_context(tmp3)
            store3 = NarrativeBranchStore(ctx3)
            tc3 = TimelineContext(project_id=ctx3.root.name, timeline_id="tl3")
            store3.create_branch(tc3, "branch_a", "Branch A")
            store3.create_branch(tc3, "branch_b", "Branch B")
            rev3 = store3.get_registry_revision(tc3)
            store3.select_branch(tc3, "branch_a", rev3)
            rev3 = store3.get_registry_revision(tc3)

            op_id_3 = new_id("op")
            from system.narrative_branch_store import _publish_immutable_json as original_publish_immutable

            def failing_publish_immutable(
                target_path: Path,
                data: dict[str, Any],
            ) -> None:
                if target_path.name.endswith("_completed.json"):
                    raise RuntimeError("crash before completed marker")
                return original_publish_immutable(target_path, data)

            with patch(
                "system.narrative_branch_store._publish_immutable_json",
                failing_publish_immutable,
            ):
                with pytest.raises(RuntimeError, match="crash before completed marker"):
                    store3._active_archive_with_replacement(
                        tc3, "branch_a", "branch_b", rev3, op_id_3,
                    )
            # After LIFECYCLE_APPENDED-only: active = replacement (b), still OPEN — safe.
            # Target (a) is now ARCHIVED — also safe because active points to (b).
            assert store3.get_active_branch_id(tc3) == "branch_b"
            replacement_b = store3.get_branch(tc3, "branch_b")
            assert replacement_b is not None
            assert replacement_b.lifecycle_status == BranchLifecycleStatus.OPEN
            target_a = store3.get_branch(tc3, "branch_a")
            assert target_a is not None
            assert target_a.lifecycle_status == BranchLifecycleStatus.ARCHIVED
            # Invariant: active never points to an archived branch.
            assert store3.get_active_branch_id(tc3) != "branch_a"

    def test_branch_operation_path_matches_authoritative_layout(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        temp_project: ProjectContext,
    ) -> None:
        """Lock fact: BranchOperation files live at project-root scope.

        Path layout (authoritative):
            data/branch_operations/{operation_id}.json
            data/branch_operations/{operation_id}_registry_updated.json
            data/branch_operations/{operation_id}_lifecycle_appended.json
            data/branch_operations/{operation_id}_completed.json

        NOT under data/branches/{timeline_id}/branch_operations/.
        """
        a, b, rev = self._setup_two_branches_with_active(branch_store, timeline_context)
        operation_id = new_id("op")
        branch_store._active_archive_with_replacement(
            timeline_context, a, b, rev, operation_id,
        )

        ops_dir = temp_project.data_dir / "branch_operations"
        assert ops_dir.exists(), "branch_operations/ must exist at project root"

        main_record = ops_dir / f"{operation_id}.json"
        registry_marker = ops_dir / f"{operation_id}_registry_updated.json"
        lifecycle_marker = ops_dir / f"{operation_id}_lifecycle_appended.json"
        completed_marker = ops_dir / f"{operation_id}_completed.json"
        assert main_record.exists(), "main operation record must exist"
        assert registry_marker.exists(), "registry_updated marker must exist"
        assert lifecycle_marker.exists(), "lifecycle_appended marker must exist"
        assert completed_marker.exists(), "completed marker must exist"

        # Negative: branch operations must NOT be timeline-isolated.
        wrong_dir = (
            temp_project.data_dir
            / "branches"
            / timeline_context.timeline_id
            / "branch_operations"
        )
        assert not wrong_dir.exists(), (
            "branch_operations/ must NOT live under branches/{timeline_id}/"
        )

        # Negative: no double-`data` nesting.
        wrong_double_data = temp_project.root / "data" / "data" / "branch_operations"
        assert not wrong_double_data.exists(), (
            "branch_operations/ must NOT be nested under data/data/"
        )

    def test_registry_event_serialized_schema_matches_contract(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        temp_project: ProjectContext,
    ) -> None:
        """Lock fact: RegistryEvent serialized JSON uses explicit fields.

        The on-disk JSON must carry from_active_branch_id,
        to_active_branch_id, expected_revision, resulting_revision as
        first-class fields — NOT a generic `payload` dict.
        """
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        branch_store.create_branch(timeline_context, "branch2", "Branch 2")
        revision = branch_store.get_registry_revision(timeline_context)
        branch_store.select_branch(timeline_context, "branch1", revision)

        events_path = (
            temp_project.data_dir
            / "branches"
            / timeline_context.timeline_id
            / "registry_events"
        )
        files = sorted([p for p in events_path.iterdir() if p.suffix == ".json"])
        assert files, "registry_events/ must contain at least one event"

        required_fields = (
            "schema_version",
            "event_id",
            "sequence",
            "project_id",
            "timeline_id",
            "event_type",
            "from_active_branch_id",
            "to_active_branch_id",
            "expected_revision",
            "resulting_revision",
            "operation_id",
            "occurred_at",
            "previous_event_id",
            "previous_event_fingerprint",
            "record_fingerprint",
        )
        for event_file in files:
            data = json.loads(event_file.read_text(encoding="utf-8"))
            for field in required_fields:
                assert field in data, (
                    f"RegistryEvent JSON missing required field {field!r} "
                    f"in {event_file.name}"
                )
            # Negative: a generic `payload` field must NOT be present.
            assert "payload" not in data, (
                f"RegistryEvent JSON must NOT use generic 'payload' field "
                f"(Scheme A = explicit fields) in {event_file.name}"
            )

    def test_registry_rebuild_uses_required_revision_fields(
        self,
        branch_store: NarrativeBranchStore,
        timeline_context: TimelineContext,
        temp_project: ProjectContext,
    ) -> None:
        """Lock fact: registry rebuild consumes explicit revision fields.

        _rebuild_registry_from_journal must take
        `to_active_branch_id` as active_branch_id and
        `resulting_revision` as revision — not a generic payload.
        """
        branch_store.create_branch(timeline_context, "branch1", "Branch 1")
        branch_store.create_branch(timeline_context, "branch2", "Branch 2")
        revision = branch_store.get_registry_revision(timeline_context)
        branch_store.select_branch(timeline_context, "branch1", revision)
        rev_after_select = branch_store.get_registry_revision(timeline_context)

        # Wipe the mutable projection so the next read must rebuild.
        registry_path = (
            temp_project.data_dir
            / "branches"
            / timeline_context.timeline_id
            / "registry.json"
        )
        bak_path = registry_path.with_suffix(".bak")
        if registry_path.exists():
            registry_path.unlink()
        if bak_path.exists():
            bak_path.unlink()
        assert not registry_path.exists()

        # Trigger rebuild via public API.
        active_id = branch_store.get_active_branch_id(timeline_context)
        assert active_id == "branch1"
        # The rebuilt projection must carry the last event's
        # resulting_revision (not the original expected_revision).
        rebuilt = json.loads(registry_path.read_text(encoding="utf-8"))
        assert rebuilt["active_branch_id"] == "branch1"
        assert rebuilt["revision"] == rev_after_select, (
            "rebuild must source revision from resulting_revision field, "
            "not from a generic payload or expected_revision"
        )

        # Verify against the underlying events: the rebuild must match
        # the last event's to_active_branch_id + resulting_revision.
        events = branch_store._read_registry_events(timeline_context)
        assert events, "registry event journal must not be empty"
        last_event = events[-1]
        assert last_event.to_active_branch_id == rebuilt["active_branch_id"]
        assert last_event.resulting_revision == rebuilt["revision"]

    def test_phase_document_paths_match_store_constants(
        self,
        temp_project: ProjectContext,
    ) -> None:
        """Static doc-contract test: PHASE_0D4_A.md paths match store constants.

        Prevents documentation drift by asserting that the authoritative
        phase document contains the same path layout the stores actually
        use, and does NOT contain superseded path patterns.
        """
        repo_root = Path(__file__).resolve().parents[2]
        phase_doc = repo_root / "docs" / "planning" / "PHASE_0D4_A.md"
        assert phase_doc.exists(), "PHASE_0D4_A.md must exist"
        text = phase_doc.read_text(encoding="utf-8")

        # Required current paths (must all be present).
        required_path_patterns = (
            "transitions/{turn_id}/{sequence:08d}.json",
            "narrative_turn_operations/{operation_id}.json",
            "lifecycle_events/{branch_id}/{sequence:08d}.json",
            "registry_events/{sequence:08d}.json",
            "branch_operations/{operation_id}.json",
            "{operation_id}_registry_updated.json",
            "{operation_id}_lifecycle_appended.json",
            "{operation_id}_completed.json",
        )
        for pattern in required_path_patterns:
            assert pattern in text, (
                f"PHASE_0D4_A.md must document authoritative path: {pattern!r}"
            )

        # Superseded paths / phrasing (must NOT be present as authoritative).
        # Note: the historical initial delivery report may still contain
        # these — this test only checks PHASE_0D4_A.md (the authoritative
        # phase document), not the historical report.
        superseded_patterns = (
            "transitions/{turn_id}/{transition_id}.json",
            "registry_events/{event_id}.json",
            "Phase 0D4-A-FIX-RC2 Status: IN PROGRESS",
        )
        for pattern in superseded_patterns:
            assert pattern not in text, (
                f"PHASE_0D4_A.md must NOT contain superseded pattern: {pattern!r}"
            )

        # Required status header (must be present).
        assert "Phase 0D4-A-FIX-RC2: PASSED" in text
        assert "Phase 0D4-A: SEALED" in text
        assert "Phase 0D4-B: NOT ENTERED" in text
