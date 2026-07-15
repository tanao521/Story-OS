from __future__ import annotations

import os

import pytest

from core.project_context import get_project_context
from system.data_store import DataStore, DataWriteError


def test_atomic_replace_retries_a_transient_windows_lock(tmp_path, monkeypatch) -> None:
    store = DataStore(get_project_context(tmp_path)); calls = {"count": 0}; original = os.replace
    def flaky(source, destination):
        calls["count"] += 1
        if calls["count"] == 1: raise PermissionError("sharing violation")
        return original(source, destination)
    monkeypatch.setattr(os, "replace", flaky)
    store.write_json("data/value.json", {"ok": True})
    assert calls["count"] == 2 and store.read_json("data/value.json") == {"ok": True}


def test_atomic_replace_does_not_retry_non_transient_errors(tmp_path, monkeypatch) -> None:
    store = DataStore(get_project_context(tmp_path)); calls = {"count": 0}
    def denied(_source, _destination):
        calls["count"] += 1
        raise OSError("invalid destination")
    monkeypatch.setattr(os, "replace", denied)
    with pytest.raises(DataWriteError): store.write_json("data/value.json", {"ok": False})
    assert calls["count"] == 1
