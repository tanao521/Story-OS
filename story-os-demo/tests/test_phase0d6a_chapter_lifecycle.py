"""Phase 0D6-A: Shared Chapter Lifecycle Authority tests.

Verifies:
  1. resolve_next_chapter() is pure read (no file creation)
  2. resolve_next_chapter() returns correct status for missing/existing chapters
  3. create_next_chapter() creates exactly one chapter with minimal assets
  4. create_next_chapter() is idempotent (same operation ID = replay)
  5. create_next_chapter() rejects different request with same operation ID
  6. create_next_chapter() first-writer-wins on concurrent creation
  7. create_next_chapter() fails closed when current chapter not complete
  8. create_next_chapter() fails closed on branch staleness
  9. Recovery: operation with fault injected can be replayed
 10. Previous chapter assets remain immutable
 11. Traditional and Simulator share the same service
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

import pytest

from core.project_context import get_project_context
from system.chapter_lifecycle_service import (
    ChapterLifecycleService,
    ChapterLifecycleError,
    CurrentChapterNotCompleteError,
    CommitRecoveryRequiredError,
    CommitResultInvalidError,
    NextChapterAlreadyExistsError,
    ChapterCreationConflictError,
    OperationConflictError,
    BranchStaleError,
    VersionInitializationError,
    CanonInitializationError,
    ChapterLifecycleRecoveryRequiredError,
)
from system.version_manager import list_versions
from system.revision_service import RevisionService


def _sha256_file(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dir_fingerprint(root: Path) -> dict[str, str]:
    fp: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            fp[str(p.relative_to(root))] = _sha256_file(p)
    return fp


def _make_project(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    chapters_dir = data_dir / "chapters"
    chapters_dir.mkdir()
    versions_dir = data_dir / "versions"
    versions_dir.mkdir()
    canon_dir = data_dir / "canon_versions"
    canon_dir.mkdir()
    (data_dir / "audit").mkdir()
    (data_dir / "branch_operations").mkdir()
    (data_dir / "chapter_lifecycle" / "operations").mkdir(parents=True)
    (data_dir / "derived_state.json").write_text("{}")
    (data_dir / "state.json").write_text('{"current_chapter": 1}')
    (data_dir / "next_chapter_plan.json").write_text("{}")
    (data_dir / "chapters" / "chapter_001.md").write_text("# Chapter 001\n\nTest content.")
    return tmp_path


def _setup_commit(data_dir: Path, chapter_id: int = 1, status: str = "committed") -> None:
    commits_dir = data_dir / "chapter_commits"
    commits_dir.mkdir(parents=True, exist_ok=True)
    commit_id = f"commit-{chapter_id:03d}"
    (commits_dir / f"commit_{chapter_id:03d}.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "commit_id": commit_id,
                "chapter_id": chapter_id,
                "status": status,
                "source_type": "committed",
                "source_version_id": f"committed_{chapter_id:03d}",
                "source_hash": "",
                "committed_at": "2025-01-01T00:00:00Z",
            },
            ensure_ascii=False,
        )
    )


def _setup_branch_registry(data_dir: Path, branch_id: str = "main", revision: str = "1") -> None:
    branches_dir = data_dir / "branches" / "main"
    branches_dir.mkdir(parents=True, exist_ok=True)
    (branches_dir / "registry.json").write_text(
        json.dumps(
            {
                "project_id": data_dir.parent.name,
                "timeline_id": "main",
                "active_branch_id": branch_id,
                "revision": revision,
            },
            ensure_ascii=False,
        )
    )


def _setup_complete_chapter(root: Path, chapter_id: int) -> None:
    """Create a fully initialized chapter (file + versions + canon)."""
    data_dir = root / "data"
    ch_path = data_dir / "chapters" / f"chapter_{chapter_id:03d}.md"
    ch_path.parent.mkdir(parents=True, exist_ok=True)
    ch_path.write_text(f"# Chapter {chapter_id:03d}\n\nContent.")
    context = get_project_context(root)
    svc = ChapterLifecycleService(context)
    svc.initialize_chapter_versions(chapter_id)
    svc.initialize_chapter_canon(chapter_id, ch_path.read_text())


@pytest.fixture
def isolated_project(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    root = _make_project(tmp_path)
    data_dir = root / "data"
    _setup_branch_registry(data_dir)
    _setup_commit(data_dir, chapter_id=1)
    before = _dir_fingerprint(root)
    return root, before


@pytest.fixture
def isolated_project_no_commit(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    root = _make_project(tmp_path)
    data_dir = root / "data"
    _setup_branch_registry(data_dir)
    before = _dir_fingerprint(root)
    return root, before


@pytest.fixture
def isolated_project_no_branch(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    root = _make_project(tmp_path)
    data_dir = root / "data"
    _setup_commit(data_dir, chapter_id=1)
    before = _dir_fingerprint(root)
    return root, before


# ── Pure read: resolve_next_chapter ─────────────────────────


class TestResolveNextChapterPureRead:
    def test_resolve_is_pure_read_no_files_created(self, isolated_project):
        tmp_path, before = isolated_project
        context = get_project_context(tmp_path)
        svc = ChapterLifecycleService(context)
        result = svc.resolve_next_chapter()
        after = _dir_fingerprint(tmp_path)
        assert before == after, "resolve_next_chapter() must not create files"

    def test_resolve_no_current_chapter_blocked(self, isolated_project):
        tmp_path, _before = isolated_project
        state_path = tmp_path / "data" / "state.json"
        state_path.write_text("{}")
        context = get_project_context(tmp_path)
        svc = ChapterLifecycleService(context)
        result = svc.resolve_next_chapter()
        assert result["status"] == "NEXT_CHAPTER_BLOCKED"
        assert result["reason"] == "NO_CURRENT_CHAPTER"

    def test_resolve_current_not_commit_blocked(self, isolated_project_no_commit):
        tmp_path, _before = isolated_project_no_commit
        context = get_project_context(tmp_path)
        svc = ChapterLifecycleService(context)
        result = svc.resolve_next_chapter()
        assert result["status"] == "NEXT_CHAPTER_BLOCKED"
        assert result["reason"] == "CURRENT_CHAPTER_NOT_COMPLETE"

    def test_resolve_next_missing_when_no_chapter_2(self, isolated_project):
        tmp_path, _before = isolated_project
        context = get_project_context(tmp_path)
        svc = ChapterLifecycleService(context)
        result = svc.resolve_next_chapter()
        assert result["status"] == "NEXT_CHAPTER_MISSING"
        assert result["next_chapter_id"] == 2
        assert result["existence"] == "absent"
        assert result["commit_ready"] is True

    def test_resolve_next_available_when_chapter_exists(self, isolated_project):
        tmp_path, _before = isolated_project
        context = get_project_context(tmp_path)
        ch2 = tmp_path / "data" / "chapters" / "chapter_002.md"
        ch2.write_text("# Chapter 002\n\nContent.")
        svc = ChapterLifecycleService(context)
        svc.initialize_chapter_versions(2)
        svc.initialize_chapter_canon(2, ch2.read_text())
        result = svc.resolve_next_chapter()
        assert result["status"] == "NEXT_CHAPTER_AVAILABLE"

    def test_resolve_detects_incomplete_chapter(self, isolated_project):
        tmp_path, _before = isolated_project
        context = get_project_context(tmp_path)
        ch2 = tmp_path / "data" / "chapters" / "chapter_002.md"
        ch2.write_text("# Chapter 002\n\nContent.")
        svc = ChapterLifecycleService(context)
        svc.initialize_chapter_versions(2)
        result = svc.resolve_next_chapter()
        assert result["status"] == "NEXT_CHAPTER_RECOVERY_REQUIRED"
        assert "missing_assets" in result

    def test_resolve_with_explicit_current_chapter(self, isolated_project):
        tmp_path, _before = isolated_project
        context = get_project_context(tmp_path)
        svc = ChapterLifecycleService(context)
        result = svc.resolve_next_chapter(current_chapter_id=1)
        assert result["current_chapter_id"] == 1
        assert result["next_chapter_id"] == 2


# ── Explicit create: next chapter ────────────────────────────


class TestCreateNextChapter:
    def test_create_creates_exactly_one_chapter(self, isolated_project):
        tmp_path, _before = isolated_project
        context = get_project_context(tmp_path)
        svc = ChapterLifecycleService(context)
        result = svc.create_next_chapter(operation_id="op-create-001")
        assert result["status"] == "CHAPTER_CREATED"
        assert result["chapter_id"] == 2
        assert result["chapter_created"] is True
        ch2 = tmp_path / "data" / "chapters" / "chapter_002.md"
        assert ch2.exists()
        assert result["version_initialized"] is True
        assert result["canon_initialized"] is True

    def test_create_initializes_versions(self, isolated_project):
        tmp_path, _before = isolated_project
        context = get_project_context(tmp_path)
        svc = ChapterLifecycleService(context)
        svc.create_next_chapter(operation_id="op-create-002")
        index_path = tmp_path / "data" / "versions" / "chapter_002_versions.json"
        assert index_path.exists()

    def test_create_initializes_canon(self, isolated_project):
        tmp_path, _before = isolated_project
        context = get_project_context(tmp_path)
        svc = ChapterLifecycleService(context)
        svc.create_next_chapter(operation_id="op-create-003")
        rs = RevisionService(context)
        canon = rs.read_active_canon(2)
        assert canon is not None
        assert canon["chapter_id"] == 2

    def test_create_is_idempotent(self, isolated_project):
        tmp_path, _before = isolated_project
        context = get_project_context(tmp_path)
        svc = ChapterLifecycleService(context)
        result1 = svc.create_next_chapter(operation_id="op-idem-001")
        result2 = svc.create_next_chapter(operation_id="op-idem-001")
        assert result1["chapter_id"] == result2["chapter_id"]
        assert result1["operation_id"] == result2["operation_id"]
        assert result1.get("outcome_fingerprint") == result2.get("outcome_fingerprint")

    def test_create_same_op_different_request_conflict(self, isolated_project):
        tmp_path, _before = isolated_project
        context = get_project_context(tmp_path)
        svc = ChapterLifecycleService(context)
        svc.create_next_chapter(
            operation_id="op-conflict-001", current_chapter_id=1
        )
        with pytest.raises(OperationConflictError):
            svc.create_next_chapter(
                operation_id="op-conflict-001",
                current_chapter_id=1,
                expected_active_branch_id="different",
            )

    def test_create_existing_chapter_returned(self, isolated_project):
        tmp_path, _before = isolated_project
        context = get_project_context(tmp_path)
        svc = ChapterLifecycleService(context)
        svc.create_next_chapter(operation_id="op-existing-001")
        result = svc.create_next_chapter(operation_id="op-existing-002")
        assert result["status"] == "NEXT_CHAPTER_ALREADY_EXISTS"
        assert result["chapter_created"] is False

    def test_create_fails_when_current_not_complete(self, isolated_project_no_commit):
        tmp_path, _before = isolated_project_no_commit
        context = get_project_context(tmp_path)
        svc = ChapterLifecycleService(context)
        with pytest.raises(CurrentChapterNotCompleteError):
            svc.create_next_chapter(operation_id="op-fail-001")

    def test_create_fails_on_commit_recovery_required(self, tmp_path):
        root = _make_project(tmp_path)
        data_dir = root / "data"
        _setup_branch_registry(data_dir)
        _setup_commit(data_dir, chapter_id=1, status="recovery_required")
        context = get_project_context(root)
        svc = ChapterLifecycleService(context)
        with pytest.raises(CommitRecoveryRequiredError):
            svc.create_next_chapter(operation_id="op-recovery-001")

    def test_create_fails_on_commit_invalid(self, tmp_path):
        root = _make_project(tmp_path)
        data_dir = root / "data"
        _setup_branch_registry(data_dir)
        _setup_commit(data_dir, chapter_id=1, status="unknown_status")
        context = get_project_context(root)
        svc = ChapterLifecycleService(context)
        with pytest.raises(CommitResultInvalidError):
            svc.create_next_chapter(operation_id="op-invalid-001")


class TestCreateBranchStaleness:
    def test_create_fails_on_branch_stale(self, isolated_project):
        tmp_path, _before = isolated_project
        context = get_project_context(tmp_path)
        svc = ChapterLifecycleService(context)
        with pytest.raises(BranchStaleError):
            svc.create_next_chapter(
                operation_id="op-stale-001",
                expected_active_branch_id="nonexistent-branch",
            )

    def test_create_fails_on_branch_revision_changed(self, isolated_project):
        tmp_path, _before = isolated_project
        context = get_project_context(tmp_path)
        svc = ChapterLifecycleService(context)
        with pytest.raises(BranchStaleError):
            svc.create_next_chapter(
                operation_id="op-rev-001", expected_branch_revision="999"
            )


# ── Recovery: fault injection & replay ───────────────────────


class TestRecovery:
    @pytest.mark.parametrize(
        "fault_point",
        [
            "after_claim",
            "after_successor_resolution",
            "after_staging_creation",
            "after_version_init",
            "after_canon_init",
            "after_publish",
            "after_result_publication",
            "before_completed_phase",
        ],
    )
    def test_eight_point_recovery_keeps_partial_chapter_unavailable(
        self, isolated_project, fault_point
    ):
        root, _before = isolated_project
        context = get_project_context(root)
        seen: set[str] = set()

        def fault(point: str) -> None:
            if point == fault_point and point not in seen:
                seen.add(point)
                raise ChapterLifecycleRecoveryRequiredError(f"fault: {point}")

        operation_id = f"op-eight-{fault_point}"
        with pytest.raises(ChapterLifecycleRecoveryRequiredError):
            ChapterLifecycleService(context, fault_injector=fault).create_next_chapter(
                operation_id=operation_id
            )

        authority = root / "data" / "chapter_lifecycle" / "operations" / f"{operation_id}.json"
        authority_before = authority.read_bytes()
        interim = ChapterLifecycleService(context).resolve_next_chapter()
        if fault_point in {
            "after_claim", "after_successor_resolution", "after_staging_creation",
            "after_version_init", "after_canon_init",
        }:
            assert interim["status"] == "NEXT_CHAPTER_MISSING"

        replay = ChapterLifecycleService(context).create_next_chapter(operation_id=operation_id)
        assert authority.read_bytes() == authority_before
        assert replay["status"] == "CHAPTER_CREATED"
        assert len(list((root / "data" / "chapters").glob("chapter_002.md"))) == 1
        assert ChapterLifecycleService(context).resolve_next_chapter()["status"] == "NEXT_CHAPTER_AVAILABLE"

    def test_replay_after_claim(self, isolated_project):
        tmp_path, _before = isolated_project
        context = get_project_context(tmp_path)
        checkpoint: dict[str, str] = {}

        def fault(point: str) -> None:
            if point == "after_claim" and "after_claim" not in checkpoint:
                checkpoint["after_claim"] = point
                raise ChapterLifecycleRecoveryRequiredError("fault: after_claim")

        svc = ChapterLifecycleService(context, fault_injector=fault)
        with pytest.raises(ChapterLifecycleRecoveryRequiredError):
            svc.create_next_chapter(operation_id="op-replay-001")

        svc2 = ChapterLifecycleService(context)
        result = svc2.create_next_chapter(operation_id="op-replay-001")
        assert result["status"] == "CHAPTER_CREATED"
        assert result["chapter_id"] == 2

    def test_replay_after_fence(self, isolated_project):
        tmp_path, _before = isolated_project
        context = get_project_context(tmp_path)
        checkpoint: dict[str, str] = {}

        def fault(point: str) -> None:
            if point == "after_fence" and "after_fence" not in checkpoint:
                checkpoint["after_fence"] = point
                raise ChapterLifecycleRecoveryRequiredError("fault: after_fence")

        svc = ChapterLifecycleService(context, fault_injector=fault)
        with pytest.raises(ChapterLifecycleRecoveryRequiredError):
            svc.create_next_chapter(operation_id="op-replay-002")

        svc2 = ChapterLifecycleService(context)
        result = svc2.create_next_chapter(operation_id="op-replay-002")
        assert result["status"] == "CHAPTER_CREATED"

    def test_replay_after_version_init(self, isolated_project):
        tmp_path, _before = isolated_project
        context = get_project_context(tmp_path)
        checkpoint: dict[str, str] = {}

        def fault(point: str) -> None:
            if point == "after_version_init" and "after_version_init" not in checkpoint:
                checkpoint["after_version_init"] = point
                raise ChapterLifecycleRecoveryRequiredError("fault: after_version_init")

        svc = ChapterLifecycleService(context, fault_injector=fault)
        with pytest.raises(ChapterLifecycleRecoveryRequiredError):
            svc.create_next_chapter(operation_id="op-replay-003")

        svc2 = ChapterLifecycleService(context)
        result = svc2.create_next_chapter(operation_id="op-replay-003")
        assert result["status"] == "CHAPTER_CREATED"

    def test_replay_durable_result_consistent(self, isolated_project):
        tmp_path, _before = isolated_project
        context = get_project_context(tmp_path)
        svc1 = ChapterLifecycleService(context)
        result1 = svc1.create_next_chapter(operation_id="op-consistent-001")
        svc2 = ChapterLifecycleService(context)
        result2 = svc2.create_next_chapter(operation_id="op-consistent-001")
        assert result1["outcome_fingerprint"] == result2["outcome_fingerprint"]

    def test_missing_result_can_be_replayed(self, isolated_project):
        tmp_path, _before = isolated_project
        context = get_project_context(tmp_path)
        svc = ChapterLifecycleService(context)
        svc.create_next_chapter(operation_id="op-partial-001")
        result_path = (
            tmp_path
            / "data"
            / "chapter_lifecycle"
            / "operations"
            / "op-partial-001.result.json"
        )
        if result_path.exists():
            result_path.unlink()
        svc2 = ChapterLifecycleService(context)
        result = svc2.create_next_chapter(operation_id="op-partial-001")
        assert result["status"] == "CHAPTER_CREATED"


# ── Concurrency: first-writer-wins ───────────────────────────


def _run_two_thread_chapter_create(context, create_operation, *, fail_on_worker_error=True):
    barrier = threading.Barrier(2)
    results: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    alive_threads: list[dict[str, object]] = []
    results_lock = threading.Lock()
    operation_ids = ("op-thread-a", "op-thread-b")

    def create(operation_id: str) -> None:
        thread_name = threading.current_thread().name
        try:
            barrier.wait(timeout=5)
            result = create_operation(operation_id)
            with results_lock:
                results.append(result)
        except BaseException as exc:
            formatted = "".join(
                traceback.TracebackException.from_exception(
                    exc,
                    capture_locals=False,
                ).format()
            )
            record = {
                "operation_id": operation_id,
                "thread_name": thread_name,
                "exception_type": type(exc).__name__,
                "exception_repr": repr(exc),
                "errno": getattr(exc, "errno", None),
                "winerror": getattr(exc, "winerror", None),
                "filename": getattr(exc, "filename", None),
                "filename2": getattr(exc, "filename2", None),
                "traceback": formatted,
            }
            with results_lock:
                failures.append(record)

    threads = [
        threading.Thread(
            target=create,
            args=(operation_id,),
            name=f"chapter-create-{operation_id}",
        )
        for operation_id in operation_ids
    ]
    for thread in threads:
        thread.start()

    for thread, operation_id in zip(threads, operation_ids):
        thread.join(timeout=10)
        if thread.is_alive():
            frame = sys._current_frames().get(thread.ident)
            stack = "".join(traceback.format_stack(frame)) if frame else None
            alive_threads.append(
                {
                    "operation_id": operation_id,
                    "thread_name": thread.name,
                    "thread_ident": thread.ident,
                    "stack": stack,
                }
            )

    if alive_threads:
        pytest.fail(f"Chapter worker thread(s) did not finish: {alive_threads!r}")
    if failures and fail_on_worker_error:
        evidence = "\n\n".join(repr(record) for record in failures)
        pytest.fail(f"Chapter worker failure evidence:\n{evidence}")
    return results, failures, alive_threads


class TestConcurrency:
    def test_two_threads_create_first_writer_wins(self, isolated_project):
        root, _before = isolated_project
        context = get_project_context(root)
        results, failures, alive_threads = _run_two_thread_chapter_create(
            context,
            lambda operation_id: ChapterLifecycleService(context).create_next_chapter(
                operation_id=operation_id
            ),
        )
        assert not failures
        assert not alive_threads
        assert len(results) == 2
        assert sum(item["status"] == "CHAPTER_CREATED" for item in results) == 1
        assert sum(item["status"] == "NEXT_CHAPTER_ALREADY_EXISTS" for item in results) == 1
        assert len(list((root / "data" / "chapters").glob("chapter_002.md"))) == 1

    def test_two_creates_first_writer_wins(self, isolated_project):
        tmp_path, _before = isolated_project
        context = get_project_context(tmp_path)
        svc1 = ChapterLifecycleService(context)
        svc2 = ChapterLifecycleService(context)
        r1 = svc1.create_next_chapter(operation_id="op-concurrent-001")
        r2 = svc2.create_next_chapter(operation_id="op-concurrent-002")
        assert r1["chapter_id"] == 2
        assert r2["chapter_id"] == 2
        ch2 = tmp_path / "data" / "chapters" / "chapter_002.md"
        assert ch2.exists()
        versions_idx = tmp_path / "data" / "versions" / "chapter_002_versions.json"
        assert versions_idx.exists()
        canon_idx = tmp_path / "data" / "canon_versions" / "chapter_002" / "index.json"
        assert canon_idx.exists()


# ── Previous chapter immutability ────────────────────────────


def test_worker_failure_preserves_traceback_and_oserror_metadata():
    synthetic = PermissionError(
        13,
        "synthetic permission denied",
        "synthetic-source-path",
        "synthetic-target-path",
    )

    def fail(operation_id: str):
        raise synthetic

    results, failures, alive_threads = _run_two_thread_chapter_create(
        None,
        fail,
        fail_on_worker_error=False,
    )

    assert results == []
    assert alive_threads == []
    assert len(failures) == 2
    for record in failures:
        assert record["exception_type"] == "PermissionError"
        assert record["errno"] == 13
        assert record["filename"] == "synthetic-source-path"
        if record["filename2"] is not None:
            assert record["filename2"] == "synthetic-target-path"
        assert record["operation_id"] in {"op-thread-a", "op-thread-b"}
        assert record["thread_name"].startswith("chapter-create-")
        assert "PermissionError" in record["traceback"]
        assert "synthetic-source-path" in record["traceback"]
        assert "create" in record["traceback"]


class TestPreviousChapterImmutability:
    def test_previous_chapter_content_unchanged(self, isolated_project):
        tmp_path, before = isolated_project
        ch1_content = (tmp_path / "data" / "chapters" / "chapter_001.md").read_text()
        context = get_project_context(tmp_path)
        svc = ChapterLifecycleService(context)
        svc.create_next_chapter(operation_id="op-immutable-001")
        ch1_after = (tmp_path / "data" / "chapters" / "chapter_001.md").read_text()
        assert ch1_content == ch1_after

    def test_previous_chapter_versions_unchanged(self, isolated_project):
        tmp_path, _before = isolated_project
        context = get_project_context(tmp_path)
        svc = ChapterLifecycleService(context)
        versions_before = list_versions(1, context.data_dir)
        svc.create_next_chapter(operation_id="op-immutable-002")
        versions_after = list_versions(1, context.data_dir)
        assert versions_before == versions_after

    def test_previous_chapter_canon_unchanged(self, isolated_project):
        tmp_path, _before = isolated_project
        context = get_project_context(tmp_path)
        svc = ChapterLifecycleService(context)
        rs = RevisionService(context)
        canon_before = rs.read_active_canon(1)
        svc.create_next_chapter(operation_id="op-immutable-003")
        canon_after = rs.read_active_canon(1)
        assert canon_before == canon_after


# ── Traditional/Simulator shared authority ───────────────────


class TestTraditionalSimulatorSharing:
    def test_same_service_resolves_after_create(self, isolated_project):
        tmp_path, _before = isolated_project
        context = get_project_context(tmp_path)
        svc_traditional = ChapterLifecycleService(context)
        svc_simulator = ChapterLifecycleService(context)
        svc_traditional.create_next_chapter(operation_id="op-share-001")
        result = svc_simulator.resolve_next_chapter()
        assert result["status"] == "NEXT_CHAPTER_AVAILABLE"
        assert result["branch_id"] is not None

    def test_shared_service_creates_once(self, isolated_project):
        tmp_path, _before = isolated_project
        context = get_project_context(tmp_path)
        svc = ChapterLifecycleService(context)
        r1 = svc.create_next_chapter(operation_id="op-share-002")
        r2 = svc.create_next_chapter(operation_id="op-share-003")
        assert r1["chapter_id"] == r2["chapter_id"] == 2


# ── Completion warning semantics ────────────────────────────


class TestCompletionWarningSemantics:
    def test_committed_with_warnings_allows_create(self, tmp_path):
        root = _make_project(tmp_path)
        data_dir = root / "data"
        _setup_branch_registry(data_dir)
        _setup_commit(data_dir, chapter_id=1, status="committed_with_warnings")
        context = get_project_context(root)
        svc = ChapterLifecycleService(context)
        result = svc.create_next_chapter(operation_id="op-warning-001")
        assert result["status"] == "CHAPTER_CREATED"

    def test_recovery_required_blocks_create(self, tmp_path):
        root = _make_project(tmp_path)
        data_dir = root / "data"
        _setup_branch_registry(data_dir)
        _setup_commit(data_dir, chapter_id=1, status="recovery_required")
        context = get_project_context(root)
        svc = ChapterLifecycleService(context)
        with pytest.raises(CommitRecoveryRequiredError):
            svc.create_next_chapter(operation_id="op-warning-002")


# ── Error codes / fail-closed ───────────────────────────────


class TestFailClosedErrors:
    def test_no_traceback_in_error(self, isolated_project):
        tmp_path, _before = isolated_project
        context = get_project_context(tmp_path)
        svc = ChapterLifecycleService(context)
        try:
            svc.create_next_chapter(
                operation_id="op-err-001", expected_active_branch_id="nope"
            )
        except BranchStaleError as exc:
            msg = str(exc)
            assert "Traceback" not in msg
            assert "FileNotFoundError" not in msg
        except Exception as exc:
            pytest.fail(f"Unexpected error type: {type(exc).__name__}: {exc}")

    def test_no_absolute_path_in_error(self, isolated_project):
        tmp_path, _before = isolated_project
        context = get_project_context(tmp_path)
        svc = ChapterLifecycleService(context)
        try:
            svc.create_next_chapter(operation_id="op-err-002")
        except Exception as exc:
            msg = str(exc)
            assert str(tmp_path) not in msg
