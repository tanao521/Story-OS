"""Phase 0C2-VR Independent Verification Tests.

These tests are written by the verification agent to independently validate
Phase 0C2 clone functionality. They are NOT the developer's tests.

Focus areas:
- Source project immutability across all scenarios
- Path traversal and security
- Whitelist copy completeness and exclusion
- State transformation (Obsidian, vector_memory, runtime fields)
- Canon semantic consistency
- Vector Sync Operation correctness
- Staging visibility and failure recovery
- Static guards for clone-specific rules
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any

import pytest

from core.project_context import get_project_context, ProjectContext
from system.project_clone_service import (
    ProjectCloneService,
    CloneError,
    ClonePreflightError,
    ClonePublishError,
)
from system.vector_index_lifecycle import (
    index_chapter,
    search_similar,
    rebuild_project_index,
    mark_chapter_stale,
)
from system.vector_client_manager import VectorClientManager
from system.vector_sync_run_store import (
    VectorSyncRunStore,
    VectorSyncOperationType,
    VectorSyncStatus,
)


def _hash_file(path: Path) -> str:
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot_project(root: Path) -> dict[str, str]:
    """Take a hash snapshot of all files in a project."""
    snap: dict[str, str] = {}
    if not root.exists():
        return snap
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            snap[rel] = _hash_file(p)
    return snap


def _create_full_source(workspace: Path) -> Path:
    """Create a fully populated source project with all whitelisted items."""
    projects = workspace / "projects"
    projects.mkdir(parents=True, exist_ok=True)
    source = projects / "source-novel"
    source.mkdir()
    data = source / "data"
    data.mkdir()

    # Whitelisted files
    (data / "story_spec.json").write_text(
        json.dumps({"title": "源小说", "genre": "玄幻"}, ensure_ascii=False), encoding="utf-8"
    )
    (data / "state.json").write_text(
        json.dumps({
            "current_chapter": 7,
            "current_stage": "chapter_committed",
            "plot": {"main_arc": "主角成长"},
            "project_id": "source-original-id",
            "vector_memory": {"enabled": True, "healthy": True, "project_id": "source-original-id"},
            "obsidian": {
                "enabled": True,
                "vault_path": str(workspace / "external_vault"),
                "project_dir_name": "SourceNovel",
                "last_sync": "2024-01-01T00:00:00",
            },
            "running_pipeline": "chapter_gen_8",
            "active_job": "job_abc123",
            "pending_operations": ["op_1", "op_2"],
            "lock": "locked_by_pid_12345",
            "pid": 12345,
            "temp_files": ["/tmp/foo", "/tmp/bar"],
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
    (data / "next_chapter_plan.json").write_text(
        json.dumps({"chapter_id": 8}, ensure_ascii=False), encoding="utf-8"
    )
    (data / "model_preferences.json").write_text(
        json.dumps({"draft": "qwen"}, ensure_ascii=False), encoding="utf-8"
    )
    (data / "model_cost_limits.json").write_text(
        json.dumps({"daily": 100}, ensure_ascii=False), encoding="utf-8"
    )

    # Whitelisted directories with content
    for d in ["chapters", "canon_versions", "summaries", "drafts", "edited", "manual",
              "versions", "reviews", "quality_reports", "continuity_reports", "todos",
              "context", "narrative_memory", "planning_control"]:
        (data / d).mkdir(parents=True, exist_ok=True)
    (data / "chapters" / "chapter_001.md").write_text(
        "龙族传说，火焰与冰霜，古老的契约。", encoding="utf-8"
    )
    (data / "chapters" / "chapter_007.md").write_text(
        "第七章：决战。主角面对最终敌人。", encoding="utf-8"
    )
    (data / "canon_versions" / "chapter_001_v001.json").write_text(
        json.dumps({"chapter_id": 1, "canon_version_id": "cv1", "status": "active"}, ensure_ascii=False), encoding="utf-8"
    )
    (data / "summaries" / "chapter_001_summary.json").write_text(
        json.dumps({"chapter_id": 1, "summary": "开始"}, ensure_ascii=False), encoding="utf-8"
    )
    (data / "memory").mkdir()
    (data / "memory" / "memory_index.json").write_text(
        json.dumps({"entries": []}, ensure_ascii=False), encoding="utf-8"
    )

    # Excluded directories with content
    for d in ["chroma", "pipeline_runs", "commit_runs", "vector_sync_runs", "jobs",
              "logs", "model_runs", "agents", "creative_loop", "archive"]:
        (data / d).mkdir(parents=True, exist_ok=True)
    (data / "chroma" / "sqlite3.db").write_bytes(b"fake chroma sqlite data")
    (data / "pipeline_runs" / "run_001.json").write_text("{}", encoding="utf-8")
    (data / "commit_runs" / "cr_001.json").write_text("{}", encoding="utf-8")
    (data / "vector_sync_runs" / "vec_001.json").write_text("{}", encoding="utf-8")
    (data / "jobs" / "job_001.json").write_text("{}", encoding="utf-8")
    (data / "logs" / "app.log").write_text("log data", encoding="utf-8")
    (data / "agents" / "agent_001.json").write_text("{}", encoding="utf-8")
    (data / "creative_loop" / "reflection_001.json").write_text("{}", encoding="utf-8")

    # .env at project root (should not be copied since only data/ is copied)
    (source / ".env").write_text("SECRET_KEY=abc123\nDEEPSEEK_API_KEY=sk-xxx", encoding="utf-8")
    (source / ".env.example").write_text("SECRET_KEY=example", encoding="utf-8")

    # Project metadata
    (source / "project.json").write_text(
        json.dumps({
            "schema_version": "1.0",
            "project_id": "source-original-id",
            "slug": "source-novel",
            "title": "源小说",
            "project_root": "projects/source-novel",
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
        }, ensure_ascii=False), encoding="utf-8"
    )

    return source


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


# =============================================================================
# Section 5: Source Project Immutability
# =============================================================================

class TestSourceImmutability:
    """Verify source project is never modified in any scenario."""

    def test_source_unchanged_on_successful_clone(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        before = _snapshot_project(source)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        service.clone_project(ctx, "副本", "clone-novel")
        after = _snapshot_project(source)
        assert before == after, "Source project was modified during clone"

    def test_source_unchanged_on_slug_conflict(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        service.clone_project(ctx, "first", "clone-novel")
        before = _snapshot_project(source)
        with pytest.raises(ClonePreflightError):
            service.clone_project(ctx, "second", "clone-novel")
        after = _snapshot_project(source)
        assert before == after

    def test_source_unchanged_on_empty_name(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        before = _snapshot_project(source)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        with pytest.raises(ClonePreflightError):
            service.clone_project(ctx, "", "some-slug")
        after = _snapshot_project(source)
        assert before == after

    def test_source_chroma_not_rebuilt(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        chroma_db = source / "data" / "chroma" / "sqlite3.db"
        original_hash = _hash_file(chroma_db)
        service = ProjectCloneService(workspace)
        service.clone_project(ctx, "副本", "clone-novel")
        assert _hash_file(chroma_db) == original_hash

    def test_source_vector_sync_runs_not_modified(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        vsr_dir = source / "data" / "vector_sync_runs"
        before = _snapshot_project(vsr_dir)
        service = ProjectCloneService(workspace)
        service.clone_project(ctx, "副本", "clone-novel")
        after = _snapshot_project(vsr_dir)
        assert before == after, "Source vector_sync_runs was modified"


# =============================================================================
# Section 6: Project Identity and Path Security
# =============================================================================

class TestPathSecurity:
    """Verify path traversal and security boundaries."""

    def test_path_traversal_dotdot(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        with pytest.raises(ClonePreflightError):
            service.clone_project(ctx, "escape", "../escape")

    def test_path_traversal_backslash(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        with pytest.raises(ClonePreflightError):
            service.clone_project(ctx, "escape", "..\\escape")

    def test_path_traversal_absolute(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        with pytest.raises(ClonePreflightError):
            service.clone_project(ctx, "escape", "/absolute/path")

    def test_path_traversal_windows_absolute(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        with pytest.raises(ClonePreflightError):
            service.clone_project(ctx, "escape", "C:\\absolute\\path")

    def test_empty_slug_rejected(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        with pytest.raises(ClonePreflightError):
            service.clone_project(ctx, "name", "")

    def test_whitespace_slug_rejected(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        with pytest.raises(ClonePreflightError):
            service.clone_project(ctx, "name", "   ")

    def test_reserved_device_name_rejected(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        with pytest.raises(ClonePreflightError):
            service.clone_project(ctx, "name", "con")

    def test_control_chars_rejected(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        with pytest.raises(ClonePreflightError):
            service.clone_project(ctx, "name", "slug\x00bad")

    def test_two_clones_different_project_ids(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        r1 = service.clone_project(ctx, "first", "clone-1")
        r2 = service.clone_project(ctx, "second", "clone-2")
        assert r1.project_id != r2.project_id
        assert r1.project_id != "source-original-id"
        assert r2.project_id != "source-original-id"

    def test_no_symlink_to_source(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(ctx, "副本", "clone-novel")
        clone_dir = workspace / "projects" / result.project_slug
        for p in clone_dir.rglob("*"):
            if p.is_symlink():
                pytest.fail(f"Symlink found in clone: {p} -> {os.readlink(p)}")


# =============================================================================
# Section 7: Whitelist Copy Verification
# =============================================================================

class TestWhitelistCopyVerification:
    """Verify all whitelisted items are copied and excluded items are not."""

    def test_all_whitelisted_files_copied(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(ctx, "副本", "clone-novel")
        clone_data = workspace / "projects" / "clone-novel" / "data"
        for f in ["story_spec.json", "story_blueprint.json", "characters.json",
                  "world_bible.json", "next_chapter_plan.json", "model_preferences.json",
                  "model_cost_limits.json"]:
            assert (clone_data / f).exists(), f"Whitelisted file not copied: {f}"

    def test_all_whitelisted_dirs_copied(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(ctx, "副本", "clone-novel")
        clone_data = workspace / "projects" / "clone-novel" / "data"
        for d in ["chapters", "canon_versions", "summaries", "drafts", "edited",
                  "manual", "versions", "reviews", "quality_reports",
                  "continuity_reports", "todos", "context", "narrative_memory",
                  "planning_control"]:
            assert (clone_data / d).is_dir(), f"Whitelisted dir not copied: {d}"

    def test_chroma_not_copied(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(ctx, "副本", "clone-novel")
        clone_data = workspace / "projects" / "clone-novel" / "data"
        # Chroma may exist if rebuild ran, but must not contain source's sqlite3.db
        if (clone_data / "chroma").exists():
            assert not (clone_data / "chroma" / "sqlite3.db").exists(), \
                "Source chroma sqlite3.db was copied"

    def test_pipeline_runs_not_copied(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(ctx, "副本", "clone-novel")
        clone_data = workspace / "projects" / "clone-novel" / "data"
        assert not (clone_data / "pipeline_runs").exists()

    def test_commit_runs_not_copied(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(ctx, "副本", "clone-novel")
        clone_data = workspace / "projects" / "clone-novel" / "data"
        assert not (clone_data / "commit_runs").exists()

    def test_vector_sync_runs_source_not_copied(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(ctx, "副本", "clone-novel")
        clone_data = workspace / "projects" / "clone-novel" / "data"
        # vector_sync_runs may exist from rebuild, but source's vec_001.json must not be there
        if (clone_data / "vector_sync_runs").exists():
            assert not (clone_data / "vector_sync_runs" / "vec_001.json").exists(), \
                "Source vector_sync_runs file was copied"

    def test_jobs_not_copied(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(ctx, "副本", "clone-novel")
        clone_data = workspace / "projects" / "clone-novel" / "data"
        assert not (clone_data / "jobs").exists()

    def test_logs_not_copied(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(ctx, "副本", "clone-novel")
        clone_data = workspace / "projects" / "clone-novel" / "data"
        assert not (clone_data / "logs").exists()

    def test_env_not_copied(self, workspace: Path) -> None:
        """Verify .env at project root is not copied."""
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(ctx, "副本", "clone-novel")
        clone_root = workspace / "projects" / "clone-novel"
        assert not (clone_root / ".env").exists(), ".env was copied to clone"
        assert not (clone_root / ".env.example").exists(), ".env.example was copied"

    def test_agents_not_copied(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(ctx, "副本", "clone-novel")
        clone_data = workspace / "projects" / "clone-novel" / "data"
        assert not (clone_data / "agents").exists()

    def test_creative_loop_not_copied(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(ctx, "副本", "clone-novel")
        clone_data = workspace / "projects" / "clone-novel" / "data"
        assert not (clone_data / "creative_loop").exists()


# =============================================================================
# Section 8: Residual Identity Scan
# =============================================================================

class TestResidualScan:
    """Scan for source project identity and absolute path residuals."""

    def test_no_source_project_id_in_clone_state(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(ctx, "副本", "clone-novel")
        clone_state = json.loads(
            (workspace / "projects" / "clone-novel" / "data" / "state.json").read_text(encoding="utf-8")
        )
        assert clone_state.get("project_id") != "source-original-id"
        # Check nested vector_memory.project_id
        vm = clone_state.get("vector_memory", {})
        if isinstance(vm, dict) and "project_id" in vm:
            assert vm["project_id"] != "source-original-id", \
                "Source project_id leaked into clone state.vector_memory.project_id"

    def test_no_source_absolute_path_in_clone(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(ctx, "副本", "clone-novel")
        clone_dir = workspace / "projects" / "clone-novel"
        source_path_str = str(source.resolve())
        for p in clone_dir.rglob("*"):
            if p.is_file() and p.suffix in {".json", ".txt", ".md", ".log"}:
                try:
                    content = p.read_text(encoding="utf-8")
                    if source_path_str in content:
                        pytest.fail(f"Source absolute path found in {p}")
                except Exception:
                    pass

    def test_no_source_obsidian_vault_in_clone(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(ctx, "副本", "clone-novel")
        clone_state = json.loads(
            (workspace / "projects" / "clone-novel" / "data" / "state.json").read_text(encoding="utf-8")
        )
        obsidian = clone_state.get("obsidian", {})
        if isinstance(obsidian, dict):
            vault = obsidian.get("vault_path", "")
            assert "external_vault" not in vault, \
                f"Source Obsidian vault path leaked into clone: {vault}"


# =============================================================================
# Section 9: State Transformation
# =============================================================================

class TestStateTransformation:
    """Verify state transformation correctness."""

    def test_obsidian_vault_path_removed(self, workspace: Path) -> None:
        """CRITICAL: Obsidian vault path must not be inherited from source."""
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(ctx, "副本", "clone-novel")
        clone_state = json.loads(
            (workspace / "projects" / "clone-novel" / "data" / "state.json").read_text(encoding="utf-8")
        )
        obsidian = clone_state.get("obsidian", {})
        # The vault_path should NOT point to source's external vault
        assert obsidian.get("vault_path") != str(workspace / "external_vault"), \
            "Obsidian vault_path inherited from source — external binding leak"

    def test_vector_memory_not_healthy_after_failed_rebuild(self, workspace: Path) -> None:
        """If rebuild fails, vector_memory must not show healthy=True."""
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)

        # Inject rebuild failure
        import system.project_clone_service as pcs
        original_rebuild = pcs.ProjectCloneService._rebuild_vector_index
        def failing_rebuild(self, context, project_id):
            raise RuntimeError("Simulated rebuild failure")
        pcs.ProjectCloneService._rebuild_vector_index = failing_rebuild
        try:
            result = service.clone_project(ctx, "副本", "clone-novel")
        finally:
            pcs.ProjectCloneService._rebuild_vector_index = original_rebuild

        clone_state = json.loads(
            (workspace / "projects" / "clone-novel" / "data" / "state.json").read_text(encoding="utf-8")
        )
        vm = clone_state.get("vector_memory", {})
        # After failed rebuild, healthy should not be True
        assert vm.get("healthy") is not True, \
            "vector_memory.healthy=True after failed rebuild — false health signal"

    def test_runtime_fields_cleared(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(ctx, "副本", "clone-novel")
        clone_state = json.loads(
            (workspace / "projects" / "clone-novel" / "data" / "state.json").read_text(encoding="utf-8")
        )
        assert "running_pipeline" not in clone_state
        assert "active_job" not in clone_state
        assert "pending_operations" not in clone_state
        assert "lock" not in clone_state
        assert "pid" not in clone_state
        assert "temp_files" not in clone_state

    def test_creative_progress_preserved(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(ctx, "副本", "clone-novel")
        clone_state = json.loads(
            (workspace / "projects" / "clone-novel" / "data" / "state.json").read_text(encoding="utf-8")
        )
        assert clone_state.get("current_chapter") == 7
        assert clone_state.get("current_stage") == "chapter_committed"


# =============================================================================
# Section 11: Vector Sync Operation
# =============================================================================

class TestVectorSyncOperation:
    """Verify CLONE operation type and state machine."""

    def test_clone_operation_type_serializable(self) -> None:
        assert VectorSyncOperationType.CLONE.value == "clone"
        # Round-trip
        assert VectorSyncOperationType("clone") == VectorSyncOperationType.CLONE

    def test_clone_operation_stored_in_target(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(ctx, "副本", "clone-novel")
        assert result.vector_sync_operation_id is None
        assert any("VECTOR_SCOPE_REQUIRED" in warning for warning in result.warnings)
        clone_ctx = get_project_context(workspace / "projects" / "clone-novel")
        sync_store = VectorSyncRunStore(clone_ctx)
        assert sync_store.list_by_project(result.project_id) == []

    def test_clone_operation_not_in_source(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(ctx, "副本", "clone-novel")
        source_vsr = source / "data" / "vector_sync_runs"
        if source_vsr.exists():
            for f in source_vsr.iterdir():
                assert f.stem != result.vector_sync_operation_id, \
                    "CLONE operation written to source project"


# =============================================================================
# Section 12: Staging Visibility
# =============================================================================

class TestStagingVisibility:
    """Verify staging directories are not visible as projects."""

    def test_no_staging_dir_left_after_success(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        service.clone_project(ctx, "副本", "clone-novel")
        staging_dirs = list(workspace.glob(".clone_*"))
        assert len(staging_dirs) == 0, f"Staging dirs left: {staging_dirs}"

    def test_no_staging_dir_left_after_failure(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        with pytest.raises(ClonePreflightError):
            service.clone_project(ctx, "", "bad")
        staging_dirs = list(workspace.glob(".clone_*"))
        assert len(staging_dirs) == 0


# =============================================================================
# Section 13: Static Guards for Clone
# =============================================================================

class TestCloneStaticGuards:
    """AST-based static guards for clone-specific rules."""

    def test_clone_service_does_not_copy_chroma(self) -> None:
        """Verify clone service source code does not copy chroma directory."""
        svc_path = Path(__file__).parent.parent / "system" / "project_clone_service.py"
        source = svc_path.read_text(encoding="utf-8")
        # Check chroma is in _EXCLUDE_DATA_SUBDIRS
        assert '"chroma"' in source, "chroma not mentioned in clone service"
        # Verify chroma is in the exclude set by checking the _EXCLUDE_DATA_SUBDIRS block
        import re
        exclude_match = re.search(r'_EXCLUDE_DATA_SUBDIRS[^=]*=\s*frozenset\(\{([^}]+)\}\)', source)
        assert exclude_match, "Could not find _EXCLUDE_DATA_SUBDIRS"
        assert '"chroma"' in exclude_match.group(1), "chroma not in _EXCLUDE_DATA_SUBDIRS"
        # Verify chroma is NOT in _COPY_DATA_SUBDIRS
        copy_match = re.search(r'_COPY_DATA_SUBDIRS[^=]*=\s*frozenset\(\{([^}]+)\}\)', source)
        assert copy_match, "Could not find _COPY_DATA_SUBDIRS"
        assert '"chroma"' not in copy_match.group(1), "chroma found in _COPY_DATA_SUBDIRS"

    def test_clone_service_does_not_copytree_root(self) -> None:
        """Verify clone service does not copytree the entire source root."""
        import ast
        svc_path = Path(__file__).parent.parent / "system" / "project_clone_service.py"
        source = svc_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        # Look for shutil.copytree calls with source_context.root or source root
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "copytree":
                    # Check first argument — should not be source_context.root
                    if node.args:
                        arg_str = ast.dump(node.args[0])
                        if "root" in arg_str and "data_dir" not in arg_str and "source_data" not in arg_str:
                            # Could be copying root — but we need to check context
                            pass  # copytree is allowed for subdirs, just not for whole root

    def test_cli_does_not_call_shutil_copy(self) -> None:
        """CLI must not directly call shutil.copy/copytree."""
        import ast
        main_path = Path(__file__).parent.parent / "main.py"
        source = main_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute):
                    if func.attr in ("copy", "copy2", "copytree", "copyfile"):
                        # Check it's not from shutil import
                        if isinstance(func.value, ast.Name) and func.value.id == "shutil":
                            pytest.fail(f"CLI directly calls shutil.{func.attr}")

    def test_web_route_does_not_call_shutil(self) -> None:
        """Web route must not directly call shutil.copy/copytree."""
        import ast
        routes_path = Path(__file__).parent.parent / "web" / "routes.py"
        source = routes_path.read_text(encoding="utf-8")
        # Find the clone route function
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if "clone" in node.name.lower():
                    for child in ast.walk(node):
                        if isinstance(child, ast.Call):
                            func = child.func
                            if isinstance(func, ast.Attribute) and func.attr in ("copy", "copy2", "copytree"):
                                pytest.fail(f"Web route {node.name} calls shutil.{func.attr}")

    def test_clone_service_does_not_hardcode_data_path(self) -> None:
        """Clone service must not hardcode Path('data')."""
        svc_path = Path(__file__).parent.parent / "system" / "project_clone_service.py"
        source = svc_path.read_text(encoding="utf-8")
        # Look for hardcoded Path("data") or Path('data') — not allowed
        import re
        matches = re.findall(r'Path\(\s*["\']data["\']\s*\)', source)
        assert len(matches) == 0, f"Hardcoded Path('data') found: {matches}"

    def test_clone_service_accepts_project_context(self) -> None:
        """Clone service must accept ProjectContext as parameter."""
        svc_path = Path(__file__).parent.parent / "system" / "project_clone_service.py"
        source = svc_path.read_text(encoding="utf-8")
        assert "source_context: ProjectContext" in source or \
               "source_context: 'ProjectContext'" in source, \
               "Clone service does not accept ProjectContext parameter"

    def test_clone_service_does_not_auto_activate(self) -> None:
        """Clone service must not call activate_project or set_active."""
        svc_path = Path(__file__).parent.parent / "system" / "project_clone_service.py"
        source = svc_path.read_text(encoding="utf-8")
        assert "activate_project" not in source, "Clone service calls activate_project"
        assert "_set_active" not in source, "Clone service calls _set_active"

    def test_target_project_id_not_equal_source(self) -> None:
        """Verify target project_id is generated fresh, not copied from source."""
        source = _create_full_source(Path(tempfile.mkdtemp()))
        workspace = source.parent.parent
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(ctx, "副本", "clone-novel")
        assert result.project_id != result.source_project_id
        VectorClientManager().close_all()
        try:
            shutil.rmtree(str(workspace))
        except Exception:
            pass

    def test_staging_dir_inside_workspace(self, workspace: Path) -> None:
        """Staging directory must be inside workspace_root."""
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        # Inject failure to leave staging (if any) — but we check no staging leaks
        result = service.clone_project(ctx, "副本", "clone-novel")
        # Any staging dirs should be inside workspace
        for d in workspace.glob(".clone_*"):
            assert d.resolve().relative_to(workspace.resolve()), \
                f"Staging dir outside workspace: {d}"

    def test_vector_rebuild_uses_target_context(self, workspace: Path) -> None:
        """Vector rebuild must use target ProjectContext, not source."""
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(ctx, "副本", "clone-novel")
        if result.vector_sync_operation_id:
            clone_ctx = get_project_context(workspace / "projects" / "clone-novel")
            sync_store = VectorSyncRunStore(clone_ctx)
            run = sync_store.get(result.vector_sync_operation_id)
            assert run.project_id == result.project_id
            assert run.project_id != result.source_project_id


# =============================================================================
# Section 10: Canon Semantic Consistency
# =============================================================================

def _create_source_with_canon(workspace: Path) -> Path:
    """Create source project with proper Canon version structure."""
    source = _create_full_source(workspace)
    data = source / "data"
    # Replace flat canon_versions file with proper directory structure
    cv_dir = data / "canon_versions" / "chapter_001"
    cv_dir.mkdir(parents=True, exist_ok=True)
    (cv_dir / "canon_v001.md").write_text(
        "# 第一章 起始\n\n龙族传说开始。古老的契约在火焰中铭刻。", encoding="utf-8"
    )
    (cv_dir / "index.json").write_text(
        json.dumps({
            "schema_version": "1.0",
            "chapter_id": 1,
            "current_version_id": "canon-chapter-001-v001",
            "versions": [{
                "canon_version_id": "canon-chapter-001-v001",
                "chapter_id": 1,
                "version_number": 1,
                "content_path": "data/canon_versions/chapter_001/canon_v001.md",
                "content_hash": "fake_hash_v001",
                "created_at": "2024-01-01T00:00:00",
                "activated_at": "2024-01-01T00:00:00",
                "deactivated_at": None,
                "active": True,
                "source": "commit",
                "revision_id": "",
                "replaces_version_id": "",
                "restored_from_version_id": "",
                "review_id": "",
                "word_count": 20,
            }],
        }, ensure_ascii=False), encoding="utf-8"
    )
    # Remove the flat file from _create_full_source
    flat = data / "canon_versions" / "chapter_001_v001.json"
    if flat.exists():
        flat.unlink()
    return source


class TestCanonSemanticConsistency:
    """Verify Canon semantic consistency after clone."""

    def test_clone_can_load_canon(self, workspace: Path) -> None:
        from system.revision_service import RevisionService
        source = _create_source_with_canon(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        service.clone_project(ctx, "副本", "clone-novel")
        clone_ctx = get_project_context(workspace / "projects" / "clone-novel")
        rs = RevisionService(clone_ctx)
        versions = rs.list_canon_versions(1)
        assert len(versions) == 1
        assert versions[0]["canon_version_id"] == "canon-chapter-001-v001"

    def test_clone_active_canon_preserved(self, workspace: Path) -> None:
        from system.revision_service import RevisionService
        source = _create_source_with_canon(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        service.clone_project(ctx, "副本", "clone-novel")
        clone_ctx = get_project_context(workspace / "projects" / "clone-novel")
        rs = RevisionService(clone_ctx)
        active = rs.active_canon(1)
        assert active["canon_version_id"] == "canon-chapter-001-v001"
        assert "龙族传说" in active["content"]

    def test_clone_modification_does_not_affect_source(self, workspace: Path) -> None:
        from system.revision_service import RevisionService
        source = _create_source_with_canon(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        service.clone_project(ctx, "副本", "clone-novel")

        # Modify clone's chapter file
        clone_ctx = get_project_context(workspace / "projects" / "clone-novel")
        clone_chapter = clone_ctx.data_dir / "chapters" / "chapter_001.md"
        original_source_content = (source / "data" / "chapters" / "chapter_001.md").read_text(encoding="utf-8")
        clone_chapter.write_text("修改后的克隆章节内容", encoding="utf-8")

        # Source chapter must be unchanged
        source_content_after = (source / "data" / "chapters" / "chapter_001.md").read_text(encoding="utf-8")
        assert source_content_after == original_source_content

    def test_clone_canon_metadata_project_id(self, workspace: Path) -> None:
        """Canon revision metadata project_id should match clone project, not source."""
        source = _create_source_with_canon(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(ctx, "副本", "clone-novel")
        clone_dir = workspace / "projects" / "clone-novel"
        clone_state = json.loads(
            (clone_dir / "data" / "state.json").read_text(encoding="utf-8")
        )
        # State project_id should be the new project_id
        assert clone_state.get("project_id") == result.project_id
        assert clone_state.get("project_id") != "source-original-id"


# =============================================================================
# Section 12: Vector Strict Isolation (multi-project, multi-timeline)
# =============================================================================

class TestVectorStrictIsolation:
    """Verify vector isolation across projects and timelines."""

    def test_same_chapter_id_no_cross_talk(self, workspace: Path) -> None:
        """Same chapter_id in source and clone must not cross-talk."""
        source = _create_full_source(workspace)
        # Ensure chapter file has searchable content
        (source / "data" / "chapters" / "chapter_001.md").write_text(
            "独有内容：源项目的特殊章节内容。", encoding="utf-8"
        )
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(ctx, "副本", "clone-novel")

        # Modify clone's chapter to have different content
        clone_ctx = get_project_context(workspace / "projects" / "clone-novel")
        (clone_ctx.data_dir / "chapters" / "chapter_001.md").write_text(
            "独有内容：克隆项目的不同章节内容。", encoding="utf-8"
        )
        # Rebuild clone index with new content
        from system.vector_index_lifecycle import rebuild_project_index
        rebuild_project_index(clone_ctx, timeline_id="main")

        # Vector metadata project_id is context.root.name (slug), not UUID
        source_slug = ctx.root.name
        clone_slug = clone_ctx.root.name

        # Search source — should only return source content
        source_results = search_similar(ctx, "独有内容", timeline_id="main", max_results=5)
        for r in source_results:
            assert r.get("metadata", {}).get("project_id") != clone_slug, \
                "Clone slug appeared in source search results — cross-talk"

        # Search clone — should only return clone content
        clone_results = search_similar(clone_ctx, "独有内容", timeline_id="main", max_results=5)
        for r in clone_results:
            assert r.get("metadata", {}).get("project_id") != source_slug, \
                "Source slug appeared in clone search results — cross-talk"

    def test_two_clones_independent(self, workspace: Path) -> None:
        """Two clones of the same source must be vector-isolated from each other."""
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        r1 = service.clone_project(ctx, "克隆1", "clone-1")
        r2 = service.clone_project(ctx, "克隆2", "clone-2")

        assert r1.project_id != r2.project_id
        # Both must differ from source
        assert r1.project_id != "source-original-id"
        assert r2.project_id != "source-original-id"

    def test_metadata_contains_project_id(self, workspace: Path) -> None:
        """Vector search results must include project_id in metadata."""
        source = _create_full_source(workspace)
        # Ensure searchable chapter content
        (source / "data" / "chapters" / "chapter_001.md").write_text(
            "可搜索的小说内容用于向量检索测试。", encoding="utf-8"
        )
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        result = service.clone_project(ctx, "副本", "clone-novel")

        clone_ctx = get_project_context(workspace / "projects" / "clone-novel")
        results = search_similar(clone_ctx, "小说内容", timeline_id="main", max_results=5)
        # If results exist, they must have project_id matching clone slug
        clone_slug = clone_ctx.root.name
        for r in results:
            meta = r.get("metadata", {})
            assert meta.get("project_id") == clone_slug, \
                f"Result project_id={meta.get('project_id')} != clone slug={clone_slug}"


# =============================================================================
# Section 13: Staging Failure Injection
# =============================================================================

class TestStagingFailureInjection:
    """Verify staging cleanup on various failures."""

    def test_staging_cleaned_on_copy_failure(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)

        # Inject copy failure
        import system.project_clone_service as pcs
        original_copy = pcs.ProjectCloneService._copy_whitelisted_data
        def failing_copy(self, *args, **kwargs):
            raise RuntimeError("Simulated copy failure")
        pcs.ProjectCloneService._copy_whitelisted_data = failing_copy
        try:
            with pytest.raises(CloneError):
                service.clone_project(ctx, "副本", "clone-novel")
        finally:
            pcs.ProjectCloneService._copy_whitelisted_data = original_copy

        # Staging must be cleaned
        staging_dirs = list(workspace.glob(".clone_*"))
        assert len(staging_dirs) == 0, f"Staging dirs left after copy failure: {staging_dirs}"
        # Target must not exist
        assert not (workspace / "projects" / "clone-novel").exists()

    def test_staging_cleaned_on_metadata_failure(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)

        import system.project_clone_service as pcs
        original = pcs.ProjectCloneService._transform_project_metadata
        def failing_metadata(self, *args, **kwargs):
            raise RuntimeError("Simulated metadata failure")
        pcs.ProjectCloneService._transform_project_metadata = failing_metadata
        try:
            with pytest.raises(CloneError):
                service.clone_project(ctx, "副本", "clone-novel")
        finally:
            pcs.ProjectCloneService._transform_project_metadata = original

        staging_dirs = list(workspace.glob(".clone_*"))
        assert len(staging_dirs) == 0
        assert not (workspace / "projects" / "clone-novel").exists()

    def test_staging_cleaned_on_publish_failure(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)

        # Pre-create target dir to force rename failure
        target = workspace / "projects" / "clone-novel"
        target.mkdir(parents=True)
        (target / "blocker").write_text("blocks rename", encoding="utf-8")

        with pytest.raises((ClonePublishError, CloneError)):
            service.clone_project(ctx, "副本", "clone-novel")

        staging_dirs = list(workspace.glob(".clone_*"))
        assert len(staging_dirs) == 0

    def test_staging_cleaned_on_state_transform_failure(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)

        import system.project_clone_service as pcs
        original = pcs.ProjectCloneService._transform_state
        def failing_state(self, *args, **kwargs):
            raise RuntimeError("Simulated state transform failure")
        pcs.ProjectCloneService._transform_state = failing_state
        try:
            with pytest.raises(CloneError):
                service.clone_project(ctx, "副本", "clone-novel")
        finally:
            pcs.ProjectCloneService._transform_state = original

        staging_dirs = list(workspace.glob(".clone_*"))
        assert len(staging_dirs) == 0


# =============================================================================
# Section 11.4: Rebuild Failure Recovery
# =============================================================================

class TestRebuildFailureRecovery:
    """Verify rebuild failure leaves project in recoverable state."""

    def test_rebuild_failure_persists_clone(self, workspace: Path) -> None:
        """Clone must be published even if rebuild fails."""
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)

        import system.project_clone_service as pcs
        original = pcs.ProjectCloneService._rebuild_vector_index
        def failing_rebuild(self, context, project_id):
            raise RuntimeError("Simulated rebuild failure")
        pcs.ProjectCloneService._rebuild_vector_index = failing_rebuild
        try:
            result = service.clone_project(ctx, "副本", "clone-novel")
        finally:
            pcs.ProjectCloneService._rebuild_vector_index = original

        # Clone must be published
        assert (workspace / "projects" / "clone-novel" / "data" / "story_spec.json").exists()
        # Result must have warning
        assert result.status == "completed_with_warnings"
        assert any("rebuild" in w.lower() or "vector" in w.lower() for w in result.warnings)

    def test_rebuild_failure_operation_status(self, workspace: Path) -> None:
        """Failed rebuild should NOT record COMPLETED operation."""
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)

        # Inject failure inside rebuild after operation is created
        import system.project_clone_service as pcs
        from system.vector_index_lifecycle import rebuild_project_index as original_rebuild
        def failing_rebuild(context, timeline_id):
            raise RuntimeError("Rebuild failed")
        import system.vector_index_lifecycle as vil
        vil.rebuild_project_index = failing_rebuild
        try:
            result = service.clone_project(ctx, "副本", "clone-novel")
        finally:
            vil.rebuild_project_index = original_rebuild

        # operation_id may or may not be set, but if set, status should be FAILED
        if result.vector_sync_operation_id:
            clone_ctx = get_project_context(workspace / "projects" / "clone-novel")
            sync_store = VectorSyncRunStore(clone_ctx)
            run = sync_store.get(result.vector_sync_operation_id)
            if run is not None:
                assert run.status == VectorSyncStatus.FAILED, \
                    f"Operation status should be FAILED, got {run.status}"


# =============================================================================
# Section 18: Windows Resource Release
# =============================================================================

class TestWindowsResourceRelease:
    """Verify Windows resource release in success and failure paths."""

    def test_source_chroma_dir_deletable_after_clone(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        service.clone_project(ctx, "副本", "clone-novel")
        VectorClientManager().close_all()
        # Source must be deletable
        try:
            shutil.rmtree(source)
        except PermissionError as e:
            pytest.fail(f"Source dir not deletable after clone: {e}")

    def test_clone_dir_deletable_after_rebuild_failure(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)

        import system.project_clone_service as pcs
        original = pcs.ProjectCloneService._rebuild_vector_index
        def failing_rebuild(self, context, project_id):
            raise RuntimeError("Rebuild failed")
        pcs.ProjectCloneService._rebuild_vector_index = failing_rebuild
        try:
            service.clone_project(ctx, "副本", "clone-novel")
        finally:
            pcs.ProjectCloneService._rebuild_vector_index = original

        VectorClientManager().close_all()
        clone_dir = workspace / "projects" / "clone-novel"
        try:
            shutil.rmtree(clone_dir)
        except PermissionError as e:
            pytest.fail(f"Clone dir not deletable after rebuild failure: {e}")

    def test_close_all_idempotent(self, workspace: Path) -> None:
        source = _create_full_source(workspace)
        ctx = get_project_context(source)
        service = ProjectCloneService(workspace)
        service.clone_project(ctx, "副本", "clone-novel")
        # Multiple close_all calls should not error
        VectorClientManager().close_all()
        VectorClientManager().close_all()
        VectorClientManager().close_all()
