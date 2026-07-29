from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import pytest

from core.project_context import bind_project_context, get_project_context
from fastapi.testclient import TestClient
from system.chapter_lifecycle_service import ChapterLifecycleService
from system.cross_chapter_readiness_service import CrossChapterReadinessService
from system.cross_chapter_turn_start_service import (
    CrossChapterTurnStartError,
    CrossChapterTurnStartService,
)
from system.cross_chapter_readiness_service import _fingerprint
from system.narrative_branch_lifecycle_service import BranchLifecycleService


def _tree(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def _project(tmp_path: Path):
    data = tmp_path / "data"
    for directory in (
        data / "chapters", data / "versions", data / "canon_versions",
        data / "audit", data / "branch_operations",
        data / "chapter_lifecycle" / "operations",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    (data / "state.json").write_text('{"current_chapter":1}', encoding="utf-8")
    (data / "derived_state.json").write_text("{}", encoding="utf-8")
    (data / "next_chapter_plan.json").write_text(
        '{"chapter_id":2,"revision":"plan-2"}', encoding="utf-8")
    (data / "chapters" / "chapter_001.md").write_text(
        "# Chapter 001\n\nDone.", encoding="utf-8")
    commits = data / "chapter_commits"
    commits.mkdir()
    (commits / "commit_001.json").write_text(json.dumps({
        "schema_version": "1.0", "commit_id": "commit-001",
        "chapter_id": 1, "status": "committed",
        "source_version_id": "source-001",
        "canon_revision_id": "canon-001",
    }), encoding="utf-8")
    context = get_project_context(tmp_path)
    branches = BranchLifecycleService(context)
    scope = {"project_id": tmp_path.name, "timeline_id": "main"}
    branches.create("branch-create", {**scope, "branch_id": "main"})
    revision = branches.list_branches(**scope)["registry_revision"]
    branches.select("branch-select", {
        **scope, "branch_id": "main", "expected_registry_revision": revision})
    ChapterLifecycleService(context).create_next_chapter(
        operation_id="chapter-create")
    return context, branches


def _ready(context):
    return CrossChapterReadinessService(context).readiness(
        project_id=context.root.name, timeline_id="main",
        branch_id="main", previous_chapter_id=1)


def _start_kwargs(context, ready, operation_id="turn-start"):
    return {
        "operation_id": operation_id, "project_id": context.root.name,
        "timeline_id": "main", "branch_id": "main",
        "previous_chapter_id": 1, "successor_chapter_id": 2,
        "expected_readiness_fingerprint": ready["authority_fingerprint"],
    }


def test_readiness_is_pure_and_deterministic(tmp_path: Path):
    context, _ = _project(tmp_path)
    before = _tree(tmp_path)
    first = _ready(context)
    second = _ready(context)
    assert first == second
    assert first["readiness_code"] == "READY_TO_START_TURN"
    assert _tree(tmp_path) == before


def test_readiness_requires_durable_lifecycle_result(tmp_path: Path):
    context, _ = _project(tmp_path)
    result = context.data_dir / "chapter_lifecycle" / "operations" / "chapter-create.result.json"
    result.unlink()
    before = _tree(tmp_path)
    readiness = _ready(context)
    assert readiness["readiness_code"] == "BLOCKED_LIFECYCLE_INCOMPLETE"
    assert _tree(tmp_path) == before


def test_start_creates_one_plan_preview_and_replays(tmp_path: Path):
    context, _ = _project(tmp_path)
    ready = _ready(context)
    service = CrossChapterTurnStartService(context)
    kwargs = _start_kwargs(context, ready)
    first = service.start_turn(**kwargs)
    second = service.start_turn(**kwargs)
    assert first == second
    assert first["turn_status"] == "awaiting_action"
    assert first["preview"]["turn_id"] == first["turn_id"]
    assert len(list((context.data_dir / "narrative_turn" / "plans" / "main" / "main").glob("*.json"))) == 1
    assert _ready(context)["readiness_code"] == "TURN_ALREADY_STARTED"


def test_same_operation_different_request_conflicts_without_second_turn(tmp_path: Path):
    context, _ = _project(tmp_path)
    ready = _ready(context)
    service = CrossChapterTurnStartService(context)
    service.start_turn(**_start_kwargs(context, ready))
    changed = _start_kwargs(context, ready)
    changed["successor_chapter_id"] = 3
    with pytest.raises(CrossChapterTurnStartError) as caught:
        service.start_turn(**changed)
    assert caught.value.code == "OPERATION_CONFLICT"
    assert len(list((context.data_dir / "narrative_turn" / "plans" / "main" / "main").glob("*.json"))) == 1


def test_response_loss_after_plan_is_recoverable(tmp_path: Path):
    context, _ = _project(tmp_path)
    ready = _ready(context)
    fired = False

    def fault(point: str):
        nonlocal fired
        if point == "after_turn_delegate" and not fired:
            fired = True
            raise RuntimeError("response lost")

    kwargs = _start_kwargs(context, ready)
    with pytest.raises(RuntimeError):
        CrossChapterTurnStartService(context, fault_injector=fault).start_turn(**kwargs)
    result = CrossChapterTurnStartService(context).start_turn(**kwargs)
    assert result["turn_status"] == "awaiting_action"
    assert len(list((context.data_dir / "narrative_turn" / "plans" / "main" / "main").glob("*.json"))) == 1


def test_plan_effect_without_phase_replays_without_duplicate(tmp_path: Path):
    context, _ = _project(tmp_path)
    ready = _ready(context)

    def fault(point: str):
        if point == "after_plan_effect":
            raise RuntimeError("crash after plan effect")

    kwargs = _start_kwargs(context, ready)
    with pytest.raises(RuntimeError):
        CrossChapterTurnStartService(context, fault_injector=fault).start_turn(**kwargs)
    result = CrossChapterTurnStartService(context).start_turn(**kwargs)
    assert result["turn_status"] == "awaiting_action"
    assert len(list((context.data_dir / "narrative_turn" / "plans" / "main" / "main").glob("*.json"))) == 1


def test_result_without_completed_phase_repairs_only_phase(tmp_path: Path):
    context, _ = _project(tmp_path)
    ready = _ready(context)
    fired = False

    def fault(point: str):
        nonlocal fired
        if point == "after_result" and not fired:
            fired = True
            raise RuntimeError("response lost")

    kwargs = _start_kwargs(context, ready)
    with pytest.raises(RuntimeError):
        CrossChapterTurnStartService(context, fault_injector=fault).start_turn(**kwargs)
    result_path = context.data_dir / "chapter_progression" / "operations" / "turn-start.result.json"
    before = result_path.read_bytes()
    result = CrossChapterTurnStartService(context).start_turn(**kwargs)
    assert result_path.read_bytes() == before
    phase = json.loads((result_path.with_name("turn-start.phase.json")).read_text())
    assert phase["phase"] == "completed"
    assert result["turn_status"] == "awaiting_action"


def test_concurrent_different_operations_publish_one_turn(tmp_path: Path):
    context, _ = _project(tmp_path)
    ready = _ready(context)
    barrier = threading.Barrier(3)
    outcomes = []

    def worker(operation_id: str):
        barrier.wait()
        try:
            outcomes.append(CrossChapterTurnStartService(context).start_turn(
                **_start_kwargs(context, ready, operation_id)))
        except Exception as exc:
            outcomes.append(exc)

    threads = [threading.Thread(target=worker, args=(f"start-{i}",)) for i in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(5)
        assert not thread.is_alive()
    assert sum(isinstance(item, dict) for item in outcomes) == 1
    assert len(list((context.data_dir / "narrative_turn" / "plans" / "main" / "main").glob("*.json"))) == 1


def test_incomplete_start_blocks_archive(tmp_path: Path):
    context, branches = _project(tmp_path)
    ready = _ready(context)

    def fault(point: str):
        if point == "after_claim":
            raise RuntimeError("crash")

    with pytest.raises(RuntimeError):
        CrossChapterTurnStartService(context, fault_injector=fault).start_turn(
            **_start_kwargs(context, ready))
    revision = branches.list_branches(context.root.name, "main")["registry_revision"]
    with pytest.raises(Exception) as caught:
        branches.archive("archive-main", {
            "project_id": context.root.name, "timeline_id": "main",
            "branch_id": "main", "expected_registry_revision": revision})
    assert getattr(caught.value, "code", "") == "NARRATIVE_TURN_CONFIRM_RECOVERY_REQUIRED"


def test_multiple_completed_same_successor_bundles_fail_closed(tmp_path: Path):
    context, _ = _project(tmp_path)
    root = context.data_dir / "chapter_lifecycle" / "operations"
    claim = json.loads((root / "chapter-create.json").read_text())
    phase = json.loads((root / "chapter-create.phase.json").read_text())
    result = json.loads((root / "chapter-create.result.json").read_text())
    result["operation_id"] = "chapter-create-copy"
    body = dict(result)
    body.pop("outcome_fingerprint", None)
    result["outcome_fingerprint"] = _fingerprint(body)
    (root / "chapter-create-copy.json").write_text(json.dumps(claim), encoding="utf-8")
    (root / "chapter-create-copy.phase.json").write_text(json.dumps(phase), encoding="utf-8")
    (root / "chapter-create-copy.result.json").write_text(json.dumps(result), encoding="utf-8")
    readiness = _ready(context)
    assert readiness["readiness_code"] == "BLOCKED_LIFECYCLE_CONFLICT"


def test_orphan_lifecycle_result_fails_closed_without_write(tmp_path: Path):
    context, _ = _project(tmp_path)
    root = context.data_dir / "chapter_lifecycle" / "operations"
    (root / "orphan.result.json").write_text("{}", encoding="utf-8")
    before = _tree(tmp_path)
    readiness = _ready(context)
    assert readiness["readiness_code"] == "BLOCKED_CORRUPT_AUTHORITY"
    assert _tree(tmp_path) == before


def test_result_without_completed_phase_blocks_archive(tmp_path: Path):
    context, branches = _project(tmp_path)
    ready = _ready(context)

    def fault(point: str):
        if point == "after_result":
            raise RuntimeError("lost response")

    with pytest.raises(RuntimeError):
        CrossChapterTurnStartService(context, fault_injector=fault).start_turn(
            **_start_kwargs(context, ready))
    revision = branches.list_branches(context.root.name, "main")["registry_revision"]
    with pytest.raises(Exception) as caught:
        branches.archive("archive-result-no-phase", {
            "project_id": context.root.name, "timeline_id": "main",
            "branch_id": "main", "expected_registry_revision": revision})
    assert getattr(caught.value, "code", "") == "NARRATIVE_TURN_CONFIRM_RECOVERY_REQUIRED"


def test_completed_replay_rejects_result_tampering(tmp_path: Path):
    context, _ = _project(tmp_path)
    ready = _ready(context)
    kwargs = _start_kwargs(context, ready)
    service = CrossChapterTurnStartService(context)
    service.start_turn(**kwargs)
    result_path = context.data_dir / "chapter_progression" / "operations" / "turn-start.result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["plan_fingerprint"] = "0" * 64
    body = dict(result)
    body.pop("outcome_fingerprint", None)
    result["outcome_fingerprint"] = _fingerprint(body)
    result_path.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(CrossChapterTurnStartError) as caught:
        service.start_turn(**kwargs)
    assert caught.value.code == "CORRUPT_OPERATION"


def test_progression_routes_are_explicit_and_no_store(tmp_path: Path):
    context, _ = _project(tmp_path)
    from web.app import app

    with bind_project_context(context):
        client = TestClient(app)
        response = client.get("/api/chapter-progression/readiness", params={
            "project_id": context.root.name, "timeline_id": "main",
            "branch_id": "main", "previous_chapter_id": 1,
        })
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        ready = response.json()["result"]
        response = client.post("/api/chapter-progression/start-turn", json={
            **_start_kwargs(context, ready, "route-start"),
        })
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["result"]["turn_status"] == "awaiting_action"


def test_malformed_start_dto_has_no_turn_write(tmp_path: Path):
    context, _ = _project(tmp_path)
    from web.app import app

    before = _tree(tmp_path)
    with bind_project_context(context):
        response = TestClient(app).post(
            "/api/chapter-progression/start-turn",
            json={"operation_id": "../bad"})
    assert response.status_code == 422
    assert _tree(tmp_path) == before
