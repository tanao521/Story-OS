from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from core.project_context import get_project_context
from system.project_manager import ProjectManager
from web.app import app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    project = ProjectManager(tmp_path).create_project({
        "title": "Formal branch route fixture",
        "genre": "fixture",
        "premise": "Formal UUID identity only",
        "protagonist": "Fixture",
        "goal": "Exercise branch routes",
        "conflict": "None",
        "tone": "precise",
        "target_words": 1000,
        "chapter_count": 2,
    })
    ctx = get_project_context(tmp_path / project["project_root"])
    return TestClient(app), ctx, project["project_id"]


def _scope(project_id: str):
    return {"project_id": project_id, "timeline_id": "main"}


def test_create_list_get_and_replay(client):
    http, _ctx, project_id = client
    body = {**_scope(project_id), "operation_id": "branch-op-create", "branch_id": "alpha", "display_name": "Alpha"}
    created = http.post("/api/narrative-branches/create", json=body)
    assert created.status_code == 200
    assert created.headers["cache-control"] == "no-store"
    assert created.json()["result"]["branch"]["lifecycle_status"] == "open"
    replay = http.post("/api/narrative-branches/create", json=body)
    assert replay.status_code == 200
    assert replay.json()["result"]["idempotent_replay"] is True
    listed = http.get("/api/narrative-branches", params=_scope(project_id))
    assert listed.status_code == 200
    assert listed.json()["result"]["branches"][0]["activity"] == "inactive"
    detail = http.get("/api/narrative-branches/alpha", params=_scope(project_id))
    assert detail.status_code == 200
    assert "fingerprint" not in detail.text


def test_select_archive_restore_and_safe_errors(client):
    http, _ctx, project_id = client
    scope = _scope(project_id)
    for op, branch in (("create-a", "alpha"), ("create-b", "beta")):
        assert http.post("/api/narrative-branches/create", json={**scope, "operation_id": op, "branch_id": branch}).status_code == 200
    revision = http.get("/api/narrative-branches", params=scope).json()["result"]["registry_revision"]
    selected = http.post("/api/narrative-branches/select", json={**scope, "operation_id": "select-a", "branch_id": "alpha", "expected_registry_revision": revision})
    assert selected.status_code == 200
    revision = selected.json()["result"]["registry_revision"]
    archived = http.post("/api/narrative-branches/archive", json={**scope, "operation_id": "archive-a", "branch_id": "alpha", "replacement_branch_id": "beta", "expected_registry_revision": revision})
    assert archived.status_code == 200
    assert archived.json()["result"]["active_branch_id"] == "beta"
    revision = archived.json()["result"]["registry_revision"]
    restored = http.post("/api/narrative-branches/restore", json={**scope, "operation_id": "restore-a", "branch_id": "alpha", "expected_registry_revision": revision})
    assert restored.status_code == 200
    assert restored.json()["result"]["branch"]["lifecycle_status"] == "open"
    assert restored.json()["result"]["branch"]["activity"] == "inactive"
    blocked = http.post("/api/narrative-branches/select", json={**scope, "operation_id": "select-archived", "branch_id": "missing"})
    assert blocked.status_code == 404
    assert blocked.json()["error"]["code"] == "BRANCH_NOT_FOUND"
    malformed = http.post("/api/narrative-branches/create", json={"operation_id": "../escape"})
    assert malformed.status_code == 400
    assert malformed.json()["error"]["code"] == "INVALID_OPERATION_ID"


def test_operation_conflict_and_stale_revision(client):
    http, _ctx, project_id = client
    scope = _scope(project_id)
    first = {**scope, "operation_id": "same-op", "branch_id": "alpha"}
    assert http.post("/api/narrative-branches/create", json=first).status_code == 200
    conflict = http.post("/api/narrative-branches/create", json={**first, "branch_id": "beta"})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "OPERATION_ID_CONFLICT"
    stale = http.post("/api/narrative-branches/select", json={**scope, "operation_id": "select-stale", "branch_id": "alpha", "expected_registry_revision": "stale"})
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "REGISTRY_REVISION_CONFLICT"
