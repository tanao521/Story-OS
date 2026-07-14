from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

ACTIVE_JOB_STATUSES = {"queued", "running", "cancel_requested"}
TERMINAL_JOB_STATUSES = {
    "completed", "completed_with_warnings", "failed", "cancelled", "interrupted", "waiting_for_review"
}
RETRYABLE_JOB_STATUSES = {"failed", "cancelled", "interrupted", "completed_with_warnings", "recoverable_failed"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_job_id() -> str:
    return f"job_{uuid4().hex}"


def make_step(name: str, label: str) -> dict[str, Any]:
    return {
        "name": name, "label": label, "status": "pending", "started_at": None,
        "finished_at": None, "message": "", "warnings": [], "errors": [], "outputs": {},
    }


def make_job(*, project_id: str, project_root: str, job_type: str,
             parameters: dict[str, Any] | None = None, retry_of: str | None = None,
             attempt: int = 1) -> dict[str, Any]:
    timestamp = now_iso()
    return {
        "schema_version": "1.0", "job_id": new_job_id(), "project_id": project_id,
        "project_root": project_root, "job_type": job_type, "parameters": parameters or {},
        "status": "queued", "created_at": timestamp, "started_at": None, "finished_at": None,
        "updated_at": timestamp, "progress": {"current": 0, "total": 0, "percent": 0},
        "current_step": "", "steps": [], "message": "Task created.", "warnings": [],
        "errors": [], "result": {}, "cancel_requested": False, "retry_of": retry_of,
        "attempt": attempt, "logs": [], "heartbeat_at": timestamp, "worker_id": "",
        "progress_message": "Task created.",
    }


def public_job(job: dict[str, Any], *, include_logs: bool = False) -> dict[str, Any]:
    result = dict(job)
    if not include_logs:
        result.pop("logs", None)
    result.pop("parameters", None)
    return result
