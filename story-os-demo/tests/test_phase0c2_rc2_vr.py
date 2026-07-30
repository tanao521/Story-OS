"""Phase 0C2-RC2-VR: Final independent verification of RC2 fixes.

Focuses on:
- Real CLI subprocess clone verification
- Real FastAPI TestClient clone verification
- HTTP status code verification
- Static code analysis for except Exception: pass
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


class TestStaticExceptionPass:
    """Static verification that state write failures are not silently swallowed."""

    def test_no_except_pass_in_vector_state_update(self):
        """Verify _rebuild_vector_index does not contain except Exception: pass."""
        import inspect
        from system.project_clone_service import ProjectCloneService

        source = inspect.getsource(ProjectCloneService._rebuild_vector_index)
        lines = source.splitlines()

        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped == "except Exception:":
                next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
                assert next_line != "pass", (
                    f"Found 'except Exception: pass' at line {i + 1} "
                    f"in _rebuild_vector_index. State write failures must not be silently swallowed."
                )

    def test_vector_state_update_failure_propagates_as_warning(self):
        """Verify clone refuses an implicit vector rebuild without branch/canon scope."""
        import inspect
        from system.project_clone_service import ProjectCloneService

        source = inspect.getsource(ProjectCloneService._rebuild_vector_index)
        assert "VECTOR_SCOPE_REQUIRED" in source, (
            "_rebuild_vector_index must fail closed until explicit vector scope exists"
        )
        assert "rebuild_project_index(" not in source


class TestRealCLISubprocess:
    """Real CLI subprocess verification of clone-project command."""

    def _prepare_workspace(self, tmp_path: Path) -> tuple[Path, Path, str]:
        """Prepare a temporary workspace with a source project for CLI testing."""
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        projects_dir = workspace_root / "projects"
        projects_dir.mkdir()

        source_dir = projects_dir / "source-project"
        source_dir.mkdir()
        source_data = source_dir / "data"
        source_data.mkdir()

        source_project_id = "source-cli-vr-id"
        with open(source_dir / "project.json", "w", encoding="utf-8") as f:
            json.dump({
                "project_id": source_project_id,
                "name": "Source Project",
                "slug": "source-project",
                "title": "Source Project",
                "genre": "test",
                "project_root": "projects/source-project",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            }, f)

        with open(source_data / "state.json", "w", encoding="utf-8") as f:
            json.dump({
                "vector_memory": {"enabled": False},
                "creative_progress": {},
            }, f)

        with open(source_data / "story_spec.json", "w", encoding="utf-8") as f:
            json.dump({"title": "Test"}, f)

        canon_dir = source_data / "canon_versions"
        canon_dir.mkdir()

        story_os_dir = workspace_root / ".story_os"
        story_os_dir.mkdir()

        with open(story_os_dir / "projects.json", "w", encoding="utf-8") as f:
            json.dump({
                "schema_version": 1,
                "projects": [{
                    "project_id": source_project_id,
                    "slug": "source-project",
                    "title": "Source Project",
                    "genre": "test",
                    "project_root": "projects/source-project",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z",
                    "active": True,
                }]
            }, f)

        with open(story_os_dir / "config.json", "w", encoding="utf-8") as f:
            json.dump({"active_project": "projects/source-project"}, f)

        return workspace_root, projects_dir, source_project_id

    def test_cli_help_displays_options(self, tmp_path):
        """Verify CLI help displays required options."""
        demo_dir = Path(__file__).parent.parent
        result = subprocess.run(
            [sys.executable, str(demo_dir / "main.py"), "clone-project", "--help"],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            timeout=30
        )

        assert result.returncode == 0
        assert "--source" in result.stdout or "--source" in result.stderr
        assert "--name" in result.stdout or "--name" in result.stderr

    @pytest.mark.timeout(180)
    def test_real_cli_clone_success(self, tmp_path):
        """Real CLI subprocess clone with temporary workspace."""
        workspace_root, projects_dir, source_project_id = self._prepare_workspace(tmp_path)
        demo_dir = Path(__file__).parent.parent

        source_hash_before = self._dir_hash(projects_dir / "source-project")

        result = subprocess.run(
            [
                sys.executable, str(demo_dir / "main.py"), "clone-project",
                "--source", source_project_id,
                "--name", "CLI VR Clone",
                "--slug", "cli-vr-clone"
            ],
            cwd=str(workspace_root),
            capture_output=True,
            text=True,
            timeout=180
        )

        assert result.returncode == 0, f"CLI failed: stdout={result.stdout[:500]}, stderr={result.stderr[:500]}"

        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"CLI output is not valid JSON: {result.stdout[:500]}")

        assert output.get("name") == "clone-project", (
            f"Unexpected command name. Full output: {json.dumps(output, indent=2, ensure_ascii=False)[:1500]}"
        )
        assert output.get("status") == "success", (
            f"CLI clone failed with status={output.get('status')}. "
            f"Full output: {json.dumps(output, indent=2, ensure_ascii=False)[:2000]}"
        )
        assert "outputs" in output

        target_dir = projects_dir / "cli-vr-clone"
        assert target_dir.exists(), "Target project directory was not created"
        assert (target_dir / "project.json").exists()
        assert (target_dir / "data" / "story_spec.json").exists()

        with open(target_dir / "project.json") as f:
            target_meta = json.load(f)
        assert target_meta["project_id"] != source_project_id
        assert target_meta["cloned_from_project_id"] == source_project_id

        source_hash_after = self._dir_hash(projects_dir / "source-project")
        assert source_hash_before == source_hash_after, "Source project was modified during clone"

    def test_cli_clone_missing_source_returns_nonzero_exit(self, tmp_path):
        """CLI clone with nonexistent source returns exit code 1."""
        workspace_root, projects_dir, _ = self._prepare_workspace(tmp_path)
        demo_dir = Path(__file__).parent.parent

        result = subprocess.run(
            [
                sys.executable, str(demo_dir / "main.py"), "clone-project",
                "--source", "non-existent-id",
                "--name", "Test Clone",
                "--slug", "test-clone"
            ],
            cwd=str(workspace_root),
            capture_output=True,
            text=True,
            timeout=60
        )

        assert result.returncode == 1, f"Expected exit code 1 for missing source, got {result.returncode}"

    def test_cli_clone_missing_name_returns_exit_code_2(self, tmp_path):
        """CLI clone with missing name returns exit code 2 (parameter error)."""
        workspace_root, _ = tmp_path / "workspace", tmp_path / "workspace" / "projects"
        demo_dir = Path(__file__).parent.parent

        result = subprocess.run(
            [
                sys.executable, str(demo_dir / "main.py"), "clone-project",
                "--source", "any-id",
            ],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            timeout=60
        )

        assert result.returncode == 2, f"Expected exit code 2 for missing name, got {result.returncode}"

    def _dir_hash(self, path: Path) -> str:
        """Simple hash of directory contents for comparison."""
        import hashlib
        h = hashlib.md5()
        if not path.exists():
            return ""
        for file_path in sorted(path.rglob("*")):
            if file_path.is_file():
                h.update(file_path.name.encode())
                try:
                    h.update(file_path.read_bytes())
                except (OSError, PermissionError):
                    pass
        return h.hexdigest()


class TestRealFastAPITestClient:
    """Real FastAPI TestClient verification of clone endpoint."""

    def _prepare_workspace(self, tmp_path: Path) -> tuple[Path, Path, str]:
        """Prepare a temporary workspace for TestClient testing."""
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        projects_dir = workspace_root / "projects"
        projects_dir.mkdir()

        source_dir = projects_dir / "source-project"
        source_dir.mkdir()
        source_data = source_dir / "data"
        source_data.mkdir()

        source_project_id = "source-api-vr-id"
        with open(source_dir / "project.json", "w", encoding="utf-8") as f:
            json.dump({
                "project_id": source_project_id,
                "name": "Source Project",
                "slug": "source-project",
                "title": "Source Project",
                "genre": "test",
                "project_root": "projects/source-project",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            }, f)

        with open(source_data / "state.json", "w", encoding="utf-8") as f:
            json.dump({
                "vector_memory": {"enabled": False},
                "creative_progress": {},
            }, f)

        with open(source_data / "story_spec.json", "w", encoding="utf-8") as f:
            json.dump({"title": "Test"}, f)

        canon_dir = source_data / "canon_versions"
        canon_dir.mkdir()

        story_os_dir = workspace_root / ".story_os"
        story_os_dir.mkdir()

        with open(story_os_dir / "projects.json", "w", encoding="utf-8") as f:
            json.dump({
                "schema_version": 1,
                "projects": [{
                    "project_id": source_project_id,
                    "slug": "source-project",
                    "title": "Source Project",
                    "genre": "test",
                    "project_root": "projects/source-project",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z",
                    "active": True,
                }]
            }, f)

        with open(story_os_dir / "config.json", "w", encoding="utf-8") as f:
            json.dump({"active_project": "projects/source-project"}, f)

        return workspace_root, projects_dir, source_project_id

    @pytest.mark.timeout(120)
    def test_api_clone_success_via_testclient(self, tmp_path):
        """Real TestClient POST /api/projects/{id}/clone with temporary workspace."""
        workspace_root, projects_dir, source_project_id = self._prepare_workspace(tmp_path)

        original_cwd = os.getcwd()
        os.chdir(str(workspace_root))
        try:
            from web.app import app
            from fastapi.testclient import TestClient

            with TestClient(app) as client:
                response = client.post(
                    f"/api/projects/{source_project_id}/clone",
                    json={"name": "API VR Clone", "slug": "api-vr-clone"}
                )

                assert response.status_code == 200, (
                    f"Expected 200, got {response.status_code}. "
                    f"Response: {response.text[:500]}"
                )
                data = response.json()

                result = data.get("result", {})
                assert result.get("project_id") != source_project_id
                assert result.get("project_slug") == "api-vr-clone"
                assert result.get("status") in ("completed", "completed_with_warnings")
        finally:
            os.chdir(original_cwd)

        target_dir = projects_dir / "api-vr-clone"
        assert target_dir.exists(), "Target directory was not created"
        assert (target_dir / "project.json").exists()

    def test_api_clone_missing_name_returns_400(self, tmp_path):
        """Verify missing name returns 400 status code."""
        workspace_root, projects_dir, source_project_id = self._prepare_workspace(tmp_path)

        original_cwd = os.getcwd()
        os.chdir(str(workspace_root))
        try:
            from web.app import app
            from fastapi.testclient import TestClient

            with TestClient(app) as client:
                response = client.post(
                    f"/api/projects/{source_project_id}/clone",
                    json={"slug": "no-name-clone"}
                )

                assert response.status_code == 400, (
                    f"Expected 400 for missing name, got {response.status_code}. "
                    f"Response: {response.text[:500]}"
                )
        finally:
            os.chdir(original_cwd)

    def test_api_clone_nonexistent_source_returns_404(self, tmp_path):
        """Verify nonexistent source returns 404 status code."""
        workspace_root, projects_dir, _ = self._prepare_workspace(tmp_path)

        original_cwd = os.getcwd()
        os.chdir(str(workspace_root))
        try:
            from web.app import app
            from fastapi.testclient import TestClient

            with TestClient(app) as client:
                response = client.post(
                    "/api/projects/non-existent-id/clone",
                    json={"name": "Test Clone", "slug": "test-clone"}
                )

                assert response.status_code == 404, (
                    f"Expected 404 for nonexistent source, got {response.status_code}. "
                    f"Response: {response.text[:500]}"
                )
        finally:
            os.chdir(original_cwd)


class TestJunctionReparsePointVR:
    """Independent verification of junction/reparse point detection."""

    def test_is_link_or_reparse_point_detects_symlink(self, tmp_path):
        """Verify _is_link_or_reparse_point detects symlinks via monkeypatch."""
        from unittest.mock import patch
        from system.project_clone_service import ProjectCloneService

        test_path = tmp_path / "test_dir"
        test_path.mkdir()

        original_is_symlink = Path.is_symlink

        def mock_is_symlink(self):
            if str(self) == str(test_path):
                return True
            return original_is_symlink(self)

        with patch.object(Path, "is_symlink", mock_is_symlink):
            assert ProjectCloneService._is_link_or_reparse_point(test_path) is True

    def test_is_link_or_reparse_point_detects_junction(self, tmp_path):
        """Verify _is_link_or_reparse_point detects junctions via monkeypatch."""
        from unittest.mock import patch
        from system.project_clone_service import ProjectCloneService

        test_path = tmp_path / "junction_dir"
        test_path.mkdir()

        with patch.object(ProjectCloneService, "_is_junction", return_value=True):
            with patch.object(Path, "is_symlink", return_value=False):
                assert ProjectCloneService._is_link_or_reparse_point(test_path) is True

    def test_is_link_or_reparse_point_detects_reparse_point(self, tmp_path):
        """Verify _is_link_or_reparse_point detects reparse points via monkeypatch."""
        from unittest.mock import patch
        from system.project_clone_service import ProjectCloneService

        test_path = tmp_path / "reparse_dir"
        test_path.mkdir()

        with patch.object(ProjectCloneService, "_is_reparse_point", return_value=True):
            with patch.object(Path, "is_symlink", return_value=False):
                with patch.object(ProjectCloneService, "_is_junction", return_value=False):
                    assert ProjectCloneService._is_link_or_reparse_point(test_path) is True

    def test_normal_dir_not_detected_as_link(self, tmp_path):
        """Verify normal directories are not detected as links."""
        from system.project_clone_service import ProjectCloneService

        normal_dir = tmp_path / "normal_dir"
        normal_dir.mkdir()

        assert ProjectCloneService._is_link_or_reparse_point(normal_dir) is False
