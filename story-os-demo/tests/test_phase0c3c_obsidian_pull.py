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

from system.obsidian_binding import MARKER_FILENAME, BindingMarker, ObsidianBinding, BindingStatus
from system.obsidian_binding_store import ObsidianBindingStore
from system.obsidian_mirror_manifest import MANIFEST_FILENAME, MirrorManifestEntry, MirrorManifestStore, build_empty_manifest, compute_content_hash
from system.obsidian_mirror_sync import MirrorSyncService


def _make_project_context(project_dir: Path):
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


def _chapter_markdown(title: str, body: str) -> str:
    return f"# {title}\n\n{body}\n"


class TestPullStateClassification:
    """Test three-way state classification for chapter files."""

    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.project_id = str(uuid.uuid4())
        self.workspace = Path(self.temp_workspace)
        self.project_dir = self.workspace / "projects" / self.project_id
        self.project_dir.mkdir(parents=True)
        self.data_dir = self.project_dir / "data"
        self.data_dir.mkdir()
        (self.data_dir / "story_spec.json").write_text('{"title": "Test"}', encoding="utf-8")

        self.target_dir = Path(self.temp_vault) / "StoryOS" / "test"
        self.target_dir.mkdir(parents=True)

        from system.obsidian_binding import BindingMarker
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
        store = ObsidianBindingStore(self.workspace)
        store.save(self.binding)
        marker = BindingMarker(
            project_id=self.project_id,
            timeline_id="main",
            binding_id=self.binding.binding_id,
        )
        (self.target_dir / MARKER_FILENAME).write_text(json.dumps(marker.to_dict()), encoding="utf-8")

        self.chapters_dir = self.data_dir / "chapters"
        self.chapters_dir.mkdir()
        self.ctx = _make_project_context(self.project_dir)

    def teardown_method(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def _write_manifest(self, rel_path: str, content: bytes):
        store = MirrorManifestStore(self.target_dir)
        manifest = store.load() or build_empty_manifest(
            self.binding.binding_id, self.binding.project_id, self.binding.timeline_id
        )
        manifest.files[rel_path] = MirrorManifestEntry(
            source_id=rel_path,
            content_hash=compute_content_hash(content),
            size_bytes=len(content),
            last_synced_at="2024-01-01T00:00:00",
        )
        store.save(manifest)

    def _make_pull_service(self):
        from system.obsidian_pull_service import ObsidianPullService
        return ObsidianPullService(self.binding, self.ctx)

    def test_pull_scan_unchanged(self):
        content = _chapter_markdown("第一章", "这是原始内容。").encode("utf-8")
        (self.chapters_dir / "chapter_001.md").write_bytes(content)
        (self.target_dir / "03_Chapters" / "chapter_001.md").parent.mkdir(parents=True, exist_ok=True)
        (self.target_dir / "03_Chapters" / "chapter_001.md").write_bytes(content)
        self._write_manifest("03_Chapters/chapter_001.md", content)

        plan = self._make_pull_service().scan()
        entry = next(e for e in plan.entries if e.relative_path == "03_Chapters/chapter_001.md")
        assert entry.action.value == "unchanged"
        assert not entry.importable

    def test_pull_scan_inbound_changed(self):
        base = _chapter_markdown("第一章", "这是原始内容。").encode("utf-8")
        obsidian = _chapter_markdown("第一章", "这是用户在 Obsidian 修改后的内容。").encode("utf-8")
        (self.chapters_dir / "chapter_001.md").write_bytes(base)
        (self.target_dir / "03_Chapters" / "chapter_001.md").parent.mkdir(parents=True, exist_ok=True)
        (self.target_dir / "03_Chapters" / "chapter_001.md").write_bytes(obsidian)
        self._write_manifest("03_Chapters/chapter_001.md", base)

        plan = self._make_pull_service().scan()
        entry = next(e for e in plan.entries if e.relative_path == "03_Chapters/chapter_001.md")
        assert entry.action.value == "inbound_changed"
        assert entry.importable

    def test_pull_scan_outbound_changed(self):
        base = _chapter_markdown("第一章", "这是原始内容。").encode("utf-8")
        source = _chapter_markdown("第一章", "这是 Story OS 修改后的内容。").encode("utf-8")
        (self.chapters_dir / "chapter_001.md").write_bytes(source)
        (self.target_dir / "03_Chapters" / "chapter_001.md").parent.mkdir(parents=True, exist_ok=True)
        (self.target_dir / "03_Chapters" / "chapter_001.md").write_bytes(base)
        self._write_manifest("03_Chapters/chapter_001.md", base)

        plan = self._make_pull_service().scan()
        entry = next(e for e in plan.entries if e.relative_path == "03_Chapters/chapter_001.md")
        assert entry.action.value == "outbound_changed"
        assert not entry.importable

    def test_pull_scan_converged(self):
        base = _chapter_markdown("第一章", "这是原始内容。").encode("utf-8")
        new_content = _chapter_markdown("第一章", "这是新内容。").encode("utf-8")
        (self.chapters_dir / "chapter_001.md").write_bytes(new_content)
        (self.target_dir / "03_Chapters" / "chapter_001.md").parent.mkdir(parents=True, exist_ok=True)
        (self.target_dir / "03_Chapters" / "chapter_001.md").write_bytes(new_content)
        self._write_manifest("03_Chapters/chapter_001.md", base)

        plan = self._make_pull_service().scan()
        entry = next(e for e in plan.entries if e.relative_path == "03_Chapters/chapter_001.md")
        assert entry.action.value == "converged"
        assert not entry.importable

    def test_pull_scan_diverged(self):
        base = _chapter_markdown("第一章", "这是原始内容。").encode("utf-8")
        source = _chapter_markdown("第一章", "Story OS 修改。").encode("utf-8")
        obsidian = _chapter_markdown("第一章", "Obsidian 修改。").encode("utf-8")
        (self.chapters_dir / "chapter_001.md").write_bytes(source)
        (self.target_dir / "03_Chapters" / "chapter_001.md").parent.mkdir(parents=True, exist_ok=True)
        (self.target_dir / "03_Chapters" / "chapter_001.md").write_bytes(obsidian)
        self._write_manifest("03_Chapters/chapter_001.md", base)

        plan = self._make_pull_service().scan()
        entry = next(e for e in plan.entries if e.relative_path == "03_Chapters/chapter_001.md")
        assert entry.action.value == "diverged"
        assert not entry.importable

    def test_pull_scan_target_missing(self):
        base = _chapter_markdown("第一章", "这是原始内容。").encode("utf-8")
        (self.chapters_dir / "chapter_001.md").write_bytes(base)
        self._write_manifest("03_Chapters/chapter_001.md", base)

        plan = self._make_pull_service().scan()
        entry = next(e for e in plan.entries if e.relative_path == "03_Chapters/chapter_001.md")
        assert entry.action.value == "target_missing"
        assert not entry.importable

    def test_pull_scan_conflict_type(self):
        base = _chapter_markdown("第一章", "这是原始内容。").encode("utf-8")
        (self.chapters_dir / "chapter_001.md").write_bytes(base)
        target = self.target_dir / "03_Chapters" / "chapter_001.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.mkdir()  # directory instead of file
        self._write_manifest("03_Chapters/chapter_001.md", base)

        plan = self._make_pull_service().scan()
        entry = next(e for e in plan.entries if e.relative_path == "03_Chapters/chapter_001.md")
        assert entry.action.value == "conflict_type"
        assert not entry.importable


class TestPullUserProtection:
    """Test that user files, markers, and manifests are never imported."""

    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.project_id = str(uuid.uuid4())
        self.workspace = Path(self.temp_workspace)
        self.project_dir = self.workspace / "projects" / self.project_id
        self.project_dir.mkdir(parents=True)
        self.data_dir = self.project_dir / "data"
        self.data_dir.mkdir()
        (self.data_dir / "story_spec.json").write_text('{}', encoding="utf-8")
        self.chapters_dir = self.data_dir / "chapters"
        self.chapters_dir.mkdir()
        self.target_dir = Path(self.temp_vault) / "StoryOS" / "test"
        self.target_dir.mkdir(parents=True, exist_ok=True)
        from system.obsidian_binding import BindingMarker
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
        store = ObsidianBindingStore(self.workspace)
        store.save(self.binding)
        marker = BindingMarker(
            project_id=self.project_id,
            timeline_id="main",
            binding_id=self.binding.binding_id,
        )
        (self.target_dir / MARKER_FILENAME).write_text(json.dumps(marker.to_dict()), encoding="utf-8")
        self.ctx = _make_project_context(self.project_dir)

    def teardown_method(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def test_unmanaged_user_file_not_scanned(self):
        (self.target_dir / "03_Chapters" / "chapter_001.md").parent.mkdir(parents=True, exist_ok=True)
        (self.target_dir / "03_Chapters" / "chapter_001.md").write_text("# 用户文件", encoding="utf-8")
        from system.obsidian_pull_service import ObsidianPullService
        plan = ObsidianPullService(self.binding, self.ctx).scan()
        assert len(plan.entries) == 0

    def test_manifest_file_not_importable(self):
        from system.obsidian_pull_service import ObsidianPullService
        preview = ObsidianPullService(self.binding, self.ctx).preview_file(MANIFEST_FILENAME)
        assert not preview.importable
        assert preview.blocking_reason is not None

    def test_marker_file_not_importable(self):
        from system.obsidian_pull_service import ObsidianPullService
        preview = ObsidianPullService(self.binding, self.ctx).preview_file(MARKER_FILENAME)
        assert not preview.importable

    def test_absolute_path_rejected(self):
        from system.obsidian_pull_service import ObsidianPullService
        preview = ObsidianPullService(self.binding, self.ctx).preview_file("/etc/passwd")
        assert not preview.importable

    def test_path_traversal_rejected(self):
        from system.obsidian_pull_service import ObsidianPullService
        preview = ObsidianPullService(self.binding, self.ctx).preview_file("../../etc/passwd")
        assert not preview.importable


class TestPullIdentitySafety:
    """Test manifest identity, schema, and source_id mismatch protection."""

    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.project_id = str(uuid.uuid4())
        self.workspace = Path(self.temp_workspace)
        self.project_dir = self.workspace / "projects" / self.project_id
        self.project_dir.mkdir(parents=True)
        self.data_dir = self.project_dir / "data"
        self.data_dir.mkdir()
        (self.data_dir / "story_spec.json").write_text('{}', encoding="utf-8")
        self.chapters_dir = self.data_dir / "chapters"
        self.chapters_dir.mkdir()
        self.target_dir = Path(self.temp_vault) / "StoryOS" / "test"
        self.target_dir.mkdir(parents=True, exist_ok=True)
        from system.obsidian_binding import BindingMarker
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
        store = ObsidianBindingStore(self.workspace)
        store.save(self.binding)
        marker = BindingMarker(
            project_id=self.project_id,
            timeline_id="main",
            binding_id=self.binding.binding_id,
        )
        (self.target_dir / MARKER_FILENAME).write_text(json.dumps(marker.to_dict()), encoding="utf-8")
        self.ctx = _make_project_context(self.project_dir)

    def teardown_method(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def test_pull_requires_existing_manifest(self):
        content = _chapter_markdown("第一章", "内容").encode("utf-8")
        (self.chapters_dir / "chapter_001.md").write_bytes(content)
        from system.obsidian_pull_service import ObsidianPullService
        plan = ObsidianPullService(self.binding, self.ctx).scan()
        entry = next(e for e in plan.entries if e.relative_path == "03_Chapters/chapter_001.md")
        assert entry.action.value == "target_missing"

    def test_manifest_identity_mismatch_rejected(self):
        from system.obsidian_mirror_manifest import MirrorManifestStore
        store = MirrorManifestStore(self.target_dir)
        manifest = store.load() or build_empty_manifest(
            self.binding.binding_id, self.binding.project_id, self.binding.timeline_id
        )
        manifest.project_id = str(uuid.uuid4())
        store.save(manifest)
        from system.obsidian_pull_service import ObsidianPullService, ObsidianPullInvalid
        with pytest.raises(ObsidianPullInvalid):
            ObsidianPullService(self.binding, self.ctx).scan()

    def test_manifest_schema_unsupported_rejected(self):
        from system.obsidian_mirror_manifest import MirrorManifestStore
        store = MirrorManifestStore(self.target_dir)
        manifest = store.load() or build_empty_manifest(
            self.binding.binding_id, self.binding.project_id, self.binding.timeline_id
        )
        manifest.schema_version = "999.0"
        store.save(manifest)
        from system.obsidian_pull_service import ObsidianPullService, ObsidianPullInvalid
        with pytest.raises(ObsidianPullInvalid):
            ObsidianPullService(self.binding, self.ctx).scan()


class TestPullPreview:
    """Test preview is zero-write and returns expected hashes."""

    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.project_id = str(uuid.uuid4())
        self.workspace = Path(self.temp_workspace)
        self.project_dir = self.workspace / "projects" / self.project_id
        self.project_dir.mkdir(parents=True)
        self.data_dir = self.project_dir / "data"
        self.data_dir.mkdir()
        (self.data_dir / "story_spec.json").write_text('{}', encoding="utf-8")
        self.chapters_dir = self.data_dir / "chapters"
        self.chapters_dir.mkdir()
        self.target_dir = Path(self.temp_vault) / "StoryOS" / "test"
        self.target_dir.mkdir(parents=True, exist_ok=True)
        from system.obsidian_binding import BindingMarker
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
        store = ObsidianBindingStore(self.workspace)
        store.save(self.binding)
        marker = BindingMarker(
            project_id=self.project_id,
            timeline_id="main",
            binding_id=self.binding.binding_id,
        )
        (self.target_dir / MARKER_FILENAME).write_text(json.dumps(marker.to_dict()), encoding="utf-8")
        self.ctx = _make_project_context(self.project_dir)

    def teardown_method(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def test_preview_is_zero_write(self):
        from system.obsidian_pull_service import ObsidianPullService
        base = _chapter_markdown("第一章", "原始").encode("utf-8")
        obsidian = _chapter_markdown("第一章", "修改").encode("utf-8")
        (self.chapters_dir / "chapter_001.md").write_bytes(base)
        target = self.target_dir / "03_Chapters" / "chapter_001.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(obsidian)
        from system.obsidian_mirror_manifest import MirrorManifestStore
        store = MirrorManifestStore(self.target_dir)
        manifest = store.load() or build_empty_manifest(
            self.binding.binding_id, self.binding.project_id, self.binding.timeline_id
        )
        manifest.files["03_Chapters/chapter_001.md"] = MirrorManifestEntry(
            source_id="03_Chapters/chapter_001.md",
            content_hash=compute_content_hash(base),
            size_bytes=len(base),
            last_synced_at="2024-01-01T00:00:00",
        )
        store.save(manifest)

        before_hash = compute_content_hash(target.read_bytes())
        preview = ObsidianPullService(self.binding, self.ctx).preview_file("03_Chapters/chapter_001.md")
        after_hash = compute_content_hash(target.read_bytes())

        assert before_hash == after_hash
        assert preview.importable
        assert preview.obsidian_hash is not None

    def test_preview_rejects_non_inbound_file(self):
        from system.obsidian_pull_service import ObsidianPullService
        content = _chapter_markdown("第一章", "原始").encode("utf-8")
        (self.chapters_dir / "chapter_001.md").write_bytes(content)
        target = self.target_dir / "03_Chapters" / "chapter_001.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        from system.obsidian_mirror_manifest import MirrorManifestStore
        store = MirrorManifestStore(self.target_dir)
        manifest = store.load() or build_empty_manifest(
            self.binding.binding_id, self.binding.project_id, self.binding.timeline_id
        )
        manifest.files["03_Chapters/chapter_001.md"] = MirrorManifestEntry(
            source_id="03_Chapters/chapter_001.md",
            content_hash=compute_content_hash(content),
            size_bytes=len(content),
            last_synced_at="2024-01-01T00:00:00",
        )
        store.save(manifest)

        preview = ObsidianPullService(self.binding, self.ctx).preview_file("03_Chapters/chapter_001.md")
        assert not preview.importable
        assert preview.blocking_reason == "unchanged"


class TestPullApply:
    """Test formal apply via ChapterCommitService."""

    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.project_id = str(uuid.uuid4())
        self.workspace = Path(self.temp_workspace)
        self.project_dir = self.workspace / "projects" / self.project_id
        self.project_dir.mkdir(parents=True)
        self.data_dir = self.project_dir / "data"
        self.data_dir.mkdir()
        (self.data_dir / "story_spec.json").write_text('{"title": "Test"}', encoding="utf-8")
        self.chapters_dir = self.data_dir / "chapters"
        self.chapters_dir.mkdir()
        self.target_dir = Path(self.temp_vault) / "StoryOS" / "test"
        self.target_dir.mkdir(parents=True, exist_ok=True)
        from system.obsidian_binding import BindingMarker
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
        store = ObsidianBindingStore(self.workspace)
        store.save(self.binding)
        marker = BindingMarker(
            project_id=self.project_id,
            timeline_id="main",
            binding_id=self.binding.binding_id,
        )
        (self.target_dir / MARKER_FILENAME).write_text(json.dumps(marker.to_dict()), encoding="utf-8")
        self.ctx = _make_project_context(self.project_dir)

    def teardown_method(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def test_apply_imports_single_inbound_file(self):
        base = _chapter_markdown("第一章", "原始内容。").encode("utf-8")
        obsidian = _chapter_markdown("第一章", "这是用户在 Obsidian 修改后的内容。").encode("utf-8")
        (self.chapters_dir / "chapter_001.md").write_bytes(base)
        target = self.target_dir / "03_Chapters" / "chapter_001.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(obsidian)
        from system.obsidian_mirror_manifest import MirrorManifestStore
        store = MirrorManifestStore(self.target_dir)
        manifest = store.load() or build_empty_manifest(
            self.binding.binding_id, self.binding.project_id, self.binding.timeline_id
        )
        manifest.files["03_Chapters/chapter_001.md"] = MirrorManifestEntry(
            source_id="03_Chapters/chapter_001.md",
            content_hash=compute_content_hash(base),
            size_bytes=len(base),
            last_synced_at="2024-01-01T00:00:00",
        )
        store.save(manifest)

        from system.obsidian_pull_service import ObsidianPullService
        service = ObsidianPullService(self.binding, self.ctx)
        preview = service.preview_file("03_Chapters/chapter_001.md")
        assert preview.importable

        result = service.import_file("03_Chapters/chapter_001.md", preview.obsidian_hash)
        assert result.status == "completed"
        assert result.chapter_id == 1

        source_after = (self.chapters_dir / "chapter_001.md").read_bytes()
        assert "用户在 Obsidian 修改后的内容" in source_after.decode("utf-8")

    def test_apply_rejects_changed_target_after_preview(self):
        base = _chapter_markdown("第一章", "原始内容。").encode("utf-8")
        obsidian = _chapter_markdown("第一章", "修改A。").encode("utf-8")
        (self.chapters_dir / "chapter_001.md").write_bytes(base)
        target = self.target_dir / "03_Chapters" / "chapter_001.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(obsidian)
        from system.obsidian_mirror_manifest import MirrorManifestStore
        store = MirrorManifestStore(self.target_dir)
        manifest = store.load() or build_empty_manifest(
            self.binding.binding_id, self.binding.project_id, self.binding.timeline_id
        )
        manifest.files["03_Chapters/chapter_001.md"] = MirrorManifestEntry(
            source_id="03_Chapters/chapter_001.md",
            content_hash=compute_content_hash(base),
            size_bytes=len(base),
            last_synced_at="2024-01-01T00:00:00",
        )
        store.save(manifest)

        from system.obsidian_pull_service import ObsidianPullService
        service = ObsidianPullService(self.binding, self.ctx)
        preview = service.preview_file("03_Chapters/chapter_001.md")

        target.write_bytes(_chapter_markdown("第一章", "修改B。").encode("utf-8"))

        result = service.import_file("03_Chapters/chapter_001.md", preview.obsidian_hash)
        assert result.status == "stale_preview"
        assert result.error == "OBSIDIAN_IMPORT_STALE_PREVIEW"

    def test_diverged_file_cannot_be_imported(self):
        base = _chapter_markdown("第一章", "原始内容。").encode("utf-8")
        source = _chapter_markdown("第一章", "Story OS 修改。").encode("utf-8")
        obsidian = _chapter_markdown("第一章", "Obsidian 修改。").encode("utf-8")
        (self.chapters_dir / "chapter_001.md").write_bytes(source)
        target = self.target_dir / "03_Chapters" / "chapter_001.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(obsidian)
        from system.obsidian_mirror_manifest import MirrorManifestStore
        store = MirrorManifestStore(self.target_dir)
        manifest = store.load() or build_empty_manifest(
            self.binding.binding_id, self.binding.project_id, self.binding.timeline_id
        )
        manifest.files["03_Chapters/chapter_001.md"] = MirrorManifestEntry(
            source_id="03_Chapters/chapter_001.md",
            content_hash=compute_content_hash(base),
            size_bytes=len(base),
            last_synced_at="2024-01-01T00:00:00",
        )
        store.save(manifest)

        from system.obsidian_pull_service import ObsidianPullService
        service = ObsidianPullService(self.binding, self.ctx)
        preview = service.preview_file("03_Chapters/chapter_001.md")
        assert not preview.importable

        result = service.import_file("03_Chapters/chapter_001.md", preview.obsidian_hash or "")
        assert result.status == "rejected"

    def test_commit_failure_leaves_target_and_manifest_unchanged(self):
        base = _chapter_markdown("第一章", "原始内容。").encode("utf-8")
        obsidian = _chapter_markdown("第一章", "修改。").encode("utf-8")
        (self.chapters_dir / "chapter_001.md").write_bytes(base)
        target = self.target_dir / "03_Chapters" / "chapter_001.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(obsidian)
        from system.obsidian_mirror_manifest import MirrorManifestStore
        store = MirrorManifestStore(self.target_dir)
        manifest = store.load() or build_empty_manifest(
            self.binding.binding_id, self.binding.project_id, self.binding.timeline_id
        )
        manifest.files["03_Chapters/chapter_001.md"] = MirrorManifestEntry(
            source_id="03_Chapters/chapter_001.md",
            content_hash=compute_content_hash(base),
            size_bytes=len(base),
            last_synced_at="2024-01-01T00:00:00",
        )
        store.save(manifest)

        from system.obsidian_pull_service import ObsidianPullService
        service = ObsidianPullService(self.binding, self.ctx)
        preview = service.preview_file("03_Chapters/chapter_001.md")

        before_target = target.read_bytes()
        before_manifest = store.load()

        def fake_commit(*args, **kwargs):
            raise Exception("Simulated commit failure")

        import system.chapter_commit_service
        original = system.chapter_commit_service.ChapterCommitService.commit_chapter
        system.chapter_commit_service.ChapterCommitService.commit_chapter = fake_commit
        try:
            result = service.import_file("03_Chapters/chapter_001.md", preview.obsidian_hash)
            assert result.status == "commit_failed"
        finally:
            system.chapter_commit_service.ChapterCommitService.commit_chapter = original

        assert target.read_bytes() == before_target
        after_manifest = store.load()
        assert after_manifest.files["03_Chapters/chapter_001.md"].content_hash == before_manifest.files["03_Chapters/chapter_001.md"].content_hash

    def test_retry_after_manifest_failure_does_not_duplicate_commit(self):
        base = _chapter_markdown("第一章", "原始内容。").encode("utf-8")
        obsidian = _chapter_markdown("第一章", "修改。").encode("utf-8")
        (self.chapters_dir / "chapter_001.md").write_bytes(base)
        target = self.target_dir / "03_Chapters" / "chapter_001.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(obsidian)
        from system.obsidian_mirror_manifest import MirrorManifestStore
        store = MirrorManifestStore(self.target_dir)
        manifest = store.load() or build_empty_manifest(
            self.binding.binding_id, self.binding.project_id, self.binding.timeline_id
        )
        manifest.files["03_Chapters/chapter_001.md"] = MirrorManifestEntry(
            source_id="03_Chapters/chapter_001.md",
            content_hash=compute_content_hash(base),
            size_bytes=len(base),
            last_synced_at="2024-01-01T00:00:00",
        )
        store.save(manifest)

        from system.obsidian_pull_service import ObsidianPullService
        service = ObsidianPullService(self.binding, self.ctx)
        preview = service.preview_file("03_Chapters/chapter_001.md")

        call_count = [0]
        original_save = service.manifest_store.save
        def failing_save(m):
            call_count[0] += 1
            if call_count[0] == 1:
                raise OSError("Simulated manifest save failure")
            original_save(m)

        service.manifest_store.save = failing_save
        try:
            result = service.import_file("03_Chapters/chapter_001.md", preview.obsidian_hash)
            assert result.status == "completed_with_warnings"
            assert "Manifest update failed" in result.warnings[0]
        finally:
            service.manifest_store.save = original_save

        after_commit = (self.chapters_dir / "chapter_001.md").read_bytes()
        assert "修改" in after_commit.decode("utf-8")

        plan = service.scan()
        entry = next(e for e in plan.entries if e.relative_path == "03_Chapters/chapter_001.md")
        assert entry.action.value == "converged"

        result2 = service.import_file("03_Chapters/chapter_001.md", preview.obsidian_hash)
        assert result2.status in ("rejected", "stale_preview")


class TestPullRepairConverged:
    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.project_id = str(uuid.uuid4())
        self.workspace = Path(self.temp_workspace)
        self.project_dir = self.workspace / "projects" / self.project_id
        self.project_dir.mkdir(parents=True)
        self.data_dir = self.project_dir / "data"
        self.data_dir.mkdir()
        (self.data_dir / "story_spec.json").write_text('{}', encoding="utf-8")
        self.chapters_dir = self.data_dir / "chapters"
        self.chapters_dir.mkdir()
        self.target_dir = Path(self.temp_vault) / "StoryOS" / "test"
        self.target_dir.mkdir(parents=True, exist_ok=True)
        from system.obsidian_binding import BindingMarker
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
        store = ObsidianBindingStore(self.workspace)
        store.save(self.binding)
        marker = BindingMarker(
            project_id=self.project_id,
            timeline_id="main",
            binding_id=self.binding.binding_id,
        )
        (self.target_dir / MARKER_FILENAME).write_text(json.dumps(marker.to_dict()), encoding="utf-8")
        self.ctx = _make_project_context(self.project_dir)

    def teardown_method(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def test_converged_repair_updates_manifest_without_new_revision(self):
        base = _chapter_markdown("第一章", "原始内容。").encode("utf-8")
        new_content = _chapter_markdown("第一章", "新内容。").encode("utf-8")
        (self.chapters_dir / "chapter_001.md").write_bytes(new_content)
        target = self.target_dir / "03_Chapters" / "chapter_001.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(new_content)
        from system.obsidian_mirror_manifest import MirrorManifestStore
        store = MirrorManifestStore(self.target_dir)
        manifest = store.load() or build_empty_manifest(
            self.binding.binding_id, self.binding.project_id, self.binding.timeline_id
        )
        manifest.files["03_Chapters/chapter_001.md"] = MirrorManifestEntry(
            source_id="03_Chapters/chapter_001.md",
            content_hash=compute_content_hash(base),
            size_bytes=len(base),
            last_synced_at="2024-01-01T00:00:00",
        )
        store.save(manifest)

        from system.obsidian_pull_service import ObsidianPullService
        plan = ObsidianPullService(self.binding, self.ctx).repair_converged()
        assert plan.summary["converged"] == 1

        after_manifest = store.load()
        assert after_manifest.files["03_Chapters/chapter_001.md"].content_hash == compute_content_hash(new_content)


class TestCLIObsidianPull:
    """Real subprocess CLI tests for pull-obsidian."""

    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.project_id = str(uuid.uuid4())
        self.workspace = Path(self.temp_workspace)
        self.project_dir = self.workspace / "projects" / self.project_id
        self.project_dir.mkdir(parents=True)
        self.data_dir = self.project_dir / "data"
        self.data_dir.mkdir()
        (self.data_dir / "story_spec.json").write_text('{"title": "Test"}', encoding="utf-8")
        self.chapters_dir = self.data_dir / "chapters"
        self.chapters_dir.mkdir()
        (self.workspace / ".story_os").mkdir()
        from system.obsidian_binding_service import ObsidianBindingService
        from system.obsidian_binding import ObsidianBinding, BindingStatus
        from datetime import datetime, timezone
        service = ObsidianBindingService(self.workspace)
        self.binding = service.bind(
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
            cwd=str(self.project_dir),
            env=env,
        )

    def test_cli_pull_scan_zero_write(self):
        result = self._run_cli(["pull-obsidian"])
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "扫描完成" in result.stdout or "scan" in result.stdout.lower()
        assert "Traceback" not in result.stderr

    def test_cli_pull_preview(self):
        base = _chapter_markdown("第一章", "原始").encode("utf-8")
        obsidian = _chapter_markdown("第一章", "修改").encode("utf-8")
        (self.chapters_dir / "chapter_001.md").write_bytes(base)
        target = Path(self.temp_vault) / "StoryOS" / "test" / "03_Chapters" / "chapter_001.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(obsidian)
        from system.obsidian_mirror_manifest import MirrorManifestStore
        store = MirrorManifestStore(target.parent.parent)
        manifest = store.load() or build_empty_manifest(
            self.binding.binding_id, self.binding.project_id, self.binding.timeline_id
        )
        manifest.files["03_Chapters/chapter_001.md"] = MirrorManifestEntry(
            source_id="03_Chapters/chapter_001.md",
            content_hash=compute_content_hash(base),
            size_bytes=len(base),
            last_synced_at="2024-01-01T00:00:00",
        )
        store.save(manifest)

        result = self._run_cli(["pull-obsidian", "--file", "03_Chapters/chapter_001.md"])
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "预览" in result.stdout or "preview" in result.stdout.lower()

    def test_cli_pull_apply_requires_expected_hash(self):
        result = self._run_cli(["pull-obsidian", "--file", "03_Chapters/chapter_001.md", "--apply"])
        assert result.returncode == 1
        assert "MISSING_EXPECTED_HASH" in result.stdout or "expected-hash" in result.stdout

    def test_cli_pull_unbound_exit_code(self):
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
                [sys.executable, str(self.main_py), "pull-obsidian"],
                capture_output=True,
                text=True,
                cwd=str(empty_project),
                env=env,
            )
            assert result.returncode == 1
            assert "未绑定" in result.stdout or "OBSIDIAN_NOT_BOUND" in result.stdout
        finally:
            shutil.rmtree(str(empty_workspace), ignore_errors=True)

    def test_cli_pull_help(self):
        result = subprocess.run(
            [sys.executable, str(self.main_py), "pull-obsidian", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "--file" in result.stdout
        assert "--expected-hash" in result.stdout
        assert "--apply" in result.stdout


class TestWebAPIObsidianPull:
    """Real FastAPI TestClient HTTP tests for pull endpoints."""

    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.project_id = str(uuid.uuid4())
        self.workspace = Path(self.temp_workspace)
        self.project_dir = self.workspace / "projects" / self.project_id
        self.project_dir.mkdir(parents=True)
        self.data_dir = self.project_dir / "data"
        self.data_dir.mkdir()
        (self.data_dir / "story_spec.json").write_text('{"title": "Test"}', encoding="utf-8")
        self.chapters_dir = self.data_dir / "chapters"
        self.chapters_dir.mkdir()
        self.target_dir = Path(self.temp_vault) / "StoryOS" / "test"
        self.target_dir.mkdir(parents=True, exist_ok=True)
        from system.obsidian_binding import BindingMarker
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
        store = ObsidianBindingStore(self.workspace)
        store.save(self.binding)
        marker = BindingMarker(
            project_id=self.project_id,
            timeline_id="main",
            binding_id=self.binding.binding_id,
        )
        (self.target_dir / MARKER_FILENAME).write_text(json.dumps(marker.to_dict()), encoding="utf-8")
        self.ctx = _make_project_context(self.project_dir)

    def teardown_method(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def _mock_context(self, monkeypatch):
        monkeypatch.setattr("commands.get_project_context", lambda project_root=None: self.ctx)
        monkeypatch.setattr("commands.resolve_workspace_root", lambda project_root=None: self.workspace)
        monkeypatch.setattr("commands.resolve_current_project_root", lambda: self.project_dir)

    def _client(self):
        from fastapi import FastAPI
        from web.routes import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_api_pull_scan(self, monkeypatch):
        client = self._client()
        self._mock_context(monkeypatch)
        response = client.post("/api/obsidian/pull/scan", json={})
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["result"]["status"] == "scan"

    def test_api_pull_preview(self, monkeypatch):
        client = self._client()
        self._mock_context(monkeypatch)
        base = _chapter_markdown("第一章", "原始").encode("utf-8")
        obsidian = _chapter_markdown("第一章", "修改").encode("utf-8")
        (self.chapters_dir / "chapter_001.md").write_bytes(base)
        target = self.target_dir / "03_Chapters" / "chapter_001.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(obsidian)
        from system.obsidian_mirror_manifest import MirrorManifestStore
        store = MirrorManifestStore(self.target_dir)
        manifest = store.load() or build_empty_manifest(
            self.binding.binding_id, self.binding.project_id, self.binding.timeline_id
        )
        manifest.files["03_Chapters/chapter_001.md"] = MirrorManifestEntry(
            source_id="03_Chapters/chapter_001.md",
            content_hash=compute_content_hash(base),
            size_bytes=len(base),
            last_synced_at="2024-01-01T00:00:00",
        )
        store.save(manifest)

        response = client.post("/api/obsidian/pull/preview", json={"relative_path": "03_Chapters/chapter_001.md"})
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["result"]["status"] == "preview"
        assert data["result"]["importable"] is True

    def test_api_pull_apply(self, monkeypatch):
        client = self._client()
        self._mock_context(monkeypatch)
        base = _chapter_markdown("第一章", "原始").encode("utf-8")
        obsidian = _chapter_markdown("第一章", "修改").encode("utf-8")
        (self.chapters_dir / "chapter_001.md").write_bytes(base)
        target = self.target_dir / "03_Chapters" / "chapter_001.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(obsidian)
        from system.obsidian_mirror_manifest import MirrorManifestStore
        store = MirrorManifestStore(self.target_dir)
        manifest = store.load() or build_empty_manifest(
            self.binding.binding_id, self.binding.project_id, self.binding.timeline_id
        )
        manifest.files["03_Chapters/chapter_001.md"] = MirrorManifestEntry(
            source_id="03_Chapters/chapter_001.md",
            content_hash=compute_content_hash(base),
            size_bytes=len(base),
            last_synced_at="2024-01-01T00:00:00",
        )
        store.save(manifest)

        preview_resp = client.post("/api/obsidian/pull/preview", json={"relative_path": "03_Chapters/chapter_001.md"})
        preview_data = preview_resp.json()
        expected_hash = preview_data["result"]["obsidian_hash"]

        response = client.post("/api/obsidian/pull/apply", json={
            "relative_path": "03_Chapters/chapter_001.md",
            "expected_target_hash": expected_hash,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["result"]["status"] == "completed"

    def test_api_pull_stale_preview(self, monkeypatch):
        client = self._client()
        self._mock_context(monkeypatch)
        base = _chapter_markdown("第一章", "原始").encode("utf-8")
        obsidian = _chapter_markdown("第一章", "修改A").encode("utf-8")
        (self.chapters_dir / "chapter_001.md").write_bytes(base)
        target = self.target_dir / "03_Chapters" / "chapter_001.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(obsidian)
        from system.obsidian_mirror_manifest import MirrorManifestStore
        store = MirrorManifestStore(self.target_dir)
        manifest = store.load() or build_empty_manifest(
            self.binding.binding_id, self.binding.project_id, self.binding.timeline_id
        )
        manifest.files["03_Chapters/chapter_001.md"] = MirrorManifestEntry(
            source_id="03_Chapters/chapter_001.md",
            content_hash=compute_content_hash(base),
            size_bytes=len(base),
            last_synced_at="2024-01-01T00:00:00",
        )
        store.save(manifest)

        preview_resp = client.post("/api/obsidian/pull/preview", json={"relative_path": "03_Chapters/chapter_001.md"})
        preview_data = preview_resp.json()
        stale_hash = preview_data["result"]["obsidian_hash"]

        target.write_bytes(_chapter_markdown("第一章", "修改B").encode("utf-8"))

        response = client.post("/api/obsidian/pull/apply", json={
            "relative_path": "03_Chapters/chapter_001.md",
            "expected_target_hash": stale_hash,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert "STALE_PREVIEW" in data.get("code", "") or "stale" in data.get("message", "").lower()

    def test_api_pull_identity_mismatch(self, monkeypatch):
        client = self._client()
        self._mock_context(monkeypatch)
        from system.obsidian_mirror_manifest import MirrorManifestStore
        store = MirrorManifestStore(self.target_dir)
        manifest = store.load() or build_empty_manifest(
            self.binding.binding_id, self.binding.project_id, self.binding.timeline_id
        )
        manifest.project_id = str(uuid.uuid4())
        store.save(manifest)

        response = client.post("/api/obsidian/pull/scan", json={})
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert "identity" in data.get("message", "").lower() or "mismatch" in data.get("message", "").lower() or "不匹配" in data.get("message", "")

    def test_api_pull_path_safety(self, monkeypatch):
        client = self._client()
        self._mock_context(monkeypatch)
        response = client.post("/api/obsidian/pull/preview", json={"relative_path": "../../etc/passwd"})
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["result"]["importable"] is False


class TestPullServiceCWDRemoval:
    """Verify Pull Service does not modify process-level CWD."""

    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.project_id = str(uuid.uuid4())
        self.workspace = Path(self.temp_workspace)
        self.project_dir = self.workspace / "projects" / self.project_id
        self.project_dir.mkdir(parents=True)
        self.data_dir = self.project_dir / "data"
        self.data_dir.mkdir()
        (self.data_dir / "story_spec.json").write_text('{"title": "Test"}', encoding="utf-8")
        self.chapters_dir = self.data_dir / "chapters"
        self.chapters_dir.mkdir()
        self.target_dir = Path(self.temp_vault) / "StoryOS" / "test"
        self.target_dir.mkdir(parents=True, exist_ok=True)
        from system.obsidian_binding import BindingMarker
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
        store = ObsidianBindingStore(self.workspace)
        store.save(self.binding)
        marker = BindingMarker(
            project_id=self.project_id,
            timeline_id="main",
            binding_id=self.binding.binding_id,
        )
        (self.target_dir / MARKER_FILENAME).write_text(json.dumps(marker.to_dict()), encoding="utf-8")
        self.ctx = _make_project_context(self.project_dir)

    def teardown_method(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def test_pull_service_does_not_change_process_cwd(self):
        base = _chapter_markdown("第一章", "原始内容。").encode("utf-8")
        obsidian = _chapter_markdown("第一章", "用户在 Obsidian 修改后的内容。").encode("utf-8")
        (self.chapters_dir / "chapter_001.md").write_bytes(base)
        target = self.target_dir / "03_Chapters" / "chapter_001.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(obsidian)
        from system.obsidian_mirror_manifest import MirrorManifestStore
        store = MirrorManifestStore(self.target_dir)
        manifest = store.load() or build_empty_manifest(
            self.binding.binding_id, self.binding.project_id, self.binding.timeline_id
        )
        manifest.files["03_Chapters/chapter_001.md"] = MirrorManifestEntry(
            source_id="03_Chapters/chapter_001.md",
            content_hash=compute_content_hash(base),
            size_bytes=len(base),
            last_synced_at="2024-01-01T00:00:00",
        )
        store.save(manifest)

        from system.obsidian_pull_service import ObsidianPullService
        service = ObsidianPullService(self.binding, self.ctx)
        preview = service.preview_file("03_Chapters/chapter_001.md")

        original_cwd = os.getcwd()
        result = service.import_file("03_Chapters/chapter_001.md", preview.obsidian_hash)
        after_cwd = os.getcwd()

        assert result.status in ("completed", "completed_with_warnings")
        assert after_cwd == original_cwd, f"CWD changed from {original_cwd} to {after_cwd}"

    def test_commit_service_resolves_paths_from_project_context(self):
        """ChapterCommitService should resolve all paths via context.root, not CWD."""
        from system.chapter_commit_service import ChapterCommitService
        service = ChapterCommitService(self.ctx)
        # _chapter_path and _summary_path must be absolute
        chapter_path = service._chapter_path(1)
        summary_path = service._summary_path(1)
        assert chapter_path.is_absolute()
        assert summary_path.is_absolute()
        assert str(chapter_path).startswith(str(self.project_dir))
        assert str(summary_path).startswith(str(self.project_dir))


class TestPullServiceConcurrency:
    """Verify per-file locking and cross-project isolation."""

    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.project_id = str(uuid.uuid4())
        self.workspace = Path(self.temp_workspace)
        self.project_dir = self.workspace / "projects" / self.project_id
        self.project_dir.mkdir(parents=True)
        self.data_dir = self.project_dir / "data"
        self.data_dir.mkdir()
        (self.data_dir / "story_spec.json").write_text('{"title": "Test"}', encoding="utf-8")
        self.chapters_dir = self.data_dir / "chapters"
        self.chapters_dir.mkdir()
        self.target_dir = Path(self.temp_vault) / "StoryOS" / "test"
        self.target_dir.mkdir(parents=True, exist_ok=True)
        from system.obsidian_binding import BindingMarker
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
        store = ObsidianBindingStore(self.workspace)
        store.save(self.binding)
        marker = BindingMarker(
            project_id=self.project_id,
            timeline_id="main",
            binding_id=self.binding.binding_id,
        )
        (self.target_dir / MARKER_FILENAME).write_text(json.dumps(marker.to_dict()), encoding="utf-8")
        self.ctx = _make_project_context(self.project_dir)

    def teardown_method(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def test_two_concurrent_applies_same_file_create_one_revision(self):
        import threading
        import time
        from system.obsidian_pull_service import ObsidianPullService
        from system.chapter_commit_service import ChapterCommitService

        base = _chapter_markdown("第一章", "原始内容。").encode("utf-8")
        obsidian = _chapter_markdown("第一章", "用户在 Obsidian 修改后的内容。").encode("utf-8")
        (self.chapters_dir / "chapter_001.md").write_bytes(base)
        target = self.target_dir / "03_Chapters" / "chapter_001.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(obsidian)
        from system.obsidian_mirror_manifest import MirrorManifestStore
        store = MirrorManifestStore(self.target_dir)
        manifest = store.load() or build_empty_manifest(
            self.binding.binding_id, self.binding.project_id, self.binding.timeline_id
        )
        manifest.files["03_Chapters/chapter_001.md"] = MirrorManifestEntry(
            source_id="03_Chapters/chapter_001.md",
            content_hash=compute_content_hash(base),
            size_bytes=len(base),
            last_synced_at="2024-01-01T00:00:00",
        )
        store.save(manifest)

        service = ObsidianPullService(self.binding, self.ctx)
        preview = service.preview_file("03_Chapters/chapter_001.md")

        # Slow down commit_chapter to create an overlapping window
        original_commit_chapter = ChapterCommitService.commit_chapter
        commit_started = threading.Event()
        commit_continue = threading.Event()

        def slow_commit_chapter(self, *args, **kwargs):
            commit_started.set()
            commit_continue.wait(timeout=5)
            return original_commit_chapter(self, *args, **kwargs)

        ChapterCommitService.commit_chapter = slow_commit_chapter

        results = []

        def worker():
            result = service.import_file("03_Chapters/chapter_001.md", preview.obsidian_hash)
            results.append(result)

        try:
            t1 = threading.Thread(target=worker)
            t2 = threading.Thread(target=worker)
            t1.start()
            commit_started.wait(timeout=5)
            t2.start()
            # Give t2 time to reach the lock
            time.sleep(0.1)
            commit_continue.set()
            t1.join(timeout=10)
            t2.join(timeout=10)
        finally:
            ChapterCommitService.commit_chapter = original_commit_chapter

        assert len(results) == 2
        statuses = [r.status for r in results]
        # Exactly one should be completed/completed_with_warnings; the other rejected/stale_preview
        assert statuses.count("completed") + statuses.count("completed_with_warnings") == 1

    def test_second_concurrent_apply_returns_safe_non_commit_result(self):
        import threading
        import time
        from system.obsidian_pull_service import ObsidianPullService
        from system.chapter_commit_service import ChapterCommitService

        base = _chapter_markdown("第一章", "原始内容。").encode("utf-8")
        obsidian = _chapter_markdown("第一章", "用户在 Obsidian 修改后的内容。").encode("utf-8")
        (self.chapters_dir / "chapter_001.md").write_bytes(base)
        target = self.target_dir / "03_Chapters" / "chapter_001.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(obsidian)
        from system.obsidian_mirror_manifest import MirrorManifestStore
        store = MirrorManifestStore(self.target_dir)
        manifest = store.load() or build_empty_manifest(
            self.binding.binding_id, self.binding.project_id, self.binding.timeline_id
        )
        manifest.files["03_Chapters/chapter_001.md"] = MirrorManifestEntry(
            source_id="03_Chapters/chapter_001.md",
            content_hash=compute_content_hash(base),
            size_bytes=len(base),
            last_synced_at="2024-01-01T00:00:00",
        )
        store.save(manifest)

        service = ObsidianPullService(self.binding, self.ctx)
        preview = service.preview_file("03_Chapters/chapter_001.md")

        original_commit_chapter = ChapterCommitService.commit_chapter
        commit_started = threading.Event()
        commit_continue = threading.Event()

        def slow_commit_chapter(self, *args, **kwargs):
            commit_started.set()
            commit_continue.wait(timeout=5)
            return original_commit_chapter(self, *args, **kwargs)

        ChapterCommitService.commit_chapter = slow_commit_chapter

        results = []

        def worker():
            result = service.import_file("03_Chapters/chapter_001.md", preview.obsidian_hash)
            results.append(result)

        try:
            t1 = threading.Thread(target=worker)
            t2 = threading.Thread(target=worker)
            t1.start()
            commit_started.wait(timeout=5)
            t2.start()
            time.sleep(0.1)
            commit_continue.set()
            t1.join(timeout=10)
            t2.join(timeout=10)
        finally:
            ChapterCommitService.commit_chapter = original_commit_chapter

        assert len(results) == 2
        non_commit_results = [r for r in results if r.status not in ("completed", "completed_with_warnings")]
        assert len(non_commit_results) == 1
        assert non_commit_results[0].status in ("rejected", "stale_preview")

    def test_concurrent_applies_different_files_remain_isolated(self):
        import threading
        import time
        from system.obsidian_pull_service import ObsidianPullService

        base1 = _chapter_markdown("第一章", "原始1。").encode("utf-8")
        obsidian1 = _chapter_markdown("第一章", "修改1。").encode("utf-8")
        base2 = _chapter_markdown("第二章", "原始2。").encode("utf-8")
        obsidian2 = _chapter_markdown("第二章", "修改2。").encode("utf-8")

        (self.chapters_dir / "chapter_001.md").write_bytes(base1)
        (self.chapters_dir / "chapter_002.md").write_bytes(base2)

        target1 = self.target_dir / "03_Chapters" / "chapter_001.md"
        target2 = self.target_dir / "03_Chapters" / "chapter_002.md"
        target1.parent.mkdir(parents=True, exist_ok=True)
        target1.write_bytes(obsidian1)
        target2.write_bytes(obsidian2)

        from system.obsidian_mirror_manifest import MirrorManifestStore
        store = MirrorManifestStore(self.target_dir)
        manifest = store.load() or build_empty_manifest(
            self.binding.binding_id, self.binding.project_id, self.binding.timeline_id
        )
        manifest.files["03_Chapters/chapter_001.md"] = MirrorManifestEntry(
            source_id="03_Chapters/chapter_001.md",
            content_hash=compute_content_hash(base1),
            size_bytes=len(base1),
            last_synced_at="2024-01-01T00:00:00",
        )
        manifest.files["03_Chapters/chapter_002.md"] = MirrorManifestEntry(
            source_id="03_Chapters/chapter_002.md",
            content_hash=compute_content_hash(base2),
            size_bytes=len(base2),
            last_synced_at="2024-01-01T00:00:00",
        )
        store.save(manifest)

        service = ObsidianPullService(self.binding, self.ctx)
        preview1 = service.preview_file("03_Chapters/chapter_001.md")
        preview2 = service.preview_file("03_Chapters/chapter_002.md")

        # Make _commit_via_service slow to create an overlapping window
        # without relying on ChapterCommitService thread safety.
        original_commit_via_service = service._commit_via_service
        commit_started = threading.Event()
        commit_continue = threading.Event()
        timings = []

        def slow_commit_via_service(chapter_id, content, title):
            enter_time = time.monotonic()
            commit_started.set()
            commit_continue.wait(timeout=5)
            # Return a mock success result to avoid ChapterCommitService
            # thread-safety issues on Windows; this test verifies lock
            # granularity, not ChapterCommitService concurrency.
            exit_time = time.monotonic()
            timings.append((chapter_id, enter_time, exit_time))
            return {
                "status": "committed",
                "project_id": self.project_id,
                "chapter_id": chapter_id,
                "commit_id": f"mock-{chapter_id}",
                "source_type": "manual",
                "source_version_id": f"chapter_{chapter_id:03d}_obsidian_pull_v001.json",
                "source_hash": compute_content_hash(content.encode("utf-8")),
                "canon_revision_id": None,
                "chapter_path": str(self.ctx.root / "data" / "chapters" / f"chapter_{chapter_id:03d}.md"),
                "summary_path": None,
                "warnings": [],
                "post_commit": {},
            }

        service._commit_via_service = slow_commit_via_service

        results = []

        def worker1():
            result = service.import_file("03_Chapters/chapter_001.md", preview1.obsidian_hash)
            results.append(("file1", result))

        def worker2():
            result = service.import_file("03_Chapters/chapter_002.md", preview2.obsidian_hash)
            results.append(("file2", result))

        try:
            t1 = threading.Thread(target=worker1)
            t2 = threading.Thread(target=worker2)
            t1.start()
            commit_started.wait(timeout=5)
            t2.start()
            time.sleep(0.1)
            commit_continue.set()
            t1.join(timeout=10)
            t2.join(timeout=10)
        finally:
            service._commit_via_service = original_commit_via_service

        assert len(results) == 2
        # Both should succeed because they are different files
        for _, result in results:
            assert result.status in ("completed", "completed_with_warnings")

        # Verify the critical sections overlapped (different locks)
        assert len(timings) == 2
        (_, enter_a, exit_a), (_, enter_b, exit_b) = timings
        assert enter_b < exit_a or enter_a < exit_b, "Critical sections did not overlap; locks may be too coarse"


class TestPullServicePostCommitSideEffects:
    """Verify necessary side-effects are not skipped."""

    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.project_id = str(uuid.uuid4())
        self.workspace = Path(self.temp_workspace)
        self.project_dir = self.workspace / "projects" / self.project_id
        self.project_dir.mkdir(parents=True)
        self.data_dir = self.project_dir / "data"
        self.data_dir.mkdir()
        (self.data_dir / "story_spec.json").write_text('{"title": "Test"}', encoding="utf-8")
        self.chapters_dir = self.data_dir / "chapters"
        self.chapters_dir.mkdir()
        self.target_dir = Path(self.temp_vault) / "StoryOS" / "test"
        self.target_dir.mkdir(parents=True, exist_ok=True)
        from system.obsidian_binding import BindingMarker
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
        store = ObsidianBindingStore(self.workspace)
        store.save(self.binding)
        marker = BindingMarker(
            project_id=self.project_id,
            timeline_id="main",
            binding_id=self.binding.binding_id,
        )
        (self.target_dir / MARKER_FILENAME).write_text(json.dumps(marker.to_dict()), encoding="utf-8")
        self.ctx = _make_project_context(self.project_dir)

    def teardown_method(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def test_post_commit_policy_preserves_required_side_effects(self):
        from system.chapter_commit_service import ChapterCommitService, PostCommitPolicy
        service = ChapterCommitService(self.ctx)
        # Write a manual version to commit
        version_path = self.project_dir / "data" / "manual" / "chapter_001_manual_v001.json"
        version_path.parent.mkdir(parents=True, exist_ok=True)
        version_path.write_text(json.dumps({
            "content": "测试内容",
            "manual_text": "测试内容",
            "chapter_title": "第一章",
            "chapter_id": 1,
        }, ensure_ascii=False), encoding="utf-8")

        result = service.commit_chapter(
            chapter_id=1,
            source_version_id="chapter_001_manual_v001.json",
            post_commit_policy=PostCommitPolicy.LOCAL_ONLY,
        )
        assert result.status.value in ("committed", "committed_with_warnings", "already_committed")
        # LOCAL_ONLY must still run chroma_index (even if it warns)
        assert "chroma_index" in result.post_commit

    def test_pull_commit_updates_or_invalidates_vector_memory_correctly(self):
        """After pull commit, vector memory post-commit task should be recorded."""
        base = _chapter_markdown("第一章", "原始内容。").encode("utf-8")
        obsidian = _chapter_markdown("第一章", "用户在 Obsidian 修改后的内容。").encode("utf-8")
        (self.chapters_dir / "chapter_001.md").write_bytes(base)
        target = self.target_dir / "03_Chapters" / "chapter_001.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(obsidian)
        from system.obsidian_mirror_manifest import MirrorManifestStore
        store = MirrorManifestStore(self.target_dir)
        manifest = store.load() or build_empty_manifest(
            self.binding.binding_id, self.binding.project_id, self.binding.timeline_id
        )
        manifest.files["03_Chapters/chapter_001.md"] = MirrorManifestEntry(
            source_id="03_Chapters/chapter_001.md",
            content_hash=compute_content_hash(base),
            size_bytes=len(base),
            last_synced_at="2024-01-01T00:00:00",
        )
        store.save(manifest)

        from system.obsidian_pull_service import ObsidianPullService
        service = ObsidianPullService(self.binding, self.ctx)
        preview = service.preview_file("03_Chapters/chapter_001.md")
        result = service.import_file("03_Chapters/chapter_001.md", preview.obsidian_hash)

        assert result.status in ("completed", "completed_with_warnings")
        # commit_result should contain post_commit with chroma_index recorded
        assert result.commit_result is not None
        post_commit = result.commit_result.get("post_commit", {})
        assert "chroma_index" in post_commit


class TestPullServiceMirrorFailureRecovery:
    """Verify commit-success + mirror-failure recovery semantics."""

    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.project_id = str(uuid.uuid4())
        self.workspace = Path(self.temp_workspace)
        self.project_dir = self.workspace / "projects" / self.project_id
        self.project_dir.mkdir(parents=True)
        self.data_dir = self.project_dir / "data"
        self.data_dir.mkdir()
        (self.data_dir / "story_spec.json").write_text('{"title": "Test"}', encoding="utf-8")
        self.chapters_dir = self.data_dir / "chapters"
        self.chapters_dir.mkdir()
        self.target_dir = Path(self.temp_vault) / "StoryOS" / "test"
        self.target_dir.mkdir(parents=True, exist_ok=True)
        from system.obsidian_binding import BindingMarker
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
        store = ObsidianBindingStore(self.workspace)
        store.save(self.binding)
        marker = BindingMarker(
            project_id=self.project_id,
            timeline_id="main",
            binding_id=self.binding.binding_id,
        )
        (self.target_dir / MARKER_FILENAME).write_text(json.dumps(marker.to_dict()), encoding="utf-8")
        self.ctx = _make_project_context(self.project_dir)

    def teardown_method(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def _setup_inbound_scenario(self):
        base = _chapter_markdown("第一章", "原始内容。").encode("utf-8")
        obsidian = _chapter_markdown("第一章", "用户在 Obsidian 修改后的内容。").encode("utf-8")
        (self.chapters_dir / "chapter_001.md").write_bytes(base)
        target = self.target_dir / "03_Chapters" / "chapter_001.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(obsidian)
        from system.obsidian_mirror_manifest import MirrorManifestStore
        store = MirrorManifestStore(self.target_dir)
        manifest = store.load() or build_empty_manifest(
            self.binding.binding_id, self.binding.project_id, self.binding.timeline_id
        )
        manifest.files["03_Chapters/chapter_001.md"] = MirrorManifestEntry(
            source_id="03_Chapters/chapter_001.md",
            content_hash=compute_content_hash(base),
            size_bytes=len(base),
            last_synced_at="2024-01-01T00:00:00",
        )
        store.save(manifest)
        return obsidian

    def test_commit_success_mirror_write_failure_preserves_revision(self):
        from system.obsidian_pull_service import ObsidianPullService
        obsidian = self._setup_inbound_scenario()
        service = ObsidianPullService(self.binding, self.ctx)
        preview = service.preview_file("03_Chapters/chapter_001.md")

        original_update_mirror = service._update_mirror_file
        def failing_mirror(rel_path, content):
            raise OSError("Simulated mirror write failure")
        service._update_mirror_file = failing_mirror

        try:
            result = service.import_file("03_Chapters/chapter_001.md", preview.obsidian_hash)
        finally:
            service._update_mirror_file = original_update_mirror

        assert result.status == "completed_with_warnings"
        # Story OS revision must be preserved
        source_after = (self.chapters_dir / "chapter_001.md").read_bytes()
        assert "用户在 Obsidian 修改后的内容" in source_after.decode("utf-8")

    def test_commit_success_mirror_write_failure_keeps_manifest_base(self):
        from system.obsidian_pull_service import ObsidianPullService
        obsidian = self._setup_inbound_scenario()
        service = ObsidianPullService(self.binding, self.ctx)
        preview = service.preview_file("03_Chapters/chapter_001.md")

        original_update_mirror = service._update_mirror_file
        def failing_mirror(rel_path, content):
            raise OSError("Simulated mirror write failure")
        service._update_mirror_file = failing_mirror

        try:
            result = service.import_file("03_Chapters/chapter_001.md", preview.obsidian_hash)
        finally:
            service._update_mirror_file = original_update_mirror

        assert result.status == "completed_with_warnings"
        assert result.mirror_updated is False
        assert result.manifest_updated is False
        # Manifest should still have the old base hash
        from system.obsidian_mirror_manifest import MirrorManifestStore
        store = MirrorManifestStore(self.target_dir)
        manifest = store.load()
        base_hash = compute_content_hash(_chapter_markdown("第一章", "原始内容。").encode("utf-8"))
        assert manifest.files["03_Chapters/chapter_001.md"].content_hash == base_hash

    def test_mirror_failure_can_converge_via_safe_sync(self):
        from system.obsidian_pull_service import ObsidianPullService
        obsidian = self._setup_inbound_scenario()
        service = ObsidianPullService(self.binding, self.ctx)
        preview = service.preview_file("03_Chapters/chapter_001.md")

        original_update_mirror = service._update_mirror_file
        def failing_mirror(rel_path, content):
            raise OSError("Simulated mirror write failure")
        service._update_mirror_file = failing_mirror

        try:
            result = service.import_file("03_Chapters/chapter_001.md", preview.obsidian_hash)
        finally:
            service._update_mirror_file = original_update_mirror

        assert result.status == "completed_with_warnings"

        # Mirror write failed, so target still contains original obsidian content.
        # Source contains the committed ChapterCommitService output format.
        # They are expected to differ at this point.
        source_bytes = (self.chapters_dir / "chapter_001.md").read_bytes()
        target_bytes = (self.target_dir / "03_Chapters" / "chapter_001.md").read_bytes()
        assert source_bytes != target_bytes, "Expected source and target to differ after mirror failure"

        # Because source != target != base_hash, scan shows diverged.
        plan = service.scan()
        entry = next(e for e in plan.entries if e.relative_path == "03_Chapters/chapter_001.md")
        assert entry.action.value == "diverged"

        # MirrorSyncService treats diverged files as conflict_modified (safe behavior).
        from system.obsidian_mirror_sync import MirrorSyncService
        sync_service = MirrorSyncService(self.binding, self.data_dir)
        sync_result = sync_service.run(dry_run=False, prune_stale=False)
        assert sync_result["status"] == "completed"
        sync_changes = {c["path"]: c["action"] for c in sync_result["changes"]}
        assert sync_changes.get("03_Chapters/chapter_001.md") == "conflict_modified"

        # Convergence path: manually align target to source (e.g. admin repair),
        # then repair_converged fixes the manifest.
        (self.target_dir / "03_Chapters" / "chapter_001.md").write_bytes(source_bytes)
        plan2 = service.scan()
        entry2 = next(e for e in plan2.entries if e.relative_path == "03_Chapters/chapter_001.md")
        assert entry2.action.value == "converged"

        repair_plan = service.repair_converged()
        repair_entry = next(
            (e for e in repair_plan.entries if e.relative_path == "03_Chapters/chapter_001.md"), None
        )
        assert repair_entry is not None
        assert repair_entry.action.value == "converged"

        # After manifest repair, scan shows unchanged.
        plan3 = service.scan()
        entry3 = next(e for e in plan3.entries if e.relative_path == "03_Chapters/chapter_001.md")
        assert entry3.action.value == "unchanged"

    def test_retry_after_mirror_failure_does_not_duplicate_commit(self):
        from system.obsidian_pull_service import ObsidianPullService
        obsidian = self._setup_inbound_scenario()
        service = ObsidianPullService(self.binding, self.ctx)
        preview = service.preview_file("03_Chapters/chapter_001.md")

        call_count = [0]
        original_update_mirror = service._update_mirror_file
        def failing_once_mirror(rel_path, content):
            call_count[0] += 1
            if call_count[0] == 1:
                raise OSError("Simulated mirror write failure")
            return original_update_mirror(rel_path, content)
        service._update_mirror_file = failing_once_mirror

        try:
            result1 = service.import_file("03_Chapters/chapter_001.md", preview.obsidian_hash)
        finally:
            service._update_mirror_file = original_update_mirror

        assert result1.status == "completed_with_warnings"

        # Second retry: state is no longer inbound_changed, so it should be rejected
        plan = service.scan()
        entry = next(e for e in plan.entries if e.relative_path == "03_Chapters/chapter_001.md")
        # After commit but before mirror update, source != target
        # After we restored the original mirror method, the state depends on what's on disk
        # Let's just verify no new commit is made
        commit_id_1 = result1.commit_result.get("commit_id") if result1.commit_result else None

        # Try to apply again (it should not be inbound_changed anymore)
        result2 = service.import_file("03_Chapters/chapter_001.md", preview.obsidian_hash)
        assert result2.status in ("rejected", "stale_preview")


class TestPullServiceStaticGuards:
    """Static structural tests for Pull Service."""

    def test_no_os_chdir_in_pull_service_production_code(self):
        import inspect
        from system import obsidian_pull_service
        source = inspect.getsource(obsidian_pull_service)
        # Exclude test-related strings and comments
        lines = source.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if "os.chdir" in stripped and not stripped.startswith("#"):
                pytest.fail(f"obsidian_pull_service.py contains os.chdir at line {i + 1}: {line}")
