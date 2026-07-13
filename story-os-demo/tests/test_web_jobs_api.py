from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from system.job_manager import JobManager
from web.app import app


def _wait(client: TestClient, job_id: str, statuses: set[str]) -> dict:
    # Windows can delay a newly-created worker while other TestClient loops
    # are closing; this is still a bounded completion wait, not a sleep-based
    # assertion.
    for _ in range(300):
        response = client.get(f"/api/jobs/{job_id}").json()
        job = response.get("result", {}).get("job", {})
        if job.get("status") in statuses:
            return job
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_job_api_contract(monkeypatch, tmp_path: Path) -> None:
    def runner(job, context, emit, cancelled):
        emit({"name": "index-vault", "status": "running"})
        emit({"name": "index-vault", "status": "completed", "message": "indexed"})
        return {"output": {"indexed": True}}

    manager = JobManager(runner=runner)
    monkeypatch.setattr("web.routes.get_job_manager", lambda: manager)
    monkeypatch.chdir(tmp_path)
    with TestClient(app) as client:
        created = client.post("/api/jobs", json={"job_type": "index_vault", "parameters": {}}).json()
        assert created["ok"] is True
        job_id = created["result"]["job"]["job_id"]
        job = _wait(client, job_id, {"completed"})
        assert job["job_id"] == job_id
        assert client.get("/api/jobs").json()["result"]["jobs"]
        assert client.get("/api/jobs/active").json()["ok"] is True
        assert client.get(f"/api/jobs/{job_id}/logs").json()["result"]["entries"]
        cancelled = client.post(f"/api/jobs/{job_id}/cancel").json()
        assert cancelled["ok"] is False
        assert client.post(f"/api/jobs/{job_id}/retry").json()["ok"] is False
    manager.shutdown()
