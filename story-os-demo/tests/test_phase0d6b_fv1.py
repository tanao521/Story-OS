"""Phase 0D6-B-FV1 final authority and recovery verification.

This file is verification-only.  It deliberately does not patch production
behavior when a gate exposes an unsafe implementation; such a failure is
reported as an RC2 requirement by the FV1 delivery report.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from system.cross_chapter_readiness_service import _fingerprint
from system.cross_chapter_turn_start_service import (
    CrossChapterTurnStartError,
    CrossChapterTurnStartService,
)
from system.narrative_turn_service import NarrativeTurnService
from system.narrative_turn_store import NarrativeTurnStore
from core.contracts.narrative_turn import NarrativeScope

from tests.test_phase0d6b_authority import _project, _ready, _start_kwargs, _tree


def _lifecycle_root(context):
    return context.data_dir / "chapter_lifecycle" / "operations"


def _progression_root(context):
    return context.data_dir / "chapter_progression" / "operations"


def _rewrite_result(path: Path, mutate) -> None:
    result = json.loads(path.read_text(encoding="utf-8"))
    mutate(result)
    body = dict(result)
    body.pop("outcome_fingerprint", None)
    result["outcome_fingerprint"] = _fingerprint(body)
    path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


def _assert_no_residue(context) -> None:
    data = context.data_dir
    assert not list(data.rglob("*.tmp"))
    assert not list((data / "narrative_turn" / ".locks").glob("*/owner.json"))
    assert not list((data / "narrative_turn" / ".locks").glob("*.lock"))


def test_fv1_valid_bundle_is_unique_and_get_is_zero_diff(tmp_path: Path):
    context, _ = _project(tmp_path)
    before = _tree(tmp_path)
    ready = _ready(context)
    assert ready["readiness_code"] == "READY_TO_START_TURN"
    assert _tree(tmp_path) == before


@pytest.mark.parametrize("kind", ["claim", "phase", "result"])
def test_fv1_lifecycle_single_record_is_incomplete_or_corrupt_without_write(
    tmp_path: Path, kind: str
):
    context, _ = _project(tmp_path)
    root = _lifecycle_root(context)
    for path in root.glob("chapter-create*.json"):
        path.unlink()
    source = {
        "claim": root / "chapter-create.json",
        "phase": root / "chapter-create.phase.json",
        "result": root / "chapter-create.result.json",
    }
    # Rebuild one selected record from the original project fixture.
    context2, _ = _project(tmp_path / "reference")
    source_ref = _lifecycle_root(context2) / f"chapter-create{'' if kind == 'claim' else '.' + kind}.json"
    target = root / source_ref.name
    target.write_bytes(source_ref.read_bytes())
    before = _tree(tmp_path)
    readiness = _ready(context)
    assert readiness["readiness_code"] in {
        "BLOCKED_LIFECYCLE_NOT_CREATED", "BLOCKED_LIFECYCLE_INCOMPLETE",
        "BLOCKED_CORRUPT_AUTHORITY",
    }
    assert _tree(tmp_path) == before


def test_fv1_result_operation_id_mismatch_fails_closed(tmp_path: Path):
    context, _ = _project(tmp_path)
    result = _lifecycle_root(context) / "chapter-create.result.json"
    _rewrite_result(result, lambda value: value.update({"operation_id": "other-op"}))
    before = _tree(tmp_path)
    assert _ready(context)["readiness_code"] == "BLOCKED_CORRUPT_AUTHORITY"
    assert _tree(tmp_path) == before


def test_fv1_orphan_result_in_other_scope_does_not_block_current_readiness(tmp_path: Path):
    context, _ = _project(tmp_path)
    orphan = _lifecycle_root(context) / "other-timeline.result.json"
    orphan.write_text(json.dumps({"project_id": context.root.name, "timeline_id": "other"}), encoding="utf-8")
    # The current implementation has no scope-bearing association for an
    # orphan; this test makes that safety boundary explicit.
    readiness = _ready(context)
    assert readiness["readiness_code"] == "READY_TO_START_TURN"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("project_id", "foreign-project"),
        ("timeline_id", "other"),
        ("branch_id", "foreign-branch"),
        ("previous_chapter_id", 99),
        ("successor_chapter_id", 99),
        ("expected_readiness_fingerprint", "0" * 64),
    ],
)
def test_fv1_client_assertions_fail_before_start_write(tmp_path: Path, field: str, value):
    context, _ = _project(tmp_path)
    ready = _ready(context)
    kwargs = _start_kwargs(context, ready, "assertion-check")
    kwargs[field] = value
    before = _tree(tmp_path)
    with pytest.raises(CrossChapterTurnStartError):
        CrossChapterTurnStartService(context).start_turn(**kwargs)
    assert _tree(tmp_path) == before


def test_fv1_planning_drift_fails_closed_at_start(tmp_path: Path):
    context, _ = _project(tmp_path)
    ready = _ready(context)
    planning = context.data_dir / "next_chapter_plan.json"
    payload = json.loads(planning.read_text(encoding="utf-8"))
    payload["revision"] = "drifted"
    planning.write_text(json.dumps(payload), encoding="utf-8")
    before = _tree(tmp_path)
    with pytest.raises(CrossChapterTurnStartError) as caught:
        CrossChapterTurnStartService(context).start_turn(**_start_kwargs(context, ready))
    assert caught.value.code in {"TURN_START_SOURCE_CHANGED", "BLOCKED_PLANNING_STALE"}
    assert _tree(tmp_path) == before


def test_fv1_source_drift_fails_closed_at_start(tmp_path: Path):
    context, _ = _project(tmp_path)
    ready = _ready(context)
    source = context.data_dir / "chapters" / "chapter_002.md"
    if not source.exists():
        pytest.skip("fixture does not materialize successor source")
    source.write_text(source.read_text(encoding="utf-8") + "\nDrift.", encoding="utf-8")
    before = _tree(tmp_path)
    with pytest.raises(CrossChapterTurnStartError) as caught:
        CrossChapterTurnStartService(context).start_turn(**_start_kwargs(context, ready))
    assert caught.value.code == "TURN_START_SOURCE_CHANGED"
    assert _tree(tmp_path) == before


@pytest.mark.parametrize(
    "fault_point",
    [
        "after_claim",
        "after_plan_effect",
        "after_plan_phase",
        "after_turn_delegate",
        "after_transition_effect",
        "after_transition_phase",
        "after_result",
        "after_result_phase",
        "after_completed_phase",
    ],
)
def test_fv1_fault_boundaries_replay_exactly_once(tmp_path: Path, fault_point: str):
    context, _ = _project(tmp_path)
    ready = _ready(context)
    kwargs = _start_kwargs(context, ready)

    def fault(point: str):
        if point == fault_point:
            raise RuntimeError(point)

    with pytest.raises(RuntimeError):
        CrossChapterTurnStartService(context, fault_injector=fault).start_turn(**kwargs)
    result = CrossChapterTurnStartService(context).start_turn(**kwargs)
    assert result["turn_status"] == "awaiting_action"
    scope = NarrativeScope(context.root.name, "main", "main")
    store = NarrativeTurnStore(context)
    assert len([p for p in store.list_plans(scope) if store.get_plan(scope, p).chapter_id == 2]) == 1
    assert len(store.get_transitions(scope, result["turn_id"])) == 1
    assert (_progression_root(context) / "turn-start.result.json").exists()
    assert json.loads((_progression_root(context) / "turn-start.phase.json").read_text(encoding="utf-8"))["phase"] == "completed"
    _assert_no_residue(context)


def test_fv1_phase_without_plan_effect_is_not_guessed(tmp_path: Path):
    context, _ = _project(tmp_path)
    ready = _ready(context)

    def fault(point: str):
        if point == "after_plan_phase":
            raise RuntimeError(point)

    kwargs = _start_kwargs(context, ready)
    with pytest.raises(RuntimeError):
        CrossChapterTurnStartService(context, fault_injector=fault).start_turn(**kwargs)
    phase = json.loads((_progression_root(context) / "turn-start.phase.json").read_text(encoding="utf-8"))
    plan = context.data_dir / "narrative_turn" / "plans" / "main" / "main" / f"{phase['turn_id']}.json"
    plan.unlink()
    with pytest.raises(CrossChapterTurnStartError) as caught:
        CrossChapterTurnStartService(context).start_turn(**kwargs)
    assert caught.value.code == "CORRUPT_OPERATION"


def test_fv1_completed_replay_detects_transition_tamper(tmp_path: Path):
    context, _ = _project(tmp_path)
    ready = _ready(context)
    service = CrossChapterTurnStartService(context)
    result = service.start_turn(**_start_kwargs(context, ready))
    transition_dir = context.data_dir / "narrative_turn" / "transitions" / "main" / "main" / result["turn_id"]
    transition = next(transition_dir.glob("*.json"))
    payload = json.loads(transition.read_text(encoding="utf-8"))
    payload["record_fingerprint"] = "0" * 64
    transition.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CrossChapterTurnStartError) as caught:
        service.start_turn(**_start_kwargs(context, ready))
    assert caught.value.code == "CORRUPT_OPERATION"


def test_fv1_initial_lock_path_is_shared_by_start_and_confirmation(tmp_path: Path):
    context, _ = _project(tmp_path)
    start = CrossChapterTurnStartService(context)
    turn = NarrativeTurnService(context)
    key = f"{context.root.name}:main:main:2"
    assert start.turn_service._lock_path("initial-turn", key) == turn._lock_path("initial-turn", key)


def test_fv1_archive_rejects_orphan_current_scope_result(tmp_path: Path):
    context, _ = _project(tmp_path)
    orphan = _progression_root(context) / "turn-start.result.json"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text(json.dumps({
        "operation_id": "turn-start", "project_id": context.root.name,
        "timeline_id": "main", "branch_id": "main",
    }), encoding="utf-8")
    with pytest.raises(CrossChapterTurnStartError) as caught:
        CrossChapterTurnStartService(context).assert_branch_archive_safe("main", "main")
    assert caught.value.code == "TURN_START_RECOVERY_REQUIRED"
