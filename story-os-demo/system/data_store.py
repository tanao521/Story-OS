"""Safe project-scoped file access for Story OS data."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from core.project_context import ProjectContext


class DataStoreError(RuntimeError):
    """Base error for project data access."""


class DataReadError(DataStoreError):
    """Raised for strict read failures."""


class DataWriteError(DataStoreError):
    """Raised when an atomic write cannot complete."""


class DataStore:
    """Atomic UTF-8 JSON, Markdown, and text storage scoped to one context."""

    def __init__(self, context: ProjectContext) -> None:
        self.context = context

    def path(self, path: str | Path) -> Path:
        """Resolve an internal path and reject traversal outside the project."""
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.context.root / candidate
        resolved = candidate.expanduser().resolve()
        try:
            resolved.relative_to(self.context.root)
        except ValueError as exc:
            raise DataStoreError(f"Project file path escapes project root: {path}") from exc
        return resolved

    def exists(self, path: str | Path) -> bool:
        return self.path(path).exists()

    def ensure_directory(self, path: str | Path) -> Path:
        directory = self.path(path)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def read_json(
        self,
        path: str | Path,
        *,
        default: Any = None,
        expected_type: type | tuple[type, ...] | None = None,
        strict: bool = False,
    ) -> Any:
        target = self.path(path)
        try:
            value = json.loads(target.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            if strict:
                raise DataReadError(f"Required JSON file is missing: {self.context.relative_path(target)}") from exc
            return default
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            if strict:
                raise DataReadError(f"Cannot read JSON file: {self.context.relative_path(target)}") from exc
            return default
        if expected_type is not None and not isinstance(value, expected_type):
            if strict:
                raise DataReadError(f"Unexpected JSON type in: {self.context.relative_path(target)}")
            return default
        return value

    def read_text(self, path: str | Path, *, default: str | None = None, strict: bool = False) -> str | None:
        target = self.path(path)
        try:
            return target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            if strict:
                raise DataReadError(f"Cannot read text file: {self.context.relative_path(target)}") from exc
            return default

    def read_markdown(self, path: str | Path, **kwargs: Any) -> str | None:
        return self.read_text(path, **kwargs)

    def write_json(self, path: str | Path, data: Any, *, backup: bool = False) -> None:
        try:
            content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        except (TypeError, ValueError) as exc:
            raise DataWriteError(f"Cannot serialize JSON for: {path}") from exc
        self._atomic(path, content, backup=backup)

    def write_text(self, path: str | Path, content: str, *, backup: bool =False) -> None:
        self._atomic(path, content, backup=backup)

    def write_markdown(self, path: str | Path, content: str, *, backup: bool = False) -> None:
        self._atomic(path, content, backup=backup)

    def backup_file(self, path: str | Path) -> Path | None:
        target = self.path(path)
        if not target.exists():
            return None
        backup = target.with_name(f"{target.name}.bak")
        try:
            shutil.copy2(target, backup)
        except OSError as exc:
            raise DataWriteError(f"Cannot back up file: {self.context.relative_path(target)}") from exc
        return backup

    def _atomic(self, path: str | Path, content: str, *, backup: bool) -> None:
        target = self.path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_name: str | None = None
        try:
            fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent, text=True)
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            if backup and target.exists():
                self.backup_file(target)
            # Windows may briefly retain a handle after a reader closes a file.
            # Retry only that narrow replace race; serialization and path errors
            # remain visible to callers instead of being hidden by retries.
            last_error: OSError | None = None
            for attempt, delay in enumerate((0.0, 0.05, 0.18)):
                if delay:
                    time.sleep(delay)
                try:
                    os.replace(temp_name, target)
                    last_error = None
                    break
                except PermissionError as exc:
                    last_error = exc
                except OSError as exc:
                    # Windows sharing violations are exposed as winerror 32/33.
                    if getattr(exc, "winerror", None) not in {32, 33}:
                        raise
                    last_error = exc
            if last_error is not None:
                raise last_error
            temp_name = None
        except OSError as exc:
            raise DataWriteError(f"Cannot write file atomically: {self.context.relative_path(target)}") from exc
        finally:
            if temp_name:
                try:
                    Path(temp_name).unlink(missing_ok=True)
                except OSError:
                    pass

