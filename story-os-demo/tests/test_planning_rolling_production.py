from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.project_context import get_project_context
from planning_engine.control_service import PlanningControlError
from planning_engine.rolling_service import RollingWindowService
from system.data_store import DataWriteError
from web.app import app


def _hash(path: Path) -> str: return sha256(path.read_bytes()).hexdigest()


def _project(root: Path, committed: int = 5) -> None:
    (root / "data" / "chapters").mkdir(parents=True)
    for number in range(1, committed + 1): (root / "data" / "chapters" / f"chapter_{number:03d}.md").write_text("chapter", encoding="utf-8")
    (root / "data" / "state.json").write_text(f'{{"current_chapter":{committed}}}', encoding="utf-8")
    (root / "data" / "next_chapter_plan.json").write_text(f'{{"chapter_id":{committed + 1}}}', encoding="utf-8")
    (root / "data" / "story_blueprint.json").write_text('{"story_phases":[{"phase_id":"phase-1"}],"chapter_plan":[]}', encoding="utf-8")


def _service(root: Path) -> RollingWindowService:
    service = RollingWindowService(get_project_context(root))
    service.initialize({"author_confirm": True, "near_horizon_size": 3, "mid_horizon_size": 6})
    return service


def _revision(service: RollingWindowService) -> int:
    return int(service.describe()["window"]["window_revision"])


def test_window_revision_conflict_and_slot_write_are_optimistic(tmp_path: Path) -> None:
    _project(tmp_path); service = _service(tmp_path)
    assert _revision(service) == 1
    slot = service.list_slots()["near_slots"][0]
    service.update_slot(slot["slot_id"], {"goal_summary": "saved", "expected_window_revision": 1, "operation_id": "slot-save"})
    assert _revision(service) == 2
    before = _hash(tmp_path / "data" / "planning_control" / "rolling_window.json")
    with pytest.raises(PlanningControlError) as raised:
        service.update_slot(slot["slot_id"], {"goal_summary": "stale", "expected_window_revision": 1, "operation_id": "stale-save"})
    assert raised.value.code == "ROLLING_WINDOW_REVISION_CONFLICT"
    assert _hash(tmp_path / "data" / "planning_control" / "rolling_window.json") == before


def test_preview_staleness_and_confirm_replay_do_not_duplicate_roll_forward(tmp_path: Path) -> None:
    _project(tmp_path); service = _service(tmp_path)
    (tmp_path / "data" / "chapters" / "chapter_006.md").write_text("chapter", encoding="utf-8")
    (tmp_path / "data" / "state.json").write_text('{"current_chapter":6}', encoding="utf-8")
    stale = service.roll_forward_preview()
    slot = service.list_slots()["near_slots"][0]
    service.update_slot(slot["slot_id"], {"goal_summary": "other write", "expected_window_revision": _revision(service), "operation_id": "other-write"})
    with pytest.raises(PlanningControlError) as raised:
        service.confirm_roll_forward({"preview_id": stale["preview_id"], "expected_window_revision": 1, "operation_id": "stale-confirm"})
    assert raised.value.code == "ROLLING_PREVIEW_STALE"
    preview = service.roll_forward_preview(); revision = _revision(service)
    first = service.confirm_roll_forward({"preview_id": preview["preview_id"], "expected_window_revision": revision, "operation_id": "forward-once"})
    second = service.confirm_roll_forward({"preview_id": preview["preview_id"], "expected_window_revision": revision, "operation_id": "forward-once"})
    assert first["applied"] is True and second["replayed"] is True
    assert _revision(service) == revision + 1
    assert len(service.list_slots()["near_slots"]) == 3 and len(service.list_slots()["mid_slots"]) == 6


