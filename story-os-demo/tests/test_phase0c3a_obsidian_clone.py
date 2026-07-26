from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from system.obsidian_binding_service import ObsidianBindingService, ObsidianBindingNotFound


class TestCloneUnbound:
    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.service = ObsidianBindingService(Path(self.temp_workspace))
        self.source_project_id = str(uuid.uuid4())
        self.clone_project_id = str(uuid.uuid4())

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def test_source_project_bound(self):
        binding = self.service.bind(
            project_id=self.source_project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/source",
        )
        assert binding is not None
        assert self.service.get_binding(self.source_project_id, "main") is not None

    def test_clone_project_unbound_by_default(self):
        self.service.bind(
            project_id=self.source_project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/source",
        )
        status = self.service.status(self.clone_project_id, "main")
        assert status["status"] == "unbound"
        assert self.service.get_binding(self.clone_project_id, "main") is None

    def test_clone_sync_fails_when_unbound(self):
        self.service.bind(
            project_id=self.source_project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/source",
        )
        with pytest.raises(ObsidianBindingNotFound):
            self.service.sync(self.clone_project_id, "main", Path("/tmp/data"))

    def test_clone_can_be_bound_to_new_target(self):
        self.service.bind(
            project_id=self.source_project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/source",
        )
        clone_binding = self.service.bind(
            project_id=self.clone_project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/clone",
        )
        assert clone_binding is not None
        assert clone_binding.target_relative_path == "StoryOS/clone"
        assert clone_binding.target_full_path != self.service.get_binding(self.source_project_id, "main").target_full_path

    def test_clone_binding_does_not_affect_source(self):
        self.service.bind(
            project_id=self.source_project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/source",
        )
        self.service.bind(
            project_id=self.clone_project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/clone",
        )
        source_binding = self.service.get_binding(self.source_project_id, "main")
        clone_binding = self.service.get_binding(self.clone_project_id, "main")
        assert source_binding is not None
        assert clone_binding is not None
        assert source_binding.binding_id != clone_binding.binding_id
        assert source_binding.target_relative_path != clone_binding.target_relative_path

    def test_clone_unbind_does_not_affect_source(self):
        self.service.bind(
            project_id=self.source_project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/source",
        )
        self.service.bind(
            project_id=self.clone_project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/clone",
        )
        result = self.service.unbind(self.clone_project_id, "main")
        assert result["deleted"] is True
        assert self.service.get_binding(self.source_project_id, "main") is not None
        assert self.service.get_binding(self.clone_project_id, "main") is None