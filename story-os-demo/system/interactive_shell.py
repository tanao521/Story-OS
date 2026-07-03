from __future__ import annotations

import contextlib
import io
import shlex
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from system.status_dashboard import build_status_dashboard


SHELL_VERSION = "2.0"
ALIASES: dict[str, list[str]] = {
    "s": ["status"],
    "sf": ["status", "--full"],
    "r": ["run-chapter"],
    "review": ["review-draft"],
    "qc": ["quality-check"],
    "cmp": ["compare-drafts"],
    "td": ["todo", "list"],
    "ask": ["ask-story"],
    "mem": ["ask-memory"],
    "state": ["ask-state"],
    "ctx": ["build-context"],
    "sync": ["sync-obsidian"],
    "idx": ["index-vault"],
}
EXIT_COMMANDS = {"exit", "quit", "q"}
HELP_COMMANDS = {"help", "?"}
SUPPORTED_COMMANDS = {
    "status",
    "setup",
    "blueprint",
    "build-assets",
    "build-context",
    "plan-next",
    "write-draft",
    "edit-draft",
    "run-chapter",
    "review-draft",
    "commit-chapter",
    "regenerate-draft",
    "reedit-draft",
    "compare-drafts",
    "quality-check",
    "todo",
    "ask-state",
    "ask-memory",
    "ask-story",
    "search-memory",
    "sync-obsidian",
    "index-vault",
    "check-llm",
}
VALUE_FLAGS = {
    "--chapter",
    "--type",
    "--priority",
    "--report",
    "--select",
    "--edited-version",
    "--draft-version",
}
SENSITIVE_MARKERS = ("API_KEY", "api_key", "sk-", "key=")
_SHELL_LOG_PATH: Path | None = None


def parse_shell_command(line: str) -> list[str]:
    if not line.strip():
        return []
    try:
        return shlex.split(line)
    except ValueError:
        return line.strip().split()


def normalize_shell_args(args: list[str]) -> list[str]:
    if not args:
        return []
    command = args[0]
    rest = args[1:]
    if command in ALIASES:
        mapped = ALIASES[command] + rest
        return normalize_shell_args(mapped)
    if command == "search-memory":
        command = "ask-memory"
    if command in {"ask-state", "ask-memory", "ask-story"}:
        return _normalize_question_command(command, rest)
    if command == "todo" and rest and rest[0] in {"add", "edit"}:
        return _normalize_todo_text(args)
    return [command] + rest


def get_shell_help_text() -> str:
    return """Story OS Shell 命令：

基础：
  help                         显示帮助
  status                       查看项目状态
  status --full                查看完整状态
  exit                         退出

写作流水线：
  run-chapter                  生成下一章到待审核
  review-draft                 审核当前草稿
  quality-check                评估当前选中版本
  compare-drafts               查看所有版本

版本：
  regenerate-draft             重新生成草稿
  reedit-draft                 重新编辑草稿
  compare-drafts --select edited:1

待办：
  todo list
  todo add "任务内容" --chapter 3 --type revision --priority high
  todo done 1
  todo reopen 1
  todo from-quality

问答：
  ask-state 现在有哪些 open 伏笔？
  ask-memory 钱满仓什么时候提到过传销组织？
  ask-story 第3章写作前要注意什么？

记忆：
  build-context
  sync-obsidian
  index-vault
  search-memory 关键词

别名：
  s=status, sf=status --full, r=run-chapter, review=review-draft
  qc=quality-check, cmp=compare-drafts, td=todo list
  state=ask-state, mem=ask-memory, ask=ask-story
  ctx=build-context, sync=sync-obsidian, idx=index-vault

退出：
  exit
  quit
  q
"""


def execute_shell_command(args: list[str]) -> dict[str, Any]:
    normalized = normalize_shell_args(args)
    command = normalized[0] if normalized else ""
    if not normalized:
        return {"ok": True, "command": "", "message": "", "result": {}, "warnings": [], "errors": []}
    if command in HELP_COMMANDS:
        return {"ok": True, "command": command, "message": get_shell_help_text(), "result": {}, "warnings": [], "errors": []}
    if command in EXIT_COMMANDS:
        return {"ok": True, "command": command, "message": "退出 Story OS 创作控制台。", "result": {}, "warnings": [], "errors": []}
    if command not in SUPPORTED_COMMANDS:
        return {
            "ok": False,
            "command": command,
            "message": f"未知或尚未实现的命令：{command}",
            "result": {},
            "warnings": [],
            "errors": [f"未知或尚未实现的命令：{command}"],
        }
    try:
        output = _run_main_command(normalized)
    except Exception as exc:
        return {
            "ok": False,
            "command": command,
            "message": "命令执行失败",
            "result": {},
            "warnings": [],
            "errors": [str(exc)],
        }
    return {
        "ok": True,
        "command": command,
        "message": output.strip(),
        "result": {"args": normalized, "output": output},
        "warnings": [],
        "errors": [],
    }


