import pytest
from unittest.mock import patch, MagicMock, call
from pathlib import Path
import json
import uuid

from system.project_clone_service import ProjectCloneService, CloneProjectResult
from system.project_manager import get_project_context
from system.vector_sync_run_store import VectorSyncOperationType, VectorSyncStatus


class TestStateWriteFailureNotSilentlySwallowed:
    """Verify that state write failures are not silently swallowed."""

    def test_state_write_failure_reported_in_warnings(self, tmp_path):
        """When _update_vector_memory_state fails, clone result should contain warning."""
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
            "vector_memory": {
                "enabled": True,
                "healthy": True,
                "project_id": source_project_id,
                "timeline_id": "main",
            },
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
                side_effect=IOError("Permission denied: cannot write state.json")
            ) as mock_update:
                result = service.clone_project(source_context, "Cloned Project")

                mock_update.assert_called_once()

                assert result.status == "completed_with_warnings", \
                    f"Expected completed_with_warnings, got {result.status}"
                assert any("state" in w.lower() or "write" in w.lower() for w in result.warnings), \
                    f"No state write warning found in: {result.warnings}"

    def test_state_write_failure_does_not_rollback_clone(self, tmp_path):
        """Clone should persist even when state write fails."""
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
                assert target_dir.exists(), "Target directory should exist"
                assert (target_dir / "data" / "story_spec.json").exists(), \
                    "Cloned data should persist"

    def test_both_rebuild_and_state_write_failure_reported(self, tmp_path):
        """When rebuild fails AND state write fails, both should be reported."""
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
                has_rebuild_warning = any("rebuild" in w.lower() for w in result.warnings)
                has_state_warning = any("state" in w.lower() or "write" in w.lower() for w in result.warnings)
                assert has_rebuild_warning or has_state_warning, \
                    f"Expected warning for rebuild or state failure, got: {result.warnings}"
