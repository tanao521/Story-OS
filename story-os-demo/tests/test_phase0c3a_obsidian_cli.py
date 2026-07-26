from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


class TestObsidianBindCLI:
    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.project_id = str(uuid.uuid4())

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def _run_cli(self, args: list[str], cwd: str | None = None) -> tuple[int, str, str]:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        main_path = Path(__file__).resolve().parents[1] / "main.py"
        result = subprocess.run(
            [sys.executable, str(main_path)] + args,
            capture_output=True,
            text=True,
            cwd=cwd or self.temp_workspace,
            env=env,
        )
        return result.returncode, result.stdout, result.stderr

    def test_bind_success(self):
        returncode, stdout, stderr = self._run_cli([
            "obsidian-bind",
            "--project", self.project_id,
            "--vault", self.temp_vault,
            "--target", "StoryOS/test-project",
        ])
        assert returncode == 0
        result = json.loads(stdout)
        assert result["status"] == "success"
        assert result["outputs"]["project_id"] == self.project_id
        assert result["outputs"]["timeline_id"] == "main"

    def test_bind_with_timeline(self):
        returncode, stdout, stderr = self._run_cli([
            "obsidian-bind",
            "--project", self.project_id,
            "--vault", self.temp_vault,
            "--target", "StoryOS/test-project/exp-a",
            "--timeline", "experiment-a",
        ])
        assert returncode == 0
        result = json.loads(stdout)
        assert result["outputs"]["timeline_id"] == "experiment-a"

    def test_bind_missing_project(self):
        returncode, stdout, stderr = self._run_cli([
            "obsidian-bind",
            "--vault", self.temp_vault,
            "--target", "StoryOS/test",
        ])
        assert returncode == 2

    def test_bind_missing_vault(self):
        returncode, stdout, stderr = self._run_cli([
            "obsidian-bind",
            "--project", self.project_id,
            "--target", "StoryOS/test",
        ])
        assert returncode == 2

    def test_bind_invalid_vault(self):
        returncode, stdout, stderr = self._run_cli([
            "obsidian-bind",
            "--project", self.project_id,
            "--vault", "/nonexistent/vault",
            "--target", "StoryOS/test",
        ])
        assert returncode == 1
        if stdout.strip():
            result = json.loads(stdout)
            assert result["status"] == "failed"
        else:
            assert returncode != 0

    def test_bind_traversal_attack(self):
        returncode, stdout, stderr = self._run_cli([
            "obsidian-bind",
            "--project", self.project_id,
            "--vault", self.temp_vault,
            "--target", "../escape",
        ])
        assert returncode == 1
        if stdout.strip():
            result = json.loads(stdout)
            assert result["status"] == "failed"
        else:
            assert returncode != 0


class TestObsidianStatusCLI:
    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.project_id = str(uuid.uuid4())

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def _run_cli(self, args: list[str]) -> tuple[int, str, str]:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        main_path = Path(__file__).resolve().parents[1] / "main.py"
        result = subprocess.run(
            [sys.executable, str(main_path)] + args,
            capture_output=True,
            text=True,
            cwd=self.temp_workspace,
            env=env,
        )
        return result.returncode, result.stdout, result.stderr

    def test_status_unbound(self):
        returncode, stdout, stderr = self._run_cli([
            "obsidian-status",
            "--project", self.project_id,
        ])
        assert returncode == 0
        result = json.loads(stdout)
        assert result["outputs"]["status"] == "unbound"

    def test_status_with_timeline(self):
        returncode, stdout, stderr = self._run_cli([
            "obsidian-status",
            "--project", self.project_id,
            "--timeline", "experiment-a",
        ])
        assert returncode == 0
        result = json.loads(stdout)
        assert result["outputs"]["status"] == "unbound"
        assert result["outputs"]["timeline_id"] == "experiment-a"


class TestObsidianUnbindCLI:
    def setup_method(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_vault = tempfile.mkdtemp()
        self.project_id = str(uuid.uuid4())

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def _run_cli(self, args: list[str]) -> tuple[int, str, str]:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        main_path = Path(__file__).resolve().parents[1] / "main.py"
        result = subprocess.run(
            [sys.executable, str(main_path)] + args,
            capture_output=True,
            text=True,
            cwd=self.temp_workspace,
            env=env,
        )
        return result.returncode, result.stdout, result.stderr

    def test_unbind_not_found(self):
        returncode, stdout, stderr = self._run_cli([
            "obsidian-unbind",
            "--project", self.project_id,
        ])
        assert returncode == 1
        result = json.loads(stdout)
        assert result["status"] == "failed"


def test_cli_help():
    result = subprocess.run(
        [sys.executable, "main.py", "obsidian-bind", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--project" in result.stdout
    assert "--vault" in result.stdout
    assert "--target" in result.stdout
    assert "--timeline" in result.stdout
