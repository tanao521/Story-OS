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
from system.narrative_branch_lifecycle_service import BranchLifecycleService
from system.vector_index_lifecycle import (
    BranchVectorNotReady,
    VectorOperationConflict,
    VectorScopeRequired,
    continuity_vector_readiness,
    rebuild_continuity_index,
)
import system.vector_index_lifecycle as vector_lifecycle


class FakeCollection:
    def __init__(self) -> None:
        self.rows = {}

    def add(self, ids, documents, metadatas):
        for index, identity in enumerate(ids):
            self.rows[identity] = (documents[index], metadatas[index])

    def delete(self, where):
        clauses = where.get("$and", []) if "$and" in where else [where]
        expected = {
            next(iter(item)): next(iter(item.values())) for item in clauses
        }
        self.rows = {
            key: value
            for key, value in self.rows.items()
            if not all(value[1].get(field) == target for field, target in expected.items())
        }

    def count(self):
        return len(self.rows)


class FakeManager:
    def __init__(self, collection: FakeCollection | None) -> None:
        self.collection = collection

    def get_collection(self, _context):
        return self.collection


def _manager(collection: FakeCollection):
    return FakeManager(collection)


def _fingerprint(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _project(tmp_path: Path):
    context = get_project_context(tmp_path)
    data = context.data_dir
    for path in (
        context.chapters_dir,
        context.versions_dir,
        data / "canon_versions",
        data / "chapter_commits",
    ):
        path.mkdir(parents=True, exist_ok=True)
    (data / "state.json").write_text('{"current_chapter": 1}', encoding="utf-8")
    (data / "next_chapter_plan.json").write_text(
        '{"chapter_id": 2, "revision": "plan-1"}', encoding="utf-8"
    )
    previous = "# Chapter 001\n\nAuthoritative previous chapter."
    (context.chapters_dir / "chapter_001.md").write_text(previous, encoding="utf-8")
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
    branches = BranchLifecycleService(context)
    common = {"project_id": tmp_path.name, "timeline_id": "main"}
    branches.create("seed-main", {**common, "branch_id": "main"})
    created_revision = branches.list_branches(**common)["registry_revision"]
    branches.select(
        "select-main",
        {
            **common,
            "branch_id": "main",
            "expected_registry_revision": created_revision,
        },
    )
    events_dir = data / "narrative_memory" / "events" / "main" / "main"
    events_dir.mkdir(parents=True)
    event = {
        "schema_version": "2.0",
        "event_id": "event-1",
        "project_id": tmp_path.name,
        "timeline_id": "main",
        "branch_id": "main",
        "chapter_id": 1,
        "event_type": "memory",
        "payload": {"fact": "immutable"},
        "status": "confirmed",
        "created_at": "2026-07-30T00:00:00Z",
    }
    event["record_fingerprint"] = _fingerprint(event)
    (events_dir / "chapter_001.json").write_text(
        json.dumps([event]), encoding="utf-8"
    )
    revision = branches.list_branches(**common)["registry_revision"]
    result = ChapterLifecycleService(context).create_next_chapter(
        operation_id="create-successor",
        expected_active_branch_id="main",
        expected_branch_revision=revision,
        planning_chapter_id=2,
    )
    assert result["memory_readiness"] == "ready"
    return context, revision


def _rebuild(context, collection, operation_id="vector-continuity"):
    return rebuild_continuity_index(
        context,
        operation_id=operation_id,
        project_id=context.root.name,
        timeline_id="main",
        branch_id="main",
        previous_chapter_id=1,
        successor_chapter_id=2,
        vector_client_manager=_manager(collection),
    )


def test_success_manifest_is_bound_to_a_snapshot_and_vector_is_cache(tmp_path: Path):
    context, _ = _project(tmp_path)
    source_before = (context.chapters_dir / "chapter_001.md").read_bytes()
    events = (
        context.narrative_memory_dir / "events" / "main" / "main"
        / "chapter_001.json"
    )
    events_before = events.read_bytes()
    result = _rebuild(context, FakeCollection())
    manifest = result["manifest"]
    assert result["vector_ready"] is True
    assert result["vector_role"] == "REBUILDABLE_CACHE"
    assert manifest["continuity_snapshot_id"] == result["continuity_snapshot_id"]
    assert manifest["continuity_record_fingerprint"] == result["continuity_record_fingerprint"]
    assert manifest["continuity_previous_chapter_id"] == 1
    assert manifest["continuity_successor_chapter_id"] == 2
    assert (context.chapters_dir / "chapter_001.md").read_bytes() == source_before
    assert events.read_bytes() == events_before
    assert continuity_vector_readiness(
        context,
        project_id=context.root.name,
        timeline_id="main",
        branch_id="main",
        previous_chapter_id=1,
        successor_chapter_id=2,
    )["vector_ready"] is True


def test_replay_has_one_logical_result_and_no_duplicate_records(tmp_path: Path):
    context, _ = _project(tmp_path)
    collection = FakeCollection()
    first = _rebuild(context, collection)
    count = collection.count()
    second = _rebuild(context, collection)
    assert second["idempotent_replay"] is True
    assert second["manifest"]["record_fingerprint"] == first["manifest"]["record_fingerprint"]
    assert collection.count() == count


def test_interrupted_manifest_publication_recovers(tmp_path: Path, monkeypatch):
    context, _ = _project(tmp_path)
    collection = FakeCollection()

    def fault(point: str):
        if point == "after_manifest_publication":
            raise RuntimeError("interrupted")

    monkeypatch.setattr(vector_lifecycle, "_fault_injector", fault)
    with pytest.raises(RuntimeError):
        _rebuild(context, collection, "vector-recover")
    monkeypatch.setattr(vector_lifecycle, "_fault_injector", None)
    recovered = _rebuild(context, collection, "vector-recover")
    assert recovered["vector_ready"] is True
    assert continuity_vector_readiness(
        context,
        project_id=context.root.name,
        timeline_id="main",
        branch_id="main",
        previous_chapter_id=1,
        successor_chapter_id=2,
    )["readiness_code"] == "VECTOR_CONTINUITY_READY"


def test_missing_or_corrupt_cache_rebuilds_from_unchanged_authority(tmp_path: Path):
    context, _ = _project(tmp_path)
    collection = FakeCollection()
    first = _rebuild(context, collection, "vector-repair")
    manifest_path = (
        context.data_dir / "chroma" / "manifests" / "main" / "main.json"
    )
    manifest_path.unlink()
    assert continuity_vector_readiness(
        context,
        project_id=context.root.name,
        timeline_id="main",
        branch_id="main",
        previous_chapter_id=1,
        successor_chapter_id=2,
    )["vector_ready"] is False
    repaired = _rebuild(context, collection, "vector-repair")
    assert repaired["vector_ready"] is True
    assert repaired["manifest"]["continuity_snapshot_id"] == first["continuity_snapshot_id"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["record_fingerprint"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert _rebuild(context, collection, "vector-repair")["vector_ready"] is True


def test_rebuild_failure_is_retryable_and_does_not_change_authority(tmp_path: Path):
    context, _ = _project(tmp_path)
    snapshot_path = next(
        (context.narrative_memory_dir / "continuity").rglob("*.json")
    )
    snapshot_before = snapshot_path.read_bytes()
    unavailable = FakeManager(None)
    with pytest.raises(BranchVectorNotReady):
        rebuild_continuity_index(
            context,
            operation_id="vector-retry",
            project_id=context.root.name,
            timeline_id="main",
            branch_id="main",
            previous_chapter_id=1,
            successor_chapter_id=2,
            vector_client_manager=unavailable,
        )
    assert snapshot_path.read_bytes() == snapshot_before
    assert _rebuild(context, FakeCollection(), "vector-retry")["vector_ready"] is True


def test_wrong_scope_stale_source_and_operation_collision_fail_closed(tmp_path: Path):
    context, _ = _project(tmp_path)
    with pytest.raises(VectorScopeRequired):
        rebuild_continuity_index(
            context,
            operation_id="wrong-timeline",
            project_id=context.root.name,
            timeline_id="alternate",
            branch_id="main",
            previous_chapter_id=1,
            successor_chapter_id=2,
            vector_client_manager=_manager(FakeCollection()),
        )
    _rebuild(context, FakeCollection(), "scope-collision")
    chapter = context.chapters_dir / "chapter_001.md"
    chapter.write_text(chapter.read_text(encoding="utf-8") + "\ndrift", encoding="utf-8")
    with pytest.raises(VectorOperationConflict):
        rebuild_continuity_index(
            context,
            operation_id="scope-collision",
            project_id=context.root.name,
            timeline_id="main",
            branch_id="main",
            previous_chapter_id=1,
            successor_chapter_id=2,
            vector_client_manager=_manager(FakeCollection()),
        )
    events = (
        context.narrative_memory_dir / "events" / "main" / "main"
        / "chapter_001.json"
    )
    rows = json.loads(events.read_text(encoding="utf-8"))
    rows[0]["payload"] = {"fact": "drifted"}
    rows[0]["record_fingerprint"] = _fingerprint(
        {key: value for key, value in rows[0].items() if key != "record_fingerprint"}
    )
    events.write_text(json.dumps(rows), encoding="utf-8")
    with pytest.raises(ContinuityConflictError):
        _rebuild(context, FakeCollection(), "source-drift")


def test_stale_branch_or_completion_authority_fails_closed(tmp_path: Path):
    branch_root = tmp_path / "branch"
    branch_root.mkdir()
    context, revision = _project(branch_root)
    branch_service = BranchLifecycleService(context)
    branch_service.create(
        "revision-drift",
        {
            "project_id": context.root.name,
            "timeline_id": "main",
            "branch_id": "other",
            "expected_registry_revision": revision,
        },
    )
    current = branch_service.list_branches(
        project_id=context.root.name, timeline_id="main"
    )["registry_revision"]
    branch_service.select(
        "select-other",
        {
            "project_id": context.root.name,
            "timeline_id": "main",
            "branch_id": "other",
            "expected_registry_revision": current,
        },
    )
    current = branch_service.list_branches(
        project_id=context.root.name, timeline_id="main"
    )["registry_revision"]
    branch_service.select(
        "reselect-main",
        {
            "project_id": context.root.name,
            "timeline_id": "main",
            "branch_id": "main",
            "expected_registry_revision": current,
        },
    )
    with pytest.raises(
        VectorOperationConflict,
        match="VECTOR_CONTINUITY_BRANCH_AUTHORITY_DRIFT",
    ):
        _rebuild(context, FakeCollection(), "stale-branch")

    commit_root = tmp_path / "commit"
    commit_root.mkdir()
    context2, _ = _project(commit_root)
    commit_path = context2.data_dir / "chapter_commits" / "commit_001.json"
    commit = json.loads(commit_path.read_text(encoding="utf-8"))
    commit["status"] = "committed_with_warnings"
    commit_path.write_text(json.dumps(commit), encoding="utf-8")
    with pytest.raises(
        VectorOperationConflict,
        match="VECTOR_CONTINUITY_COMPLETION_AUTHORITY_DRIFT",
    ):
        _rebuild(context2, FakeCollection(), "stale-completion")


def test_cross_project_branch_and_symlink_manifest_fail_closed(tmp_path: Path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    context, _ = _project(first)
    other, _ = _project(second)
    with pytest.raises(ContinuityScopeError):
        rebuild_continuity_index(
            context,
            operation_id="wrong-project",
            project_id=other.root.name,
            timeline_id="main",
            branch_id="main",
            previous_chapter_id=1,
            successor_chapter_id=2,
            vector_client_manager=_manager(FakeCollection()),
        )
    with pytest.raises(ContinuityRecoveryRequiredError):
        rebuild_continuity_index(
            context,
            operation_id="wrong-branch",
            project_id=context.root.name,
            timeline_id="main",
            branch_id="other",
            previous_chapter_id=1,
            successor_chapter_id=2,
            vector_client_manager=_manager(FakeCollection()),
        )
    manifest_parent = context.data_dir / "chroma" / "manifests" / "main"
    manifest_parent.parent.mkdir(parents=True, exist_ok=True)
    outside = context.root / "outside-manifests"
    outside.mkdir()
    os.symlink(outside, manifest_parent, target_is_directory=True)
    with pytest.raises(VectorScopeRequired):
        _rebuild(context, FakeCollection(), "symlink-manifest")
