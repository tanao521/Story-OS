from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from tests._phase0d6c_fv_browser_fixture_server import setup_workspace
from web.app import app


def _project_ids(value):
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "project_id":
                found.append(item)
            found.extend(_project_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_project_ids(item))
    return found


def test_formal_narrative_turn_and_progression_keep_uuid_outside(
    tmp_path: Path, monkeypatch
) -> None:
    info = setup_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    project_id = info["project_a"]["project_id"]
    storage_id = info["project_a"]["slug"]
    client = TestClient(app)
    params = {
        "project_id": project_id,
        "timeline_id": "main",
        "branch_id": "main",
        "chapter_id": 2,
    }

    context = client.get("/api/narrative-turn/context", params=params)
    assert context.status_code == 200, context.text
    assert project_id in _project_ids(context.json())
    assert storage_id not in _project_ids(context.json())

    plan = client.get("/api/narrative-turn/plan", params=params)
    assert plan.status_code == 200, plan.text
    assert project_id in _project_ids(plan.json())
    assert storage_id not in _project_ids(plan.json())

    readiness = client.get(
        "/api/chapter-progression/readiness",
        params={
            "project_id": project_id,
            "timeline_id": "main",
            "branch_id": "main",
            "previous_chapter_id": 1,
        },
    )
    assert readiness.status_code == 200, readiness.text
    authority = readiness.json()["result"]
    assert authority["project_id"] == project_id
    assert authority["ready_to_start_turn"] is True

    started = client.post(
        "/api/chapter-progression/start-turn",
        json={
            "operation_id": "rc12_formal_start",
            "project_id": project_id,
            "timeline_id": "main",
            "branch_id": "main",
            "previous_chapter_id": 1,
            "successor_chapter_id": 2,
            "expected_readiness_fingerprint": authority["authority_fingerprint"],
        },
    )
    assert started.status_code == 200, started.text
    result = started.json()["result"]
    assert result["project_id"] == project_id
    assert result["preview"]["scope"]["project_id"] == project_id

    operation_path = (
        info["project"]
        / "data"
        / "chapter_progression"
        / "operations"
        / "rc12_formal_start.json"
    )
    operation = json.loads(operation_path.read_text(encoding="utf-8"))
    assert operation["request"]["project_id"] == project_id
    turn_root = info["project"] / "data" / "narrative_turn" / "plans" / "main" / "main"
    assert turn_root.exists()


def test_formal_project_b_never_reads_project_a_scope(tmp_path: Path, monkeypatch) -> None:
    info = setup_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    client = TestClient(app)
    project_a = info["project_a"]
    project_b = info["project_b"]

    for project in (project_a, project_b):
        response = client.get(
            "/api/narrative-turn/context",
            params={
                "project_id": project["project_id"],
                "timeline_id": "main",
                "branch_id": "main",
                "chapter_id": 2,
            },
        )
        assert response.status_code == 200, response.text
        ids = _project_ids(response.json())
        assert project["project_id"] in ids
        other = project_b if project is project_a else project_a
        assert other["project_id"] not in ids
        assert project["slug"] not in ids


def test_formal_narrative_confirm_operation_scope_stays_uuid(
    tmp_path: Path, monkeypatch
) -> None:
    info = setup_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    project = info["project_a"]
    client = TestClient(app)
    params = {
        "project_id": project["project_id"],
        "timeline_id": "main",
        "branch_id": "main",
        "chapter_id": 1,
    }
    plan = client.get("/api/narrative-turn/plan", params=params)
    assert plan.status_code == 200, plan.text
    action_id = plan.json()["recommended_actions"][0]["action_id"]
    body = {
        **params,
        "operation_id": "rc12_narrative_confirm",
        "source_version_id": None,
        "expected_context_fingerprint": None,
        "expected_turn_id": None,
        "expected_validation_id": None,
        "expected_preview_fingerprint": None,
        "action_source": "recommended",
        "selected_action_id": action_id,
    }
    first = client.post("/api/narrative-turn/confirm", json=body)
    second = client.post("/api/narrative-turn/confirm", json=body)
    assert first.status_code == second.status_code == 200
    assert second.json()["idempotent_replay"] is True
    assert project["project_id"] in _project_ids(first.json())
    assert project["slug"] not in _project_ids(first.json())

    operations = info["project"] / "data" / "narrative_turn" / "operations"
    claim = json.loads((operations / "rc12_narrative_confirm.json").read_text(encoding="utf-8"))
    phase = json.loads(
        (operations / "rc12_narrative_confirm.phase.json").read_text(encoding="utf-8")
    )
    assert claim["scope"]["project_id"] == project["project_id"]
    assert phase["project_id"] == project["project_id"]
