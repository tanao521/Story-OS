from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from system.project_identity_resolver import ProjectIdentityResolutionError, ProjectIdentityResolver
from system.project_manager import ProjectManager
from web.app import app


def _project(manager: ProjectManager, title: str) -> dict:
    return manager.create_project(
        {
            "title": title,
            "genre": "science fiction",
            "premise": "A formal identity fixture.",
            "protagonist": "Ada",
            "goal": "Resolve authority",
            "conflict": "Legacy storage",
            "tone": "precise",
            "target_words": 1000,
            "chapter_count": 1,
        }
    )


def test_registry_only_resolver_maps_two_formal_uuids_without_cross_scope(tmp_path: Path) -> None:
    manager = ProjectManager(tmp_path)
    a = _project(manager, "RC11 Project A")
    b = _project(manager, "RC11 Project B")
    resolved_a = ProjectIdentityResolver(tmp_path).resolve(a["project_id"])
    resolved_b = ProjectIdentityResolver(tmp_path).resolve(b["project_id"])
    assert resolved_a.project_id == a["project_id"]
    assert resolved_b.project_id == b["project_id"]
    assert resolved_a.storage_project_id != resolved_b.storage_project_id
    assert resolved_a.context.root != resolved_b.context.root


def test_resolver_fails_closed_for_missing_mismatched_and_ambiguous_authority(tmp_path: Path) -> None:
    manager = ProjectManager(tmp_path)
    project = _project(manager, "RC11 Fail Closed")
    resolver = ProjectIdentityResolver(tmp_path)
    with pytest.raises(ProjectIdentityResolutionError, match="Project not found") as missing:
        resolver.resolve("0" * 32)
    assert missing.value.code == "PROJECT_NOT_FOUND"

    metadata_path = tmp_path / project["project_root"] / "project.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["project_id"] = "f" * 32
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ProjectIdentityResolutionError) as mismatch:
        resolver.resolve(project["project_id"])
    assert mismatch.value.code == "PROJECT_IDENTITY_UNAVAILABLE"

    metadata["project_id"] = project["project_id"]
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    registry_path = tmp_path / ".story_os" / "projects.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["projects"].append(dict(registry["projects"][0]))
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(ProjectIdentityResolutionError) as ambiguous:
        resolver.resolve(project["project_id"])
    assert ambiguous.value.code == "PROJECT_IDENTITY_UNAVAILABLE"


def test_branch_and_simulator_routes_keep_uuid_outside_and_slug_inside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    projects = [_project(ProjectManager(tmp_path), "RC11 Route A"), _project(ProjectManager(tmp_path), "RC11 Route B")]
    client = TestClient(app)
    for index, project in enumerate(projects):
        branch_id = f"root_{index}"
        created = client.post(
            "/api/narrative-branches/create",
            json={
                "operation_id": f"rc11_create_{index}",
                "project_id": project["project_id"],
                "timeline_id": "main",
                "branch_id": branch_id,
                "display_name": f"Root {index}",
            },
        )
        assert created.status_code == 200, created.text
        listed = client.get(
            "/api/narrative-branches",
            params={"project_id": project["project_id"], "timeline_id": "main"},
        )
        assert listed.status_code == 200
        assert [item["branch_id"] for item in listed.json()["result"]["branches"]] == [branch_id]
        state = client.get(
            "/api/simulator/state",
            params={
                "project_id": project["project_id"],
                "timeline_id": "main",
                "chapter_id": 1,
                "branch_id": branch_id,
            },
        )
        assert state.status_code == 200, state.text
        assert state.json()["result"]["scope"]["project_id"] == project["project_id"]
        authority_path = (
            tmp_path
            / project["project_root"]
            / "data"
            / "branch_operations"
            / f"rc11_create_{index}.json"
        )
        authority = json.loads(authority_path.read_text(encoding="utf-8"))
        assert authority["project_id"] == project["project_id"]

    a_branches = client.get(
        "/api/narrative-branches",
        params={"project_id": projects[0]["project_id"], "timeline_id": "main"},
    ).json()["result"]["branches"]
    assert "root_1" not in {item["branch_id"] for item in a_branches}
