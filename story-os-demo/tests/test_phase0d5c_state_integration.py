from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from tests._rc2_browser_fixture_server import setup_workspace


def test_simulator_state_endpoint_drives_loop_from_isolated_fixture(tmp_path: Path):
    info = setup_workspace(tmp_path)
    old = os.getcwd()
    os.chdir(tmp_path)
    try:
        from web.app import app
        with TestClient(app) as client:
            response = client.get("/api/simulator/state", params={"project_id": info["project_id"], "timeline_id": info["timeline_id"], "chapter_id": info["chapter_id"], "branch_id": info["active_branch"]})
        assert response.status_code == 200
        assert response.headers.get("cache-control") == "no-store"
        payload = response.json()["result"]
        assert payload["scope"]["branch_id"] == info["active_branch"]
        assert payload["current_stage"] in {"ENTRY", "TURN", "HISTORY", "CANDIDATE", "REVIEW", "COMMIT", "COMPLETE", "BLOCKED"}
        assert "approval" in payload
    finally:
        os.chdir(old)

