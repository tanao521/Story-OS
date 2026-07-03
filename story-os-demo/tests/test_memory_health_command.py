from __future__ import annotations

import sys
import types
from pathlib import Path

import commands


def test_memory_health_command_returns_dict(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = commands.memory_health_command()
    assert isinstance(result, dict)
    assert result["health_version"] == "2.4-A"


def test_memory_health_command_json_output_does_not_fail(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    result = commands.memory_health_command(json_output=True)
    captured = capsys.readouterr()
    assert result["health_version"] == "2.4-A"
    assert "health_version" in captured.out


def test_memory_health_command_full_contains_sections(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = commands.memory_health_command(full=True)
    assert "sections" in result
    assert "project_initialization" in result["sections"]


def test_memory_health_command_does_not_call_deepseek(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    import llm.planning_service as planning_service

    monkeypatch.setattr(
        planning_service,
        "create_deepseek_client",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("DeepSeek called")),
    )
    commands.memory_health_command()


def test_memory_health_command_does_not_call_local_model(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    import llm.openai_compatible_client as client_module

    monkeypatch.setattr(
        client_module.OpenAICompatibleClient,
        "chat_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("local model called")),
    )
    commands.memory_health_command()


def test_memory_health_command_does_not_access_obsidian(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    import system.obsidian_sync as obsidian_sync

    monkeypatch.setattr(
        obsidian_sync,
        "sync_to_obsidian",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("obsidian called")),
    )
    commands.memory_health_command()


def test_memory_health_command_does_not_call_chroma(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    vector_memory = types.ModuleType("system.vector_memory")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("chroma called")

    vector_memory.build_or_update_index = fail_if_called
    monkeypatch.setitem(sys.modules, "system.vector_memory", vector_memory)
    commands.memory_health_command()
