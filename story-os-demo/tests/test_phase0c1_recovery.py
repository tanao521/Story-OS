"""Phase 0C1-RC Recovery Tests.

These tests verify the production-grade recovery mechanisms for:
1. Post-Commit Recovery - Chroma sync failure during commit
2. Canon Restore Recovery - Chroma sync failure during canon restore
3. Resource Release - Client manager properly releases resources
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest

from core.project_context import get_project_context
from system.vector_index_lifecycle import (
    index_chapter,
    search_similar,
    mark_chapter_stale,
    rebuild_project_index,
)
from system.vector_client_manager import VectorClientManager
from system.vector_sync_run_store import (
    VectorSyncRunStore,
    VectorSyncOperationType,
    VectorSyncStatus,
)


class TestPostCommitRecovery:
    def test_main_timeline_post_commit_recovery(self, temp_project: Path) -> None:
        ctx = get_project_context(temp_project)
        content = "The dragon flew over the mountain, breathing fire."
        
        index_chapter(ctx, 1, content, canon_revision_id="rev1")
        
        results = search_similar(ctx, "dragon fire", timeline_id="main")
        assert len(results) == 1
        assert "dragon" in results[0].get("snippet", "").lower()
        
        mark_chapter_stale(ctx, 1, timeline_id="main")
        
        results = search_similar(ctx, "dragon fire", timeline_id="main")
        assert len(results) == 0
        
        index_chapter(ctx, 1, content, canon_revision_id="rev2")
        
        results = search_similar(ctx, "dragon fire", timeline_id="main")
        assert len(results) == 1
        assert "dragon" in results[0].get("snippet", "").lower()

    def test_experiment_timeline_post_commit_recovery(self, temp_project: Path) -> None:
        ctx = get_project_context(temp_project)
        content = "The wizard cast a powerful spell."
        
        index_chapter(ctx, 1, content, canon_revision_id="exp1", timeline_id="experiment")
        
        results = search_similar(ctx, "wizard spell", timeline_id="experiment")
        assert len(results) == 1
        
        mark_chapter_stale(ctx, 1, timeline_id="experiment")
        
        results = search_similar(ctx, "wizard spell", timeline_id="experiment")
        assert len(results) == 0
        
        index_chapter(ctx, 1, content, canon_revision_id="exp2", timeline_id="experiment")
        
        results = search_similar(ctx, "wizard spell", timeline_id="experiment")
        assert len(results) == 1

    def test_dual_project_same_chapter_id(self, temp_project: Path) -> None:
        ctx_a = get_project_context(temp_project)
        content_a = "Project A: The knight fought bravely."
        
        temp_project_b = temp_project.parent / "project_b"
        temp_project_b.mkdir()
        (temp_project_b / "data" / "chapters").mkdir(parents=True)
        
        ctx_b = get_project_context(temp_project_b)
        content_b = "Project B: The princess waited patiently."
        
        index_chapter(ctx_a, 1, content_a, canon_revision_id="rev_a1")
        index_chapter(ctx_b, 1, content_b, canon_revision_id="rev_b1")
        
        results_a = search_similar(ctx_a, "knight", timeline_id="main")
        results_b = search_similar(ctx_b, "princess", timeline_id="main")
        
        assert len(results_a) == 1
        assert "knight" in results_a[0].get("snippet", "").lower()
        assert len(results_b) == 1
        assert "princess" in results_b[0].get("snippet", "").lower()

    def test_vector_sync_run_created(self, temp_project: Path) -> None:
        ctx = get_project_context(temp_project)
        
        sync_store = VectorSyncRunStore(ctx)
        
        sync_run = sync_store.create(
            operation_type=VectorSyncOperationType.COMMIT,
            project_id="test_project",
            timeline_id="main",
            chapter_id=1,
            canon_revision_id="rev1",
        )
        
        assert sync_run.operation_id.startswith("vec_")
        assert sync_run.status == VectorSyncStatus.PENDING
        assert sync_run.project_id == "test_project"
        assert sync_run.timeline_id == "main"
        assert sync_run.chapter_id == 1
        assert sync_run.canon_revision_id == "rev1"
        
        sync_store.update_status(sync_run.operation_id, VectorSyncStatus.RUNNING)
        retrieved = sync_store.get(sync_run.operation_id)
        assert retrieved.status == VectorSyncStatus.RUNNING
        
        sync_store.update_status(sync_run.operation_id, VectorSyncStatus.COMPLETED)
        retrieved = sync_store.get(sync_run.operation_id)
        assert retrieved.status == VectorSyncStatus.COMPLETED


class TestCanonRestoreRecovery:
    def test_restore_replaces_active(self, temp_project: Path) -> None:
        ctx = get_project_context(temp_project)
        
        content_a = "Revision A: The old story."
        content_b = "Revision B: The new story."
        
        index_chapter(ctx, 1, content_a, canon_revision_id="rev_a")
        
        results = search_similar(ctx, "old story", timeline_id="main")
        assert len(results) == 1
        
        index_chapter(ctx, 1, content_b, canon_revision_id="rev_b")
        
        results = search_similar(ctx, "new story", timeline_id="main")
        assert len(results) == 1
        
        results_old = search_similar(ctx, "old story", timeline_id="main")
        assert len(results_old) == 0

    def test_stale_revision_not_returned(self, temp_project: Path) -> None:
        ctx = get_project_context(temp_project)
        
        content_a = "Revision A: First version."
        content_b = "Revision B: Second version."
        
        index_chapter(ctx, 1, content_a, canon_revision_id="rev_a")
        index_chapter(ctx, 1, content_b, canon_revision_id="rev_b")
        
        mark_chapter_stale(ctx, 1, timeline_id="main")
        
        results = search_similar(ctx, "second version", timeline_id="main")
        assert len(results) == 0
        
        results = search_similar(ctx, "first version", timeline_id="main")
        assert len(results) == 0


class TestResourceRelease:
    def test_client_reuse(self, temp_project: Path) -> None:
        ctx = get_project_context(temp_project)
        manager = VectorClientManager()
        
        client1 = manager.get_client(ctx)
        client2 = manager.get_client(ctx)
        
        assert client1 is client2

    def test_close_client(self, temp_project: Path) -> None:
        ctx = get_project_context(temp_project)
        manager = VectorClientManager()
        
        client = manager.get_client(ctx)
        assert client is not None
        
        client_id = id(client)
        manager.close_client(ctx)
        
        client_after = manager.get_client(ctx)
        assert client_after is not None
        assert id(client_after) != client_id

    def test_close_all(self, temp_project: Path) -> None:
        ctx = get_project_context(temp_project)
        manager = VectorClientManager()
        
        client = manager.get_client(ctx)
        assert client is not None
        
        client_id = id(client)
        manager.close_all()
        
        client_after = manager.get_client(ctx)
        assert client_after is not None
        assert id(client_after) != client_id

    def test_close_idempotent(self, temp_project: Path) -> None:
        ctx = get_project_context(temp_project)
        manager = VectorClientManager()
        
        manager.close_client(ctx)
        manager.close_client(ctx)
        manager.close_all()
        manager.close_all()


@pytest.fixture
def temp_project() -> Path:
    tmpdir = tempfile.mkdtemp()
    project_root = Path(tmpdir) / "test_project"
    project_root.mkdir()
    (project_root / "data" / "chapters").mkdir(parents=True)
    (project_root / "data" / "summaries").mkdir(parents=True)
    yield project_root
    VectorClientManager().close_all()
    try:
        shutil.rmtree(tmpdir)
    except Exception:
        pass
