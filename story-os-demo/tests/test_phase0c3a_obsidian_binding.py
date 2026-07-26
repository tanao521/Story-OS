from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path

import pytest

from system.obsidian_binding import BindingStatus, MARKER_FILENAME
from system.obsidian_binding_service import (
    ObsidianBindingService,
    ObsidianBindingConflict,
    ObsidianBindingNotFound,
    ObsidianBindingInvalid,
    ObsidianMarkerMismatch,
    ObsidianTargetUnsafe,
)
from system.obsidian_binding_store import ObsidianBindingStore


class TestObsidianBindingStore:
    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.store = ObsidianBindingStore(Path(self.temp_workspace))
        self.project_id = str(uuid.uuid4())
        self.timeline_id = "main"

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def test_load_nonexistent(self):
        binding = self.store.load(self.project_id, self.timeline_id)
        assert binding is None

    def test_save_and_load(self):
        from system.obsidian_binding import ObsidianBinding
        from datetime import datetime, timezone

        binding = ObsidianBinding(
            binding_id="test_id",
            project_id=self.project_id,
            timeline_id=self.timeline_id,
            vault_root=Path("/tmp/test"),
            target_relative_path="StoryOS/test",
            status=BindingStatus.BOUND,
            created_at=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            updated_at=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        )
        self.store.save(binding)
        loaded = self.store.load(self.project_id, self.timeline_id)
        assert loaded is not None
        assert loaded.binding_id == "test_id"
        assert loaded.project_id == self.project_id
        assert loaded.timeline_id == self.timeline_id

    def test_delete(self):
        from system.obsidian_binding import ObsidianBinding
        from datetime import datetime, timezone

        binding = ObsidianBinding(
            binding_id="test_id",
            project_id=self.project_id,
            timeline_id=self.timeline_id,
            vault_root=Path("/tmp/test"),
            target_relative_path="StoryOS/test",
            status=BindingStatus.BOUND,
            created_at=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            updated_at=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        )
        self.store.save(binding)
        self.store.delete(self.project_id, self.timeline_id)
        loaded = self.store.load(self.project_id, self.timeline_id)
        assert loaded is None

    def test_list_bindings(self):
        from system.obsidian_binding import ObsidianBinding
        from datetime import datetime, timezone

        binding1 = ObsidianBinding(
            binding_id="test1",
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path("/tmp/test"),
            target_relative_path="StoryOS/test1",
            status=BindingStatus.BOUND,
            created_at=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            updated_at=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        )
        binding2 = ObsidianBinding(
            binding_id="test2",
            project_id=self.project_id,
            timeline_id="experiment",
            vault_root=Path("/tmp/test"),
            target_relative_path="StoryOS/test2",
            status=BindingStatus.BOUND,
            created_at=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            updated_at=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        )
        self.store.save(binding1)
        self.store.save(binding2)
        bindings = self.store.list_bindings()
        assert len(bindings) == 2

    def test_find_by_target(self):
        from system.obsidian_binding import ObsidianBinding
        from datetime import datetime, timezone

        binding = ObsidianBinding(
            binding_id="test1",
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path("/tmp/vault"),
            target_relative_path="StoryOS/test1",
            status=BindingStatus.BOUND,
            created_at=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            updated_at=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        )
        self.store.save(binding)
        found = self.store.find_by_target(Path("/tmp/vault"), "StoryOS/test1")
        assert found is not None
        assert found.binding_id == "test1"

    def test_is_target_conflict(self):
        from system.obsidian_binding import ObsidianBinding
        from datetime import datetime, timezone

        binding = ObsidianBinding(
            binding_id="test1",
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path("/tmp/vault"),
            target_relative_path="StoryOS/test1",
            status=BindingStatus.BOUND,
            created_at=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            updated_at=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        )
        self.store.save(binding)
        assert self.store.is_target_conflict(Path("/tmp/vault"), "StoryOS/test1") is True
        assert self.store.is_target_conflict(Path("/tmp/vault"), "StoryOS/test1", exclude_project_id=self.project_id) is False


