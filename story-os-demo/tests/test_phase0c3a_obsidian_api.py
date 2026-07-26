from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from web.routes import router
from system.obsidian_binding_service import ObsidianBindingService


class TestObsidianBindingAPI:
    @pytest.fixture
    def temp_workspace(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        vault = tmp_path / "vault"
        vault.mkdir(parents=True, exist_ok=True)
        return workspace, vault

    @pytest.fixture
    def client(self, temp_workspace):
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_get_binding_unbound(self, temp_workspace, client, monkeypatch):
        workspace, vault = temp_workspace
        project_id = str(uuid.uuid4())

        def mock_resolve():
            return workspace
        monkeypatch.setattr("core.project.resolve_workspace_root", mock_resolve)

        response = client.get(f"/api/projects/{project_id}/obsidian-binding")
        assert response.status_code == 200
        data = response.json()
        assert data["result"]["status"] == "unbound"

    def test_put_binding_success(self, temp_workspace, client, monkeypatch):
        workspace, vault = temp_workspace
        project_id = str(uuid.uuid4())

        def mock_resolve(*args, **kwargs):
            return workspace
        monkeypatch.setattr("core.project.resolve_workspace_root", mock_resolve)

        response = client.put(
            f"/api/projects/{project_id}/obsidian-binding",
            json={
                "vault_root": str(vault),
                "target_relative_path": "StoryOS/test-project",
                "timeline_id": "main",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["result"]["status"] == "bound"
        assert data["result"]["project_id"] == project_id
        assert data["result"]["timeline_id"] == "main"

    def test_put_binding_with_timeline(self, temp_workspace, client, monkeypatch):
        workspace, vault = temp_workspace
        project_id = str(uuid.uuid4())

        def mock_resolve(*args, **kwargs):
            return workspace
        monkeypatch.setattr("core.project.resolve_workspace_root", mock_resolve)

        response = client.put(
            f"/api/projects/{project_id}/obsidian-binding",
            json={
                "vault_root": str(vault),
                "target_relative_path": "StoryOS/test-project/exp-a",
                "timeline_id": "experiment-a",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["result"]["timeline_id"] == "experiment-a"

    def test_get_binding_with_timeline(self, temp_workspace, client, monkeypatch):
        workspace, vault = temp_workspace
        project_id = str(uuid.uuid4())

        def mock_resolve(*args, **kwargs):
            return workspace
        monkeypatch.setattr("core.project.resolve_workspace_root", mock_resolve)

        client.put(
            f"/api/projects/{project_id}/obsidian-binding",
            json={
                "vault_root": str(vault),
                "target_relative_path": "StoryOS/test-project/exp-a",
                "timeline_id": "experiment-a",
            },
        )

        response = client.get(f"/api/projects/{project_id}/obsidian-binding?timeline=experiment-a")
        assert response.status_code == 200
        data = response.json()
        assert data["result"]["timeline_id"] == "experiment-a"

    def test_delete_binding(self, temp_workspace, client, monkeypatch):
        workspace, vault = temp_workspace
        project_id = str(uuid.uuid4())

        def mock_resolve(*args, **kwargs):
            return workspace
        monkeypatch.setattr("core.project.resolve_workspace_root", mock_resolve)

        client.put(
            f"/api/projects/{project_id}/obsidian-binding",
            json={
                "vault_root": str(vault),
                "target_relative_path": "StoryOS/test-project",
            },
        )

        response = client.delete(f"/api/projects/{project_id}/obsidian-binding")
        assert response.status_code == 200

        response = client.get(f"/api/projects/{project_id}/obsidian-binding")
        assert response.json()["result"]["status"] == "unbound"

    def test_delete_binding_with_timeline(self, temp_workspace, client, monkeypatch):
        workspace, vault = temp_workspace
        project_id = str(uuid.uuid4())

        def mock_resolve(*args, **kwargs):
            return workspace
        monkeypatch.setattr("core.project.resolve_workspace_root", mock_resolve)

        client.put(
            f"/api/projects/{project_id}/obsidian-binding",
            json={
                "vault_root": str(vault),
                "target_relative_path": "StoryOS/test-project/main",
                "timeline_id": "main",
            },
        )
        client.put(
            f"/api/projects/{project_id}/obsidian-binding",
            json={
                "vault_root": str(vault),
                "target_relative_path": "StoryOS/test-project/exp",
                "timeline_id": "experiment-a",
            },
        )

        response = client.delete(f"/api/projects/{project_id}/obsidian-binding?timeline=experiment-a")
        assert response.status_code == 200

        response = client.get(f"/api/projects/{project_id}/obsidian-binding?timeline=main")
        assert response.json()["result"]["status"] == "bound"

        response = client.get(f"/api/projects/{project_id}/obsidian-binding?timeline=experiment-a")
        assert response.json()["result"]["status"] == "unbound"

    def test_put_binding_invalid_vault(self, temp_workspace, client, monkeypatch):
        workspace, vault = temp_workspace
        project_id = str(uuid.uuid4())

        def mock_resolve(*args, **kwargs):
            return workspace
        monkeypatch.setattr("core.project.resolve_workspace_root", mock_resolve)

        response = client.put(
            f"/api/projects/{project_id}/obsidian-binding",
            json={
                "vault_root": "/nonexistent/vault",
                "target_relative_path": "StoryOS/test",
            },
        )
        assert response.status_code == 400

    def test_put_binding_traversal_attack(self, temp_workspace, client, monkeypatch):
        workspace, vault = temp_workspace
        project_id = str(uuid.uuid4())

        def mock_resolve(*args, **kwargs):
            return workspace
        monkeypatch.setattr("core.project.resolve_workspace_root", mock_resolve)

        response = client.put(
            f"/api/projects/{project_id}/obsidian-binding",
            json={
                "vault_root": str(vault),
                "target_relative_path": "../escape",
            },
        )
        assert response.status_code == 400

    def test_put_binding_target_conflict(self, temp_workspace, client, monkeypatch):
        workspace, vault = temp_workspace
        project_a = str(uuid.uuid4())
        project_b = str(uuid.uuid4())

        def mock_resolve(*args, **kwargs):
            return workspace
        monkeypatch.setattr("core.project.resolve_workspace_root", mock_resolve)

        client.put(
            f"/api/projects/{project_a}/obsidian-binding",
            json={
                "vault_root": str(vault),
                "target_relative_path": "StoryOS/shared-target",
            },
        )

        response = client.put(
            f"/api/projects/{project_b}/obsidian-binding",
            json={
                "vault_root": str(vault),
                "target_relative_path": "StoryOS/shared-target",
            },
        )
        assert response.status_code == 409

    def test_delete_binding_not_found(self, temp_workspace, client, monkeypatch):
        workspace, vault = temp_workspace
        project_id = str(uuid.uuid4())

        def mock_resolve(*args, **kwargs):
            return workspace
        monkeypatch.setattr("core.project.resolve_workspace_root", mock_resolve)

        response = client.delete(f"/api/projects/{project_id}/obsidian-binding")
        assert response.status_code == 404