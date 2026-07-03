from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any


REQUIRED_PATHS = [
    "main.py",
    "commands.py",
    "data",
    "web",
    "system",
    "AGENTS.md",
    "PROJECT_ROADMAP.md",
    "README.md",
]

IMPORT_TARGETS = [
    "commands",
    "web.routes",
    "system.memory_health",
    "system.status_dashboard",
]

COMMAND_FUNCTIONS = [
    "build_context_command",
    "plan_next_command",
    "write_draft_command",
    "edit_draft_command",
    "quality_check_command",
    "memory_health_command",
]


def run_self_check(project_root: str | Path = ".") -> dict[str, Any]:
    root = Path(project_root)
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    infos: list[str] = []

    for relative in REQUIRED_PATHS:
        path = root / relative
        if path.exists():
            _add_check(checks, "path_exists", "ok", f"{relative} exists", relative)
        else:
            message = f"{relative} not found."
            _add_check(checks, "path_exists", "error", message, relative)
            errors.append(message)

    env_path = root / ".env"
    if env_path.exists():
        message = ".env exists but self-check does not read or print it."
        _add_check(checks, "secret_safety", "info", message, ".env")
        infos.append(message)
    else:
        _add_check(checks, "secret_safety", "ok", ".env not found; no secret file inspected.", ".env")

    for module_name in IMPORT_TARGETS:
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            message = f"{module_name} import failed: {exc}"
            _add_check(checks, "import", "error", message, module_name)
            errors.append(message)
            continue
        _add_check(checks, "import", "ok", f"{module_name} import ok", module_name)
        if module_name == "commands":
            for function_name in COMMAND_FUNCTIONS:
                if hasattr(module, function_name):
                    _add_check(checks, "command_function", "ok", f"commands.{function_name} exists", function_name)
                else:
                    message = f"commands.{function_name} not found."
                    _add_check(checks, "command_function", "warning", message, function_name)
                    warnings.append(message)

    summary = {
        "errors": len(errors),
        "warnings": len(warnings),
        "infos": len(infos),
    }
    return {
        "ok": not errors,
        "summary": summary,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "infos": infos,
    }


def _add_check(checks: list[dict[str, Any]], category: str, status: str, message: str, target: str) -> None:
    checks.append({
        "category": category,
        "status": status,
        "message": message,
        "target": target,
    })
