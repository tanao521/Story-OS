from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from core.contracts import HashGuard, OperationEnvelope
from core.project_context import get_project_context
from system.planning_mutation_service import PlanningMutationError, PlanningMutationService, PlanningMutationTarget
from planning_engine.control_service import PlanningControlService
from planning_engine.dependency_service import PlanningDependencyService
from planning_engine.scheduling_service import NarrativeSchedulingService
from system import planning_service
from web.routes import api_save_or_plan_next_chapter


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _operation(service: PlanningMutationService, operation_id: str = "planning-mutation-1") -> OperationEnvelope:
    return OperationEnvelope(
        operation_id=operation_id, operation_type="planning_mutation", project_id=service.project.project_id,
        target_type="planning_bundle", target_id="next_chapter", expected_hashes={"request": HashGuard.sha256_json({"request": operation_id})},
        confirmed=True, reason="test planning mutation",
    )


def _targets(root: Path) -> list[PlanningMutationTarget]:
    return [
        PlanningMutationTarget("next_chapter_plan", {"chapter_id": 2, "goal": "continue"}, HashGuard.file_sha256(root / "data/next_chapter_plan.json")),
        PlanningMutationTarget("planning_state", {"current_stage": "next_chapter_planned", "next_chapter_plan": {"chapter_id": 2}}, HashGuard.file_sha256(root / "data/state.json")),
    ]


def test_bundle_is_project_scoped_idempotent_and_preserves_state_boundary(tmp_path: Path) -> None:
    _write(tmp_path / "data/next_chapter_plan.json", '{"chapter_id":1}\n')
    _write(tmp_path / "data/state.json", '{"current_chapter":1,"characters":{"a":"keep"}}\n')
    service = PlanningMutationService(get_project_context(tmp_path))
    operation, targets = _operation(service), _targets(tmp_path)

    result = service.mutation(mutation_type="save_next_chapter_plan", operation=operation, targets=targets)
    assert result["replayed"] is False
    state = service.store.read_json("data/state.json", strict=True, expected_type=dict)
    assert state["characters"] == {"a": "keep"}
    assert state["next_chapter_plan"]["chapter_id"] == 2
    audit = service.store.read_json("data/planning_control/mutation_audit.json", strict=True, expected_type=dict)
    assert audit["operations"][-1]["operation_id"] == operation.operation_id
    assert "payload" not in audit["operations"][-1]

    replay = PlanningMutationService(get_project_context(tmp_path)).mutation(mutation_type="save_next_chapter_plan", operation=operation, targets=targets)
    assert replay["replayed"] is True
    with pytest.raises(PlanningMutationError, match="OPERATION_ID_CONFLICT"):
        service.mutation(mutation_type="save_next_chapter_plan", operation=operation, targets=[PlanningMutationTarget("next_chapter_plan", {"chapter_id": 3}, targets[0].expected_before_hash)])


def test_rejects_unknown_target_and_state_overreach_without_writes(tmp_path: Path) -> None:
    _write(tmp_path / "data/state.json", '{"current_chapter":1}\n')
    service = PlanningMutationService(get_project_context(tmp_path))
    before = HashGuard.file_sha256(tmp_path / "data/state.json")
    with pytest.raises(PlanningMutationError, match="PLANNING_TARGET_INVALID"):
        service.mutation(mutation_type="x", operation=_operation(service), targets=[PlanningMutationTarget("../../outside", {}, None)])
    with pytest.raises(PlanningMutationError, match="PLANNING_STATE_FIELD_FORBIDDEN"):
        service.mutation(mutation_type="x", operation=_operation(service, "planning-mutation-2"), targets=[PlanningMutationTarget("planning_state", {"current_chapter": 99}, before)])
    assert HashGuard.file_sha256(tmp_path / "data/state.json") == before
    assert not list(tmp_path.rglob("*.bak"))


def test_failed_later_write_rolls_back_previously_written_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path / "data/next_chapter_plan.json", '{"chapter_id":1}\n')
    _write(tmp_path / "data/state.json", '{"current_chapter":1}\n')
    service = PlanningMutationService(get_project_context(tmp_path))
    original = HashGuard.file_sha256(tmp_path / "data/next_chapter_plan.json")
    real = service._write_item

    def fail_state(item: dict, operation: OperationEnvelope, mutation_type: str) -> None:
        if item["target_type"] == "planning_state" and not mutation_type.endswith("_rollback"):
            raise PlanningMutationError("PLANNING_WRITE_FAILED")
        real(item, operation, mutation_type)

    monkeypatch.setattr(service, "_write_item", fail_state)
    with pytest.raises(PlanningMutationError, match="PLANNING_WRITE_FAILED"):
        service.mutation(mutation_type="save_next_chapter_plan", operation=_operation(service), targets=_targets(tmp_path))
    assert HashGuard.file_sha256(tmp_path / "data/next_chapter_plan.json") == original
    assert not (tmp_path / "data/planning_control/mutation_audit.json").exists()
    assert not list(tmp_path.rglob("*.bak"))


def test_high_risk_planning_callers_have_no_direct_write_bypass() -> None:
    assert "PlanningMutationService" in inspect.getsource(api_save_or_plan_next_chapter)
    assert ".write_text(" not in inspect.getsource(api_save_or_plan_next_chapter)
    assert "write_bundle_legacy" in inspect.getsource(PlanningControlService._write)
    assert "legacy_write(\"dependencies\"" in inspect.getsource(PlanningDependencyService._save)
    assert "legacy_write(\"schedules\"" in inspect.getsource(NarrativeSchedulingService._save)
    assert "PlanningMutationService" in inspect.getsource(planning_service.save_planning)
