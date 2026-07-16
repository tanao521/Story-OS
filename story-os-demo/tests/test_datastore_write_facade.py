from __future__ import annotations

import json

import pytest

from core.contracts import HashExpectation, HashGuard, OperationEnvelope, ProjectRef
from core.contracts.project_ref import ProjectRefError
from core.contracts.safety import SafetyContractError
from core.project_context import get_project_context
from system.data_store import DataStore
from system.safe_write import DataStoreWriteError, DataStoreWriteFacade


def _context(tmp_path, name: str = "project"):
    root = tmp_path / name
    root.mkdir()
    return get_project_context(root)


def _operation(operation_id: str = "write-1", **changes) -> OperationEnvelope:
    value = {
        "operation_id": operation_id, "operation_type": "write_json", "project_id": "project",
        "target_type": "test_artifact", "target_id": "fixture", "confirmed": True, "reason": "test write",
    }
    value.update(changes)
    return OperationEnvelope(**value)


def test_write_facade_uses_datastore_and_replays_identical_operation(tmp_path, monkeypatch) -> None:
    context = _context(tmp_path)
    facade = DataStoreWriteFacade(context)
    ref = ProjectRef.from_context(context)
    payload = {"value": 1}
    calls = []
    original = facade.store._atomic

    def tracked(path, content, *, backup=False):
        calls.append(path)
        return original(path, content, backup=backup)

    monkeypatch.setattr(facade.store, "_atomic", tracked)
    result = facade.write_json(
        project=ref,
        target_path="data/test/artifact.json",
        payload=payload,
        operation=_operation(),
        expectation=HashExpectation.for_new_target(candidate_sha256=HashGuard.sha256_json(payload)),
    )
    replay = facade.write_json(
        project=ref,
        target_path="data/test/artifact.json",
        payload=payload,
        operation=_operation(),
        expectation=HashExpectation.for_new_target(candidate_sha256=HashGuard.sha256_json(payload)),
    )

    assert calls == ["data/test/artifact.json"]
    assert json.loads((context.root / "data/test/artifact.json").read_text(encoding="utf-8")) == payload
    assert result.before_hash is None and result.after_hash == HashGuard.file_sha256(context.root / "data/test/artifact.json")
    assert replay.replayed and replay.audit_metadata["replayed"] is True
    assert str(context.root) not in str(result.public_view())


def test_write_facade_rejects_hash_conflict_operation_conflict_and_cross_project(tmp_path) -> None:
    context = _context(tmp_path)
    facade = DataStoreWriteFacade(context)
    ref = ProjectRef.from_context(context)
    store = DataStore(context)
    store.write_json("data/test/existing.json", {"value": "original"})
    original = (context.root / "data/test/existing.json").read_text(encoding="utf-8")
    payload = {"value": "replacement"}

    with pytest.raises(SafetyContractError) as hash_error:
        facade.replace_json(project=ref, target_path="data/test/existing.json", payload=payload, operation=_operation(), expectation=HashExpectation(expected_sha256="0" * 64, candidate_sha256=HashGuard.sha256_json(payload)))
    assert hash_error.value.code == "HASH_MISMATCH"
    assert (context.root / "data/test/existing.json").read_text(encoding="utf-8") == original

    first = facade.write_json(project=ref, target_path="data/test/one.json", payload={"one": 1}, operation=_operation("shared"), expectation=HashExpectation.for_new_target(candidate_sha256=HashGuard.sha256_json({"one": 1})))
    assert first.replayed is False
    with pytest.raises(DataStoreWriteError) as conflict:
        facade.write_json(project=ref, target_path="data/test/two.json", payload={"two": 2}, operation=_operation("shared", target_id="other"), expectation=HashExpectation.for_new_target(candidate_sha256=HashGuard.sha256_json({"two": 2})))
    assert conflict.value.code == "OPERATION_ID_CONFLICT"

    other_context = _context(tmp_path, "other")
    with pytest.raises(ProjectRefError) as cross:
        facade.write_json(project=ProjectRef.from_context(other_context), target_path="data/test/nope.json", payload={}, operation=_operation("cross", project_id="other"), expectation=HashExpectation.for_new_target(candidate_sha256=HashGuard.sha256_json({})))
    assert cross.value.code == "PROJECT_MISMATCH"


def test_write_facade_rejects_unsafe_paths_and_preserves_existing_file_on_write_failure(tmp_path, monkeypatch) -> None:
    context = _context(tmp_path)
    facade = DataStoreWriteFacade(context)
    ref = ProjectRef.from_context(context)
    for path in ("../escape.json", "C:\\escape.json"):
        with pytest.raises(ProjectRefError):
            facade.write_json(project=ref, target_path=path, payload={}, operation=_operation("path-" + str(len(path))), expectation=HashExpectation.for_new_target(candidate_sha256=HashGuard.sha256_json({})))

    target = context.root / "data/test/preserved.json"
    DataStore(context).write_text("data/test/preserved.json", "original")
    before = HashGuard.file_sha256(target)
    monkeypatch.setattr(facade.store, "write_text", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("write failed")))
    with pytest.raises(DataStoreWriteError) as failed:
        facade.replace_text(project=ref, target_path="data/test/preserved.json", payload="replacement", operation=_operation("failure", operation_type="replace_text"), expectation=HashExpectation(expected_sha256=before, candidate_sha256=HashGuard.sha256_text("replacement")))
    assert failed.value.code == "DATASTORE_WRITE_FAILED"
    assert target.read_text(encoding="utf-8") == "original"
