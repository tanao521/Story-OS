from __future__ import annotations

import time
from pathlib import Path
from threading import Event

import pytest

from core.project_context import get_project_context
from system.data_store import DataStore
from system.job_manager import JobAlreadyRunningError, JobManager


def wait_for(manager, job_id, context, statuses):
    for _ in range(150):
        job = manager.get_job(job_id, context=context)
        if job["status"] in statuses:
            return job
        time.sleep(.02)
    raise AssertionError("job did not reach terminal state")


def test_persistence_waiting_review_and_logs(tmp_path: Path):
    context = get_project_context(tmp_path)
    def runner(job, context, emit, cancelled):
        emit({"name":"build-context", "status":"completed", "message":"saved"})
        return {"pipeline_report":{"status":"waiting_for_review", "chapter_id":1, "review":{"status":"pending"}}}
    manager = JobManager(runner=runner); manager.startup()
    created = manager.create_job("run_chapter", context=context)
    job = wait_for(manager, created["job_id"], context, {"waiting_for_review"})
    assert job["progress"]["total"] == 4
    assert (context.jobs_dir / f"{created['job_id']}.json").exists()
    assert (context.jobs_dir / "logs" / f"{created['job_id']}.log").exists()
    manager.shutdown()


def test_duplicate_cancel_and_project_binding(tmp_path: Path):
    a, b = tmp_path / "a", tmp_path / "b"; a.mkdir(); b.mkdir()
    context_a, context_b = get_project_context(a), get_project_context(b); release = Event()
    def runner(job, context, emit, cancelled):
        DataStore(context).write_text("data/owned.txt", context.root.name)
        emit({"name":"build-context", "status":"running"}); release.wait(2)
        return {"cancelled": cancelled()}
    manager = JobManager(max_workers=1, runner=runner); manager.startup()
    created = manager.create_job("run_chapter", context=context_a)
    wait_for(manager, created["job_id"], context_a, {"running"})
    with pytest.raises(JobAlreadyRunningError): manager.create_job("run_chapter", context=context_a)
    manager.cancel_job(created["job_id"], context=context_a); release.set()
    assert wait_for(manager, created["job_id"], context_a, {"cancelled"})["status"] == "cancelled"
    assert (context_a.data_dir / "owned.txt").exists() and not (context_b.data_dir / "owned.txt").exists()
    assert manager.list_jobs(context=context_b) == []; manager.shutdown()


def test_retry_and_interruption(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    context = get_project_context(tmp_path); attempts=[]
    def runner(job, context, emit, cancelled):
        attempts.append(job["job_id"])
        if len(attempts) == 1: raise RuntimeError("model failed")
        return {"pipeline_report":{"status":"waiting_for_review", "chapter_id":1, "review":{}}}
    manager = JobManager(runner=runner); manager.startup(); first = manager.create_job("run_chapter", context=context)
    assert wait_for(manager, first["job_id"], context, {"failed"})["status"] == "failed"
    retry = manager.retry_job(first["job_id"], context=context)
    retried = wait_for(manager, retry["job_id"], context, {"waiting_for_review"})
    assert retried["retry_of"] == first["job_id"] and retried["attempt"] == 2
    stale = {"job_id":"job_stale", "project_root":manager._project_root(context), "project_id":"test", "status":"running", "logs":[]}
    manager._save(context, stale); manager.mark_interrupted_jobs()
    assert manager.get_job("job_stale", context=context)["status"] == "interrupted"; manager.shutdown()


def test_running_job_keeps_creation_context_after_active_project_switch(tmp_path: Path, monkeypatch):
    """The worker must use its captured context, never re-read active_project mid-run."""
    monkeypatch.chdir(tmp_path)
    project_a, project_b = tmp_path / "projects" / "a", tmp_path / "projects" / "b"
    project_a.mkdir(parents=True); project_b.mkdir(parents=True)
    context_a = get_project_context(project_a)
    release = Event()

    def runner(job, context, emit, cancelled):
        release.wait(1)
        # This deliberately resolves implicitly inside the worker.  JobManager's
        # context binding must still select project A after the UI activates B.
        DataStore(get_project_context()).write_text("data/job_owner.txt", get_project_context().root.name)
        return {"result": "done"}

    manager = JobManager(max_workers=1, runner=runner)
    manager.startup()
    created = manager.create_job("index_vault", context=context_a)
    wait_for(manager, created["job_id"], context_a, {"running"})
    config = tmp_path / ".story_os" / "config.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"active_project": "projects/b"}', encoding="utf-8")
    release.set()
    assert wait_for(manager, created["job_id"], context_a, {"completed"})["status"] == "completed"
    assert (project_a / "data" / "job_owner.txt").read_text(encoding="utf-8") == "a"
    assert not (project_b / "data" / "job_owner.txt").exists()
    manager.shutdown()
