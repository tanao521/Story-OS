from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from core.project_context import get_project_context
from core.project_context import bind_project_context
from system.narrative_branch_lifecycle_service import BranchLifecycleService
from web.app import app


def test_branch_memory_routes_require_scope_and_isolate_branches(tmp_path: Path):
    context = get_project_context(tmp_path)
    lifecycle = BranchLifecycleService(context)
    scope = {"project_id": context.root.name, "timeline_id": "main"}
    lifecycle.create("seed-a", {**scope, "branch_id": "a"})
    lifecycle.create("seed-b", {**scope, "branch_id": "b"})
    revision = lifecycle.list_branches(**scope)["registry_revision"]
    lifecycle.select("select-a", {**scope, "branch_id": "a", "expected_registry_revision": revision})
    with bind_project_context(context):
        client = TestClient(app)
        missing = client.get("/api/narrative-memory/branch/events")
        assert missing.status_code == 422
        created = client.post("/api/narrative-memory/branch/events", json={**scope, "branch_id": "a", "chapter_id": 1, "event_type": "arrival", "payload": {"x": 1}})
        assert created.status_code == 200
        events_b = client.get("/api/narrative-memory/branch/events", params={**scope, "branch_id": "b"})
        assert events_b.status_code == 409 and events_b.json()["errors"] == ["BRANCH_MEMORY_INACTIVE"]
        admin_events_b = client.get("/api/narrative-memory/branch/events", params={**scope, "branch_id": "b", "administrative": "true"})
        assert admin_events_b.status_code == 200 and admin_events_b.json()["result"]["events"] == []
