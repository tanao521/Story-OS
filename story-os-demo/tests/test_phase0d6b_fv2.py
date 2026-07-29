"""Phase 0D6-B-FV2 verification-only assertions."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from system.cross_chapter_scope import (
    AMBIGUOUS,
    CORRUPT,
    CURRENT,
    UNRELATED,
    ScopeTarget,
    classify_scope_fields,
)
from system.cross_chapter_turn_start_service import (
    CrossChapterTurnStartError,
    CrossChapterTurnStartService,
)
from system.narrative_turn_planner import NarrativeTurnPlanner

from tests.test_phase0d6b_authority import _project, _ready, _start_kwargs, _tree


def test_fv2_shared_classifier_has_stable_four_way_contract():
    target = ScopeTarget("project", "main", "main", 1, 2)
    assert classify_scope_fields(
        {"project_id": "project", "timeline_id": "main", "branch_id": "main"},
        target,
    ) == CURRENT
    assert classify_scope_fields(
        {"project_id": "other", "timeline_id": "main"}, target
    ) == UNRELATED
    assert classify_scope_fields({"timeline_id": "main"}, target) == AMBIGUOUS
    assert classify_scope_fields(
        {"project_id": "other", "timeline_id": 3}, target
    ) == CORRUPT


def test_fv2_plan_phase_without_effect_never_invokes_planner(tmp_path: Path, monkeypatch):
    context, _ = _project(tmp_path)
    ready = _ready(context)
    kwargs = _start_kwargs(context, ready)

    def fault(point: str):
        if point == "after_plan_phase":
            raise RuntimeError(point)

    with pytest.raises(RuntimeError):
        CrossChapterTurnStartService(context, fault_injector=fault).start_turn(**kwargs)
    phase_path = context.data_dir / "chapter_progression" / "operations" / "turn-start.phase.json"
    phase = json.loads(phase_path.read_text(encoding="utf-8"))
    plan_path = context.data_dir / "narrative_turn" / "plans" / "main" / "main" / f"{phase['turn_id']}.json"
    plan_path.unlink()

    def planner_must_not_run(*args, **kwargs):
        raise AssertionError("planner invoked for phase-without-effect recovery")

    monkeypatch.setattr(NarrativeTurnPlanner, "build_plan", planner_must_not_run)
    with pytest.raises(CrossChapterTurnStartError) as caught:
        CrossChapterTurnStartService(context).start_turn(**kwargs)
    assert caught.value.code == "CORRUPT_OPERATION"
    assert not plan_path.exists()


def test_fv2_archive_claim_only_is_fail_closed(tmp_path: Path):
    context, _ = _project(tmp_path)
    operations = context.data_dir / "chapter_progression" / "operations"
    operations.mkdir(parents=True, exist_ok=True)
    (operations / "claim-only.json").write_text(json.dumps({
        "operation_id": "claim-only",
        "request": {
            "project_id": context.root.name,
            "timeline_id": "main",
            "branch_id": "main",
        },
    }), encoding="utf-8")
    with pytest.raises(CrossChapterTurnStartError) as caught:
        CrossChapterTurnStartService(context).assert_branch_archive_safe("main", "main")
    assert caught.value.code == "TURN_START_RECOVERY_REQUIRED"


def test_fv2_completed_replay_is_byte_stable_after_current_planning_drift(tmp_path: Path):
    context, _ = _project(tmp_path)
    ready = _ready(context)
    service = CrossChapterTurnStartService(context)
    kwargs = _start_kwargs(context, ready)
    first = service.start_turn(**kwargs)
    result_path = context.data_dir / "chapter_progression" / "operations" / "turn-start.result.json"
    before = result_path.read_bytes()
    planning_path = context.data_dir / "next_chapter_plan.json"
    planning = json.loads(planning_path.read_text(encoding="utf-8"))
    planning["revision"] = "post-completion-drift"
    planning_path.write_text(json.dumps(planning), encoding="utf-8")
    replay = CrossChapterTurnStartService(context).start_turn(**kwargs)
    assert replay == first
    assert result_path.read_bytes() == before


def test_fv2_successful_start_respects_filesystem_allowlist(tmp_path: Path):
    context, _ = _project(tmp_path)
    ready = _ready(context)
    before = _tree(tmp_path)
    result = CrossChapterTurnStartService(context).start_turn(**_start_kwargs(context, ready))
    after = _tree(tmp_path)
    changed = {path.replace("\\", "/") for path in set(after) - set(before)}
    allowed = {
        "data/chapter_progression/operations/turn-start.json",
        "data/chapter_progression/operations/turn-start.phase.json",
        "data/chapter_progression/operations/turn-start.result.json",
    }
    assert allowed <= changed
    assert all(
        path in allowed
        or path.startswith(f"data/narrative_turn/plans/main/main/{result['turn_id']}.json")
        or path.startswith(f"data/narrative_turn/transitions/main/main/{result['turn_id']}/")
        for path in changed
    )
