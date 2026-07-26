from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

from system.obsidian_binding import BindingMarker, BindingStatus, MARKER_FILENAME
from system.obsidian_binding_service import (
    ObsidianBindingService,
    ObsidianBindingConflict,
    ObsidianBindingInvalid,
    ObsidianMarkerMismatch,
)
from system.obsidian_binding_store import ObsidianBindingStore


class TestUnbindMarkerLifecycle:
    """Test that unbind correctly manages marker lifecycle."""

    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.service = ObsidianBindingService(Path(self.temp_workspace))
        self.project_id = str(uuid.uuid4())

    def teardown_method(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def test_unbind_deletes_matching_marker(self):
        binding = self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project",
        )
        marker_path = binding.target_full_path / MARKER_FILENAME
        assert marker_path.exists()

        result = self.service.unbind(self.project_id, "main")
        assert result["deleted"] is True
        assert result["reason"] == "OK"
        assert not marker_path.exists()

    def test_unbind_retains_target_directory(self):
        binding = self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project",
        )
        # create a user file in target
        user_file = binding.target_full_path / "chapter1.md"
        user_file.write_text("user content", encoding="utf-8")

        self.service.unbind(self.project_id, "main")
        assert binding.target_full_path.exists()
        assert user_file.exists()
        assert user_file.read_text(encoding="utf-8") == "user content"

    def test_unbind_missing_marker_allows_cleanup(self):
        binding = self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project",
        )
        marker_path = binding.target_full_path / MARKER_FILENAME
        marker_path.unlink()
        assert not marker_path.exists()

        result = self.service.unbind(self.project_id, "main")
        assert result["deleted"] is True
        assert result["reason"] == "OK"

    def test_unbind_missing_target_allows_cleanup(self):
        binding = self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project",
        )
        shutil.rmtree(binding.target_full_path)
        assert not binding.target_full_path.exists()

        result = self.service.unbind(self.project_id, "main")
        assert result["deleted"] is True
        assert result["reason"] == "OK"

    def test_unbind_foreign_project_marker_rejected(self):
        project_b = str(uuid.uuid4())
        binding_a = self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/shared",
        )
        # overwrite marker with foreign project
        foreign_marker = BindingMarker(
            project_id=project_b,
            timeline_id="main",
            binding_id="foreign_id",
        )
        marker_path = binding_a.target_full_path / MARKER_FILENAME
        marker_path.write_text(
            json.dumps(foreign_marker.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        result = self.service.unbind(self.project_id, "main")
        assert result["deleted"] is False
        assert result["reason"] == "FOREIGN_MARKER_PROJECT"
        # marker still exists
        assert marker_path.exists()

    def test_unbind_foreign_timeline_marker_rejected(self):
        binding = self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/shared",
        )
        # overwrite marker with foreign timeline
        foreign_marker = BindingMarker(
            project_id=self.project_id,
            timeline_id="experiment-a",
            binding_id=binding.binding_id,
        )
        marker_path = binding.target_full_path / MARKER_FILENAME
        marker_path.write_text(
            json.dumps(foreign_marker.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        result = self.service.unbind(self.project_id, "main")
        assert result["deleted"] is False
        assert result["reason"] == "FOREIGN_MARKER_TIMELINE"
        assert marker_path.exists()

    def test_unbind_foreign_binding_id_rejected(self):
        binding = self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/shared",
        )
        # overwrite marker with foreign binding_id
        foreign_marker = BindingMarker(
            project_id=self.project_id,
            timeline_id="main",
            binding_id="different_binding_id",
        )
        marker_path = binding.target_full_path / MARKER_FILENAME
        marker_path.write_text(
            json.dumps(foreign_marker.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        result = self.service.unbind(self.project_id, "main")
        assert result["deleted"] is False
        assert result["reason"] == "FOREIGN_MARKER_BINDING"
        assert marker_path.exists()

    def test_unbind_idempotent(self):
        self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project",
        )
        result1 = self.service.unbind(self.project_id, "main")
        assert result1["deleted"] is True

        result2 = self.service.unbind(self.project_id, "main")
        assert result2["deleted"] is False
        assert result2["reason"] == "NOT_FOUND"

    def test_unbind_one_project_not_affect_other(self):
        project_b = str(uuid.uuid4())
        binding_a = self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/project-a",
        )
        binding_b = self.service.bind(
            project_id=project_b,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/project-b",
        )

        self.service.unbind(self.project_id, "main")

        assert not (binding_a.target_full_path / MARKER_FILENAME).exists()
        assert (binding_b.target_full_path / MARKER_FILENAME).exists()

    def test_unbind_main_not_affect_experiment(self):
        binding_main = self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/main",
        )
        binding_exp = self.service.bind(
            project_id=self.project_id,
            timeline_id="experiment-a",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/experiment-a",
        )

        self.service.unbind(self.project_id, "main")

        assert not (binding_main.target_full_path / MARKER_FILENAME).exists()
        assert (binding_exp.target_full_path / MARKER_FILENAME).exists()


class TestBindHalfState:
    """Fault injection: bind operations that fail halfway."""

    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.service = ObsidianBindingService(Path(self.temp_workspace))
        self.project_id = str(uuid.uuid4())

    def teardown_method(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def test_status_detects_missing_marker(self):
        binding = self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project",
        )
        # simulate marker deletion after bind
        marker_path = binding.target_full_path / MARKER_FILENAME
        marker_path.unlink()

        status = self.service.status(self.project_id, "main")
        assert status["status"] == "marker_mismatch"

    def test_sync_rejects_missing_marker(self):
        binding = self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project",
        )
        marker_path = binding.target_full_path / MARKER_FILENAME
        marker_path.unlink()

        with pytest.raises(ObsidianMarkerMismatch):
            self.service.sync(self.project_id, "main", Path("/tmp/data"))

    def test_rebind_recoverable_after_marker_loss(self):
        binding = self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project",
        )
        # simulate marker loss
        marker_path = binding.target_full_path / MARKER_FILENAME
        marker_path.unlink()

        # unbind should still clean up the record
        result = self.service.unbind(self.project_id, "main")
        assert result["deleted"] is True

        # rebind with adopt_existing should succeed
        new_binding = self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project",
            adopt_existing=True,
        )
        assert new_binding is not None
        assert marker_path.exists()


