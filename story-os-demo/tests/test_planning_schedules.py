from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.project_context import get_project_context
from planning_engine.control_service import PlanningControlError, PlanningControlService
from planning_engine.dependency_service import PlanningDependencyService
from planning_engine.rolling_service import RollingWindowService
from planning_engine.scheduling_service import NarrativeSchedulingService
from web.app import app


def _hash(path: Path) -> str: return sha256(path.read_bytes()).hexdigest()


def _project(root: Path, committed: int = 3) -> None:
    (root / "data" / "chapters").mkdir(parents=True)
    for index in range(1, committed + 1): (root / "data" / "chapters" / f"chapter_{index:03d}.md").write_text("chapter", encoding="utf-8")
    (root / "data" / "state.json").write_text('{"current_chapter":' + str(committed) + ',"foreshadows":[{"id":"runtime-f","content":"运行态伏笔","status":"open"}]}', encoding="utf-8")
    (root / "data" / "next_chapter_plan.json").write_text('{"chapter_id":' + str(committed + 1) + '}', encoding="utf-8")
    (root / "data" / "story_blueprint.json").write_text('{"plot_threads":[{"thread_id":"thread-1","title":"主线"}],"character_arcs":[{"character_arc_id":"arc-1","title":"主角弧光"}],"initial_foreshadow_pool":[{"foreshadow_id":"foreshadow-1","title":"通道编号"}]}', encoding="utf-8")


def _setup(root: Path) -> tuple[NarrativeSchedulingService, dict]:
    context = get_project_context(root)
    window = RollingWindowService(context).initialize({"author_confirm": True, "near_horizon_size": 3, "mid_horizon_size": 6})
    return NarrativeSchedulingService(context), window


def _payload(kind: str, subject_id: str, slot: dict, action: str, **extra: object) -> dict:
    return {"subject_type": kind, "subject_ref": {"subject_id": subject_id}, "schedule_action": action, "target_slot_id": slot["slot_id"], "target_chapter_number": slot["planned_chapter_number"], **extra}


def test_schedules_are_lazy_and_do_not_modify_protected_files(tmp_path: Path) -> None:
    _project(tmp_path); context = get_project_context(tmp_path); protected = {name: _hash(tmp_path / "data" / name) for name in ("story_blueprint.json", "next_chapter_plan.json", "state.json")}
    service = NarrativeSchedulingService(context)
    assert service.describe()["materialized"] is False and not context.planning_schedules_path.exists()
    kinds = service.describe()["subjects"]
    assert kinds["plot_thread"][0]["subject_id"] == "thread-1" and kinds["character_arc"][0]["subject_id"] == "arc-1" and kinds["foreshadowing"][0]["subject_id"] == "foreshadow-1"
    assert protected == {name: _hash(tmp_path / "data" / name) for name in protected}


def test_manual_schedule_crud_status_timeline_and_rebind(tmp_path: Path) -> None:
    _project(tmp_path); service, window = _setup(tmp_path); first, second = window["near_slots"][:2]
    plot = service.create(_payload("plot_thread", "thread-1", first, "introduce", operation_id="create-once"))
    replay = service.create(_payload("plot_thread", "thread-1", first, "introduce", operation_id="create-once"))
    assert replay["schedule_id"] == plot["schedule_id"] and replay["replayed"]
    arc = service.create(_payload("character_arc", "arc-1", second, "pressure", expected_schedule_revision=plot["schedule_revision"]))
    reviewed = service.transition(arc["schedule_id"], {"action": "review", "expected_schedule_revision": arc["schedule_revision"]})
    rebound = service.rebind(plot["schedule_id"], {"target_slot_id": second["slot_id"], "target_chapter_number": second["planned_chapter_number"], "expected_schedule_revision": reviewed["schedule_revision"]})
    assert rebound["target_slot_id"] == second["slot_id"]
    timeline = service.timeline("plot_thread", "thread-1")["timeline"]
    assert [row["schedule_id"] for row in timeline] == [plot["schedule_id"]]
    assert service.by_slot(second["slot_id"])["schedule_count"] == 2


def test_foreshadow_order_slot_validation_and_locks(tmp_path: Path) -> None:
    _project(tmp_path); service, window = _setup(tmp_path); first, second = window["near_slots"][:2]
    payoff = service.create(_payload("foreshadowing", "foreshadow-1", first, "payoff"))
    with pytest.raises(PlanningControlError) as error:
        service.create(_payload("foreshadowing", "foreshadow-1", second, "plant", expected_schedule_revision=payoff["schedule_revision"]))
    assert error.value.code == "NARRATIVE_SCHEDULE_ORDER_CONFLICT"
    control = PlanningControlService(service.context); lock = control.lock({"entity_type": "narrative_schedule", "entity_id": payoff["schedule_id"], "field": "status"})
    with pytest.raises(PlanningControlError, match="NARRATIVE_SCHEDULE_LOCK_CONFLICT"):
        service.transition(payoff["schedule_id"], {"action": "cancel", "expected_schedule_revision": payoff["schedule_revision"]})
    control.release_lock(lock["lock_id"])
    cancelled = service.transition(payoff["schedule_id"], {"action": "cancel", "expected_schedule_revision": payoff["schedule_revision"]})
    assert cancelled["status"] == "cancelled"


