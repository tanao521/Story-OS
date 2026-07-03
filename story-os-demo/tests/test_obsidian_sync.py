from __future__ import annotations

import json
from pathlib import Path

from system.obsidian_sync import (
    OBSIDIAN_DIRS,
    ensure_obsidian_structure,
    load_local_config,
    save_local_config,
    sync_to_obsidian,
)


def make_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "story_spec.json").write_text(
        json.dumps({"title": "测试小说"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (data_dir / "project.md").write_text("# 项目", encoding="utf-8")
    (data_dir / "characters.json").write_text(
        json.dumps(
            {
                "main_characters": [
                    {
                        "id": "char_001",
                        "name": "测试/角色",
                        "role": "主角",
                        "age": "待定",
                        "gender": "未知",
                        "appearance": "灰尘里的轮廓",
                        "personality": ["谨慎"],
                        "core_desire": "活下去",
                        "core_fear": "失去选择",
                        "current_state": {"physical": "可行动", "mental": "警惕"},
                        "voice_profile": {"tone": "克制"},
                        "relationships": {},
                    }
                ],
                "supporting_characters": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (data_dir / "state.json").write_text(
        json.dumps(
            {
                "foreshadows": [
                    {"id": "fs_001", "content": "门后的异常", "status": "open", "introduced_at": "chapter_001", "importance": "medium"}
                ],
                "timeline": [
                    {"chapter_id": 1, "chapter_title": "第一章", "event": "发现异常", "time_note": "未明确时间"}
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return data_dir


def test_save_and_load_local_config(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = {"obsidian_vault_dir": "D:/Vault", "obsidian_project_dir_name": "StoryOS"}

    save_local_config(config)

    assert load_local_config() == config


def test_ensure_obsidian_structure_creates_project_dir(tmp_path) -> None:
    result = ensure_obsidian_structure(tmp_path, "StoryOS")

    assert (tmp_path / "StoryOS").exists()
    assert result["project_root"].endswith("StoryOS")


def test_ensure_obsidian_structure_creates_all_subdirs(tmp_path) -> None:
    ensure_obsidian_structure(tmp_path, "StoryOS")

    assert all((tmp_path / "StoryOS" / directory).exists() for directory in OBSIDIAN_DIRS)


def test_sync_to_obsidian_returns_dict(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    data_dir = make_data_dir(tmp_path)

    result = sync_to_obsidian(data_dir, tmp_path / "Vault", "StoryOS")

    assert isinstance(result, dict)


def test_sync_version_is_0_8(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    data_dir = make_data_dir(tmp_path)

    result = sync_to_obsidian(data_dir, tmp_path / "Vault", "StoryOS")

    assert result["sync_version"] == "0.8"


def test_sync_generates_index(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    data_dir = make_data_dir(tmp_path)

    result = sync_to_obsidian(data_dir, tmp_path / "Vault", "StoryOS")

    assert Path(result["index_path"]).exists()


def test_sync_generates_story_spec_markdown(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    data_dir = make_data_dir(tmp_path)

    sync_to_obsidian(data_dir, tmp_path / "Vault", "StoryOS")

    assert (tmp_path / "Vault" / "StoryOS" / "00_Project" / "Story_Spec.md").exists()


def test_sync_generates_character_markdown(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    data_dir = make_data_dir(tmp_path)

    sync_to_obsidian(data_dir, tmp_path / "Vault", "StoryOS")

    files = list((tmp_path / "Vault" / "StoryOS" / "02_Characters").glob("char_001_*.md"))
    assert files


def test_sync_generates_foreshadows_markdown(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    data_dir = make_data_dir(tmp_path)

    sync_to_obsidian(data_dir, tmp_path / "Vault", "StoryOS")

    assert (tmp_path / "Vault" / "StoryOS" / "05_Foreshadows" / "Foreshadows.md").exists()


def test_sync_generates_timeline_markdown(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    data_dir = make_data_dir(tmp_path)

    sync_to_obsidian(data_dir, tmp_path / "Vault", "StoryOS")

    assert (tmp_path / "Vault" / "StoryOS" / "06_Timeline" / "Timeline.md").exists()


def test_sync_does_not_create_project_vault_dir(tmp_path, monkeypatch) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)
    data_dir = make_data_dir(project_dir)

    sync_to_obsidian(data_dir, tmp_path / "ObsidianVault", "StoryOS")

    assert not (project_dir / "vault").exists()


def test_missing_optional_files_record_warnings(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "story_spec.json").write_text("{}", encoding="utf-8")

    result = sync_to_obsidian(data_dir, tmp_path / "Vault", "StoryOS")

    assert result["warnings"]



def test_sync_generates_todos_markdown(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    data_dir = make_data_dir(tmp_path)
    todos_dir = data_dir / "todos"
    todos_dir.mkdir()
    (todos_dir / "todos.md").write_text("# Story OS 待办事项", encoding="utf-8")

    sync_to_obsidian(data_dir, tmp_path / "Vault", "StoryOS")

    assert (tmp_path / "Vault" / "StoryOS" / "13_Todos" / "Todos.md").exists()
