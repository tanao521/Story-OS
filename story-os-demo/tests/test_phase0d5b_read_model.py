from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.contracts.narrative_turn import (
    ActionType,
    NarrativeActionOption,
    NarrativeCustomActionPolicy,
    NarrativeScope,
    NarrativeTurnPlan,
    NarrativeTurnResult,
    NarrativeTurnTransition,
    ResultStatus,
    TurnState,
    TimelineContext,
    now_utc,
    new_id,
)
from core.project_context import get_project_context
from system.narrative_branch_lifecycle_service import BranchLifecycleService
from system.narrative_turn_store import NarrativeTurnStore
from system.simulator_loop_state import SimulatorLoopStateService


def make_context(tmp_path: Path):
    context = get_project_context(tmp_path)
    context.chapters_dir.mkdir(parents=True, exist_ok=True)
    return context


def seed_branch(context, branch_id: str = "root"):
    service = BranchLifecycleService(context)
    service.create(f"create-{branch_id}", {"project_id": context.root.name, "timeline_id": "main", "branch_id": branch_id, "display_name": branch_id})
    service.select(f"select-{branch_id}", {"project_id": context.root.name, "timeline_id": "main", "branch_id": branch_id})
    return NarrativeScope(context.root.name, "main", branch_id)


def seed_turn(context, scope: NarrativeScope, turn_id: str = "turn-1"):
    store = NarrativeTurnStore(context)
    actions = tuple(
        NarrativeActionOption(f"a-{i}", ActionType.ADVANCE, f"Action {i}", f"intent-{i}", (), (), (), (), "deterministic-planner", i)
        for i in (1, 2, 3)
    )
    plan = NarrativeTurnPlan("1.0", turn_id, scope, 1, "manual_v001", None, "a" * 64, "planner-1", None, now_utc(), actions, NarrativeCustomActionPolicy(500, (), ("scope",)))
    store.append_plan(plan)
    result = NarrativeTurnResult("1.0", turn_id, scope, 1, "a-1", None, ResultStatus.SUCCESS, "The door opens.", (("door", "open"),), (), "b" * 64, "rev-1", "c" * 64, now_utc(), f"op-{turn_id}")
    store.append_result(result)
    previous_id = previous_fp = None
    state = TurnState.PLANNED
    for next_state, reason in ((TurnState.AWAITING_ACTION, "plan"), (TurnState.VALIDATING, "validate"), (TurnState.VALIDATED, "validated"), (TurnState.PREVIEWED, "preview"), (TurnState.CONFIRMED, "confirm"), (TurnState.APPLIED_TO_BRANCH, "apply")):
        payload = f"{turn_id}:{state.value}:{next_state.value}:{len(store.get_transitions(scope, turn_id))}"
        fp = hashlib.sha256(payload.encode()).hexdigest()
        transition = NarrativeTurnTransition("1.0", new_id("trn"), turn_id, scope, state, next_state, reason, result.operation_id, now_utc(), fp, len(store.get_transitions(scope, turn_id)), previous_id, previous_fp)
        store.append_transition(transition)
        previous_id, previous_fp, state = transition.transition_id, transition.record_fingerprint, next_state


def test_read_model_scope_branch_and_no_authority_write(tmp_path: Path):
    context = make_context(tmp_path)
    scope = seed_branch(context)
    before = sorted(p.relative_to(context.data_dir).as_posix() for p in context.data_dir.rglob("*"))
    state = SimulatorLoopStateService(context).build(project_id=context.root.name, timeline_id="main", chapter_id=1, branch_id=scope.branch_id)
    after = sorted(p.relative_to(context.data_dir).as_posix() for p in context.data_dir.rglob("*"))
    assert state.scope["branch_id"] == "root"
    assert state.branch["active"] is True
    assert state.approval["status"] == "none"
    assert state.approval["can_commit"] is False
    assert before == after


def test_read_model_turn_state_and_history_are_immutable_views(tmp_path: Path):
    context = make_context(tmp_path)
    scope = seed_branch(context)
    seed_turn(context, scope)
    state = SimulatorLoopStateService(context).build(project_id=context.root.name, timeline_id="main", chapter_id=1, branch_id=scope.branch_id)
    assert state.current_stage == "TURN"
    assert state.turn["history"][0]["turn_id"] == "turn-1"
    assert state.turn["history"][0]["lifecycle"] == "applied_to_branch"
    assert "edit" not in state.turn["history"][0]


def test_simulator_state_route_is_registered_and_no_store():
    from web.app import app

    routes = {}
    for route in app.routes:
        original = getattr(route, "original_router", None)
        for child in getattr(original or route, "routes", [route]):
            routes[getattr(child, "path", "")] = child
    assert "/api/simulator/state" in routes
    assert routes["/api/simulator/state"].methods == {"GET"}
