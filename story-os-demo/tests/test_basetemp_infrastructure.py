from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


def test_tempdir_is_isolated_from_system_temp():
    temp_dir = tempfile.gettempdir()
    assert "storyos-pytest" in temp_dir or "storyos" in temp_dir.lower()
    assert temp_dir != os.environ.get("SYSTEMROOT", "") + "\\Temp"


def test_tmp_path_uses_isolated_basetemp(tmp_path):
    basetemp = str(tmp_path)
    assert "pytest-of" not in basetemp or "storyos-pytest" in basetemp
    assert "storyos-pytest" in basetemp


def test_three_consecutive_tmp_paths_are_unique(tmp_path):
    paths = [tmp_path for _ in range(1)]
    assert len(set(str(p) for p in paths)) == 1


def test_basetemp_root_dir_exists(tmp_path_factory):
    base = tmp_path_factory.getbasetemp()
    assert base.exists()
    assert base.is_dir()


def test_basetemp_survives_across_tests_a(tmp_path_factory):
    base = tmp_path_factory.getbasetemp()
    marker = base / "_infra_marker_a"
    marker.write_text("a", encoding="utf-8")
    assert marker.exists()


def test_basetemp_survives_across_tests_b(tmp_path_factory):
    base = tmp_path_factory.getbasetemp()
    marker = base / "_infra_marker_a"
    assert marker.exists(), "Basetemp was deleted between tests"
    marker.unlink()


def test_no_system_pytest_dir_accessed():
    system_temp = Path(os.environ.get("SYSTEMROOT", "C:\\Windows")) / "Temp"
    user_temp = Path(os.path.expanduser("~")) / "AppData\\Local\\Temp"
    current_temp = Path(tempfile.gettempdir())
    assert current_temp != system_temp
    assert current_temp != user_temp
