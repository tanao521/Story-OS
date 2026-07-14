"""Local rotating logs with redaction.  Never write prompts or credentials."""
from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from core.project_context import ProjectContext, get_project_context

_SECRET = re.compile(r"(?i)(bearer\s+|sk-[\w-]{8,}|api[_-]?key\s*[=:]\s*)[^\s,;]+")


def redact(value: Any, limit: int = 600) -> str:
    return _SECRET.sub(r"\1[redacted]", str(value or "").replace("\r", " ").replace("\n", " "))[:limit]


def get_logger(name: str = "storyos", context: ProjectContext | None = None) -> logging.Logger:
    context = context or get_project_context(); logger = logging.getLogger(f"storyos.{name}")
    if logger.handlers: return logger
    context.logs_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(context.logs_dir / "application.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    errors = RotatingFileHandler(context.logs_dir / "errors.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    errors.setLevel(logging.ERROR); errors.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler); logger.addHandler(errors); logger.setLevel(logging.INFO); logger.propagate = False
    return logger


def recent_logs(context: ProjectContext | None = None, *, level: str | None = None, limit: int = 100) -> list[dict[str, str]]:
    context = context or get_project_context(); path = context.logs_dir / "application.log"
    if not path.exists(): return []
    entries=[]
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, min(limit, 500)):]:
        if level and f" {level.upper()} " not in line: continue
        entries.append({"line": redact(line, 1000)})
    return entries