class TestObsidianBindingService:
    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.service = ObsidianBindingService(Path(self.temp_workspace))
        self.project_id = str(uuid.uuid4())

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def test_bind_success(self):
        binding = self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project",
        )
        assert binding is not None
        assert binding.project_id == self.project_id
        assert binding.timeline_id == "main"
        assert binding.vault_root.as_posix() == Path(self.temp_vault).resolve().as_posix()
        assert binding.target_relative_path == "StoryOS/my-project"

    def test_bind_creates_marker(self):
        binding = self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project",
        )
        marker_path = binding.target_full_path / MARKER_FILENAME
        assert marker_path.exists()
        marker_data = json.loads(marker_path.read_text(encoding="utf-8"))
        assert marker_data["project_id"] == self.project_id
        assert marker_data["timeline_id"] == "main"

    def test_get_binding(self):
        self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project",
        )
        binding = self.service.get_binding(self.project_id, "main")
        assert binding is not None
        assert binding.project_id == self.project_id

    def test_unbind(self):
        binding = self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project",
        )
        result = self.service.unbind(self.project_id, "main")
        assert result["deleted"] is True
        assert result["reason"] == "OK"
        assert self.service.get_binding(self.project_id, "main") is None
        # marker must be deleted
        marker_path = binding.target_full_path / MARKER_FILENAME
        assert not marker_path.exists()

    def test_unbind_nonexistent(self):
        result = self.service.unbind(self.project_id, "main")
        assert result["deleted"] is False
        assert result["reason"] == "NOT_FOUND"

    def test_status_unbound(self):
        status = self.service.status(self.project_id, "main")
        assert status["status"] == "unbound"

    def test_status_bound(self):
        self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project",
        )
        status = self.service.status(self.project_id, "main")
        assert status["status"] == "bound"

    def test_bind_target_conflict(self):
        project_b = str(uuid.uuid4())
        self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project",
        )
        with pytest.raises(ObsidianBindingConflict):
            self.service.bind(
                project_id=project_b,
                timeline_id="main",
                vault_root=Path(self.temp_vault),
                target_relative_path="StoryOS/my-project",
            )

    def test_bind_marker_mismatch(self):
        project_b = str(uuid.uuid4())
        self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project",
        )
        with pytest.raises(ObsidianBindingConflict):
            self.service.bind(
                project_id=project_b,
                timeline_id="main",
                vault_root=Path(self.temp_vault),
                target_relative_path="StoryOS/my-project",
                adopt_existing=True,
            )

    def test_bind_existing_directory_without_adopt(self):
        existing_dir = Path(self.temp_vault) / "StoryOS" / "existing"
        existing_dir.mkdir(parents=True, exist_ok=True)
        with pytest.raises(ObsidianBindingConflict):
            self.service.bind(
                project_id=self.project_id,
                timeline_id="main",
                vault_root=Path(self.temp_vault),
                target_relative_path="StoryOS/existing",
            )

    def test_bind_existing_directory_with_adopt(self):
        existing_dir = Path(self.temp_vault) / "StoryOS" / "existing"
        existing_dir.mkdir(parents=True, exist_ok=True)
        binding = self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/existing",
            adopt_existing=True,
        )
        assert binding is not None

    def test_bind_invalid_target_traversal(self):
        with pytest.raises(ObsidianTargetUnsafe):
            self.service.bind(
                project_id=self.project_id,
                timeline_id="main",
                vault_root=Path(self.temp_vault),
                target_relative_path="../escape",
            )

    def test_bind_absolute_target(self):
        with pytest.raises(ObsidianTargetUnsafe):
            self.service.bind(
                project_id=self.project_id,
                timeline_id="main",
                vault_root=Path(self.temp_vault),
                target_relative_path="/absolute/path",
            )