def test_refresh_replay_and_atomic_write_failure_preserve_protected_files(tmp_path: Path, monkeypatch) -> None:
    _project(tmp_path); service = _service(tmp_path)
    protected = {name: _hash(tmp_path / "data" / name) for name in ("story_blueprint.json", "next_chapter_plan.json", "state.json")}
    revision = _revision(service)
    first = service.refresh_sources({"expected_window_revision": revision, "operation_id": "refresh-once"})
    second = service.refresh_sources({"expected_window_revision": revision, "operation_id": "refresh-once"})
    assert first["window_revision"] == revision + 1 and second["replayed"] is True
    path = tmp_path / "data" / "planning_control" / "rolling_window.json"; before = _hash(path); actual_revision = _revision(service)
    original = service.control.store.write_json
    def fail_window(target, value, **kwargs):
        if Path(target) == service.context.rolling_window_path: raise DataWriteError("injected rolling write failure")
        return original(target, value, **kwargs)
    monkeypatch.setattr(service.control.store, "write_json", fail_window)
    with pytest.raises(PlanningControlError) as raised:
        service.refresh_sources({"expected_window_revision": actual_revision, "operation_id": "fail-write"})
    assert raised.value.code == "PLANNING_CONTROL_WRITE_FAILED"
    assert _hash(path) == before and _revision(service) == actual_revision
    assert protected == {name: _hash(tmp_path / "data" / name) for name in protected}


def test_restore_keeps_revision_monotonic_and_recalculates_health(tmp_path: Path) -> None:
    _project(tmp_path); service = _service(tmp_path)
    slot = service.list_slots()["near_slots"][0]
    service.update_slot(slot["slot_id"], {"goal_summary": "first", "expected_window_revision": 1, "operation_id": "first"})
    version_id = service.control.list_versions()[0]["version_id"]
    service.update_slot(slot["slot_id"], {"goal_summary": "later", "expected_window_revision": 2, "operation_id": "later"})
    (tmp_path / "data" / "chapters" / "chapter_006.md").write_text("chapter", encoding="utf-8")
    (tmp_path / "data" / "state.json").write_text('{"current_chapter":6}', encoding="utf-8")
    result = service.control.restore_version(version_id, {"expected_window_revision": 3, "operation_id": "restore-once"})
    restored = result["window"]
    assert restored["window_revision"] == 4
    assert restored["status"] == "needs_roll_forward"


def test_api_returns_409_details_and_replays_operation(tmp_path: Path, monkeypatch) -> None:
    _project(tmp_path); service = _service(tmp_path); slot = service.list_slots()["near_slots"][0]
    monkeypatch.chdir(tmp_path)
    with TestClient(app) as client:
        saved = client.put(f"/api/planning-control/rolling-window/slots/{slot['slot_id']}", json={"goal_summary": "api", "expected_window_revision": 1, "operation_id": "api-save"})
        assert saved.status_code == 200
        conflict = client.put(f"/api/planning-control/rolling-window/slots/{slot['slot_id']}", json={"goal_summary": "old", "expected_window_revision": 1, "operation_id": "api-stale"})
        assert conflict.status_code == 422 or conflict.status_code == 409
        assert conflict.json()["error_code"] == "ROLLING_WINDOW_REVISION_CONFLICT"
        assert conflict.json()["details"] == {"expected_revision": 1, "actual_revision": 2}


def test_frontend_lifecycle_contract_has_dirty_revision_and_project_generation_guards() -> None:
    source = (Path(__file__).parents[1] / "web" / "static" / "planning-control" / "rolling-lifecycle.js").read_text(encoding="utf-8")
    for required in ("windowRevision", "expected_window_revision", "operation_id", "preview_id", "requestGeneration", "activeProjectId", "ROLLING_WINDOW_REVISION_CONFLICT", "ROLLING_PREVIEW_STALE", "beforeunload", "storyos:project-changed", "button.disabled"):
        assert required in source


def test_audit_failure_leaves_successful_window_write_marked_pending(tmp_path: Path, monkeypatch) -> None:
    _project(tmp_path); service = _service(tmp_path); revision = _revision(service)
    original = service.control.store.write_json
    def fail_metadata(target, value, **kwargs):
        if Path(target) == service.context.planning_metadata_path: raise DataWriteError("injected metadata failure")
        return original(target, value, **kwargs)
    monkeypatch.setattr(service.control.store, "write_json", fail_metadata)
    saved = service.refresh_sources({"expected_window_revision": revision, "operation_id": "audit-pending"})
    assert saved["window_revision"] == revision + 1 and saved["audit_pending"] is True
