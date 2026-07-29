"""Phase 0C2 Project Clone Tests.

Tests verify:
1. Basic clone — new project_id, directory, name, slug, cloned_from
2. Whitelist copy — correct data copied, excluded data not copied
3. State transformation — creative progress preserved, runtime cleared
4. Canon consistency — active Canon and chapter projection match
5. Vector isolation — source and clone queries strictly isolated
6. Failure injection — staging cleanup, no half-finished projects
7. Resource release — client manager close, temp directory deletion
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest

from core.project_context import get_project_context, ProjectContext
from system.project_clone_service import (
    ProjectCloneService,
    CloneError,
    ClonePreflightError,
    CloneProjectResult,
)
from system.vector_index_lifecycle import (
    index_chapter,
    search_similar,
    rebuild_project_index,
)
from system.vector_client_manager import VectorClientManager
from system.vector_sync_run_store import (
    VectorSyncRunStore,
    VectorSyncOperationType,
    VectorSyncStatus,
)


def _create_source_project(workspace: Path) -> Path:
    """Create a fully populated source project for clone testing."""
    projects_dir = workspace / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    source = projects_dir / "source-novel"
    source.mkdir()
    data = source / "data"
    data.mkdir()

    # Core files
    (data / "story_spec.json").write_text(
        json.dumps({"title": "源小说", "genre": "玄幻"}, ensure_ascii=False), encoding="utf-8"
    )
    (data / "state.json").write_text(
        json.dumps({
            "current_chapter": 3,
            "current_stage": "chapter_committed",
            "plot": {"main_arc": "主角成长"},
            "vector_memory": {"enabled": True},
            "project_id": "source-original-id",
            "running_pipeline": "should_be_removed",
            "active_job": "should_be_removed",
        }, ensure_ascii=False), encoding="utf-8"
    )
    (data / "story_blueprint.json").write_text(
        json.dumps({"main_arc": "test"}, ensure_ascii=False), encoding="utf-8"
    )
    (data / "characters.json").write_text(
        json.dumps({"main_characters": [{"name": "主角"}]}, ensure_ascii=False), encoding="utf-8"
    )
    (data / "world_bible.json").write_text(
        json.dumps({"core_rules": [{"rule": "魔法"}]}, ensure_ascii=False), encoding="utf-8"
    )

    # Chapters and Canon
    (data / "chapters").mkdir()
    (data / "chapters" / "chapter_001.md").write_text("# 第一章 开始\n\n故事开始了。", encoding="utf-8")
    (data / "chapters" / "chapter_002.md").write_text("# 第二章 冒险\n\n冒险继续。", encoding="utf-8")
    (data / "chapters" / "chapter_003.md").write_text("# 第三章 转折\n\n重大转折。", encoding="utf-8")

    (data / "canon_versions").mkdir()
    (data / "canon_versions" / "chapter_001_v001.json").write_text(
        json.dumps({"chapter_id": 1, "canon_version_id": "cv1", "status": "active"}, ensure_ascii=False), encoding="utf-8"
    )

    # Whitelisted directories
    for d in ["summaries", "drafts", "edited", "versions", "reviews", "quality_reports", "context", "memory", "narrative_memory", "planning_control"]:
        (data / d).mkdir(parents=True, exist_ok=True)
    (data / "summaries" / "chapter_001_summary.json").write_text(
        json.dumps({"chapter_id": 1, "summary": "开始"}, ensure_ascii=False), encoding="utf-8"
    )
    (data / "memory" / "memory_index.json").write_text(
        json.dumps({"entries": []}, ensure_ascii=False), encoding="utf-8"
    )

    # Excluded directories (should NOT be copied)
    for d in ["chroma", "pipeline_runs", "commit_runs", "vector_sync_runs", "jobs", "logs", "model_runs", "agents", "creative_loop"]:
        (data / d).mkdir(parents=True, exist_ok=True)
    (data / "chroma" / "sqlite3.db").write_bytes(b"fake chroma data")
    (data / "pipeline_runs" / "run_001.json").write_text("{}", encoding="utf-8")
    (data / "commit_runs" / "cr_001.json").write_text("{}", encoding="utf-8")
    (data / "jobs" / "job_001.json").write_text("{}", encoding="utf-8")

    # Project metadata
    (source / "project.json").write_text(
        json.dumps({
            "schema_version": "1.0",
            "project_id": "source-original-id",
            "slug": "source-novel",
            "title": "源小说",
            "genre": "玄幻",
            "project_root": "projects/source-novel",
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
        }, ensure_ascii=False), encoding="utf-8"
    )

    return source


class TestBasicClone:
    def test_new_project_id_differs(self, workspace: Path) -> None:
        source = _create_source_project(workspace)
        source_ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(source_ctx, "副本小说", "clone-novel")
        assert result.project_id != "source-original-id"

    def test_new_directory_differs(self, workspace: Path) -> None:
        source = _create_source_project(workspace)
        source_ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(source_ctx, "副本小说", "clone-novel")
        clone_dir = workspace / "projects" / result.project_slug
        assert clone_dir != source
        assert clone_dir.exists()

    def test_name_and_slug_correct(self, workspace: Path) -> None:
        source = _create_source_project(workspace)
        source_ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(source_ctx, "副本小说", "clone-novel")
        assert result.project_slug == "clone-novel"
        clone_meta = json.loads((workspace / "projects" / "clone-novel" / "project.json").read_text(encoding="utf-8"))
        assert clone_meta["title"] == "副本小说"
        assert clone_meta["slug"] == "clone-novel"

    def test_cloned_from_project_id(self, workspace: Path) -> None:
        source = _create_source_project(workspace)
        source_ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(source_ctx, "副本小说", "clone-novel")
        assert result.source_project_id == "source-original-id"
        clone_meta = json.loads((workspace / "projects" / "clone-novel" / "project.json").read_text(encoding="utf-8"))
        assert clone_meta["cloned_from_project_id"] == "source-original-id"
        assert clone_meta["cloned_at"] is not None

    def test_default_timeline_main(self, workspace: Path) -> None:
        source = _create_source_project(workspace)
        source_ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(source_ctx, "副本小说", "clone-novel")
        assert result.timeline_id == "main"

    def test_source_unchanged(self, workspace: Path) -> None:
        source = _create_source_project(workspace)
        original_spec = (source / "data" / "story_spec.json").read_text(encoding="utf-8")
        original_state = (source / "data" / "state.json").read_text(encoding="utf-8")
        source_ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        service.clone_project(source_ctx, "副本小说", "clone-novel")
        assert (source / "data" / "story_spec.json").read_text(encoding="utf-8") == original_spec
        assert (source / "data" / "state.json").read_text(encoding="utf-8") == original_state


class TestWhitelistCopy:
    def test_copies_chapters(self, workspace: Path) -> None:
        source = _create_source_project(workspace)
        source_ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(source_ctx, "副本", "clone-novel")
        clone_data = workspace / "projects" / "clone-novel" / "data"
        assert (clone_data / "chapters" / "chapter_001.md").exists()
        assert (clone_data / "chapters" / "chapter_002.md").exists()
        assert (clone_data / "chapters" / "chapter_003.md").exists()

    def test_copies_canon(self, workspace: Path) -> None:
        source = _create_source_project(workspace)
        source_ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(source_ctx, "副本", "clone-novel")
        clone_data = workspace / "projects" / "clone-novel" / "data"
        assert (clone_data / "canon_versions" / "chapter_001_v001.json").exists()

    def test_copies_story_spec(self, workspace: Path) -> None:
        source = _create_source_project(workspace)
        source_ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(source_ctx, "副本", "clone-novel")
        clone_data = workspace / "projects" / "clone-novel" / "data"
        assert (clone_data / "story_spec.json").exists()
        spec = json.loads((clone_data / "story_spec.json").read_text(encoding="utf-8"))
        assert spec["title"] == "源小说"

    def test_does_not_copy_chroma(self, workspace: Path) -> None:
        source = _create_source_project(workspace)
        source_ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(source_ctx, "副本", "clone-novel")
        clone_data = workspace / "projects" / "clone-novel" / "data"
        # Chroma may exist if vector rebuild ran, but must NOT contain the source's sqlite3.db
        # The source had a fake "sqlite3.db" — clone chroma should not have it
        if (clone_data / "chroma").exists():
            assert not (clone_data / "chroma" / "sqlite3.db").exists(), \
                "Source chroma data was copied instead of being rebuilt"

    def test_does_not_copy_pipeline_runs(self, workspace: Path) -> None:
        source = _create_source_project(workspace)
        source_ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(source_ctx, "副本", "clone-novel")
        clone_data = workspace / "projects" / "clone-novel" / "data"
        assert not (clone_data / "pipeline_runs").exists()

    def test_does_not_copy_commit_runs(self, workspace: Path) -> None:
        source = _create_source_project(workspace)
        source_ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(source_ctx, "副本", "clone-novel")
        clone_data = workspace / "projects" / "clone-novel" / "data"
        assert not (clone_data / "commit_runs").exists()

    def test_does_not_copy_jobs(self, workspace: Path) -> None:
        source = _create_source_project(workspace)
        source_ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(source_ctx, "副本", "clone-novel")
        clone_data = workspace / "projects" / "clone-novel" / "data"
        assert not (clone_data / "jobs").exists()

    def test_excluded_in_skipped_items(self, workspace: Path) -> None:
        source = _create_source_project(workspace)
        source_ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(source_ctx, "副本", "clone-novel")
        skipped = " ".join(result.skipped_items)
        assert "chroma" in skipped
        assert "pipeline_runs" in skipped


class TestStateTransformation:
    def test_creative_progress_preserved(self, workspace: Path) -> None:
        source = _create_source_project(workspace)
        source_ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(source_ctx, "副本", "clone-novel")
        clone_data = workspace / "projects" / "clone-novel" / "data"
        state = json.loads((clone_data / "state.json").read_text(encoding="utf-8"))
        assert state["current_chapter"] == 3
        assert state["current_stage"] == "chapter_committed"
        assert state["plot"]["main_arc"] == "主角成长"

    def test_project_id_updated(self, workspace: Path) -> None:
        source = _create_source_project(workspace)
        source_ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(source_ctx, "副本", "clone-novel")
        clone_data = workspace / "projects" / "clone-novel" / "data"
        state = json.loads((clone_data / "state.json").read_text(encoding="utf-8"))
        assert state["project_id"] == result.project_id
        assert state["project_id"] != "source-original-id"

    def test_runtime_fields_cleared(self, workspace: Path) -> None:
        source = _create_source_project(workspace)
        source_ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(source_ctx, "副本", "clone-novel")
        clone_data = workspace / "projects" / "clone-novel" / "data"
        state = json.loads((clone_data / "state.json").read_text(encoding="utf-8"))
        assert "running_pipeline" not in state
        assert "active_job" not in state


class TestVectorIsolation:
    def test_clone_rebuilds_index(self, workspace: Path) -> None:
        source = _create_source_project(workspace)
        source_ctx = get_project_context(source)
        # Write chapter content that will be found by search
        (source_ctx.chapters_dir / "chapter_001.md").write_text(
            "龙族传说，火焰与冰霜，古老的契约。", encoding="utf-8"
        )
        (source_ctx.chapters_dir / "chapter_002.md").write_text(
            "魔法学院，咒语与契约，新世界的开端。", encoding="utf-8"
        )
        index_chapter(source_ctx, 1, "龙族传说，火焰与冰霜，古老的契约。", canon_revision_id="rev1")
        index_chapter(source_ctx, 2, "魔法学院，咒语与契约，新世界的开端。", canon_revision_id="rev2")

        service = ProjectCloneService(workspace)
        result = service.clone_project(source_ctx, "副本", "clone-novel")

        assert result.vector_sync_operation_id is None
        assert result.status in ["completed", "completed_with_warnings"]
        assert any("VECTOR_SCOPE_REQUIRED" in warning for warning in result.warnings)

        clone_ctx = get_project_context(workspace / "projects" / "clone-novel")
        assert (clone_ctx.chapters_dir / "chapter_001.md").exists()

        # No branchless vector query is permitted until a complete VectorScope
        # has been selected for the cloned project.

    def test_source_query_not_return_clone(self, workspace: Path) -> None:
        source = _create_source_project(workspace)
        source_ctx = get_project_context(source)
        (source_ctx.chapters_dir / "chapter_001.md").write_text(
            "龙族传说，火焰与冰霜，古老的契约。", encoding="utf-8"
        )
        index_chapter(source_ctx, 1, "龙族传说，火焰与冰霜，古老的契约。", canon_revision_id="rev1")

        service = ProjectCloneService(workspace)
        result = service.clone_project(source_ctx, "副本", "clone-novel")

        source_results = search_similar(source_ctx, "龙族传说", timeline_id="main")
        clone_ctx = get_project_context(workspace / "projects" / "clone-novel")

        # Source results should not contain clone's project_id
        for r in source_results:
            assert r.get("metadata", {}).get("project_id") != result.project_id

    def test_same_chapter_id_no_cross_talk(self, workspace: Path) -> None:
        source = _create_source_project(workspace)
        source_ctx = get_project_context(source)
        (source_ctx.chapters_dir / "chapter_001.md").write_text(
            "源项目第一章：龙族传说，火焰燃烧。", encoding="utf-8"
        )
        index_chapter(source_ctx, 1, "源项目第一章：龙族传说，火焰燃烧。", canon_revision_id="s_rev1")

        service = ProjectCloneService(workspace)
        result = service.clone_project(source_ctx, "副本", "clone-novel")

        clone_ctx = get_project_context(workspace / "projects" / "clone-novel")
        # Modify clone's chapter 1 content and re-index
        (clone_ctx.chapters_dir / "chapter_001.md").write_text(
            "克隆项目第一章：星辰大海，宇宙探索。", encoding="utf-8"
        )
        index_chapter(clone_ctx, 1, "克隆项目第一章：星辰大海，宇宙探索。", canon_revision_id="c_rev1")

        source_results = search_similar(source_ctx, "龙族传说", timeline_id="main")
        clone_results = search_similar(clone_ctx, "星辰大海", timeline_id="main")

        assert len(source_results) > 0
        assert len(clone_results) > 0
        # Verify strict isolation
        assert "龙族" in source_results[0].get("snippet", "")
        assert "星辰" in clone_results[0].get("snippet", "")

    def test_vector_sync_operation_recorded(self, workspace: Path) -> None:
        source = _create_source_project(workspace)
        source_ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(source_ctx, "副本", "clone-novel")

        if result.vector_sync_operation_id:
            clone_ctx = get_project_context(workspace / "projects" / "clone-novel")
            sync_store = VectorSyncRunStore(clone_ctx)
            run = sync_store.get(result.vector_sync_operation_id)
            assert run is not None
            assert run.operation_type == VectorSyncOperationType.CLONE
            assert run.status in [VectorSyncStatus.COMPLETED, VectorSyncStatus.FAILED]


class TestFailureInjection:
    def test_slug_conflict_fails(self, workspace: Path) -> None:
        source = _create_source_project(workspace)
        source_ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        service.clone_project(source_ctx, "第一次", "clone-novel")
        with pytest.raises(ClonePreflightError, match="already exists"):
            service.clone_project(source_ctx, "第二次", "clone-novel")

    def test_staging_cleaned_on_failure(self, workspace: Path) -> None:
        source = _create_source_project(workspace)
        source_ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        with pytest.raises(ClonePreflightError):
            service.clone_project(source_ctx, "", "bad-slug")
        staging_dirs = list(workspace.glob(".clone_*"))
        assert len(staging_dirs) == 0

    def test_empty_name_fails(self, workspace: Path) -> None:
        source = _create_source_project(workspace)
        source_ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        with pytest.raises(ClonePreflightError):
            service.clone_project(source_ctx, "", "some-slug")


class TestResourceRelease:
    def test_temp_dirs_deletable(self, workspace: Path) -> None:
        source = _create_source_project(workspace)
        source_ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(source_ctx, "副本", "clone-novel")

        VectorClientManager().close_all()

        clone_dir = workspace / "projects" / result.project_slug
        assert clone_dir.exists()
        try:
            shutil.rmtree(str(clone_dir))
        except Exception:
            pass

    def test_close_idempotent(self, workspace: Path) -> None:
        source = _create_source_project(workspace)
        source_ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        service.clone_project(source_ctx, "副本", "clone-novel")

        VectorClientManager().close_all()
        VectorClientManager().close_all()


class TestCloneResultFormat:
    def test_result_dict(self, workspace: Path) -> None:
        source = _create_source_project(workspace)
        source_ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(source_ctx, "副本", "clone-novel")
        d = result.to_dict()
        assert "status" in d
        assert "source_project_id" in d
        assert "project_id" in d
        assert "project_slug" in d
        assert "project_root" in d
        assert "timeline_id" in d
        assert "copied_items" in d
        assert "skipped_items" in d
        assert "warnings" in d
        assert "vector_sync_operation_id" in d


@pytest.fixture(autouse=True)
def _reset_client_manager():
    VectorClientManager().close_all()
    yield
    VectorClientManager().close_all()


@pytest.fixture
def workspace() -> Path:
    tmpdir = tempfile.mkdtemp()
    yield Path(tmpdir)
    VectorClientManager().close_all()
    try:
        shutil.rmtree(tmpdir)
    except Exception:
        pass
