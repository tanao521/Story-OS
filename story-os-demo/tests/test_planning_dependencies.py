from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.project_context import get_project_context
from planning_engine.control_service import PlanningControlError, PlanningControlService
from planning_engine.dependency_service import PlanningDependencyService
from planning_engine.rolling_service import RollingWindowService
from web.app import app


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _project(root: Path, committed: int = 2) -> None:
    (root / "data" / "chapters").mkdir(parents=True)
    for chapter in range(1, committed + 1):
        (root / "data" / "chapters" / f"chapter_{chapter:03d}.md").write_text("chapter", encoding="utf-8")
    (root / "data" / "state.json").write_text('{"current_chapter":' + str(committed) + '}', encoding="utf-8")
    (root / "data" / "next_chapter_plan.json").write_text('{"chapter_id":' + str(committed + 1) + '}', encoding="utf-8")
    (root / "data" / "story_blueprint.json").write_text('{"story_phases":[{"phase_id":"phase-1","title":"第一阶段","chapter_start":3,"chapter_end":8}],"foreshadowing":[{"foreshadow_id":"f-1","title":"伏笔"}],"plot_threads":[{"thread_id":"t-1","title":"主线"}],"character_arcs":[{"arc_id":"a-1","title":"主角弧光"}],"chapter_plan":[{"chapter_id":3,"chapter_title":"只读参考"}]}', encoding="utf-8")


def _milestone(service: PlanningControlService, title: str, chapter: int) -> dict:
    return service.create("milestones", {"title": title, "target_scope": {"target_chapter_min": chapter, "target_chapter_max": chapter}})


def _edge(source: dict, target: dict, **extra: object) -> dict:
    return {"from_node": {"node_type": "milestone", "node_id": source["milestone_id"]}, "to_node": {"node_type": "milestone", "node_id": target["milestone_id"]}, "dependency_type": "precedes", "strength": "hard", **extra}


def test_dependency_get_is_lazy_and_projects_existing_nodes(tmp_path: Path) -> None:
    _project(tmp_path)
    context = get_project_context(tmp_path)
    control = PlanningControlService(context)
    _milestone(control, "起点", 3)
    service = PlanningDependencyService(context)
    view = service.describe()
    assert view["materialized"] is False
    assert not context.planning_dependencies_path.exists()
    kinds = {row["node_type"] for row in view["available_nodes"]}
    assert {"milestone", "blueprint_phase", "blueprint_foreshadow", "structured_plot_thread", "structured_character_arc"} <= kinds


def test_create_edit_cancel_and_idempotency(tmp_path: Path) -> None:
    _project(tmp_path); context = get_project_context(tmp_path); control = PlanningControlService(context)
    first, second = _milestone(control, "前置", 3), _milestone(control, "后置", 4)
    service = PlanningDependencyService(context)
    created = service.create_dependency(_edge(first, second, operation_id="create-once"))
    replay = service.create_dependency(_edge(first, second, operation_id="create-once"))
    assert replay["dependency_id"] == created["dependency_id"] and replay["replayed"] is True
    changed = service.update_dependency(created["dependency_id"], {"description": "作者确认", "expected_dependency_revision": created["dependency_revision"]})
    assert changed["description"] == "作者确认"
    disabled = service.transition_dependency(created["dependency_id"], {"action": "disable", "expected_dependency_revision": changed["dependency_revision"]})
    assert disabled["status"] == "disabled"
    cancelled = service.transition_dependency(created["dependency_id"], {"action": "cancel", "expected_dependency_revision": disabled["dependency_revision"]})
    assert cancelled["status"] == "cancelled" and service.get_dependency(created["dependency_id"])["status"] == "cancelled"


def test_cycles_self_and_non_prerequisite_edges(tmp_path: Path) -> None:
    _project(tmp_path); control = PlanningControlService(get_project_context(tmp_path))
    a, b, c = _milestone(control, "A", 3), _milestone(control, "B", 4), _milestone(control, "C", 5)
    service = PlanningDependencyService(control.context)
    with pytest.raises(PlanningControlError, match="PLANNING_DEPENDENCY_SELF_REFERENCE"):
        service.create_dependency(_edge(a, a))
    service.create_dependency(_edge(a, b)); service.create_dependency(_edge(b, c))
    with pytest.raises(PlanningControlError) as error:
        service.create_dependency(_edge(c, a))
    assert error.value.code == "PLANNING_DEPENDENCY_CYCLE" and len(error.value.details["cycle_path"]) == 4
    # Contradiction is deliberately outside the prerequisite cycle graph.
    contradiction = service.create_dependency(_edge(c, a, dependency_type="contradicts"))
    assert contradiction["dependency_type"] == "contradicts"


