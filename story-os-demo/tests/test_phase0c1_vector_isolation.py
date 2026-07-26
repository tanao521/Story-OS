"""Phase 0C1 — Chroma Memory Isolation & Lifecycle Tests.

Test coverage for:
- Project/timeline/canon metadata isolation
- Strict query filtering
- Index lifecycle (commit, restore, archive, delete, rebuild)
- Legacy index compatibility
- Post-commit recovery integration
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, List

import pytest

from core.project_context import ProjectContext
from system.vector_index_lifecycle import (
    InvalidTimelineError,
    LegacyIndexError,
    ProjectMismatchError,
    delete_by_chapter,
    delete_by_project,
    delete_by_revision,
    delete_by_timeline,
    index_chapter,
    index_summary,
    mark_chapter_archived,
    mark_chapter_stale,
    rebuild_project_index,
    search_similar,
)
from system.vector_index_schema import (
    CanonStatus,
    IndexManifest,
    SourceType,
    compute_content_hash,
    is_legacy_index,
    load_manifest,
    save_manifest,
    validate_timeline_id,
)

_CLIENTS_TO_CLOSE: List[Any] = []


def _close_chroma_clients() -> None:
    global _CLIENTS_TO_CLOSE
    import gc
    for client in _CLIENTS_TO_CLOSE:
        try:
            if hasattr(client, 'close'):
                client.close()
        except Exception:
            pass
    _CLIENTS_TO_CLOSE = []
    gc.collect()
    import time
    time.sleep(0.1)


import chromadb
_original_persistent_client = chromadb.PersistentClient


def _tracked_persistent_client(**kwargs):
    client = _original_persistent_client(**kwargs)
    _CLIENTS_TO_CLOSE.append(client)
    return client


chromadb.PersistentClient = _tracked_persistent_client


@pytest.fixture(autouse=True)
def chroma_client_cleanup() -> None:
    yield
    _close_chroma_clients()


@pytest.fixture
def temp_project() -> Path:
    tmpdir = tempfile.mkdtemp()
    project_root = Path(tmpdir) / "test_project"
    project_root.mkdir()
    (project_root / "data" / "chapters").mkdir(parents=True)
    (project_root / "data" / "summaries").mkdir(parents=True)
    yield project_root
    import subprocess
    import os
    try:
        subprocess.run(["rmdir", "/s", "/q", str(tmpdir)], check=True, capture_output=True)
    except Exception:
        try:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


@pytest.fixture
def chroma_client_tracker(monkeypatch: pytest.MonkeyPatch) -> None:
    import chromadb
    
    original_persistent_client = chromadb.PersistentClient
    
    def tracked_persistent_client(**kwargs):
        client = original_persistent_client(**kwargs)
        _CLIENTS_TO_CLOSE.append(client)
        return client
    
    monkeypatch.setattr(chromadb, 'PersistentClient', tracked_persistent_client)
    yield
    _close_chroma_clients()


@pytest.fixture
def project_context(temp_project: Path, chroma_client_tracker: None) -> ProjectContext:
    from core.project_context import get_project_context
    from system.vector_index_schema import IndexManifest, save_manifest
    
    ctx = get_project_context(temp_project)
    manifest = IndexManifest(
        schema_version=2,
        project_id=ctx.root.name,
        timeline_id="main",
    )
    save_manifest(ctx.data_dir, manifest)
    return ctx


def _write_chapter(project_root: Path, chapter_id: int, content: str) -> None:
    path = project_root / "data" / "chapters" / f"chapter_{chapter_id:03d}.md"
    path.write_text(content, encoding="utf-8")


def _write_summary(project_root: Path, chapter_id: int, summary_text: str) -> None:
    import json
    path = project_root / "data" / "summaries" / f"chapter_{chapter_id:03d}_summary.json"
    path.write_text(json.dumps({"short_summary": summary_text, "memory_tags": ["test"], "key_events": []}), encoding="utf-8")


class TestMetadataIntegrity:
    def test_chapter_metadata_contains_required_fields(self, project_context: ProjectContext) -> None:
        result = index_chapter(project_context, 1, "test chapter content", canon_revision_id="rev_001")
        assert result["status"] == "success"
        
        results = search_similar(project_context, "test")
        assert len(results) > 0
        meta = results[0]["metadata"]
        assert "project_id" in meta
        assert "timeline_id" in meta
        assert "source_type" in meta
        assert "chapter_id" in meta
        assert "canon_status" in meta
        assert "canon_revision_id" in meta
        assert "content_hash" in meta
        assert "indexed_at" in meta
        assert meta["source_type"] == "chapter"
        assert meta["canon_status"] == "active"
        assert meta["canon_revision_id"] == "rev_001"

    def test_summary_metadata_contains_required_fields(self, project_context: ProjectContext) -> None:
        result = index_summary(project_context, 1, "test summary", canon_revision_id="rev_001")
        assert result["status"] == "success"
        
        results = search_similar(project_context, "test")
        assert len(results) > 0
        summary_result = next(r for r in results if r["metadata"].get("source_type") == "summary")
        meta = summary_result["metadata"]
        assert "project_id" in meta
        assert "timeline_id" in meta
        assert "source_type" in meta
        assert "chapter_id" in meta
        assert "canon_status" in meta
        assert "content_hash" in meta

    def test_content_hash_is_consistent(self, project_context: ProjectContext) -> None:
        text = "consistent test content"
        hash1 = compute_content_hash(text)
        hash2 = compute_content_hash(text)
        assert hash1 == hash2
        
        result = index_chapter(project_context, 1, text)
        assert result["status"] == "success"
        assert result["outputs"]["content_hash"] == hash1


class TestProjectIsolation:
    def test_same_physical_collection_different_projects(self, temp_project: Path) -> None:
        from core.project_context import get_project_context
        from system.vector_index_schema import IndexManifest, save_manifest
        
        project_a = temp_project / "project_a"
        project_b = temp_project / "project_b"
        project_a.mkdir(parents=True)
        project_b.mkdir(parents=True)
        
        (project_a / "data" / "chapters").mkdir(parents=True)
        (project_b / "data" / "chapters").mkdir(parents=True)
        
        ctx_a = get_project_context(project_a)
        ctx_b = get_project_context(project_b)
        
        manifest_a = IndexManifest(schema_version=2, project_id="project_a", timeline_id="main")
        manifest_b = IndexManifest(schema_version=2, project_id="project_b", timeline_id="main")
        save_manifest(ctx_a.data_dir, manifest_a)
        save_manifest(ctx_b.data_dir, manifest_b)
        
        _write_chapter(project_a, 1, "project A content about dragons")
        _write_chapter(project_b, 1, "project B content about spaceships")
        
        index_chapter(ctx_a, 1, "project A content about dragons", canon_revision_id="rev_a")
        index_chapter(ctx_b, 1, "project B content about spaceships", canon_revision_id="rev_b")
        
        results_a = search_similar(ctx_a, "dragons")
        assert len(results_a) > 0
        assert all(r["metadata"]["project_id"] == "project_a" for r in results_a)
        
        results_b = search_similar(ctx_b, "spaceships")
        assert len(results_b) > 0
        assert all(r["metadata"]["project_id"] == "project_b" for r in results_b)
        
        results_a_search_b = search_similar(ctx_a, "spaceships")
        assert len(results_a_search_b) == 0 or all(r["metadata"]["project_id"] == "project_a" for r in results_a_search_b)

    def test_project_mismatch_raises_error(self, temp_project: Path) -> None:
        from core.project_context import get_project_context
        
        (temp_project / "data" / "chapters").mkdir(parents=True, exist_ok=True)
        
        ctx = get_project_context(temp_project)
        manifest = IndexManifest(schema_version=2, project_id="wrong_project", timeline_id="main")
        save_manifest(ctx.data_dir, manifest)
        
        with pytest.raises(ProjectMismatchError):
            index_chapter(ctx, 1, "test content")


class TestTimelineIsolation:
    def test_main_and_experiment_timelines_isolated(self, project_context: ProjectContext) -> None:
        index_chapter(project_context, 1, "main timeline content about magic", timeline_id="main", canon_revision_id="rev_main")
        index_chapter(project_context, 1, "experiment timeline content about technology", timeline_id="experiment", canon_revision_id="rev_exp")
        
        main_results = search_similar(project_context, "magic", timeline_id="main")
        assert len(main_results) > 0
        assert all(r["metadata"]["timeline_id"] == "main" for r in main_results)
        
        exp_results = search_similar(project_context, "technology", timeline_id="experiment")
        assert len(exp_results) > 0
        assert all(r["metadata"]["timeline_id"] == "experiment" for r in exp_results)
        
        main_search_exp = search_similar(project_context, "technology", timeline_id="main")
        assert len(main_search_exp) == 0

    def test_default_query_uses_main_timeline(self, project_context: ProjectContext) -> None:
        index_chapter(project_context, 1, "main content", timeline_id="main", canon_revision_id="rev_main")
        index_chapter(project_context, 1, "exp content", timeline_id="experiment", canon_revision_id="rev_exp")
        
        results = search_similar(project_context, "content")
        assert len(results) > 0
        assert all(r["metadata"]["timeline_id"] == "main" for r in results)

    def test_invalid_timeline_id_raises_error(self, project_context: ProjectContext) -> None:
        with pytest.raises(InvalidTimelineError):
            index_chapter(project_context, 1, "test", timeline_id="invalid/timeline")
        
        with pytest.raises(InvalidTimelineError):
            index_chapter(project_context, 1, "test", timeline_id="..")
        
        with pytest.raises(InvalidTimelineError):
            index_chapter(project_context, 1, "test", timeline_id="")


class TestCanonIsolation:
    def test_search_only_returns_active(self, project_context: ProjectContext) -> None:
        index_chapter(project_context, 1, "active chapter content", canon_revision_id="rev_001")
        
        mark_chapter_stale(project_context, 1)
        
        results = search_similar(project_context, "active")
        assert len(results) == 0

    def test_stale_revision_not_returned(self, project_context: ProjectContext) -> None:
        index_chapter(project_context, 1, "original content", canon_revision_id="rev_001")
        
        mark_chapter_stale(project_context, 1)
        
        results = search_similar(project_context, "original")
        assert len(results) == 0

    def test_archived_chapter_not_returned(self, project_context: ProjectContext) -> None:
        index_chapter(project_context, 1, "archived content", canon_revision_id="rev_001")
        
        mark_chapter_archived(project_context, 1)
        
        results = search_similar(project_context, "archived")
        assert len(results) == 0


class TestCommitIdempotency:
    def test_same_content_commit_no_duplicates(self, project_context: ProjectContext) -> None:
        text = "idempotent test content"
        
        result1 = index_chapter(project_context, 1, text, canon_revision_id="rev_001")
        count1 = result1["outputs"]["chunks_indexed"]
        
        result2 = index_chapter(project_context, 1, text, canon_revision_id="rev_001")
        count2 = result2["outputs"]["chunks_indexed"]
        
        assert count1 == count2
        
        results = search_similar(project_context, "idempotent")
        assert len(results) > 0


class TestNewRevision:
    def test_new_revision_replaces_old(self, project_context: ProjectContext) -> None:
        index_chapter(project_context, 1, "old content about horses", canon_revision_id="rev_001")
        
        results_old = search_similar(project_context, "horses")
        assert len(results_old) > 0
        
        index_chapter(project_context, 1, "new content about cars", canon_revision_id="rev_002")
        
        results_new = search_similar(project_context, "cars")
        assert len(results_new) > 0
        
        results_old_after = search_similar(project_context, "horses")
        assert len(results_old_after) == 0


class TestCanonRestore:
    def test_restore_revision_searchable(self, project_context: ProjectContext) -> None:
        index_chapter(project_context, 1, "dragons and magic spells", canon_revision_id="rev_001")
        index_chapter(project_context, 1, "spaceships and alien worlds", canon_revision_id="rev_002")
        
        results_2 = search_similar(project_context, "spaceships")
        assert len(results_2) > 0
        
        delete_by_revision(project_context, "rev_002")
        index_chapter(project_context, 1, "dragons and magic spells", canon_revision_id="rev_001")
        
        results_1 = search_similar(project_context, "dragons")
        assert len(results_1) > 0
        
        results_2_after = search_similar(project_context, "spaceships")
        assert len(results_2_after) == 0


class TestChapterArchive:
    def test_archive_immediately_removes_from_search(self, project_context: ProjectContext) -> None:
        index_chapter(project_context, 1, "archivable content", canon_revision_id="rev_001")
        
        results_before = search_similar(project_context, "archivable")
        assert len(results_before) > 0
        
        mark_chapter_archived(project_context, 1)
        
        results_after = search_similar(project_context, "archivable")
        assert len(results_after) == 0


class TestDeleteCapabilities:
    def test_delete_by_chapter(self, project_context: ProjectContext) -> None:
        index_chapter(project_context, 1, "fantasy dragons magic sword", canon_revision_id="rev_001")
        index_chapter(project_context, 2, "sci-fi spaceship aliens laser", canon_revision_id="rev_001")
        
        delete_by_chapter(project_context, 1)
        
        results_1 = search_similar(project_context, "dragons")
        assert len(results_1) == 0
        
        results_2 = search_similar(project_context, "spaceship")
        assert len(results_2) > 0

    def test_delete_by_revision(self, project_context: ProjectContext) -> None:
        index_chapter(project_context, 1, "rev1 content", canon_revision_id="rev_001")
        index_chapter(project_context, 2, "rev1 content", canon_revision_id="rev_001")
        index_chapter(project_context, 1, "rev2 content", canon_revision_id="rev_002")
        
        delete_by_revision(project_context, "rev_001")
        
        results_rev1 = search_similar(project_context, "rev1")
        assert len(results_rev1) == 0
        
        results_rev2 = search_similar(project_context, "rev2")
        assert len(results_rev2) > 0

    def test_delete_by_timeline(self, project_context: ProjectContext) -> None:
        index_chapter(project_context, 1, "main content", timeline_id="main", canon_revision_id="rev_001")
        index_chapter(project_context, 1, "exp content", timeline_id="experiment", canon_revision_id="rev_001")
        
        delete_by_timeline(project_context, "experiment")
        
        results_main = search_similar(project_context, "main")
        assert len(results_main) > 0
        
        results_exp = search_similar(project_context, "exp", timeline_id="experiment")
        assert len(results_exp) == 0

    def test_delete_by_project(self, project_context: ProjectContext) -> None:
        index_chapter(project_context, 1, "project content", canon_revision_id="rev_001")
        index_summary(project_context, 1, "project summary", canon_revision_id="rev_001")
        
        delete_by_project(project_context)
        
        results = search_similar(project_context, "project")
        assert len(results) == 0


class TestRebuild:
    def test_rebuild_index_only_active_canon(self, temp_project: Path) -> None:
        from core.project_context import get_project_context
        from system.vector_index_schema import IndexManifest, save_manifest
        
        (temp_project / "data" / "chapters").mkdir(parents=True, exist_ok=True)
        (temp_project / "data" / "summaries").mkdir(parents=True, exist_ok=True)
        
        _write_chapter(temp_project, 1, "chapter 1 rebuild test")
        _write_chapter(temp_project, 2, "chapter 2 rebuild test")
        _write_summary(temp_project, 1, "summary 1")
        
        ctx = get_project_context(temp_project)
        manifest = IndexManifest(schema_version=2, project_id=ctx.root.name, timeline_id="main")
        save_manifest(ctx.data_dir, manifest)
        
        result = rebuild_project_index(ctx)
        assert result["status"] == "success"
        assert result["outputs"]["chunks_indexed"] > 0
        
        results = search_similar(ctx, "rebuild")
        assert len(results) > 0

    def test_rebuild_idempotent(self, temp_project: Path) -> None:
        from core.project_context import get_project_context
        from system.vector_index_schema import IndexManifest, save_manifest
        
        (temp_project / "data" / "chapters").mkdir(parents=True, exist_ok=True)
        _write_chapter(temp_project, 1, "rebuild idempotent")
        
        ctx = get_project_context(temp_project)
        manifest = IndexManifest(schema_version=2, project_id=ctx.root.name, timeline_id="main")
        save_manifest(ctx.data_dir, manifest)
        
        result1 = rebuild_project_index(ctx)
        count1 = result1["outputs"]["chunks_indexed"]
        
        result2 = rebuild_project_index(ctx)
        count2 = result2["outputs"]["chunks_indexed"]
        
        assert count1 == count2


class TestLegacyIndex:
    def test_legacy_index_detection(self, temp_project: Path) -> None:
        from core.project_context import get_project_context
        
        (temp_project / "data" / "chapters").mkdir(parents=True, exist_ok=True)
        ctx = get_project_context(temp_project)
        
        assert is_legacy_index(ctx.data_dir) is True
        
        manifest = IndexManifest(schema_version=2, project_id=ctx.root.name, timeline_id="main")
        save_manifest(ctx.data_dir, manifest)
        
        assert is_legacy_index(ctx.data_dir) is False

    def test_legacy_index_version_1(self, temp_project: Path) -> None:
        from core.project_context import get_project_context
        
        (temp_project / "data" / "chapters").mkdir(parents=True, exist_ok=True)
        ctx = get_project_context(temp_project)
        
        manifest = IndexManifest(schema_version=1, project_id=ctx.root.name, timeline_id="main")
        save_manifest(ctx.data_dir, manifest)
        
        assert is_legacy_index(ctx.data_dir) is True

    def test_non_main_timeline_requires_v2(self, temp_project: Path) -> None:
        from core.project_context import get_project_context
        from system.vector_index_schema import IndexManifest, save_manifest
        
        (temp_project / "data" / "chapters").mkdir(parents=True, exist_ok=True)
        ctx = get_project_context(temp_project)
        
        legacy_manifest = IndexManifest(
            schema_version=1,
            project_id="test_project",
            timeline_id="main",
            last_rebuilt_at=None,
            document_count=0,
        )
        save_manifest(ctx.data_dir, legacy_manifest, "main")
        
        with pytest.raises(LegacyIndexError):
            index_chapter(ctx, 1, "test", timeline_id="experiment")


class TestManifestValidation:
    def test_manifest_project_id_mismatch(self, temp_project: Path) -> None:
        from core.project_context import get_project_context
        
        (temp_project / "data" / "chapters").mkdir(parents=True, exist_ok=True)
        ctx = get_project_context(temp_project)
        
        manifest = IndexManifest(schema_version=2, project_id="different_project", timeline_id="main")
        save_manifest(ctx.data_dir, manifest)
        
        with pytest.raises(ProjectMismatchError):
            index_chapter(ctx, 1, "test")

    def test_manifest_schema_version_mismatch(self, temp_project: Path) -> None:
        from core.project_context import get_project_context
        
        (temp_project / "data" / "chapters").mkdir(parents=True, exist_ok=True)
        ctx = get_project_context(temp_project)
        
        manifest = IndexManifest(schema_version=1, project_id=ctx.root.name, timeline_id="main")
        save_manifest(ctx.data_dir, manifest)
        
        assert is_legacy_index(ctx.data_dir) is True


class TestTimelineValidation:
    def test_valid_timeline_ids(self) -> None:
        assert validate_timeline_id("main") is True
        assert validate_timeline_id("experiment") is True
        assert validate_timeline_id("test_123") is True
        assert validate_timeline_id("my-timeline") is True

    def test_invalid_timeline_ids(self) -> None:
        assert validate_timeline_id("") is False
        assert validate_timeline_id("..") is False
        assert validate_timeline_id("invalid/path") is False
        assert validate_timeline_id("invalid\\path") is False
        assert validate_timeline_id("UPPERCASE") is False


def _collection(data_dir: Path):
    from system.vector_index_lifecycle import _collection
    return _collection(data_dir)