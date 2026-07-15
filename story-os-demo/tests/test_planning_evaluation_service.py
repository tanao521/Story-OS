from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from core.project_context import get_project_context
from evaluation_engine.planning_evaluation import PlanningEvaluationError, PlanningEvaluationService
from planning_engine.control_service import PlanningControlService
from planning_engine.rolling_service import RollingWindowService
from tests.test_planning_rolling_window import _project


def _hash(path: Path) -> str: return sha256(path.read_bytes()).hexdigest()


def _ready(root: Path):
    _project(root)
    context = get_project_context(root); control = PlanningControlService(context)
    control.save_strategy({"story_promise": "A strategic promise", "central_conflict": "A conflict"})
    control.create("milestones", {"title": "Turn", "milestone_type": "plot", "target_scope": {"target_chapter_min": 6, "target_chapter_max": 6}})
    RollingWindowService(context).initialize({"author_confirm": True, "near_horizon_size": 3, "mid_horizon_size": 6})
    (root / "data" / "story_planning.json").write_text(json.dumps({"schema_version": "2.0", "story": {}, "volumes": [{"volume_id": "volume_1", "title": "Volume 1"}], "phases": [], "chapters": [{"chapter_id": "6", "chapter_number": 6, "volume_id": "volume_1"}], "plot_threads": [], "character_arcs": [], "foreshadowing": []}), encoding="utf-8")
    return PlanningEvaluationService(context)


def test_near_window_report_is_read_only_and_has_eight_dimensions(tmp_path: Path) -> None:
    service = _ready(tmp_path)
    protected = {name: _hash(tmp_path / "data" / name) for name in ("story_blueprint.json", "next_chapter_plan.json", "state.json", "story_planning.json")}
    report, replayed = service.generate({"target_type": "near_planning_window", "scope_ref": {}, "operation_id": "planning-near"})
    assert not replayed and len(report["dimensions"]) == 8
    assert sum(item["weight"] for item in report["dimensions"]) == pytest.approx(1.0)
    assert report["target_ref"]["scope_ref"]["window_id"]
    assert protected == {name: _hash(tmp_path / "data" / name) for name in protected}
    replay, replayed = service.generate({"target_type": "near_planning_window", "scope_ref": {}, "operation_id": "planning-near"})
    assert replayed and replay["evaluation_id"] == report["evaluation_id"]


def test_adapters_only_expose_existing_service_results(tmp_path: Path) -> None:
    service = _ready(tmp_path)
    sources = service._sources()
    assert set(sources["adapters"]) == {"strategy", "rolling_window", "dependency_graph", "narrative_schedule", "milestone_contract"}
    assert sources["adapters"]["dependency_graph"]["description"] == sources["dependency"]
    assert sources["adapters"]["narrative_schedule"]["description"] == sources["schedule"]


def test_scope_lifecycle_and_stale_snapshot(tmp_path: Path) -> None:
    service = _ready(tmp_path)
    near, _ = service.generate({"target_type": "near_planning_window", "operation_id": "near"})
    volume, _ = service.generate({"target_type": "current_volume", "scope_ref": {"volume_id": "volume_1"}, "operation_id": "volume"})
    whole, _ = service.generate({"target_type": "whole_book_planning", "operation_id": "whole"})
    assert {item["target_type"] for item in service.list_reports()} == {"near_planning_window", "current_volume", "whole_book_planning"}
    assert service.detail(near["evaluation_id"])["status"] == "current"
    dependency_path = tmp_path / "data" / "planning_control" / "dependencies.json"
    dependency_path.write_text('{"dependency_revision":1,"dependencies":[]}', encoding="utf-8")
    assert service.detail(near["evaluation_id"])["status"] == "stale"
    assert service.detail(volume["evaluation_id"])["status"] == "stale"
    assert service.detail(whole["evaluation_id"])["status"] == "stale"


def test_invalid_scope_and_insufficient_evidence_are_explicit(tmp_path: Path) -> None:
    service = _ready(tmp_path)
    with pytest.raises(PlanningEvaluationError) as error:
        service.generate({"target_type": "near_planning_window", "scope_ref": {"window_id": "missing"}})
    assert error.value.code == "PLANNING_EVALUATION_SCOPE_NOT_FOUND"
    report, _ = service.generate({"target_type": "near_planning_window", "operation_id": "no-character"})
    character = next(item for item in report["dimensions"] if item["dimension_id"] == "character_arc")
    assert character["score"] is None and character["status"] == "insufficient_evidence"


def test_foreign_planning_document_is_rejected(tmp_path: Path) -> None:
    service = _ready(tmp_path)
    path = tmp_path / "data" / "planning_control" / "dependencies.json"
    path.write_text(json.dumps({"project_id": "foreign-project", "dependency_revision": 0, "dependencies": []}), encoding="utf-8")
    with pytest.raises(PlanningEvaluationError) as error:
        service.generate({"target_type": "near_planning_window"})
    assert error.value.code == "PLANNING_EVALUATION_PROJECT_MISMATCH"


def test_foreshadow_order_blocks_even_when_score_is_high(tmp_path: Path) -> None:
    service = _ready(tmp_path); context = service.context
    planning_path = tmp_path / "data" / "story_planning.json"; planning = json.loads(planning_path.read_text(encoding="utf-8")); planning["foreshadowing"] = [{"foreshadowing_id": "f-1", "title": "Seed"}]; planning_path.write_text(json.dumps(planning), encoding="utf-8")
    window = RollingWindowService(context).describe()["window"]; slots = window["near_slots"]
    document = {"schema_version": "1.0", "project_id": context.root.resolve().as_posix(), "schedule_revision": 1, "schedules": [
        {"schedule_id": "payoff", "subject_type": "foreshadowing", "subject_ref": {"subject_id": "f-1", "title": "Seed"}, "schedule_action": "payoff", "target_slot_id": slots[0]["slot_id"], "target_chapter_number": slots[0]["planned_chapter_number"], "status": "planned"},
        {"schedule_id": "plant", "subject_type": "foreshadowing", "subject_ref": {"subject_id": "f-1", "title": "Seed"}, "schedule_action": "plant", "target_slot_id": slots[1]["slot_id"], "target_chapter_number": slots[1]["planned_chapter_number"], "status": "planned"},
    ], "operations": [], "audit": []}
    (tmp_path / "data" / "planning_control" / "schedules.json").write_text(json.dumps(document), encoding="utf-8")
    report, _ = service.generate({"target_type": "near_planning_window"})
    assert report["gate_status"] == "blocked"
    assert report["overall_score"] is not None and report["overall_score"] > 70
    assert any(item["issue_type"] == "payoff_before_plant" for item in report["hard_issues"])