def test_order_conflict_blocks_and_node_health(tmp_path: Path) -> None:
    _project(tmp_path); control = PlanningControlService(get_project_context(tmp_path))
    late, early = _milestone(control, "晚", 12), _milestone(control, "早", 8)
    service = PlanningDependencyService(control.context)
    with pytest.raises(PlanningControlError) as error:
        service.create_dependency(_edge(late, early))
    assert error.value.code == "PLANNING_DEPENDENCY_ORDER_CONFLICT"
    soft = service.create_dependency(_edge(late, early, strength="soft"))
    assert soft["validation_warnings"][0]["code"] == "PLANNING_DEPENDENCY_ORDER_CONFLICT"
    one = service.create_dependency(_edge(early, late, dependency_type="blocks", strength="advisory"))
    two = service.create_dependency(_edge(late, early, dependency_type="blocks", strength="advisory"))
    assert one["dependency_id"] and any(issue["code"] == "PLANNING_MUTUAL_BLOCK" for issue in service.health()["issues"])
    control.delete_milestone(early["milestone_id"])
    assert any(issue["code"] == "PLANNING_DEPENDENCY_SOURCE_CANCELLED" for issue in service.health()["issues"])
    assert two["dependency_id"]


def test_custom_nodes_project_isolation_locks_and_versions(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"; _project(first); _project(second)
    context = get_project_context(first); service = PlanningDependencyService(context)
    node = service.create_custom_node({"title": "开战条件", "category": "condition"})
    assert PlanningDependencyService(get_project_context(second)).describe()["materialized"] is False
    lock = PlanningControlService(context).lock({"entity_type": "custom_planning_node", "entity_id": node["node_id"], "field": "title"})
    with pytest.raises(PlanningControlError, match="PLANNING_LOCK_CONFLICT"):
        service.update_custom_node(node["node_id"], {"title": "不能改", "expected_dependency_revision": node["dependency_revision"]})
    PlanningControlService(context).release_lock(lock["lock_id"])
    updated = service.update_custom_node(node["node_id"], {"title": "可改", "expected_dependency_revision": node["dependency_revision"]})
    assert updated["title"] == "可改"
    version = PlanningControlService(context).list_versions()[0]
    PlanningControlService(context).restore_version(version["version_id"])
    assert isinstance(PlanningDependencyService(context).validate()["issues"], list)


def test_api_protected_files_and_rolling_slot_nodes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _project(tmp_path); protected = {name: _hash(tmp_path / "data" / name) for name in ("story_blueprint.json", "next_chapter_plan.json", "state.json")}
    context = get_project_context(tmp_path); window = RollingWindowService(context).initialize({"author_confirm": True, "near_horizon_size": 3, "mid_horizon_size": 6})
    control = PlanningControlService(context); milestone = _milestone(control, "里程碑", 3); slot = window["near_slots"][0]
    monkeypatch.chdir(tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/planning-control/dependencies").status_code == 200
        created = client.post("/api/planning-control/dependencies", json={"from_node": {"node_type": "milestone", "node_id": milestone["milestone_id"]}, "to_node": {"node_type": "chapter_slot", "node_id": slot["slot_id"]}, "dependency_type": "requires", "strength": "hard", "operation_id": "api-create"})
        assert created.status_code == 201
        dependency_id = created.json()["result"]["dependency"]["dependency_id"]
        assert client.get(f"/api/planning-control/dependencies/{dependency_id}").status_code == 200
        assert client.get("/api/planning-control/dependencies/upstream", params={"node_type": "chapter_slot", "node_id": slot["slot_id"]}).status_code == 200
        assert client.post(f"/api/planning-control/dependencies/{dependency_id}/transition", json={"action": "disable"}).status_code == 200
        assert client.post("/api/planning-control/dependency-nodes", json={"title": "人工条件"}).status_code == 201
    assert protected == {name: _hash(tmp_path / "data" / name) for name in protected}


def test_dependency_ui_contract_is_planning_control_subarea() -> None:
    root = Path(__file__).resolve().parents[1]
    template = (root / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    script = (root / "web" / "static" / "planning-control" / "dependencies.js").read_text(encoding="utf-8")
    assert 'id="planning-dependency-area"' in template
    assert "/static/planning-control/dependencies.js" in template
    for token in ("/dependencies", "/dependency-nodes", "data-dependency-transition", "upstream", "downstream"):
        assert token in script
    assert "roll-forward" not in script and "reanchor" not in script and "model" not in script.lower()
