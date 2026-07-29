"""Phase 0D4-D-RC1 authority, concurrency, and recovery closure tests."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from core.contracts.narrative_turn import NarrativeTurnError, TurnState
from core.project_context import get_project_context
from system.narrative_turn_context import NarrativeTurnContextBinder
from system.narrative_turn_planner import NarrativeTurnPlanner
from system.narrative_turn_service import ConfirmOperationPhase, NarrativeTurnService
from system.narrative_turn_store import NarrativeTurnStore
from tests.test_phase0d4d_narrative_turn_service import (
    _build_plan,
    _create_branch,
    _make_scope,
    _seed_minimal_project,
)


def _project(root: Path):
    root.mkdir(parents=True)
    ctx = get_project_context(root)
    _seed_minimal_project(ctx)
    _create_branch(ctx, "tl-main", "br-alpha")
    return ctx


def _request(ctx, *, operation_id: str, branch_id: str = "br-alpha", chapter_id: int = 1):
    scope = _make_scope(ctx, "tl-main", branch_id)
    plan = _build_plan(ctx, scope)
    return {
        "operation_id": operation_id,
        "scope": scope,
        "chapter_id": chapter_id,
        "source_version_id": None,
        "expected_context_fingerprint": None,
        "expected_turn_id": None,
        "expected_validation_id": None,
        "expected_preview_fingerprint": None,
        "action_source": "recommended",
        "selected_action_id": plan.recommended_actions[0].action_id,
    }


def test_confirm_projection_is_read_by_context_binder(tmp_path: Path) -> None:
    ctx = _project(tmp_path / "project")
    request = _request(ctx, operation_id="op-rc1-state")
    binder = NarrativeTurnContextBinder(ctx)
    before = binder.bind(request["scope"], 1)

    confirmed = NarrativeTurnService(ctx).confirm_turn(**request)
    rebound = binder.bind(request["scope"], 1)

    assert rebound.branch_state_revision == confirmed.branch_state_revision
    assert rebound.narrative_state_dict()["last_turn_id"] == confirmed.result.turn_id
    assert rebound.context_fingerprint != before.context_fingerprint
    assert rebound.context_fingerprint == confirmed.result.next_context_fingerprint


def test_project_a_state_never_visible_to_project_b(tmp_path: Path) -> None:
    ctx_a = _project(tmp_path / "a" / "project")
    ctx_b = _project(tmp_path / "b" / "project")
    request_a = _request(ctx_a, operation_id="op-shared")
    request_b = _request(ctx_b, operation_id="op-shared")

    result_a = NarrativeTurnService(ctx_a).confirm_turn(**request_a)
    before_b = NarrativeTurnContextBinder(ctx_b).bind(request_b["scope"], 1)
    result_b = NarrativeTurnService(ctx_b).confirm_turn(**request_b)

    assert result_a.result.operation_id == result_b.result.operation_id
    assert result_a.result.fingerprint() != result_b.result.fingerprint()
    assert before_b.narrative_state_dict().get("last_turn_id") is None


def test_no_duplicate_project_id_segment_in_state_path(tmp_path: Path) -> None:
    ctx = _project(tmp_path / "project")
    request = _request(ctx, operation_id="op-path")
    state_path = NarrativeTurnService(ctx)._branch_state_path(request["scope"])
    relative = state_path.relative_to(ctx.root)
    assert relative.as_posix() == "data/narrative_memory/state/tl-main/br-alpha/current.json"
    assert relative.parts.count(ctx.root.name) == 0


def test_context_binder_fails_closed_on_projected_state_revision_tamper(
    tmp_path: Path,
) -> None:
    ctx = _project(tmp_path / "project")
    request = _request(ctx, operation_id="op-state-integrity")
    NarrativeTurnService(ctx).confirm_turn(**request)
    state_path = (
        ctx.narrative_state_dir / "tl-main" / "br-alpha" / "current.json"
    )
    import json

    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["last_result_status"] = "tampered"
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    rebound = NarrativeTurnContextBinder(ctx).bind(request["scope"], 1)
    assert rebound.branch_state_revision is None
    assert "BRANCH_STATE_INVALID" in rebound.limitations


def test_operation_id_scope_and_payload_authority(tmp_path: Path) -> None:
    ctx = _project(tmp_path / "project")
    request = _request(ctx, operation_id="op-authority")
    service = NarrativeTurnService(ctx)
    first = service.confirm_turn(**request)
    replay = NarrativeTurnService(ctx).confirm_turn(**request)
    assert replay.idempotent_replay is True
    assert replay.result.fingerprint() == first.result.fingerprint()

    changed = dict(request)
    changed["selected_action_id"] = _build_plan(ctx, request["scope"]).recommended_actions[1].action_id
    with pytest.raises(NarrativeTurnError) as exc:
        NarrativeTurnService(ctx).confirm_turn(**changed)
    assert exc.value.code == NarrativeTurnError.OPERATION_COLLISION

    authority = ctx.data_dir / "narrative_turn" / "operations" / "op-authority.json"
    assert authority.exists()


def test_operation_record_scope_mismatch_fails_closed(tmp_path: Path) -> None:
    ctx = _project(tmp_path / "project")
    request = _request(ctx, operation_id="op-scope-tamper")
    NarrativeTurnService(ctx).confirm_turn(**request)
    authority = (
        ctx.data_dir / "narrative_turn" / "operations" / "op-scope-tamper.json"
    )
    import json

    record = json.loads(authority.read_text(encoding="utf-8"))
    record["scope"]["branch_id"] = "other"
    authority.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(NarrativeTurnError) as exc:
        NarrativeTurnService(ctx).confirm_turn(**request)
    assert exc.value.code == NarrativeTurnError.OPERATION_COLLISION


def test_same_operation_different_branch_and_timeline_conflicts(tmp_path: Path) -> None:
    ctx = _project(tmp_path / "project")
    _create_branch(ctx, "tl-other", "br-other")
    request = _request(ctx, operation_id="op-cross-scope")
    NarrativeTurnService(ctx).confirm_turn(**request)

    other = dict(request)
    other["scope"] = _make_scope(ctx, "tl-other", "br-other")
    with pytest.raises(NarrativeTurnError) as exc:
        NarrativeTurnService(ctx).confirm_turn(**other)
    assert exc.value.code == NarrativeTurnError.OPERATION_COLLISION


@pytest.mark.parametrize("operation_id", ["../escape", r"..\escape", "nested/op"])
def test_operation_id_path_traversal_rejected(tmp_path: Path, operation_id: str) -> None:
    ctx = _project(tmp_path / "project")
    request = _request(ctx, operation_id=operation_id)
    with pytest.raises(NarrativeTurnError) as exc:
        NarrativeTurnService(ctx).confirm_turn(**request)
    assert exc.value.code == NarrativeTurnError.INVALID_ID


class _BarrierService(NarrativeTurnService):
    def __init__(self, *args, barrier: Barrier, **kwargs):
        super().__init__(*args, **kwargs)
        self._barrier = barrier

    def confirm_turn(self, **kwargs):
        self._barrier.wait(timeout=10)
        return super().confirm_turn(**kwargs)


def test_result_first_writer_wins_two_services(tmp_path: Path) -> None:
    ctx = _project(tmp_path / "project")
    barrier = Barrier(2)
    requests = [
        _request(ctx, operation_id="op-race-a"),
        _request(ctx, operation_id="op-race-b"),
    ]

    def run(request):
        try:
            return _BarrierService(ctx, barrier=barrier).confirm_turn(**request)
        except NarrativeTurnError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(run, requests))

    successes = [item for item in outcomes if not isinstance(item, Exception)]
    failures = [item for item in outcomes if isinstance(item, NarrativeTurnError)]
    assert len(successes) == 1
    assert [item.code for item in failures] == [NarrativeTurnError.TURN_ALREADY_CONFIRMED]

    winner = successes[0]
    store = NarrativeTurnStore(ctx)
    transitions = store.get_transitions(requests[0]["scope"], winner.result.turn_id)
    assert sum(t.to_state == TurnState.CONFIRMED for t in transitions) == 1
    assert sum(t.to_state == TurnState.APPLIED_TO_BRANCH for t in transitions) == 1
    assert len(NarrativeTurnService(ctx)._read_branch_events(requests[0]["scope"])) == 1


def test_two_turns_same_branch_keep_single_event_chain_and_both_applications(
    tmp_path: Path,
) -> None:
    ctx = _project(tmp_path / "project")
    planning_path = ctx.data_dir / "story_planning.json"
    import json

    planning = json.loads(planning_path.read_text(encoding="utf-8"))
    planning["chapters"].append(
        {
            "chapter_id": "ch-002-test",
            "chapter_number": 2,
            "title": "Chapter two",
            "goal": "Continue",
            "conflicts": [],
            "plot_threads": [],
        }
    )
    planning_path.write_text(json.dumps(planning, ensure_ascii=False), encoding="utf-8")
    (ctx.chapters_dir / "chapter_002.md").write_text("# Chapter two\n", encoding="utf-8")

    scope = _make_scope(ctx, "tl-main", "br-alpha")

    def request_for(chapter_id: int, operation_id: str):
        snapshot = NarrativeTurnContextBinder(ctx).bind(scope, chapter_id)
        plan = NarrativeTurnPlanner.build_plan(
            snapshot, parent_turn_id=None, clock_now="2025-01-15T12:00:00+00:00"
        )
        return {
            "operation_id": operation_id,
            "scope": scope,
            "chapter_id": chapter_id,
            "source_version_id": None,
            "expected_context_fingerprint": None,
            "expected_turn_id": None,
            "expected_validation_id": None,
            "expected_preview_fingerprint": None,
            "action_source": "recommended",
            "selected_action_id": plan.recommended_actions[0].action_id,
        }

    barrier = Barrier(2)
    requests = [request_for(1, "op-turn-1"), request_for(2, "op-turn-2")]

    def run(request):
        return _BarrierService(ctx, barrier=barrier).confirm_turn(**request)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, requests))

    events = NarrativeTurnService(ctx)._read_branch_events(scope)
    assert [event["sequence"] for event in events] == [0, 1]
    assert events[1]["previous_event_fingerprint"] == events[0]["record_fingerprint"]
    state = NarrativeTurnContextBinder(ctx).bind(scope, 2).narrative_state_dict()
    assert len(state["applied_result_fingerprints"]) == 2
    assert {result.result.fingerprint() for result in results} == set(
        state["applied_result_fingerprints"]
    )


FAULT_POINTS = (
    "after_result_publish",
    "after_plan_append",
    "after_validation_append",
    "after_previewed_transition",
    "after_confirmed_transition",
    "after_branch_event_append",
    "before_projection_replace",
    "after_projection_replace",
    "after_applied_transition",
    "before_completed_marker",
)


@pytest.mark.parametrize("fault_point", FAULT_POINTS)
def test_restart_recovery_at_all_fault_points(tmp_path: Path, fault_point: str) -> None:
    ctx = _project(tmp_path / fault_point / "project")
    request = _request(ctx, operation_id=f"op-{fault_point.replace('_', '-')}")

    def inject(point: str) -> None:
        if point == fault_point:
            raise RuntimeError(f"fault:{point}")

    with pytest.raises(RuntimeError, match=fault_point):
        NarrativeTurnService(ctx, fault_injector=inject).confirm_turn(**request)

    recovered = NarrativeTurnService(ctx).confirm_turn(**request)
    assert recovered.idempotent_replay is True
    assert recovered.recovery_performed is True
    assert recovered.final_phase == ConfirmOperationPhase.COMPLETED

    store = NarrativeTurnStore(ctx)
    assert len(store.list_plans(request["scope"])) == 1
    assert store.get_result(request["scope"], recovered.result.turn_id) is not None
    events = NarrativeTurnService(ctx)._read_branch_events(request["scope"])
    assert len(events) == 1
    transitions = store.get_transitions(request["scope"], recovered.result.turn_id)
    assert sum(t.to_state == TurnState.CONFIRMED for t in transitions) == 1
    assert sum(t.to_state == TurnState.APPLIED_TO_BRANCH for t in transitions) == 1
