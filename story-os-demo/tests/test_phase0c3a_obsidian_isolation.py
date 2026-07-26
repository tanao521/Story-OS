from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from system.obsidian_binding_service import ObsidianBindingService


class TestMultiProjectIsolation:
    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.service = ObsidianBindingService(Path(self.temp_workspace))
        self.project_a_id = str(uuid.uuid4())
        self.project_b_id = str(uuid.uuid4())

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def test_project_a_bind(self):
        binding = self.service.bind(
            project_id=self.project_a_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/project-a",
        )
        assert binding is not None

    def test_project_b_bind(self):
        binding = self.service.bind(
            project_id=self.project_b_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/project-b",
        )
        assert binding is not None

    def test_both_projects_bound(self):
        self.service.bind(
            project_id=self.project_a_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/project-a",
        )
        self.service.bind(
            project_id=self.project_b_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/project-b",
        )
        bindings = self.service.store.list_bindings()
        assert len(bindings) == 2
        assert any(b.project_id == self.project_a_id for b in bindings)
        assert any(b.project_id == self.project_b_id for b in bindings)

    def test_project_a_sync_does_not_affect_b(self):
        self.service.bind(
            project_id=self.project_a_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/project-a",
        )
        self.service.bind(
            project_id=self.project_b_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/project-b",
        )

        target_a = Path(self.temp_vault) / "StoryOS" / "project-a"
        target_b = Path(self.temp_vault) / "StoryOS" / "project-b"

        assert target_a.exists()
        assert target_b.exists()
        assert target_a != target_b

    def test_project_a_unbind_does_not_affect_b(self):
        self.service.bind(
            project_id=self.project_a_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/project-a",
        )
        self.service.bind(
            project_id=self.project_b_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/project-b",
        )

        result = self.service.unbind(self.project_a_id, "main")
        assert result["deleted"] is True

        assert self.service.get_binding(self.project_a_id, "main") is None
        assert self.service.get_binding(self.project_b_id, "main") is not None


class TestTimelineIsolation:
    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.service = ObsidianBindingService(Path(self.temp_workspace))
        self.project_id = str(uuid.uuid4())

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def test_main_timeline_bind(self):
        binding = self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project/main",
        )
        assert binding is not None

    def test_experiment_timeline_bind(self):
        binding = self.service.bind(
            project_id=self.project_id,
            timeline_id="experiment-a",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project/experiments/experiment-a",
        )
        assert binding is not None

    def test_both_timelines_bound(self):
        self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project/main",
        )
        self.service.bind(
            project_id=self.project_id,
            timeline_id="experiment-a",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project/experiments/experiment-a",
        )
        bindings = self.service.store.list_bindings()
        assert len(bindings) == 2
        assert any(b.timeline_id == "main" for b in bindings)
        assert any(b.timeline_id == "experiment-a" for b in bindings)

    def test_main_and_experiment_have_different_targets(self):
        main_binding = self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project/main",
        )
        exp_binding = self.service.bind(
            project_id=self.project_id,
            timeline_id="experiment-a",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project/experiments/experiment-a",
        )
        assert main_binding.target_full_path != exp_binding.target_full_path

    def test_same_target_conflict_between_timelines(self):
        self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project",
        )
        from system.obsidian_binding_service import ObsidianBindingConflict
        with pytest.raises(ObsidianBindingConflict):
            self.service.bind(
                project_id=self.project_id,
                timeline_id="experiment-a",
                vault_root=Path(self.temp_vault),
                target_relative_path="StoryOS/my-project",
            )

    def test_status_independent(self):
        self.service.bind(
            project_id=self.project_id,
            timeline_id="main",
            vault_root=Path(self.temp_vault),
            target_relative_path="StoryOS/my-project/main",
        )
        main_status = self.service.status(self.project_id, "main")
        exp_status = self.service.status(self.project_id, "experiment-a")
        assert main_status["status"] == "bound"
        assert exp_status["status"] == "unbound"