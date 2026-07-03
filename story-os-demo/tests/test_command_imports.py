from __future__ import annotations

import importlib
import py_compile
from pathlib import Path


def test_core_command_files_py_compile() -> None:
    for path in [
        "main.py",
        "commands.py",
        "system/status_dashboard.py",
        "system/memory_health.py",
        "system/self_check.py",
        "web/routes.py",
    ]:
        py_compile.compile(path, doraise=True)


def test_commands_and_self_check_import() -> None:
    commands = importlib.import_module("commands")
    self_check = importlib.import_module("system.self_check")

    assert hasattr(commands, "self_check_command")
    assert hasattr(self_check, "run_self_check")
    assert Path("system/self_check.py").exists()
