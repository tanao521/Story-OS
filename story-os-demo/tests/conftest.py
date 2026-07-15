from __future__ import annotations

import os
from pathlib import Path

import pytest

import config
from system.data_store import DataStore


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_REAL_DATA_ROOT = (_REPOSITORY_ROOT / "data").resolve()


def _targets_real_data(path: str | Path) -> bool:
    try:
        Path(path).resolve().relative_to(_REAL_DATA_ROOT)
        return True
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def block_real_project_data_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail fast if a test writes the checked-out project's real data directory.

    Test projects must use ``tmp_path``/an explicit ``ProjectContext``.  The
    guard deliberately applies only while pytest is running and leaves normal
    application writes and all temporary project roots untouched.
    """
    original_open = Path.open
    original_replace = Path.replace
    original_rename = Path.rename
    original_unlink = Path.unlink
    original_atomic = DataStore._atomic

    def blocked(path: str | Path) -> RuntimeError:
        return RuntimeError(f"TEST_REAL_DATA_WRITE_BLOCKED: {Path(path).resolve()}")

    def guarded_open(path: Path, mode: str = "r", *args, **kwargs):
        if os.environ.get("PYTEST_CURRENT_TEST") and any(flag in mode for flag in ("w", "a", "x", "+")) and _targets_real_data(path):
            raise blocked(path)
        return original_open(path, mode, *args, **kwargs)

    def guarded_replace(path: Path, target: str | Path):
        if os.environ.get("PYTEST_CURRENT_TEST") and (_targets_real_data(path) or _targets_real_data(target)):
            raise blocked(target)
        return original_replace(path, target)

    def guarded_rename(path: Path, target: str | Path):
        if os.environ.get("PYTEST_CURRENT_TEST") and (_targets_real_data(path) or _targets_real_data(target)):
            raise blocked(target)
        return original_rename(path, target)

    def guarded_unlink(path: Path, *args, **kwargs):
        if os.environ.get("PYTEST_CURRENT_TEST") and _targets_real_data(path):
            raise blocked(path)
        return original_unlink(path, *args, **kwargs)

    def guarded_atomic(store: DataStore, path: str | Path, content: str, *, backup: bool = False) -> None:
        if os.environ.get("PYTEST_CURRENT_TEST") and _targets_real_data(store.path(path)):
            raise blocked(store.path(path))
        return original_atomic(store, path, content, backup=backup)

    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(Path, "replace", guarded_replace)
    monkeypatch.setattr(Path, "rename", guarded_rename)
    monkeypatch.setattr(Path, "unlink", guarded_unlink)
    monkeypatch.setattr(DataStore, "_atomic", guarded_atomic)


@pytest.fixture(autouse=True)
def disable_real_model_calls_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", "mock", raising=False)
    monkeypatch.setattr(config, "USE_LOCAL_MODEL_FOR_DRAFT", False, raising=False)
    monkeypatch.setattr(config, "USE_DEEPSEEK_FOR_EDITING", False, raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OLLAMA_CLOUD_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_CLOUD_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_CLOUD_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_TIMEOUT_SECONDS", raising=False)
