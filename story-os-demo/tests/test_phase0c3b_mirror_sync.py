from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from system.obsidian_binding import BindingStatus, MARKER_FILENAME
from system.obsidian_mirror_manifest import (
    MANIFEST_FILENAME,
    MirrorManifestEntry,
    MirrorManifestStore,
    compute_content_hash,
    build_empty_manifest,
)
from system.obsidian_mirror_sync import (
    MirrorSyncManifestInvalid,
    MirrorSyncManifestMismatch,
    MirrorSyncService,
)


def _make_test_binding(project_id: str, vault_root: Path, target_rel: str):
    """Create a minimal binding object for testing."""
    from system.obsidian_binding import ObsidianBinding
    from datetime import datetime, timezone
    return ObsidianBinding(
        binding_id=f"obs_{uuid.uuid4().hex[:16]}",
        project_id=project_id,
        timeline_id="main",
        vault_root=vault_root,
        target_relative_path=target_rel,
        status=BindingStatus.BOUND,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


class TestManifestModel:
    def test_manifest_identity_validation(self):
        manifest = build_empty_manifest("obs_123", "proj_123", "main")
        assert manifest.validate_identity("obs_123", "proj_123", "main") is True
        assert manifest.validate_identity("obs_456", "proj_123", "main") is False
        assert manifest.validate_identity("obs_123", "proj_456", "main") is False
        assert manifest.validate_identity("obs_123", "proj_123", "experiment") is False

    def test_manifest_store_atomic_write(self):
        tmp_dir = Path(tempfile.mkdtemp())
        store = MirrorManifestStore(tmp_dir)
        manifest = build_empty_manifest("obs_test", "proj_test", "main")
        manifest.files["test.md"] = MirrorManifestEntry(
            source_id="test",
            content_hash="sha256:abc",
            size_bytes=10,
            last_synced_at="2024-01-01T00:00:00Z",
        )
        store.save(manifest)
        loaded = store.load()
        assert loaded is not None
        assert loaded.binding_id == "obs_test"
        assert loaded.files["test.md"].content_hash == "sha256:abc"
        assert (tmp_dir / MANIFEST_FILENAME).exists()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_manifest_store_load_none(self):
        tmp_dir = Path(tempfile.mkdtemp())
        store = MirrorManifestStore(tmp_dir)
        assert store.load() is None
        shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_manifest_store_load_corrupted(self):
        tmp_dir = Path(tempfile.mkdtemp())
        store = MirrorManifestStore(tmp_dir)
        (tmp_dir / MANIFEST_FILENAME).write_text("not json", encoding="utf-8")
        assert store.load() is None
        shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_compute_content_hash(self):
        assert compute_content_hash(b"hello").startswith("sha256:")
        assert compute_content_hash(b"hello") == compute_content_hash(b"hello")
        assert compute_content_hash(b"hello") != compute_content_hash(b"world")


class TestDiffPlan:
    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.project_id = str(uuid.uuid4())
        self.binding = _make_test_binding(
            self.project_id,
            Path(self.temp_vault),
            "StoryOS/test",
        )
        self.data_dir = Path(self.temp_workspace) / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "project.md").write_text("# Test Project", encoding="utf-8")

    def teardown_method(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def test_first_sync_creates_files(self):
        service = MirrorSyncService(self.binding, self.data_dir)
        result = service.run(dry_run=False, prune_stale=False)
        assert result["status"] == "completed"
        assert result["summary"]["create"] > 0
        assert (self.binding.target_full_path / "00_Project" / "Project.md").exists()

    def test_second_sync_unchanged(self):
        service = MirrorSyncService(self.binding, self.data_dir)
        service.run(dry_run=False, prune_stale=False)
        result = service.run(dry_run=False, prune_stale=False)
        assert result["status"] == "completed"
        assert result["summary"]["unchanged"] > 0
        assert result["summary"]["create"] == 0
        assert result["summary"]["update"] == 0

    def test_update_detected(self):
        service = MirrorSyncService(self.binding, self.data_dir)
        service.run(dry_run=False, prune_stale=False)
        (self.data_dir / "project.md").write_text("# Updated Project", encoding="utf-8")
        result = service.run(dry_run=False, prune_stale=False)
        assert result["summary"]["update"] > 0

    def test_dry_run_zero_writes(self):
        service = MirrorSyncService(self.binding, self.data_dir)
        result = service.run(dry_run=True, prune_stale=False)
        assert result["status"] == "dry_run"
        assert not (self.binding.target_full_path / "00_Project" / "Project.md").exists()

    def test_dry_run_detects_create(self):
        service = MirrorSyncService(self.binding, self.data_dir)
        result = service.run(dry_run=True, prune_stale=False)
        assert result["status"] == "dry_run"
        assert result["summary"]["create"] > 0

    def test_stale_file_preserved_without_prune(self):
        service = MirrorSyncService(self.binding, self.data_dir)
        service.run(dry_run=False, prune_stale=False)
        user_file = self.binding.target_full_path / "user_note.md"
        user_file.write_text("user content", encoding="utf-8")
        (self.data_dir / "project.md").unlink()
        result = service.run(dry_run=False, prune_stale=False)
        assert user_file.exists()

    def test_stale_file_not_managed(self):
        service = MirrorSyncService(self.binding, self.data_dir)
        service.run(dry_run=False, prune_stale=False)
        user_file = self.binding.target_full_path / "user_note.md"
        user_file.write_text("user content", encoding="utf-8")
        result = service.run(dry_run=False, prune_stale=False)
        for change in result["changes"]:
            assert "user_note.md" not in change["path"]

    def test_safe_stale_pruned_with_flag(self):
        service = MirrorSyncService(self.binding, self.data_dir)
        service.run(dry_run=False, prune_stale=False)
        (self.data_dir / "project.md").unlink()
        result = service.run(dry_run=False, prune_stale=True)
        assert result["summary"]["stale"] > 0
        assert not (self.binding.target_full_path / "00_Project" / "Project.md").exists()

    def test_modified_stale_not_pruned(self):
        service = MirrorSyncService(self.binding, self.data_dir)
        service.run(dry_run=False, prune_stale=False)
        target_file = self.binding.target_full_path / "00_Project" / "Project.md"
        target_file.write_text("# Modified by user", encoding="utf-8")
        (self.data_dir / "project.md").unlink()
        result = service.run(dry_run=False, prune_stale=True)
        assert result["summary"]["conflict_modified"] > 0
        assert result["summary"]["stale"] == 0
        assert target_file.exists()

    def test_manifest_identity_mismatch_rejected(self):
        service = MirrorSyncService(self.binding, self.data_dir)
        service.run(dry_run=False, prune_stale=False)
        store = MirrorManifestStore(self.binding.target_full_path)
        manifest = store.load()
        manifest.project_id = str(uuid.uuid4())
        store.save(manifest)
        with pytest.raises(MirrorSyncManifestMismatch):
            service.run(dry_run=False, prune_stale=False)

    def test_manifest_schema_unsupported(self):
        service = MirrorSyncService(self.binding, self.data_dir)
        service.run(dry_run=False, prune_stale=False)
        store = MirrorManifestStore(self.binding.target_full_path)
        manifest = store.load()
        manifest.schema_version = "999.0"
        store.save(manifest)
        with pytest.raises(MirrorSyncManifestInvalid):
            service.run(dry_run=False, prune_stale=False)

    def test_manifest_corrupted_rejected(self):
        service = MirrorSyncService(self.binding, self.data_dir)
        service.run(dry_run=False, prune_stale=False)
        manifest_path = self.binding.target_full_path / MANIFEST_FILENAME
        manifest_path.write_text("not json", encoding="utf-8")
        result = service.run(dry_run=False, prune_stale=False)
        assert result["status"] == "completed"

    def test_manifest_preserved_from_prune(self):
        service = MirrorSyncService(self.binding, self.data_dir)
        service.run(dry_run=False, prune_stale=False)
        assert (self.binding.target_full_path / MANIFEST_FILENAME).exists()
        (self.data_dir / "project.md").unlink()
        result = service.run(dry_run=False, prune_stale=True)
        assert (self.binding.target_full_path / MANIFEST_FILENAME).exists()


class TestPartialApplyRecovery:
    """True fault injection: simulate second file write failure during apply."""

    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.project_id = str(uuid.uuid4())
        self.binding = _make_test_binding(
            self.project_id,
            Path(self.temp_vault),
            "StoryOS/test",
        )
        self.data_dir = Path(self.temp_workspace) / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # Create two source files that will both be synced
        (self.data_dir / "project.md").write_text("# Project v1", encoding="utf-8")
        (self.data_dir / "world_bible.md").write_text("# World v1", encoding="utf-8")

    def teardown_method(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def test_partial_apply_failure_does_not_commit_manifest(self):
        """First sync succeeds. Second sync: first file written, second fails, manifest not updated."""
        service = MirrorSyncService(self.binding, self.data_dir)
        # First sync: establish baseline manifest
        service.run(dry_run=False, prune_stale=False)
        store = MirrorManifestStore(self.binding.target_full_path)
        manifest_after_first = store.load()
        assert manifest_after_first is not None

        # Change both source files
        (self.data_dir / "project.md").write_text("# Project v2", encoding="utf-8")
        (self.data_dir / "world_bible.md").write_text("# World v2", encoding="utf-8")

        # Inject failure on second file write
        original_write_bytes = Path.write_bytes
        call_count = [0]

        def failing_write_bytes(self, data):
            call_count[0] += 1
            if call_count[0] >= 2:
                raise IOError("Simulated disk failure on second file")
            return original_write_bytes(self, data)

        # Run second sync with injected failure
        with pytest.raises(IOError):
            with pytest.MonkeyPatch().context() as mp:
                mp.setattr(Path, "write_bytes", failing_write_bytes)
                service.run(dry_run=False, prune_stale=False)

        # Manifest must NOT be updated to v2 hashes
        manifest_after_failure = store.load()
        assert manifest_after_failure is not None
        # Manifest should still have v1 hashes (or not exist, but should exist from first sync)
        assert manifest_after_failure.files["00_Project/Project.md"].content_hash == manifest_after_first.files["00_Project/Project.md"].content_hash

    def test_re_sync_recovers_already_applied_file(self):
        """After partial failure, re-sync should recognize first file as already applied."""
        service = MirrorSyncService(self.binding, self.data_dir)
        service.run(dry_run=False, prune_stale=False)

        # Change both source files
        (self.data_dir / "project.md").write_text("# Project v2", encoding="utf-8")
        (self.data_dir / "world_bible.md").write_text("# World v2", encoding="utf-8")

        # Inject failure on second file write
        original_write_bytes = Path.write_bytes
        call_count = [0]

        def failing_write_bytes(self, data):
            call_count[0] += 1
            if call_count[0] >= 2:
                raise IOError("Simulated disk failure")
            return original_write_bytes(self, data)

        with pytest.raises(IOError):
            with pytest.MonkeyPatch().context() as mp:
                mp.setattr(Path, "write_bytes", failing_write_bytes)
                service.run(dry_run=False, prune_stale=False)

        # Now re-sync without failure
        result = service.run(dry_run=False, prune_stale=False)

        # First file should NOT be conflict - it's already the desired content
        first_file_changes = [c for c in result["changes"] if c["path"] == "00_Project/Project.md"]
        if first_file_changes:
            assert first_file_changes[0]["action"] == "unchanged", f"Expected unchanged, got {first_file_changes[0]}"

        # Second file should be updated
        second_file_changes = [c for c in result["changes"] if c["path"] == "01_World/World_Bible.md"]
        assert len(second_file_changes) == 1
        assert second_file_changes[0]["action"] == "update"

    def test_manifest_converges_after_partial_failure(self):
        """After recovery sync, manifest should record both files' new hashes."""
        service = MirrorSyncService(self.binding, self.data_dir)
        service.run(dry_run=False, prune_stale=False)

        (self.data_dir / "project.md").write_text("# Project v2", encoding="utf-8")
        (self.data_dir / "world_bible.md").write_text("# World v2", encoding="utf-8")

        original_write_bytes = Path.write_bytes
        call_count = [0]

        def failing_write_bytes(self, data):
            call_count[0] += 1
            if call_count[0] >= 2:
                raise IOError("Simulated disk failure")
            return original_write_bytes(self, data)

        with pytest.raises(IOError):
            with pytest.MonkeyPatch().context() as mp:
                mp.setattr(Path, "write_bytes", failing_write_bytes)
                service.run(dry_run=False, prune_stale=False)

        # Recovery sync
        service.run(dry_run=False, prune_stale=False)

        store = MirrorManifestStore(self.binding.target_full_path)
        manifest = store.load()
        assert manifest is not None

        # Verify manifest has v2 hashes
        project_hash = compute_content_hash(b"# Project v2")
        world_hash = compute_content_hash(b"# World v2")
        assert manifest.files["00_Project/Project.md"].content_hash == project_hash
        assert manifest.files["01_World/World_Bible.md"].content_hash == world_hash

    def test_third_sync_is_fully_unchanged(self):
        """After recovery, third sync should be all unchanged."""
        service = MirrorSyncService(self.binding, self.data_dir)
        service.run(dry_run=False, prune_stale=False)

        (self.data_dir / "project.md").write_text("# Project v2", encoding="utf-8")
        (self.data_dir / "world_bible.md").write_text("# World v2", encoding="utf-8")

        original_write_bytes = Path.write_bytes
        call_count = [0]

        def failing_write_bytes(self, data):
            call_count[0] += 1
            if call_count[0] >= 2:
                raise IOError("Simulated disk failure")
            return original_write_bytes(self, data)

        with pytest.raises(IOError):
            with pytest.MonkeyPatch().context() as mp:
                mp.setattr(Path, "write_bytes", failing_write_bytes)
                service.run(dry_run=False, prune_stale=False)

        # Recovery sync
        service.run(dry_run=False, prune_stale=False)

        # Third sync
        result = service.run(dry_run=False, prune_stale=False)
        assert result["summary"]["unchanged"] > 0
        assert result["summary"]["create"] == 0
        assert result["summary"]["update"] == 0
        assert result["summary"]["conflict_modified"] == 0

    def test_true_user_modification_still_conflict(self):
        """Verify that real user modifications are still detected as conflicts after recovery logic."""
        service = MirrorSyncService(self.binding, self.data_dir)
        service.run(dry_run=False, prune_stale=False)

        # Change source
        (self.data_dir / "project.md").write_text("# Project v2", encoding="utf-8")

        # User modifies file to something DIFFERENT from both old and new
        target_file = self.binding.target_full_path / "00_Project" / "Project.md"
        target_file.write_text("# User modified completely", encoding="utf-8")

        result = service.run(dry_run=False, prune_stale=False)
        assert result["summary"]["conflict_modified"] > 0
        # File should NOT be overwritten
        assert target_file.read_text(encoding="utf-8") == "# User modified completely"


class TestFirstSyncCollision:
    """Test behavior when no manifest exists but target already has files."""

    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.project_id = str(uuid.uuid4())
        self.binding = _make_test_binding(
            self.project_id,
            Path(self.temp_vault),
            "StoryOS/test",
        )
        self.data_dir = Path(self.temp_workspace) / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "project.md").write_text("# Test Project", encoding="utf-8")

    def teardown_method(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def test_first_sync_existing_matching_file_safe_takeover(self):
        """If target already has content identical to expected, safe takeover."""
        # Pre-create target with matching content
        target_file = self.binding.target_full_path / "00_Project" / "Project.md"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text("# Test Project", encoding="utf-8")

        service = MirrorSyncService(self.binding, self.data_dir)
        result = service.run(dry_run=False, prune_stale=False)

        # Should be unchanged, not conflict
        project_changes = [c for c in result["changes"] if c["path"] == "00_Project/Project.md"]
        assert len(project_changes) == 1
        assert project_changes[0]["action"] == "unchanged"

        # Manifest should be created
        store = MirrorManifestStore(self.binding.target_full_path)
        manifest = store.load()
        assert manifest is not None
        assert "00_Project/Project.md" in manifest.files

    def test_first_sync_existing_different_file_conflict(self):
        """If target has different content, must report conflict, not overwrite."""
        target_file = self.binding.target_full_path / "00_Project" / "Project.md"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text("# Different existing content", encoding="utf-8")

        service = MirrorSyncService(self.binding, self.data_dir)
        result = service.run(dry_run=False, prune_stale=False)

        project_changes = [c for c in result["changes"] if c["path"] == "00_Project/Project.md"]
        assert len(project_changes) == 1
        assert project_changes[0]["action"] == "conflict_modified"

        # File should NOT be overwritten
        assert target_file.read_text(encoding="utf-8") == "# Different existing content"

        # Manifest should still be created, but without this conflict file
        store = MirrorManifestStore(self.binding.target_full_path)
        manifest = store.load()
        assert manifest is not None
        assert "00_Project/Project.md" not in manifest.files


class TestMultiProjectIsolation:
    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.project_a = str(uuid.uuid4())
        self.project_b = str(uuid.uuid4())

    def teardown_method(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def test_manifests_are_isolated(self):
        data_a = Path(self.temp_workspace) / "data_a"
        data_a.mkdir()
        (data_a / "project.md").write_text("# Project A", encoding="utf-8")
        binding_a = _make_test_binding(self.project_a, Path(self.temp_vault), "StoryOS/project-a")

        data_b = Path(self.temp_workspace) / "data_b"
        data_b.mkdir()
        (data_b / "project.md").write_text("# Project B", encoding="utf-8")
        binding_b = _make_test_binding(self.project_b, Path(self.temp_vault), "StoryOS/project-b")

        svc_a = MirrorSyncService(binding_a, data_a)
        svc_b = MirrorSyncService(binding_b, data_b)

        svc_a.run(dry_run=False, prune_stale=False)
        svc_b.run(dry_run=False, prune_stale=False)

        store_a = MirrorManifestStore(binding_a.target_full_path)
        store_b = MirrorManifestStore(binding_b.target_full_path)

        manifest_a = store_a.load()
        manifest_b = store_b.load()

        assert manifest_a.project_id == self.project_a
        assert manifest_b.project_id == self.project_b
        assert manifest_a.binding_id == binding_a.binding_id
        assert manifest_b.binding_id == binding_b.binding_id


def _make_project_context(project_dir: Path):
    """Build a minimal ProjectContext for a temp project directory."""
    from core.project_context import ProjectContext
    data = project_dir / "data"
    return ProjectContext(
        root=project_dir,
        data_dir=data,
        chapters_dir=data / "chapters",
        drafts_dir=data / "drafts",
        edited_dir=data / "edited",
        manual_dir=data / "manual",
        versions_dir=data / "versions",
        summaries_dir=data / "summaries",
        quality_reports_dir=data / "quality_reports",
        continuity_reports_dir=data / "continuity_reports",
        reviews_dir=data / "reviews",
        todos_dir=data / "todos",
        context_dir=data / "context",
        memory_dir=data / "memory",
        pipeline_runs_dir=data / "pipeline_runs",
        jobs_dir=data / "jobs",
        archive_dir=data / "archive",
        logs_dir=project_dir / "logs",
        config_dir=project_dir / ".story_os",
        legacy_chapters_dir=project_dir / "chapters",
        narrative_memory_dir=data / "narrative_memory",
        narrative_events_dir=data / "narrative_memory" / "events",
        narrative_state_dir=data / "narrative_memory" / "state",
        narrative_snapshots_dir=data / "narrative_memory" / "snapshots",
        model_runs_dir=data / "model_runs",
        model_preferences_path=data / "model_preferences.json",
        model_cost_limits_path=data / "model_cost_limits.json",
        agents_dir=data / "agents",
        agent_runs_dir=data / "agents" / "runs",
        agent_workflows_dir=data / "agents" / "workflows",
        creative_loop_dir=data / "creative_loop",
        reflections_dir=data / "creative_loop" / "reflections",
        creative_health_dir=data / "creative_loop" / "health",
        creative_issues_dir=data / "creative_loop" / "issues",
        creative_proposals_dir=data / "creative_loop" / "proposals",
        creative_experiments_dir=data / "creative_loop" / "experiments",
        creative_patterns_dir=data / "creative_loop" / "patterns",
        creative_evolution_dir=data / "creative_loop" / "evolution",
        creative_outcomes_dir=data / "creative_loop" / "outcomes",
        creative_events_dir=data / "creative_loop" / "events",
        creative_audit_dir=data / "creative_loop" / "audit",
        planning_control_dir=data / "planning_control",
        planning_strategy_path=data / "planning_control" / "strategy.json",
        planning_milestones_path=data / "planning_control" / "milestones.json",
        volume_contracts_path=data / "planning_control" / "volume_contracts.json",
        phase_contracts_path=data / "planning_control" / "phase_contracts.json",
        planning_locks_path=data / "planning_control" / "locks.json",
        planning_conflicts_path=data / "planning_control" / "conflicts.json",
        planning_metadata_path=data / "planning_control" / "metadata.json",
        planning_control_versions_dir=data / "planning_control" / "versions",
        rolling_window_path=data / "planning_control" / "rolling_window.json",
        planning_dependencies_path=data / "planning_control" / "dependencies.json",
        planning_schedules_path=data / "planning_control" / "schedules.json",
    )


class TestWebAPIMirrorSync:
    """Real FastAPI TestClient HTTP tests for sync-obsidian endpoint."""

    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.project_id = str(uuid.uuid4())

        workspace = Path(self.temp_workspace)
        self.project_dir = workspace / "projects" / self.project_id
        self.project_dir.mkdir(parents=True)
        self.data_dir = self.project_dir / "data"
        self.data_dir.mkdir()
        (self.data_dir / "story_spec.json").write_text('{"title": "Test"}', encoding="utf-8")
        (self.data_dir / "project.md").write_text("# Test Project", encoding="utf-8")

        # Create binding
        target_dir = Path(self.temp_vault) / "StoryOS" / "test"
        target_dir.mkdir(parents=True)
        from system.obsidian_binding import ObsidianBinding, BindingStatus, BindingMarker
        from system.obsidian_binding_store import ObsidianBindingStore
        from datetime import datetime, timezone
        self.binding = ObsidianBinding(
            binding_id=f"obs_{uuid.uuid4().hex[:16]}",
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/test",
            status=BindingStatus.BOUND,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        store = ObsidianBindingStore(workspace)
        store.save(self.binding)

        marker = BindingMarker(
            project_id=self.project_id,
            timeline_id="main",
            binding_id=self.binding.binding_id,
        )
        (target_dir / MARKER_FILENAME).write_text(json.dumps(marker.to_dict()), encoding="utf-8")

        self.workspace = workspace

    def teardown_method(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def _mock_context(self, monkeypatch):
        ctx = _make_project_context(self.project_dir)
        monkeypatch.setattr("commands.get_project_context", lambda project_root=None: ctx)
        monkeypatch.setattr("core.project.resolve_workspace_root", lambda project_root=None: self.workspace)

    def _client(self):
        from fastapi import FastAPI
        from web.routes import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_api_dry_run(self, monkeypatch):
        client = self._client()
        self._mock_context(monkeypatch)

        response = client.post("/api/sync-obsidian", json={"dry_run": True, "prune_stale": False})
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["result"]["status"] == "dry_run"
        assert data["result"]["summary"]["create"] > 0

        # No files should be written
        target_dir = Path(self.temp_vault) / "StoryOS" / "test"
        assert not (target_dir / "00_Project" / "Project.md").exists()

    def test_api_normal_sync(self, monkeypatch):
        client = self._client()
        self._mock_context(monkeypatch)

        response = client.post("/api/sync-obsidian", json={"dry_run": False, "prune_stale": False})
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["result"]["status"] == "completed"
        assert data["result"]["summary"]["create"] > 0

        target_dir = Path(self.temp_vault) / "StoryOS" / "test"
        assert (target_dir / "00_Project" / "Project.md").exists()
        assert (target_dir / MANIFEST_FILENAME).exists()

    def test_api_prune_stale(self, monkeypatch):
        client = self._client()
        self._mock_context(monkeypatch)

        # First sync
        client.post("/api/sync-obsidian", json={"dry_run": False, "prune_stale": False})

        # Remove source to create stale
        (self.data_dir / "project.md").unlink()

        response = client.post("/api/sync-obsidian", json={"dry_run": False, "prune_stale": True})
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["result"]["status"] == "completed"
        assert data["result"]["summary"]["stale"] > 0

        target_dir = Path(self.temp_vault) / "StoryOS" / "test"
        assert not (target_dir / "00_Project" / "Project.md").exists()
        assert (target_dir / MANIFEST_FILENAME).exists()

    def test_api_unbound_returns_error(self, monkeypatch):
        client = self._client()

        # Use an unbound workspace
        unbound_workspace = Path(tempfile.mkdtemp())
        try:
            unbound_project = unbound_workspace / "projects" / self.project_id
            unbound_project.mkdir(parents=True)
            (unbound_project / "data").mkdir(parents=True, exist_ok=True)
            (unbound_project / "data" / "story_spec.json").write_text('{}', encoding="utf-8")

            ctx = _make_project_context(unbound_project)
            monkeypatch.setattr("commands.get_project_context", lambda project_root=None: ctx)
            monkeypatch.setattr("core.project.resolve_workspace_root", lambda project_root=None: unbound_workspace)

            response = client.post("/api/sync-obsidian", json={"dry_run": False, "prune_stale": False})
            assert response.status_code == 200
            data = response.json()
            assert data["ok"] is False
            assert "OBSIDIAN_NOT_BOUND" in data.get("code", "") or "未绑定" in data.get("message", "")
        finally:
            shutil.rmtree(unbound_workspace, ignore_errors=True)

    def test_api_manifest_identity_mismatch(self, monkeypatch):
        client = self._client()
        self._mock_context(monkeypatch)

        # First sync to create manifest
        client.post("/api/sync-obsidian", json={"dry_run": False, "prune_stale": False})

        # Corrupt manifest identity
        target_dir = Path(self.temp_vault) / "StoryOS" / "test"
        store = MirrorManifestStore(target_dir)
        manifest = store.load()
        manifest.project_id = str(uuid.uuid4())
        store.save(manifest)

        response = client.post("/api/sync-obsidian", json={"dry_run": False, "prune_stale": False})
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert "identity" in data.get("message", "").lower() or "mismatch" in data.get("message", "").lower() or "不匹配" in data.get("message", "")

    def test_api_manifest_schema_unsupported(self, monkeypatch):
        client = self._client()
        self._mock_context(monkeypatch)

        # First sync to create manifest
        client.post("/api/sync-obsidian", json={"dry_run": False, "prune_stale": False})

        target_dir = Path(self.temp_vault) / "StoryOS" / "test"
        store = MirrorManifestStore(target_dir)
        manifest = store.load()
        manifest.schema_version = "999.0"
        store.save(manifest)

        response = client.post("/api/sync-obsidian", json={"dry_run": False, "prune_stale": False})
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert "schema" in data.get("message", "").lower() or "版本" in data.get("message", "")

    def test_api_path_safety_failure(self, monkeypatch):
        client = self._client()
        self._mock_context(monkeypatch)

        # Patch _apply to simulate a path safety exception mid-sync
        def _fake_apply(self, plan, expected, *, prune_stale):
            raise MirrorSyncUnsafe("Simulated path safety failure")

        monkeypatch.setattr("system.obsidian_mirror_sync.MirrorSyncService._apply", _fake_apply)

        response = client.post("/api/sync-obsidian", json={"dry_run": False, "prune_stale": False})
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert "path" in data.get("message", "").lower() or "unsafe" in data.get("message", "").lower() or "路径" in data.get("message", "")


class TestCLIMirrorSync:
    """Real subprocess CLI tests for sync-obsidian."""

    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.project_id = str(uuid.uuid4())

        workspace = Path(self.temp_workspace)
        self.project_dir = workspace / "projects" / self.project_id
        self.project_dir.mkdir(parents=True)
        data_dir = self.project_dir / "data"
        data_dir.mkdir()
        (data_dir / "story_spec.json").write_text('{"title": "Test"}', encoding="utf-8")
        (data_dir / "project.md").write_text("# Test Project", encoding="utf-8")

        # Create workspace marker
        (workspace / ".story_os").mkdir()

        # Create binding
        from system.obsidian_binding_service import ObsidianBindingService
        service = ObsidianBindingService(workspace)
        service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/test",
        )

        self.main_py = Path(os.getcwd()) / "main.py"

    def teardown_method(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def _run_cli(self, args: list[str]) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [sys.executable, str(self.main_py)] + args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(self.project_dir),
            env=env,
        )

    def test_cli_dry_run_bound_project(self):
        result = self._run_cli(["sync-obsidian", "--dry-run"])
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "预览" in result.stdout or "dry_run" in result.stdout or "同步" in result.stdout
        assert "Traceback" not in result.stderr

        # Dry-run must not create mirror files
        target_dir = Path(self.temp_vault) / "StoryOS" / "test"
        assert not (target_dir / "00_Project" / "Project.md").exists()

    def test_cli_sync_creates_files_and_manifest(self):
        result = self._run_cli(["sync-obsidian"])
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "同步完成" in result.stdout or "completed" in result.stdout
        assert "Traceback" not in result.stderr

        target_dir = Path(self.temp_vault) / "StoryOS" / "test"
        assert (target_dir / "00_Project" / "Project.md").exists()
        assert (target_dir / MANIFEST_FILENAME).exists()

    def test_cli_prune_stale(self):
        # First sync
        self._run_cli(["sync-obsidian"])

        # Remove source to create stale
        (self.project_dir / "data" / "project.md").unlink()

        result = self._run_cli(["sync-obsidian", "--prune-stale"])
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Traceback" not in result.stderr

        target_dir = Path(self.temp_vault) / "StoryOS" / "test"
        assert not (target_dir / "00_Project" / "Project.md").exists()
        # Marker and manifest must survive prune
        assert (target_dir / MARKER_FILENAME).exists()
        assert (target_dir / MANIFEST_FILENAME).exists()

    def test_cli_dry_run_unbound_project(self):
        # Run from a project without binding
        empty_workspace = Path(tempfile.mkdtemp())
        try:
            empty_project = empty_workspace / "projects" / "unbound"
            empty_project.mkdir(parents=True)
            (empty_project / "data").mkdir(parents=True, exist_ok=True)
            (empty_project / "data" / "story_spec.json").write_text('{}', encoding="utf-8")
            (empty_workspace / ".story_os").mkdir()

            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            result = subprocess.run(
                [sys.executable, str(self.main_py), "sync-obsidian", "--dry-run"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(empty_project),
                env=env,
            )
            assert result.returncode == 1
            assert "未绑定" in result.stdout or "OBSIDIAN_NOT_BOUND" in result.stdout
            assert "Traceback" not in result.stderr
        finally:
            shutil.rmtree(str(empty_workspace), ignore_errors=True)

    def test_cli_help_flags(self):
        result = subprocess.run(
            [sys.executable, str(self.main_py), "sync-obsidian", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        assert result.returncode == 0
        assert "--dry-run" in result.stdout
        assert "--prune-stale" in result.stdout


class TestFailureRecovery:
    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.project_id = str(uuid.uuid4())
        self.binding = _make_test_binding(
            self.project_id,
            Path(self.temp_vault),
            "StoryOS/test",
        )
        self.data_dir = Path(self.temp_workspace) / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "project.md").write_text("# Test Project", encoding="utf-8")

    def teardown_method(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def test_re_sync_after_partial_failure(self):
        service = MirrorSyncService(self.binding, self.data_dir)
        service.run(dry_run=False, prune_stale=False)
        target_file = self.binding.target_full_path / "00_Project" / "Project.md"
        target_file.write_text("# User modified", encoding="utf-8")
        result = service.run(dry_run=False, prune_stale=False)
        assert result["summary"]["conflict_modified"] > 0
        result2 = service.run(dry_run=False, prune_stale=False)
        assert result2["summary"]["conflict_modified"] > 0

    def test_manifest_updated_on_success(self):
        service = MirrorSyncService(self.binding, self.data_dir)
        service.run(dry_run=False, prune_stale=False)
        store = MirrorManifestStore(self.binding.target_full_path)
        manifest = store.load()
        assert manifest is not None
        assert "00_Project/Project.md" in manifest.files

    def test_manifest_not_updated_on_dry_run(self):
        service = MirrorSyncService(self.binding, self.data_dir)
        service.run(dry_run=False, prune_stale=False)
        store = MirrorManifestStore(self.binding.target_full_path)
        manifest_before = store.load()
        old_generated_at = manifest_before.generated_at

        (self.data_dir / "project.md").write_text("# Changed", encoding="utf-8")
        service.run(dry_run=True, prune_stale=False)
        manifest_after = store.load()
        assert manifest_after.generated_at == old_generated_at
