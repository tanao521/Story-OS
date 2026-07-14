from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from fastapi.testclient import TestClient

from core.project_context import get_project_context
from planning_engine.control_service import PlanningControlError, PlanningControlService
from web.app import app


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _project(root: Path, conflict: str = "blueprint conflict") -> None:
    (root / "data").mkdir(parents=True)
    (root / "data" / "story_blueprint.json").write_text(
        '{"core_conflict":"' + conflict + '","ending_direction":"blueprint ending","story_phases":[{"phase_id":"phase-01"}]}',
        encoding="utf-8",
    )
    (root / "data" / "next_chapter_plan.json").write_text('{"chapter_id":1}', encoding="utf-8")
    (root / "data" / "state.json").write_text('{"current_chapter":1}', encoding="utf-8")


def test_control_layer_is_lazy_isolated_and_preserves_existing_planning_files(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    _project(first); _project(second, "second conflict")
    blueprint_hash, plan_hash, state_hash = (_hash(first / "data" / name) for name in ("story_blueprint.json", "next_chapter_plan.json", "state.json"))
    service = PlanningControlService(get_project_context(first))
    assert service.overview()["materialized"] is False
    assert not (first / "data" / "planning_control").exists()
    strategy = service.save_strategy({"central_conflict": "author conflict", "ending_direction": "author ending"})
    service.create("milestones", {"title": "A milestone", "milestone_type": "plot"})
    service.create("volume_contracts", {"volume_ref": {"manual_scope": True, "display_name": "A logical volume"}})
    service.create("phase_contracts", {"phase_ref": {"source_type": "story_blueprint", "entity_type": "story_phase", "entity_id": "phase-01"}})
    service.lock({"entity_type": "story_strategy", "entity_id": strategy["strategy_id"], "field": "central_conflict"})
    assert (first / "data" / "planning_control" / "strategy.json").exists()
    other = PlanningControlService(get_project_context(second)).overview()
    assert other["saved_strategy"] is None and not other["milestones"] and not other["volume_contracts"] and not other["phase_contracts"] and not other["locks"] and not other["versions"]
    assert blueprint_hash == _hash(first / "data" / "story_blueprint.json")
    assert plan_hash == _hash(first / "data" / "next_chapter_plan.json")
    assert state_hash == _hash(first / "data" / "state.json")
    assert strategy["project_id"] == first.resolve().as_posix()


def test_locks_conflicts_and_version_restore_are_author_controlled(tmp_path: Path) -> None:
    _project(tmp_path)
    protected = {name: _hash(tmp_path / "data" / name) for name in ("story_blueprint.json", "next_chapter_plan.json", "state.json")}
    service = PlanningControlService(get_project_context(tmp_path))
    strategy = service.save_strategy({"central_conflict": "author conflict", "ending_direction": "first"})
    lock = service.lock({"entity_type": "story_strategy", "entity_id": strategy["strategy_id"], "field": "ending_direction", "reason": "author decision"})
    try:
        service.save_strategy({"ending_direction": "blocked"})
    except PlanningControlError as error:
        assert error.code == "PLANNING_LOCK_CONFLICT"
    else:
        raise AssertionError("locked strategy field was changed")
    service.release_lock(lock["lock_id"])
    service.save_strategy({"ending_direction": "second"})
    conflicts = service.scan_conflicts()
    assert any(item["field"] == "central_conflict" for item in conflicts)
    version_id = service.list_versions()[0]["version_id"]
    service.save_strategy({"ending_direction": "third"})
    service.restore_version(version_id)
    assert service.get_strategy()["ending_direction"] == "second"
    assert protected == {name: _hash(tmp_path / "data" / name) for name in protected}


def test_planning_control_api_contract(tmp_path: Path, monkeypatch) -> None:
    _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/planning-control/overview").json()["result"]["materialized"] is False
        strategy = client.put("/api/planning-control/strategy", json={"central_conflict": "author"})
        assert strategy.status_code == 200
        milestone = client.post("/api/planning-control/milestones", json={"title": "First turn", "milestone_type": "plot"})
        assert milestone.status_code == 201
        milestone_id = milestone.json()["result"]["milestone"]["milestone_id"]
        assert client.post(f"/api/planning-control/milestones/{milestone_id}/transition", json={"status": "achieved"}).status_code == 200
        assert client.post("/api/planning-control/phase-contracts", json={"phase_ref": {"source_type": "story_blueprint", "entity_type": "story_phase", "entity_id": "phase-01"}}).status_code == 201
        assert client.post("/api/planning-control/volume-contracts", json={"volume_ref": {"manual_scope": True, "display_name": "logical volume"}}).status_code == 201
        strategy_id = strategy.json()["result"]["strategy"]["strategy_id"]
        lock = client.post("/api/planning-control/locks", json={"entity_type": "story_strategy", "entity_id": strategy_id, "field": "central_conflict"})
        assert lock.status_code == 201
        assert client.post(f"/api/planning-control/locks/{lock.json()['result']['lock']['lock_id']}/release").status_code == 200
        assert client.post("/api/planning-control/conflicts/scan").status_code == 200
        assert client.get("/api/planning-control/versions").json()["result"]["versions"]
