from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from core.project_context import get_project_context
from system.branch_memory_continuity_service import (
    BranchMemoryContinuityService,
    ContinuityConflictError,
    ContinuityRecoveryRequiredError,
    ContinuityScopeError,
)
from system.chapter_lifecycle_service import ChapterLifecycleService


def _fingerprint(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _project(tmp_path: Path) -> tuple[Path, dict]:
    data = tmp_path / "data"
    for path in (
        data / "chapters",
        data / "versions",
        data / "canon_versions",
        data / "chapter_commits",
        data / "branches" / "main",
    ):
        path.mkdir(parents=True, exist_ok=True)
    (data / "state.json").write_text('{"current_chapter": 1}', encoding="utf-8")
    (data / "next_chapter_plan.json").write_text(
        '{"chapter_id": 2, "revision": "plan-1"}', encoding="utf-8"
    )
    previous = "# Chapter 001\n\nImmutable source."
    (data / "chapters" / "chapter_001.md").write_text(previous, encoding="utf-8")
    commit = {
        "schema_version": "1.0",
        "commit_id": "commit-001",
        "chapter_id": 1,
        "status": "committed",
        "source_version_id": "manual_v001",
        "canon_revision_id": "canon-001",
    }
    (data / "chapter_commits" / "commit_001.json").write_text(
        json.dumps(commit), encoding="utf-8"
    )
    registry = {
        "project_id": tmp_path.name,
        "timeline_id": "main",
        "active_branch_id": "main",
        "revision": "7",
    }
    (data / "branches" / "main" / "registry.json").write_text(
        json.dumps(registry), encoding="utf-8"
    )
    events_dir = data / "narrative_memory" / "events" / "main" / "main"
    events_dir.mkdir(parents=True)
    event = {
        "schema_version": "2.0",
        "event_id": "memory-1",
        "project_id": tmp_path.name,
        "timeline_id": "main",
        "branch_id": "main",
        "chapter_id": 1,
        "event_type": "chapter_memory",
        "payload": {"fact": "source"},
        "status": "confirmed",
        "created_at": "2026-07-30T00:00:00Z",
    }
    event["record_fingerprint"] = _fingerprint(event)
    (events_dir / "chapter_001.json").write_text(
        json.dumps([event]), encoding="utf-8"
    )
    return tmp_path, {
        "chapter": (data / "chapters" / "chapter_001.md").read_bytes(),
        "commit": (data / "chapter_commits" / "commit_001.json").read_bytes(),
        "events": (events_dir / "chapter_001.json").read_bytes(),
    }


def _create(root: Path, operation_id: str = "d6da-create"):
    return ChapterLifecycleService(get_project_context(root)).create_next_chapter(
        operation_id=operation_id,
        project_id=root.name,
        timeline_id="main",
        current_chapter_id=1,
        expected_active_branch_id="main",
        expected_branch_revision="7",
        planning_chapter_id=2,
    )


def test_success_binds_scope_source_and_preserves_source(tmp_path: Path):
    root, before = _project(tmp_path)
    result = _create(root)
    assert result["memory_readiness"] == "ready"
    assert result["vector_readiness"] == "not_ready"
    assert result["memory_continuity"]["vector_role"] == "REBUILDABLE_CACHE"
    path = (
        root / "data" / "narrative_memory" / "continuity" / "main" / "main"
        / "chapter_001_to_002.json"
    )
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    assert (
        snapshot["project_id"],
        snapshot["timeline_id"],
        snapshot["branch_id"],
        snapshot["previous_chapter_id"],
        snapshot["successor_chapter_id"],
    ) == (root.name, "main", "main", 1, 2)
    assert snapshot["source_authority"]["kind"] == "branch_narrative_memory"
    assert snapshot["vector_authority_included"] is False
    assert (root / "data" / "chapters" / "chapter_001.md").read_bytes() == before["chapter"]
    assert (root / "data" / "chapter_commits" / "commit_001.json").read_bytes() == before["commit"]
    assert (
        root / "data" / "narrative_memory" / "events" / "main" / "main"
        / "chapter_001.json"
    ).read_bytes() == before["events"]


def test_lifecycle_replay_is_one_durable_snapshot(tmp_path: Path):
    root, _ = _project(tmp_path)
    first = _create(root)
    second = _create(root)
    paths = list(
        (root / "data" / "narrative_memory" / "continuity").rglob("*.json")
    )
    assert len(paths) == 1
    assert first["memory_continuity"] == second["memory_continuity"]


def test_existing_successor_recovery_creates_missing_snapshot(tmp_path: Path):
    root, _ = _project(tmp_path)
    context = get_project_context(root)
    lifecycle = ChapterLifecycleService(context)
    successor = root / "data" / "chapters" / "chapter_002.md"
    successor.write_text("# Chapter 002\n", encoding="utf-8")
    lifecycle.initialize_chapter_versions(2)
    lifecycle.initialize_chapter_canon(2, successor.read_text(encoding="utf-8"))
    result = _create(root, "d6da-existing")
    assert result["status"] == "NEXT_CHAPTER_ALREADY_EXISTS"
    assert result["memory_readiness"] == "ready"
    assert result["recovery_performed"] is True


def test_interrupted_after_snapshot_recovers_one_result(tmp_path: Path):
    root, _ = _project(tmp_path)

    def fault(point: str) -> None:
        if point == "after_memory_continuity_snapshot":
            raise RuntimeError("simulated interruption")

    context = get_project_context(root)
    with pytest.raises(RuntimeError):
        ChapterLifecycleService(context, fault_injector=fault).create_next_chapter(
            operation_id="d6da-recover"
        )
    result = ChapterLifecycleService(context).resume_operation("d6da-recover")
    assert result["memory_readiness"] == "ready"
    assert len(list((root / "data" / "narrative_memory" / "continuity").rglob("*.json"))) == 1


def test_wrong_project_timeline_branch_and_transition_fail_closed(tmp_path: Path):
    root, _ = _project(tmp_path)
    service = BranchMemoryContinuityService(get_project_context(root))
    kwargs = {
        "project_id": root.name,
        "timeline_id": "main",
        "branch_id": "main",
        "previous_chapter_id": 1,
        "successor_chapter_id": 2,
    }
    with pytest.raises(ContinuityScopeError):
        service.read(**{**kwargs, "project_id": "other"})
    with pytest.raises(ContinuityScopeError):
        service.read(**{**kwargs, "timeline_id": "alternate"})
    with pytest.raises(ContinuityRecoveryRequiredError):
        service.read(**{**kwargs, "branch_id": "other"})
    with pytest.raises(ContinuityScopeError):
        service.read(**{**kwargs, "successor_chapter_id": 3})


def test_corrupt_incomplete_and_source_change_fail_closed(tmp_path: Path):
    root, _ = _project(tmp_path)
    _create(root)
    service = BranchMemoryContinuityService(get_project_context(root))
    kwargs = {
        "project_id": root.name,
        "timeline_id": "main",
        "branch_id": "main",
        "previous_chapter_id": 1,
        "successor_chapter_id": 2,
    }
    snapshot_path = (
        root / "data" / "narrative_memory" / "continuity" / "main" / "main"
        / "chapter_001_to_002.json"
    )
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["completion_state"] = "incomplete"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    with pytest.raises(ContinuityRecoveryRequiredError):
        service.read(**kwargs)

    root2 = tmp_path / "second"
    root2.mkdir()
    _project(root2)
    _create(root2)
    events = (
        root2 / "data" / "narrative_memory" / "events" / "main" / "main"
        / "chapter_001.json"
    )
    rows = json.loads(events.read_text(encoding="utf-8"))
    rows[0]["payload"] = {"fact": "changed"}
    rows[0]["record_fingerprint"] = _fingerprint(
        {key: value for key, value in rows[0].items() if key != "record_fingerprint"}
    )
    events.write_text(json.dumps(rows), encoding="utf-8")
    with pytest.raises(ContinuityConflictError):
        BranchMemoryContinuityService(get_project_context(root2)).read(
            project_id=root2.name,
            timeline_id="main",
            branch_id="main",
            previous_chapter_id=1,
            successor_chapter_id=2,
        )


def test_symlink_snapshot_is_rejected(tmp_path: Path):
    root, _ = _project(tmp_path)
    _create(root)
    snapshot_path = (
        root / "data" / "narrative_memory" / "continuity" / "main" / "main"
        / "chapter_001_to_002.json"
    )
    outside = root / "outside-continuity.json"
    outside.write_text(snapshot_path.read_text(encoding="utf-8"), encoding="utf-8")
    snapshot_path.unlink()
    os.symlink(outside, snapshot_path)
    with pytest.raises(ContinuityScopeError):
        BranchMemoryContinuityService(get_project_context(root)).read(
            project_id=root.name,
            timeline_id="main",
            branch_id="main",
            previous_chapter_id=1,
            successor_chapter_id=2,
        )
