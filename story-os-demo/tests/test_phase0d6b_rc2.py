"""Phase 0D6-B-RC2 closure matrix."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from system.cross_chapter_readiness_service import _fingerprint
from system.cross_chapter_turn_start_service import (
    CrossChapterTurnStartError,
    CrossChapterTurnStartService,
)
from system.narrative_turn_store import NarrativeTurnStore
from core.contracts.narrative_turn import NarrativeScope

from tests.test_phase0d6b_authority import _project, _ready, _start_kwargs, _tree


def _lifecycle_root(context: object) -> Path:
    return context.data_dir / "chapter_lifecycle" / "operations"  # type: ignore[attr-defined]


def _progression_root(context: object) -> Path:
    return context.data_dir / "chapter_progression" / "operations"  # type: ignore[attr-defined]


def _write_orphan(root: Path, name: str, payload: dict, suffix: str = ".result.json") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}{suffix}").write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.parametrize(
    "payload",
    [
        {"project_id": "other-project", "timeline_id": "main"},
        {"project_id": "placeholder", "timeline_id": "other"},
        {"project_id": "placeholder", "timeline_id": "main", "branch_id": "sibling"},
        {"project_id": "placeholder", "timeline_id": "main", "branch_id": "main", "previous_chapter_id": 99},
    ],
)
def test_rc2_unrelated_lifecycle_orphans_do_not_block(tmp_path: Path, payload: dict):
    context, _ = _project(tmp_path)
    payload = {**payload}
    if payload["project_id"] == "placeholder":
        payload["project_id"] = context.root.name
    _write_orphan(_lifecycle_root(context), "unrelated", payload)
    before = _tree(tmp_path)
    assert _ready(context)["readiness_code"] == "READY_TO_START_TURN"
    assert _tree(tmp_path) == before


def test_rc2_other_timeline_scoped_phase_orphan_does_not_block(tmp_path: Path):
    context, _ = _project(tmp_path)
    _write_orphan(
        _lifecycle_root(context), "other-phase", {
            "project_id": context.root.name, "timeline_id": "other",
            "branch_id": "main", "previous_chapter_id": 1,
            "successor_chapter_id": 2,
        }, ".phase.json")
    before = _tree(tmp_path)
    assert _ready(context)["readiness_code"] == "READY_TO_START_TURN"
    assert _tree(tmp_path) == before


def test_rc2_other_timeline_incomplete_claim_does_not_block(tmp_path: Path):
    context, _ = _project(tmp_path)
    source = json.loads((_lifecycle_root(context) / "chapter-create.json").read_text(encoding="utf-8"))
    request = dict(source["request"])
    request["timeline_id"] = "other"
    source["request"] = request
    source["request_fingerprint"] = _fingerprint(request)
    (_lifecycle_root(context) / "other-claim.json").write_text(
        json.dumps(source), encoding="utf-8"
    )
    before = _tree(tmp_path)
    assert _ready(context)["readiness_code"] == "READY_TO_START_TURN"
    assert _tree(tmp_path) == before


def test_rc2_scope_mismatch_inside_current_bundle_fails_closed(tmp_path: Path):
    context, _ = _project(tmp_path)
    result_path = _lifecycle_root(context) / "chapter-create.result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["timeline_id"] = "other"
    body = dict(result)
    body.pop("outcome_fingerprint", None)
    result["outcome_fingerprint"] = _fingerprint(body)
    result_path.write_text(json.dumps(result), encoding="utf-8")
    before = _tree(tmp_path)
    assert _ready(context)["readiness_code"] == "BLOCKED_CORRUPT_AUTHORITY"
    assert _tree(tmp_path) == before


def test_rc2_malformed_claim_request_fails_closed(tmp_path: Path):
    context, _ = _project(tmp_path)
    claim_path = _lifecycle_root(context) / "chapter-create.json"
    claim = json.loads(claim_path.read_text(encoding="utf-8"))
    claim["request"] = []
    claim_path.write_text(json.dumps(claim), encoding="utf-8")
    assert _ready(context)["readiness_code"] == "BLOCKED_CORRUPT_AUTHORITY"


@pytest.mark.parametrize("suffix", [".phase.json", ".result.json"])
def test_rc2_current_scope_orphan_blocks_readiness_without_repair(tmp_path: Path, suffix: str):
    context, _ = _project(tmp_path)
    payload = {
        "project_id": context.root.name,
        "timeline_id": "main",
        "branch_id": "main",
        "previous_chapter_id": 1,
        "successor_chapter_id": 2,
    }
    _write_orphan(_lifecycle_root(context), "current", payload, suffix)
    before = _tree(tmp_path)
    readiness = _ready(context)
    assert readiness["readiness_code"] in {"BLOCKED_LIFECYCLE_INCOMPLETE", "BLOCKED_CORRUPT_AUTHORITY"}
    assert _tree(tmp_path) == before


@pytest.mark.parametrize(
    "payload",
    [{}, {"project_id": "bad", "timeline_id": 5}, {"project_id": "bad", "timeline_id": "main", "branch_id": None}],
)
def test_rc2_ambiguous_or_malformed_lifecycle_orphan_fails_closed(tmp_path: Path, payload: dict):
    context, _ = _project(tmp_path)
    _write_orphan(_lifecycle_root(context), "ambiguous", payload)
    before = _tree(tmp_path)
    assert _ready(context)["readiness_code"] == "BLOCKED_CORRUPT_AUTHORITY"
    assert _tree(tmp_path) == before


def test_rc2_plan_phase_without_effect_fails_without_new_plan(tmp_path: Path):
    context, _ = _project(tmp_path)
    ready = _ready(context)
    kwargs = _start_kwargs(context, ready)

    def fault(point: str):
        if point == "after_plan_phase":
            raise RuntimeError(point)

    with pytest.raises(RuntimeError):
        CrossChapterTurnStartService(context, fault_injector=fault).start_turn(**kwargs)
    phase_path = _progression_root(context) / "turn-start.phase.json"
    phase = json.loads(phase_path.read_text(encoding="utf-8"))
    plan_path = context.data_dir / "narrative_turn" / "plans" / "main" / "main" / f"{phase['turn_id']}.json"
    plan_path.unlink()
    before = _tree(tmp_path)
    with pytest.raises(CrossChapterTurnStartError) as caught:
        CrossChapterTurnStartService(context).start_turn(**kwargs)
    assert caught.value.code == "CORRUPT_OPERATION"
    assert not plan_path.exists()
    assert _tree(tmp_path) == before


def test_rc2_transition_phase_without_effect_fails_closed(tmp_path: Path):
    context, _ = _project(tmp_path)
    ready = _ready(context)

    def fault(point: str):
        if point == "after_transition_phase":
            raise RuntimeError(point)

    kwargs = _start_kwargs(context, ready)
    with pytest.raises(RuntimeError):
        CrossChapterTurnStartService(context, fault_injector=fault).start_turn(**kwargs)
    phase = json.loads((_progression_root(context) / "turn-start.phase.json").read_text(encoding="utf-8"))
    transitions = context.data_dir / "narrative_turn" / "transitions" / "main" / "main" / phase["turn_id"]
    for path in transitions.glob("*.json"):
        path.unlink()
    with pytest.raises(CrossChapterTurnStartError) as caught:
        CrossChapterTurnStartService(context).start_turn(**kwargs)
    assert caught.value.code == "CORRUPT_OPERATION"
    assert not list(transitions.glob("*.json"))


@pytest.mark.parametrize("phase_name", ["result_published", "completed"])
def test_rc2_result_phase_without_result_fails_closed(tmp_path: Path, phase_name: str):
    context, _ = _project(tmp_path)
    ready = _ready(context)
    kwargs = _start_kwargs(context, ready)

    def fault(point: str):
        if point == "after_plan_phase":
            raise RuntimeError(point)

    with pytest.raises(RuntimeError):
        CrossChapterTurnStartService(context, fault_injector=fault).start_turn(**kwargs)
    phase_path = _progression_root(context) / "turn-start.phase.json"
    phase = json.loads(phase_path.read_text(encoding="utf-8"))
    phase["phase"] = phase_name
    phase_path.write_text(json.dumps(phase), encoding="utf-8")
    with pytest.raises(CrossChapterTurnStartError) as caught:
        CrossChapterTurnStartService(context).start_turn(**kwargs)
    assert caught.value.code == "CORRUPT_OPERATION"


@pytest.mark.parametrize(
    "payload",
    [
        {"project_id": "other-project", "timeline_id": "main", "branch_id": "main"},
        {"project_id": "placeholder", "timeline_id": "other", "branch_id": "main"},
        {"project_id": "placeholder", "timeline_id": "main", "branch_id": "sibling"},
    ],
)
def test_rc2_unrelated_archive_orphans_do_not_block(tmp_path: Path, payload: dict):
    context, _ = _project(tmp_path)
    if payload["project_id"] == "placeholder":
        payload = {**payload, "project_id": context.root.name}
    _write_orphan(_progression_root(context), "unrelated", payload)
    CrossChapterTurnStartService(context).assert_branch_archive_safe("main", "main")


@pytest.mark.parametrize("suffix", [".phase.json", ".result.json"])
def test_rc2_current_archive_orphans_block_without_registry_mutation(tmp_path: Path, suffix: str):
    context, branches = _project(tmp_path)
    _write_orphan(
        _progression_root(context), "current", {
            "project_id": context.root.name, "timeline_id": "main", "branch_id": "main"
        }, suffix)
    registry = context.data_dir / "branches" / "main" / "registry.json"
    before = registry.read_bytes()
    with pytest.raises(Exception) as caught:
        branches.archive("archive-current-orphan", {
            "project_id": context.root.name, "timeline_id": "main", "branch_id": "main",
            "expected_registry_revision": branches.list_branches(context.root.name, "main")["registry_revision"],
        })
    assert getattr(caught.value, "code", "") == "NARRATIVE_TURN_CONFIRM_RECOVERY_REQUIRED"
    assert registry.read_bytes() == before


def test_rc2_ambiguous_archive_orphan_blocks(tmp_path: Path):
    context, _ = _project(tmp_path)
    _write_orphan(_progression_root(context), "ambiguous", {})
    with pytest.raises(CrossChapterTurnStartError) as caught:
        CrossChapterTurnStartService(context).assert_branch_archive_safe("main", "main")
    assert caught.value.code == "TURN_START_RECOVERY_REQUIRED"


def test_rc2_valid_completed_bundle_still_allows_archive_validation(tmp_path: Path):
    context, _ = _project(tmp_path)
    ready = _ready(context)
    CrossChapterTurnStartService(context).start_turn(**_start_kwargs(context, ready))
    CrossChapterTurnStartService(context).assert_branch_archive_safe("main", "main")
