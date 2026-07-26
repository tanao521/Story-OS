import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import json
import os
import stat as stat_module
import subprocess
import sys

from system.project_clone_service import ProjectCloneService, CloneCopyError
from system.project_manager import get_project_context


class TestVectorStateWarningPropagation:
    """Verify state write failures are properly reported as warnings."""

    def test_rebuild_success_state_write_failure_reports_warning(self, tmp_path):
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        projects_dir = workspace_root / "projects"
        projects_dir.mkdir()

        source_dir = projects_dir / "source-project"
        source_dir.mkdir()
        source_data = source_dir / "data"
        source_data.mkdir()

        source_project_id = "source-id-123"
        (source_dir / "project.json").write_text(json.dumps({
            "project_id": source_project_id,
            "name": "Source Project",
            "slug": "source-project",
        }))
        (source_data / "state.json").write_text(json.dumps({
            "vector_memory": {"enabled": True, "healthy": True, "project_id": source_project_id},
            "creative_progress": {"words_written": 1000},
        }))
        (source_data / "story_spec.json").write_text('{"title": "Test"}')
        canon_dir = source_data / "canon_versions"
        canon_dir.mkdir()

        source_context = get_project_context(source_dir)
        service = ProjectCloneService(workspace_root)

        with patch("system.vector_index_lifecycle.rebuild_project_index") as mock_rebuild:
            mock_rebuild.return_value = {"status": "success"}

            with patch.object(
                service,
                "_update_vector_memory_state",
                side_effect=IOError("Permission denied")
            ):
                result = service.clone_project(source_context, "Cloned Project")

                assert result.status == "completed_with_warnings"
                assert any("VECTOR_STATE_UPDATE_FAILED" in w for w in result.warnings)
                assert not any("VECTOR_REBUILD_FAILED" in w for w in result.warnings)

    def test_rebuild_failure_state_write_failure_reports_both_warnings(self, tmp_path):
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        projects_dir = workspace_root / "projects"
        projects_dir.mkdir()

        source_dir = projects_dir / "source-project"
        source_dir.mkdir()
        source_data = source_dir / "data"
        source_data.mkdir()

        source_project_id = "source-id-123"
        (source_dir / "project.json").write_text(json.dumps({
            "project_id": source_project_id,
            "name": "Source Project",
            "slug": "source-project",
        }))
        (source_data / "state.json").write_text(json.dumps({
            "vector_memory": {"enabled": True, "healthy": True},
            "creative_progress": {"words_written": 1000},
        }))
        (source_data / "story_spec.json").write_text('{"title": "Test"}')
        canon_dir = source_data / "canon_versions"
        canon_dir.mkdir()

        source_context = get_project_context(source_dir)
        service = ProjectCloneService(workspace_root)

        with patch("system.vector_index_lifecycle.rebuild_project_index") as mock_rebuild:
            mock_rebuild.return_value = {"status": "failed", "message": "Rebuild error"}

            with patch.object(
                service,
                "_update_vector_memory_state",
                side_effect=IOError("State write error")
            ):
                result = service.clone_project(source_context, "Cloned Project")

                assert result.status == "completed_with_warnings"
                assert any("VECTOR_REBUILD_FAILED" in w for w in result.warnings)
                assert any("VECTOR_STATE_UPDATE_FAILED" in w for w in result.warnings)

    def test_state_write_failure_does_not_rollback_clone(self, tmp_path):
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        projects_dir = workspace_root / "projects"
        projects_dir.mkdir()

        source_dir = projects_dir / "source-project"
        source_dir.mkdir()
        source_data = source_dir / "data"
        source_data.mkdir()

        source_project_id = "source-id-123"
        (source_dir / "project.json").write_text(json.dumps({
            "project_id": source_project_id,
            "name": "Source Project",
            "slug": "source-project",
        }))
        (source_data / "state.json").write_text(json.dumps({
            "vector_memory": {"enabled": True, "healthy": True},
            "creative_progress": {"words_written": 1000},
        }))
        (source_data / "story_spec.json").write_text('{"title": "Test"}')
        canon_dir = source_data / "canon_versions"
        canon_dir.mkdir()

        source_context = get_project_context(source_dir)
        service = ProjectCloneService(workspace_root)

        with patch("system.vector_index_lifecycle.rebuild_project_index") as mock_rebuild:
            mock_rebuild.return_value = {"status": "success"}

            with patch.object(
                service,
                "_update_vector_memory_state",
                side_effect=IOError("Cannot write state")
            ):
                result = service.clone_project(source_context, "Cloned Project")

                target_dir = projects_dir / result.project_slug
                assert target_dir.exists()
                assert (target_dir / "data" / "story_spec.json").exists()