def test_dependency_conflict_and_window_roll_forward_elapsed(tmp_path: Path) -> None:
    _project(tmp_path); context = get_project_context(tmp_path); service, window = _setup(tmp_path); first, third = window["near_slots"][0], window["near_slots"][2]
    dependencies = PlanningDependencyService(context)
    with pytest.raises(PlanningControlError) as missing:
        service.create(_payload("plot_thread", "thread-1", first, "advance", dependency_refs=["missing-dependency"]))
    assert missing.value.code == "NARRATIVE_SCHEDULE_DEPENDENCY_CONFLICT"
    dependencies.create_dependency({"from_node": {"node_type": "chapter_slot", "node_id": third["slot_id"]}, "to_node": {"node_type": "structured_plot_thread", "node_id": "thread-1"}, "dependency_type": "requires", "strength": "hard"})
    with pytest.raises(PlanningControlError) as error:
        service.create(_payload("plot_thread", "thread-1", first, "advance"))
    assert error.value.code == "NARRATIVE_SCHEDULE_DEPENDENCY_CONFLICT"
    planned = service.create(_payload("character_arc", "arc-1", first, "pressure"))
    (tmp_path / "data" / "chapters" / "chapter_004.md").write_text("chapter", encoding="utf-8")
    (tmp_path / "data" / "state.json").write_text('{"current_chapter":4,"foreshadows":[]}', encoding="utf-8")
    rolled = RollingWindowService(context).roll_forward({"author_confirm": True})
    assert rolled["applied"] is True and service.get(planned["schedule_id"])["status"] == "elapsed"


def test_project_isolation_api_and_protected_hashes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = tmp_path / "a", tmp_path / "b"; _project(first); _project(second)
    protected = {name: _hash(first / "data" / name) for name in ("story_blueprint.json", "next_chapter_plan.json", "state.json")}
    service, window = _setup(first); first_slot = window["near_slots"][0]
    assert NarrativeSchedulingService(get_project_context(second)).describe()["materialized"] is False
    monkeypatch.chdir(first)
    with TestClient(app) as client:
        created = client.post("/api/planning-control/schedules", json=_payload("foreshadowing", "foreshadow-1", first_slot, "plant", operation_id="api-once"))
        assert created.status_code == 201
        schedule_id = created.json()["result"]["schedule"]["schedule_id"]
        assert client.get(f"/api/planning-control/schedules/{schedule_id}").status_code == 200
        assert client.get("/api/planning-control/schedules/timeline", params={"subject_type":"foreshadowing","subject_id":"foreshadow-1"}).status_code == 200
        assert client.get(f"/api/planning-control/schedules/by-slot/{first_slot['slot_id']}").status_code == 200
        assert client.post("/api/planning-control/schedules/validate").status_code == 200
    assert protected == {name: _hash(first / "data" / name) for name in protected}


def test_revision_version_slot_cancellation_and_load_warning(tmp_path: Path) -> None:
    _project(tmp_path); context = get_project_context(tmp_path); service, window = _setup(tmp_path); first, second, third = window["near_slots"][:3]
    created = service.create(_payload("plot_thread", "thread-1", first, "introduce"))
    with pytest.raises(PlanningControlError) as error:
        service.update(created["schedule_id"], {"author_notes": "stale", "expected_schedule_revision": 0})
    assert error.value.code == "NARRATIVE_SCHEDULE_REVISION_CONFLICT"
    updated = service.update(created["schedule_id"], {"author_notes": "作者说明", "expected_schedule_revision": created["schedule_revision"]})
    assert PlanningControlService(context).list_versions()
    RollingWindowService(context).cancel_slot(first["slot_id"])
    health = service.health()
    assert health["invalid_slot_count"] == 1
    for action in ("pressure", "choice", "realization", "change"):
        service.create(_payload("character_arc", "arc-1", second, action, expected_schedule_revision=service.describe()["schedule_revision"]))
    # The summary is a warning-only capacity hint: it never moves a schedule.
    assert service.by_slot(second["slot_id"])["warnings"][0]["code"] == "SCHEDULE_SLOT_OVERLOADED" and updated["author_notes"] == "作者说明"


def test_schedule_ui_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    template = (root / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    script = (root / "web" / "static" / "planning-control" / "schedules.js").read_text(encoding="utf-8")
    assert 'id="narrative-scheduling-area"' in template and "/static/planning-control/schedules.js" in template
    for token in ("plot_thread", "character_arc", "foreshadowing", "/schedules/timeline", "/schedules/by-slot"):
        assert token in script
    assert "auto" not in script.lower() and "model" not in script.lower() and "roll-forward" not in script
