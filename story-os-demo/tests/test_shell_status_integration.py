from __future__ import annotations

import json
from pathlib import Path

from system.obsidian_sync import OBSIDIAN_DIRS, save_local_config, sync_to_obsidian
from system.status_dashboard import build_status_dashboard


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def prepare_project(root: Path) -> Path:
    data_dir = root / "data"
    data_dir.mkdir(exist_ok=True)
    write_json(data_dir / "story_spec.json", {"title": "Shell Novel"})
    write_json(data_dir / "story_blueprint.json", {"title": "Shell Novel"})
    write_json(data_dir / "characters.json", {"main_characters": []})
    write_json(data_dir / "world_bible.json", {"core_rules": []})
    write_json(data_dir / "state.json", {"current_chapter": 1})
    return data_dir


def test_status_contains_shell_available(tmp_path: Path) -> None:
    prepare_project(tmp_path)

    status = build_status_dashboard(tmp_path / "data")

    assert status["shell"]["available"] is True
    assert status["shell"]["aliases_enabled"] is True


def test_obsidian_dirs_include_shell_logs() -> None:
    assert "15_Shell_Logs" in OBSIDIAN_DIRS


def test_sync_obsidian_does_not_sync_shell_logs_by_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    data_dir = prepare_project(tmp_path)
    shell_dir = data_dir / "shell_logs"
    shell_dir.mkdir()
    (shell_dir / "shell_20260101_000000.log").write_text("[time] command: status", encoding="utf-8")

    sync_to_obsidian(data_dir, tmp_path / "Vault", "StoryOS")

    assert not (tmp_path / "Vault" / "StoryOS" / "15_Shell_Logs" / "shell_20260101_000000.log").exists()


def test_sync_obsidian_syncs_shell_logs_when_config_enabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    data_dir = prepare_project(tmp_path)
    shell_dir = data_dir / "shell_logs"
    shell_dir.mkdir()
    (shell_dir / "shell_20260101_000000.log").write_text("[time] command: status", encoding="utf-8")
    save_local_config({"sync_shell_logs_to_obsidian": True})

    sync_to_obsidian(data_dir, tmp_path / "Vault", "StoryOS")

    assert (tmp_path / "Vault" / "StoryOS" / "15_Shell_Logs" / "shell_20260101_000000.log").exists()