def render_shell_result(result: dict[str, Any]) -> str:
    if result.get("ok"):
        return str(result.get("message", "")).rstrip() + "\n" if result.get("message") else ""
    lines = ["命令执行失败："]
    errors = result.get("errors", [])
    lines.extend(f"- {error}" for error in errors)
    lines.extend(["", "你可以运行：", "status", "查看下一步建议。"])
    return "\n".join(lines) + "\n"


def append_shell_log(command: str, ok: bool, data_dir: str | Path = "data") -> None:
    if _is_sensitive(command):
        return
    path = _shell_log_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with path.open("a", encoding="utf-8") as file:
        file.write(f"[{timestamp}] command: {command}\n")
        file.write(f"[{timestamp}] ok: {str(ok).lower()}\n")


def run_interactive_shell() -> None:
    _setup_history()
    print(_startup_text())
    while True:
        try:
            line = input("story-os> ")
        except KeyboardInterrupt:
            print("\n已取消当前输入。输入 exit 退出。")
            continue
        except EOFError:
            print("\n已退出 Story OS 创作控制台。")
            _save_history()
            break
        args = normalize_shell_args(parse_shell_command(line))
        if not args:
            continue
        if args[0] in EXIT_COMMANDS:
            print("已退出 Story OS 创作控制台。")
            append_shell_log(" ".join(args), True)
            _save_history()
            break
        if args[0] in HELP_COMMANDS:
            print(get_shell_help_text())
            continue
        result = execute_shell_command(args)
        append_shell_log(" ".join(args), bool(result.get("ok")))
        print(render_shell_result(result), end="")


def _normalize_question_command(command: str, rest: list[str]) -> list[str]:
    question_parts: list[str] = []
    flags: list[str] = []
    index = 0
    while index < len(rest):
        item = rest[index]
        if item.startswith("--"):
            flags.append(item)
            if item in VALUE_FLAGS and index + 1 < len(rest):
                flags.append(rest[index + 1])
                index += 2
                continue
        else:
            question_parts.append(item)
        index += 1
    question = " ".join(question_parts).strip()
    return [command] + ([question] if question else []) + flags


def _normalize_todo_text(args: list[str]) -> list[str]:
    command, action, *rest = args
    prefix = [command, action]
    if action == "edit" and rest:
        prefix.append(rest[0])
        rest = rest[1:]
    title_parts: list[str] = []
    tail: list[str] = []
    index = 0
    while index < len(rest):
        item = rest[index]
        if item.startswith("--"):
            tail.append(item)
            if item in VALUE_FLAGS and index + 1 < len(rest):
                tail.append(rest[index + 1])
                index += 2
                continue
        else:
            title_parts.append(item)
        index += 1
    title = " ".join(title_parts).strip()
    return prefix + ([title] if title else []) + tail


def _run_main_command(args: list[str]) -> str:
    import main

    old_argv = sys.argv[:]
    buffer = io.StringIO()
    try:
        sys.argv = ["main.py"] + args
        with contextlib.redirect_stdout(buffer):
            main.main()
    finally:
        sys.argv = old_argv
    return buffer.getvalue()


def _startup_text() -> str:
    lines = [f"Story OS 创作控制台 v{SHELL_VERSION}", ""]
    try:
        status = build_status_dashboard()
        project = status.get("project", {})
        progress = status.get("progress", {})
        actions = status.get("next_actions", [])
        lines.extend([
            f"项目：{project.get('title', '') or '未命名'}",
            f"当前章节：第{progress.get('current_chapter', 0)}章",
            f"当前阶段：{progress.get('current_stage', '') or '未知'}",
            f"下一步建议：{actions[0].get('command', 'status') if actions else 'status'}",
            "",
        ])
    except Exception:
        lines.extend(["状态读取失败，但你仍然可以使用 shell。", "输入 status 查看详情。", ""])
    lines.extend(["输入 help 查看命令。", "输入 exit 退出。"])
    return "\n".join(lines)


def _setup_history() -> None:
    try:
        import readline  # type: ignore
    except ImportError:
        return
    history_path = Path(".story_os") / "shell_history.txt"
    if history_path.exists():
        try:
            readline.read_history_file(history_path)
        except Exception:
            return


def _save_history() -> None:
    try:
        import readline  # type: ignore
    except ImportError:
        return
    history_path = Path(".story_os") / "shell_history.txt"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    entries = [
        readline.get_history_item(index)
        for index in range(1, readline.get_current_history_length() + 1)
    ]
    safe_entries = [entry for entry in entries if entry and not _is_sensitive(entry)]
    history_path.write_text("\n".join(safe_entries) + ("\n" if safe_entries else ""), encoding="utf-8")


def _shell_log_path(data_dir: str | Path) -> Path:
    global _SHELL_LOG_PATH
    if _SHELL_LOG_PATH is None or not str(_SHELL_LOG_PATH).startswith(str(Path(data_dir))):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        _SHELL_LOG_PATH = Path(data_dir) / "shell_logs" / f"shell_{stamp}.log"
    return _SHELL_LOG_PATH


def _is_sensitive(text: str) -> bool:
    return any(marker in text for marker in SENSITIVE_MARKERS)