class TestWindowsReparsePointGuard:
    """Verify junction/reparse point detection works correctly."""

    def test_symlink_detection_rejects_clone(self, tmp_path):
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        projects_dir = workspace_root / "projects"
        projects_dir.mkdir()

        source_dir = projects_dir / "source-project"
        source_dir.mkdir()
        source_data = source_dir / "data"
        source_data.mkdir()

        (source_dir / "project.json").write_text(json.dumps({
            "project_id": "source-id",
            "name": "Source",
            "slug": "source-project",
        }))
        (source_data / "state.json").write_text(json.dumps({
            "vector_memory": {"enabled": False},
            "creative_progress": {},
        }))
        (source_data / "story_spec.json").write_text('{"title": "Test"}')
        canon_dir = source_data / "canon_versions"
        canon_dir.mkdir()

        source_context = get_project_context(source_dir)
        service = ProjectCloneService(workspace_root)

        with patch.object(Path, "is_symlink", return_value=True):
            with pytest.raises(CloneCopyError, match="Symlink detected"):
                service.clone_project(source_context, "Cloned")

    def test_junction_detection_rejects_clone(self, tmp_path):
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        projects_dir = workspace_root / "projects"
        projects_dir.mkdir()

        source_dir = projects_dir / "source-project"
        source_dir.mkdir()
        source_data = source_dir / "data"
        source_data.mkdir()

        (source_dir / "project.json").write_text(json.dumps({
            "project_id": "source-id",
            "name": "Source",
            "slug": "source-project",
        }))
        (source_data / "state.json").write_text(json.dumps({
            "vector_memory": {"enabled": False},
            "creative_progress": {},
        }))
        (source_data / "story_spec.json").write_text('{"title": "Test"}')
        canon_dir = source_data / "canon_versions"
        canon_dir.mkdir()

        source_context = get_project_context(source_dir)
        service = ProjectCloneService(workspace_root)

        with patch.object(Path, "is_symlink", return_value=False):
            with patch.object(ProjectCloneService, "_is_junction", return_value=True):
                with pytest.raises(CloneCopyError, match="Junction detected"):
                    service.clone_project(source_context, "Cloned")

    def test_reparse_point_detection_rejects_clone(self, tmp_path):
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        projects_dir = workspace_root / "projects"
        projects_dir.mkdir()

        source_dir = projects_dir / "source-project"
        source_dir.mkdir()
        source_data = source_dir / "data"
        source_data.mkdir()

        (source_dir / "project.json").write_text(json.dumps({
            "project_id": "source-id",
            "name": "Source",
            "slug": "source-project",
        }))
        (source_data / "state.json").write_text(json.dumps({
            "vector_memory": {"enabled": False},
            "creative_progress": {},
        }))
        (source_data / "story_spec.json").write_text('{"title": "Test"}')
        canon_dir = source_data / "canon_versions"
        canon_dir.mkdir()

        source_context = get_project_context(source_dir)
        service = ProjectCloneService(workspace_root)

        mock_stat = MagicMock()
        mock_stat.st_file_attributes = stat_module.FILE_ATTRIBUTE_REPARSE_POINT

        with patch.object(Path, "is_symlink", return_value=False):
            with patch.object(ProjectCloneService, "_is_junction", return_value=False):
                with patch("os.lstat", return_value=mock_stat):
                    with pytest.raises(CloneCopyError, match="reparse point"):
                        service.clone_project(source_context, "Cloned")

    def test_no_links_allows_clone(self, tmp_path):
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        projects_dir = workspace_root / "projects"
        projects_dir.mkdir()

        source_dir = projects_dir / "source-project"
        source_dir.mkdir()
        source_data = source_dir / "data"
        source_data.mkdir()

        (source_dir / "project.json").write_text(json.dumps({
            "project_id": "source-id",
            "name": "Source",
            "slug": "source-project",
        }))
        (source_data / "state.json").write_text(json.dumps({
            "vector_memory": {"enabled": False},
            "creative_progress": {},
        }))
        (source_data / "story_spec.json").write_text('{"title": "Test"}')
        canon_dir = source_data / "canon_versions"
        canon_dir.mkdir()

        source_context = get_project_context(source_dir)
        service = ProjectCloneService(workspace_root)

        with patch("system.vector_index_lifecycle.rebuild_project_index") as mock_rebuild:
            mock_rebuild.return_value = {"status": "success"}

            result = service.clone_project(source_context, "Cloned")

            assert result.status == "completed"
            target_dir = projects_dir / result.project_slug
            assert target_dir.exists()


class TestStagingDeletionGuard:
    """Verify staging cleanup respects workspace boundaries."""

    def test_staging_outside_workspace_not_deleted(self, tmp_path):
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()

        malicious_staging = tmp_path / "outside" / ".clone_malicious"
        malicious_staging.mkdir(parents=True)
        data_dir = malicious_staging / "data"
        data_dir.mkdir()
        (data_dir / "story_spec.json").write_text('{"title": "Malicious"}')

        service = ProjectCloneService(workspace_root)
        service._cleanup_staging(malicious_staging)

        assert malicious_staging.exists()

    def test_staging_not_clone_prefix_not_deleted(self, tmp_path):
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()

        malicious_staging = workspace_root / "not_clone_prefix"
        malicious_staging.mkdir()
        (malicious_staging / "data").mkdir()

        service = ProjectCloneService(workspace_root)
        service._cleanup_staging(malicious_staging)

        assert malicious_staging.exists()

    def test_staging_symlink_not_deleted(self, tmp_path):
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()

        real_dir = tmp_path / "real_staging"
        real_dir.mkdir()
        (real_dir / "data").mkdir()

        staging_link = workspace_root / ".clone_link"

        service = ProjectCloneService(workspace_root)

        with patch.object(Path, "is_symlink", return_value=True):
            service._cleanup_staging(staging_link)

        assert real_dir.exists()

    def test_valid_staging_deleted(self, tmp_path):
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()

        valid_staging = workspace_root / ".clone_valid_123"
        valid_staging.mkdir()
        (valid_staging / "data").mkdir()

        service = ProjectCloneService(workspace_root)
        service._cleanup_staging(valid_staging)

        assert not valid_staging.exists()