class TestSyncPathRevalidation:
    """Test that sync re-validates paths after bind."""

    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.service = ObsidianBindingService(Path(self.temp_workspace))
        self.project_id = str(uuid.uuid4())

    def teardown_method(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def test_sync_rejects_when_target_deleted(self):
        binding = self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project",
        )
        shutil.rmtree(binding.target_full_path)

        with pytest.raises(ObsidianBindingInvalid):
            self.service.sync(self.project_id, "main", Path("/tmp/data"))

    def test_sync_rejects_when_marker_tampered(self):
        binding = self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project",
        )
        marker_path = binding.target_full_path / MARKER_FILENAME
        marker_data = json.loads(marker_path.read_text(encoding="utf-8"))
        marker_data["project_id"] = str(uuid.uuid4())
        marker_path.write_text(json.dumps(marker_data), encoding="utf-8")

        with pytest.raises(ObsidianMarkerMismatch):
            self.service.sync(self.project_id, "main", Path("/tmp/data"))


class TestWindowsJunction:
    """Test junction/reparse point detection on Windows."""

    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.service = ObsidianBindingService(Path(self.temp_workspace))
        self.project_id = str(uuid.uuid4())

    def teardown_method(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        # vault cleanup may follow junctions; be careful
        vault = Path(self.temp_vault)
        if vault.exists():
            shutil.rmtree(vault, ignore_errors=True)

    def _create_junction(self, junction_path: Path, target_path: Path) -> bool:
        """Create a Windows directory junction. Returns True if successful."""
        try:
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction_path), str(target_path)],
                capture_output=True,
                check=True,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def _remove_junction(self, junction_path: Path) -> None:
        """Remove a junction without following it."""
        if junction_path.exists():
            subprocess.run(
                ["cmd", "/c", "rmdir", str(junction_path)],
                capture_output=True,
                check=False,
            )

    def test_bind_rejects_junction_target(self):
        outside_dir = Path(self.temp_workspace) / "outside"
        outside_dir.mkdir(parents=True, exist_ok=True)
        junction_path = Path(self.temp_vault) / "StoryOS" / "link"
        junction_path.parent.mkdir(parents=True, exist_ok=True)

        if not self._create_junction(junction_path, outside_dir):
            pytest.fail("Cannot create junction for test - this is a test environment issue, not a code skip")

        try:
            from system.obsidian_binding_service import ObsidianTargetUnsafe
            with pytest.raises(ObsidianTargetUnsafe):
                self.service.bind(
                    project_id=self.project_id,
                    timeline_id="main",
                    vault_root=Path(self.temp_vault),
                    target_relative_path="StoryOS/link",
                )
        finally:
            self._remove_junction(junction_path)

    def test_sync_rejects_when_target_replaced_by_junction(self):
        outside_dir = Path(self.temp_workspace) / "outside"
        outside_dir.mkdir(parents=True, exist_ok=True)

        binding = self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project",
        )

        # remove real target, replace with junction
        shutil.rmtree(binding.target_full_path)
        if not self._create_junction(binding.target_full_path, outside_dir):
            pytest.fail("Cannot create junction for test")

        try:
            from system.obsidian_binding_service import ObsidianTargetUnsafe
            with pytest.raises(ObsidianTargetUnsafe):
                self.service.sync(self.project_id, "main", Path("/tmp/data"))
            # verify outside directory was NOT written to
            assert not (outside_dir / ".storyos-binding.json").exists()
        finally:
            self._remove_junction(binding.target_full_path)

    def test_sync_rejects_when_parent_replaced_by_junction(self):
        outside_dir = Path(self.temp_workspace) / "outside_parent"
        outside_dir.mkdir(parents=True, exist_ok=True)

        binding = self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project",
        )

        parent = binding.target_full_path.parent
        grandparent = parent.parent
        # remove parent, replace with junction at grandparent level
        # this is harder - need to replace a parent dir
        # let's just replace "StoryOS" with junction
        storyos_dir = Path(self.temp_vault) / "StoryOS"
        if storyos_dir.exists():
            shutil.rmtree(storyos_dir)
        storyos_parent = storyos_dir.parent
        storyos_junction = storyos_parent / "StoryOS_junction_temp"
        storyos_junction.mkdir(parents=True, exist_ok=True)

        if not self._create_junction(storyos_dir, outside_dir):
            pytest.fail("Cannot create junction for test")

        try:
            from system.obsidian_binding_service import ObsidianTargetUnsafe
            with pytest.raises(ObsidianTargetUnsafe):
                self.service.sync(self.project_id, "main", Path("/tmp/data"))
        finally:
            self._remove_junction(storyos_dir)