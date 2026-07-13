from __future__ import annotations

from pathlib import Path
from typing import Any

from core.project_context import get_project_context
from system.data_store import DataStore


def _store() -> DataStore:
    return DataStore(get_project_context())


def _store_for(path: str | Path) -> DataStore:
    """Compatibility adapter for legacy helpers given an explicit absolute path.

    Normal product calls remain scoped to the active ProjectContext.  A few
    long-standing library/test callers intentionally supply a temporary
    absolute path; give that one file's parent its own isolated context rather
    than weakening DataStore's project-boundary checks.
    """
    candidate = Path(path).expanduser()
    return DataStore(get_project_context(candidate.parent)) if candidate.is_absolute() else _store()


def ensure_data_dir() -> None:
    _store().context.data_dir.mkdir(parents=True, exist_ok=True)


def save_json(path: str | Path, data: dict[str, Any]) -> None:
    _store_for(path).write_json(path, data, backup=Path(path).name in {"state.json", "story_spec.json", "story_blueprint.json"})


def load_json(path: str | Path) -> dict[str, Any]:
    return _store_for(path).read_json(path, strict=True, expected_type=dict)


def save_markdown(path: str | Path, content: str) -> None:
    _store_for(path).write_markdown(path, content)