class TestCloneCLIIntegration:
    """Test CLI clone-project functionality."""

    def test_cli_clone_success(self, tmp_path):
        from system.project_manager import ProjectManager

        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        projects_dir = workspace_root / "projects"
        projects_dir.mkdir()

        source_dir = projects_dir / "source-project"
        source_dir.mkdir()
        source_data = source_dir / "data"
        source_data.mkdir()

        source_project_id = "source-id-cli"
        (source_dir / "project.json").write_text(json.dumps({
            "project_id": source_project_id,
            "name": "Source Project",
            "slug": "source-project",
            "title": "Source Project",
            "genre": "test",
            "project_root": str(source_dir),
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }))
        (source_data / "state.json").write_text(json.dumps({
            "vector_memory": {"enabled": False},
            "creative_progress": {},
        }))
        (source_data / "story_spec.json").write_text('{"title": "Test"}')
        canon_dir = source_data / "canon_versions"
        canon_dir.mkdir()

        manager = ProjectManager(workspace_root)
        result = manager.clone_project(source_project_id, "CLI Clone", "cli-clone")

        assert result["status"] in ("completed", "completed_with_warnings")
        assert result["project_id"] != source_project_id
        assert result["project_slug"] == "cli-clone"

        target_dir = projects_dir / "cli-clone"
        assert target_dir.exists(), f"Target directory not found: {target_dir}"
        assert (target_dir / "project.json").exists()
        assert (target_dir / "data" / "story_spec.json").exists()

    def test_cli_clone_missing_source(self, tmp_path):
        from system.project_manager import ProjectManager, ProjectManagerError

        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        projects_dir = workspace_root / "projects"
        projects_dir.mkdir()

        manager = ProjectManager(workspace_root)
        with pytest.raises(ProjectManagerError, match="Project not found"):
            manager.clone_project("non-existent", "Test", "test")


class TestCloneWebAPIIntegration:
    """Test Web API clone functionality."""

    def test_api_clone_success(self, tmp_path):
        from system.project_manager import ProjectManager

        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        projects_dir = workspace_root / "projects"
        projects_dir.mkdir()

        source_dir = projects_dir / "source-project"
        source_dir.mkdir()
        source_data = source_dir / "data"
        source_data.mkdir()

        source_project_id = "source-id-api"
        (source_dir / "project.json").write_text(json.dumps({
            "project_id": source_project_id,
            "name": "Source Project",
            "slug": "source-project",
            "title": "Source Project",
            "genre": "test",
            "project_root": str(source_dir),
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }))
        (source_data / "state.json").write_text(json.dumps({
            "vector_memory": {"enabled": False},
            "creative_progress": {},
        }))
        (source_data / "story_spec.json").write_text('{"title": "Test"}')
        canon_dir = source_data / "canon_versions"
        canon_dir.mkdir()

        manager = ProjectManager(workspace_root)
        result = manager.clone_project(source_project_id, "API Clone", "api-clone")

        assert result["status"] in ("completed", "completed_with_warnings")
        assert result["project_id"] != source_project_id
        assert result["project_slug"] == "api-clone"

        target_dir = projects_dir / "api-clone"
        assert target_dir.exists()

    def test_api_clone_empty_name(self, tmp_path):
        from system.project_manager import ProjectManager, ProjectManagerError
        from system.project_clone_service import ProjectCloneService

        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        projects_dir = workspace_root / "projects"
        projects_dir.mkdir()

        source_dir = projects_dir / "source-project"
        source_dir.mkdir()
        source_data = source_dir / "data"
        source_data.mkdir()

        source_project_id = "source-id-api2"
        (source_dir / "project.json").write_text(json.dumps({
            "project_id": source_project_id,
            "name": "Source Project",
            "slug": "source-project",
            "title": "Source Project",
            "genre": "test",
            "project_root": str(source_dir),
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }))
        (source_data / "state.json").write_text(json.dumps({}))
        (source_data / "story_spec.json").write_text('{"title": "Test"}')
        canon_dir = source_data / "canon_versions"
        canon_dir.mkdir()

        with pytest.raises((ProjectManagerError, ValueError)):
            manager = ProjectManager(workspace_root)
            manager.clone_project(source_project_id, "", "api-clone")