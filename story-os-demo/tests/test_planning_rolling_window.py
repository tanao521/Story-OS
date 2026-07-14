from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from fastapi.testclient import TestClient

from core.project_context import get_project_context
from planning_engine.control_service import PlanningControlError
from planning_engine.rolling_service import RollingWindowService
from web.app import app


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _project(root: Path, committed: int = 5) -> None:
    (root / "data" / "chapters").mkdir(parents=True)
    for chapter in range(1, committed + 1):
        (root / "data" / "chapters" / f"chapter_{chapter:03d}.md").write_text(f"chapter {chapter}", encoding="utf-8")
    (root / "data" / "state.json").write_text('{"current_chapter":' + str(committed) + '}', encoding="utf-8")
    (root / "data" / "next_chapter_plan.json").write_text('{"chapter_id":' + str(committed + 1) + '}', encoding="utf-8")
    (root / "data" / "story_blueprint.json").write_text('{"story_phases":[{"phase_id":"phase-01","title":"Phase"}],"chapter_plan":[{"chapter_id":' + str(committed + 1) + ',"chapter_title":"Future","chapter_goal":"future goal","phase_position":{"phase_id":"phase-01","phase_title":"Phase"}}]}', encoding="utf-8")


def test_rolling_window_is_lazy_and_uses_next_unwritten_anchor(tmp_path: Path) -> None:
    _project(tmp_path)
    protected = {name: _hash(tmp_path / "data" / name) for name in ("story_blueprint.json", "next_chapter_plan.json", "state.json")}
    service = RollingWindowService(get_project_context(tmp_path))
    view = service.describe()
    assert view["materialized"] is False and view["anchor_suggestion"]["next_chapter_number"] == 6
    assert not (tmp_path / "data" / "planning_control" / "rolling_window.json").exists()
    window = service.initialize({"near_horizon_size": 5, "mid_horizon_size": 10, "author_confirm": True})
    assert len(window["near_slots"]) == 5 and len(window["mid_slots"]) == 10
    assert protected == {name: _hash(tmp_path / "data" / name) for name in protected}


def test_slot_create_edit_cancel_and_blueprint_adoption_preserve_protected_files(tmp_path: Path) -> None:
    _project(tmp_path)
    protected = {name: _hash(tmp_path / "data" / name) for name in ("story_blueprint.json", "next_chapter_plan.json", "state.json")}
    service = RollingWindowService(get_project_context(tmp_path))
    window = service.initialize({"author_confirm": True, "near_horizon_size": 3, "mid_horizon_size": 6})
    first = window["near_slots"][0]
    adopted = service.adopt_blueprint_suggestion(first["slot_id"], 6)
    assert adopted["goal_summary"] == "future goal" and adopted["source_refs"]
    edited = service.update_slot(first["slot_id"], {"goal_summary": "author-edited intent"})
    assert edited["goal_summary"] == "author-edited intent"
    cancelled = service.cancel_slot(first["slot_id"])
    assert cancelled["status"] == "cancelled"
    retained = next(slot for slot in service.list_slots()["near_slots"] if slot["slot_id"] == first["slot_id"])
    assert retained["status"] == "cancelled" and retained["goal_summary"] == "author-edited intent"
    service.update_configuration({"near_horizon_size": 3, "mid_horizon_size": 7})
    created = service.create_slot({"planned_chapter_number": 15, "goal_summary": "manually created future slot"})
    assert created["planned_chapter_number"] == 15 and created["horizon"] == "mid"
    assert protected == {name: _hash(tmp_path / "data" / name) for name in protected}


def test_slots_locks_roll_forward_and_stale_detection(tmp_path: Path) -> None:
    _project(tmp_path)
    context = get_project_context(tmp_path); service = RollingWindowService(context)
    window = service.initialize({"near_horizon_size": 3, "mid_horizon_size": 6, "author_confirm": True})
    first = window["near_slots"][0]
    adopted = service.adopt_blueprint_suggestion(first["slot_id"], 6)
    assert adopted["goal_summary"] == "future goal" and adopted["source_refs"]
    lock = service.lock("chapter_slot", first["slot_id"], "goal_summary")
    try:
        service.update_slot(first["slot_id"], {"goal_summary": "blocked"})
    except PlanningControlError as error:
        assert error.code == "PLANNING_LOCK_CONFLICT"
    else:
        raise AssertionError("locked future slot was changed")
    service.release_lock(lock["lock_id"])
    (tmp_path / "data" / "chapters" / "chapter_006.md").write_text("chapter 6", encoding="utf-8")
    (tmp_path / "data" / "state.json").write_text('{"current_chapter":6}', encoding="utf-8")
    assert service.mark_anchor_changed("canon_commit")["status"] == "needs_roll_forward"
    assert service.roll_forward({"author_confirm": False})["applied"] is False
    rolled = service.roll_forward({"author_confirm": True})["window"]
    assert rolled["anchor"]["next_chapter_number"] == 7
    assert any(item["planned_chapter_number"] == 6 and item["status"] == "elapsed" for item in rolled["elapsed_slots"])
    (tmp_path / "data" / "story_blueprint.json").write_text('{"core_conflict":"changed"}', encoding="utf-8")
    assert service.describe()["window"]["effective_status"] == "stale"


def test_rolling_window_project_isolation_and_api_contract(tmp_path: Path, monkeypatch) -> None:
    first, second = tmp_path / "a", tmp_path / "b"; _project(first); _project(second, 0)
    first_service = RollingWindowService(get_project_context(first)); first_service.initialize({"author_confirm": True, "near_horizon_size": 3, "mid_horizon_size": 6})
    assert RollingWindowService(get_project_context(second)).describe()["materialized"] is False
    monkeypatch.chdir(first)
    with TestClient(app) as client:
        assert client.get("/api/planning-control/rolling-window").status_code == 200
        slots = client.get("/api/planning-control/rolling-window/slots").json()["result"]
        slot_id = slots["near_slots"][0]["slot_id"]
        assert client.put(f"/api/planning-control/rolling-window/slots/{slot_id}", json={"goal_summary": "manual future intent"}).status_code == 200
        cancelled = client.post(f"/api/planning-control/rolling-window/slots/{slot_id}/cancel")
        assert cancelled.status_code == 200 and cancelled.json()["result"]["slot"]["status"] == "cancelled"
        assert client.post("/api/planning-control/rolling-window/roll-forward", json={"author_confirm": False}).status_code == 200
        assert client.post("/api/planning-control/rolling-window/locks", json={"entity_type":"chapter_slot","entity_id":slot_id,"field":"goal_summary"}).status_code == 201


def test_rolling_window_is_included_in_planning_control_versions(tmp_path: Path) -> None:
    _project(tmp_path)
    service = RollingWindowService(get_project_context(tmp_path))
    window = service.initialize({"author_confirm": True, "near_horizon_size": 3, "mid_horizon_size": 6})
    slot = window["near_slots"][0]
    service.update_slot(slot["slot_id"], {"goal_summary": "first intent"})
    service.update_slot(slot["slot_id"], {"goal_summary": "later intent"})
    restore_id = service.control.list_versions()[0]["version_id"]
    service.control.restore_version(restore_id)
    restored = service.describe()["window"]
    assert next(item for item in restored["near_slots"] if item["slot_id"] == slot["slot_id"])["goal_summary"] == "first intent"
