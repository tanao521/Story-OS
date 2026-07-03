from __future__ import annotations

from pathlib import Path
from typing import Any

import main
from system.interactive_shell import (
    append_shell_log,
    execute_shell_command,
    get_shell_help_text,
    normalize_shell_args,
    parse_shell_command,
    render_shell_result,
)


def test_parse_shell_command_empty_returns_empty() -> None:
    assert parse_shell_command("") == []


def test_parse_shell_command_status() -> None:
    assert parse_shell_command("status") == ["status"]


def test_parse_shell_command_quoted_argument() -> None:
    assert parse_shell_command('todo add "重写第3章结尾" --chapter 3') == [
        "todo",
        "add",
        "重写第3章结尾",
        "--chapter",
        "3",
    ]


def test_normalize_shell_args_merges_ask_state_question() -> None:
    args = normalize_shell_args(["ask-state", "现在还有哪些", "open", "伏笔？"])

    assert args == ["ask-state", "现在还有哪些 open 伏笔？"]


def test_normalize_shell_args_keeps_json_flag() -> None:
    args = normalize_shell_args(["ask-story", "第3章", "注意什么？", "--llm", "--json"])

    assert args == ["ask-story", "第3章 注意什么？", "--llm", "--json"]


def test_alias_s_maps_to_status() -> None:
    assert normalize_shell_args(["s"]) == ["status"]


def test_alias_state_maps_to_ask_state() -> None:
    assert normalize_shell_args(["state", "还有", "open", "伏笔"]) == ["ask-state", "还有 open 伏笔"]


def test_get_shell_help_text_contains_status() -> None:
    assert "status" in get_shell_help_text()


def test_unknown_command_returns_not_ok() -> None:
    result = execute_shell_command(["not-a-command"])

    assert result["ok"] is False


def test_execute_shell_command_catches_exception(monkeypatch: Any) -> None:
    def boom() -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(main, "main", boom)

    result = execute_shell_command(["status"])

    assert result["ok"] is False
    assert "boom" in result["errors"][0]


def test_render_shell_result_renders_error() -> None:
    text = render_shell_result({"ok": False, "errors": ["缺少 story_blueprint.json"]})

    assert "命令执行失败" in text
    assert "缺少 story_blueprint.json" in text


def test_append_shell_log_writes_log(tmp_path: Path) -> None:
    append_shell_log("status", True, tmp_path / "data")

    logs = list((tmp_path / "data" / "shell_logs").glob("shell_*.log"))

    assert logs
    assert "command: status" in logs[0].read_text(encoding="utf-8")
