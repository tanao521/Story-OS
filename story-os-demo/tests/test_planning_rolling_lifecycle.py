from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from fastapi.testclient import TestClient

from core.project_context import get_project_context
from planning_engine.control_service import PlanningControlError
from planning_engine.rolling_integration import mark_rolling_window_dirty
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


def _window(root: Path) -> RollingWindowService:
    service = RollingWindowService(get_project_context(root))
    service.initialize({"author_confirm": True, "near_horizon_size": 3, "mid_horizon_size": 6})
    return service


def test_health_reports_active_needs_stale_and_reanchor_required(tmp_path: Path) -> None:
    _project(tmp_path)
    service = _window(tmp_path)
    assert service.check_window_health()["status"] == "active"
    service.update_configuration({"near_horizon_size": 3, "mid_horizon_size": 6})
    assert service.check_window_health()["status"] == "active"
    (tmp_path / "data" / "chapters" / "chapter_006.md").write_text("chapter 6", encoding="utf-8")
    (tmp_path / "data" / "state.json").write_text('{"current_chapter":6}', encoding="utf-8")
    assert service.check_window_health()["status"] == "needs_roll_forward"

    _project(tmp_path / "stale")
    stale_service = _window(tmp_path / "stale")
    stale_service.control.save_strategy({"central_conflict": "author change"})
    assert stale_service.check_window_health()["status"] == "stale"

    _project(tmp_path / "broken")
    broken_service = _window(tmp_path / "broken")
    (tmp_path / "broken" / "data" / "state.json").write_text("{}", encoding="utf-8")
    health = broken_service.check_window_health()
    assert health["status"] == "reanchor_required" and health["issues"]

    _project(tmp_path / "missing-ref")
    reference_service = _window(tmp_path / "missing-ref")
    slot = reference_service.list_slots()["near_slots"][0]
    reference_service.update_slot(slot["slot_id"], {"milestone_refs": ["missing-milestone"]})
    reference_health = reference_service.check_window_health()
    assert reference_health["status"] == "reanchor_required"
    assert any(issue["type"] == "missing_reference" for issue in reference_health["issues"])


def test_each_planning_source_change_marks_window_stale(tmp_path: Path) -> None:
    changes = (
        lambda control: control.save_strategy({"central_conflict": "changed"}),
        lambda control: control.create("milestones", {"title": "M", "milestone_type": "plot"}),
        lambda control: control.create("volume_contracts", {"volume_ref": {"manual_scope": True, "display_name": "V"}}),
        lambda control: control.create("phase_contracts", {"phase_ref": {"source_type": "story_blueprint", "entity_type": "story_phase", "entity_id": "phase-01"}}),
    )
    for index, change in enumerate(changes):
        root = tmp_path / f"source-{index}"; _project(root)
        service = _window(root)
        change(service.control)
        assert service.check_window_health()["status"] == "stale"


def test_roll_forward_preview_confirm_elapsed_versions_and_protected_files(tmp_path: Path) -> None:
    _project(tmp_path)
    service = _window(tmp_path)
    (tmp_path / "data" / "chapters" / "chapter_006.md").write_text("chapter 6", encoding="utf-8")
    (tmp_path / "data" / "state.json").write_text('{"current_chapter":6}', encoding="utf-8")
    protected = {name: _hash(tmp_path / "data" / name) for name in ("story_blueprint.json", "next_chapter_plan.json", "state.json")}
    versions_before = len(service.control.list_versions())
    preview = service.roll_forward_preview()
    assert preview["old_anchor"] == 6 and preview["new_anchor"] == 7 and preview["elapsed_slots"]
    assert protected == {name: _hash(tmp_path / "data" / name) for name in protected}
    result = service.confirm_roll_forward()
    assert result["applied"] is True and result["window"]["anchor"]["next_chapter_number"] == 7
    assert any(slot["status"] == "elapsed" for slot in result["window"]["elapsed_slots"])
    assert len(service.list_slots()["near_slots"]) == 3 and len(service.list_slots()["mid_slots"]) == 6
    assert len(service.control.list_versions()) == versions_before + 1
    assert protected == {name: _hash(tmp_path / "data" / name) for name in protected}


def test_reanchor_requires_confirmation_respects_locks_and_creates_version(tmp_path: Path) -> None:
    _project(tmp_path)
    service = _window(tmp_path)
    (tmp_path / "data" / "chapters" / "chapter_006.md").write_text("chapter 6", encoding="utf-8")
    (tmp_path / "data" / "state.json").write_text('{"current_chapter":6}', encoding="utf-8")
    slot = service.list_slots()["near_slots"][0]
    lock = service.lock("chapter_slot", slot["slot_id"], "*")
    preview = service.reanchor({"next_chapter_number": 7, "author_confirm": False})
    assert preview["applied"] is False and preview["preview"]["locked_slot_ids"] == [slot["slot_id"]]
    try:
        service.reanchor({"next_chapter_number": 7, "author_confirm": True})
    except PlanningControlError as error:
        assert error.code == "PLANNING_LOCK_CONFLICT"
    else:
        raise AssertionError("locked slot allowed a reanchor")
    service.release_lock(lock["lock_id"])
    before = len(service.control.list_versions())
    rebound = service.reanchor({"next_chapter_number": 7, "author_confirm": True})
    assert rebound["applied"] is True and rebound["window"]["anchor"]["next_chapter_number"] == 7
    assert len(service.control.list_versions()) == before + 1
    try:
        service.reanchor({"next_chapter_number": 0, "author_confirm": False})
    except PlanningControlError as error:
        assert error.code == "ROLLING_WINDOW_REANCHOR_INVALID"
    else:
        raise AssertionError("invalid anchor was accepted")


def test_refresh_marks_source_change_without_rewriting_slots_and_commit_hook_is_nonblocking(tmp_path: Path) -> None:
    _project(tmp_path)
    service = _window(tmp_path)
    slot_before = service.list_slots()["near_slots"][0]
    service.control.save_strategy({"central_conflict": "changed strategy"})
    assert service.check_window_health()["status"] == "stale"
    versions_before = len(service.control.list_versions())
    refreshed = service.refresh_sources()
    slot_after = next(slot for slot in service.list_slots()["near_slots"] if slot["slot_id"] == slot_before["slot_id"])
    assert refreshed["status"] == "active" and slot_after == slot_before
    assert len(service.control.list_versions()) == versions_before + 1
    (tmp_path / "data" / "chapters" / "chapter_006.md").write_text("chapter 6", encoding="utf-8")
    (tmp_path / "data" / "state.json").write_text('{"current_chapter":6}', encoding="utf-8")
    notice = mark_rolling_window_dirty(get_project_context(tmp_path), "canon_commit")
    assert notice["status"] == "needs_roll_forward"


def test_lifecycle_api_and_projects_are_isolated(tmp_path: Path, monkeypatch) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    _project(first); _project(second)
    _window(first)
    monkeypatch.chdir(first)
    with TestClient(app) as client:
        assert client.get("/api/planning-control/rolling-window/health").json()["result"]["status"] == "active"
        preview = client.post("/api/planning-control/rolling-window/roll-forward")
        assert preview.status_code == 200 and preview.json()["result"]["applied"] is False
        assert client.post("/api/planning-control/rolling-window/refresh").status_code == 200
        assert client.post("/api/planning-control/rolling-window/reanchor", json={"next_chapter_number": 6, "author_confirm": False}).json()["result"]["applied"] is False
    assert RollingWindowService(get_project_context(second)).check_window_health()["status"] == "uninitialized"
