from __future__ import annotations

import json
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from core.project_context import ProjectContext, bind_project_context, get_project_context
from system.data_store import DataStore
from system.job_models import ACTIVE_JOB_STATUSES, RETRYABLE_JOB_STATUSES, make_job, make_step, now_iso, public_job

SUPPORTED_JOB_TYPES = {"run_chapter", "index_vault", "sync_obsidian", "quality_check", "memory_health", "revision_quality_check", "revision_continuity_check", "revision_impact_analysis", "apply_revision", "restore_canon_version", "rebuild_chapter_summary", "reindex_chapter_memory", "sync_revised_chapter_to_obsidian", "extract_narrative_events", "rebuild_narrative_memory", "recheck_memory_conflicts", "generate_context_preview"}
STEP_LABELS = {
    "build-context": "Build writing context", "plan-next": "Plan next chapter",
    "write-draft": "Write draft", "prepare-review": "Prepare review",
    "index-vault": "Update vector index", "sync-obsidian": "Sync Obsidian",
    "quality-check": "Quality assessment", "memory-health": "Memory health check",
    "revision-quality": "Check revision quality", "revision-continuity": "Check revision continuity",
    "revision-impact": "Analyze revision impact", "apply-revision": "Apply approved revision",
    "restore-canon": "Restore historical canon", "rebuild-summary": "Rebuild chapter summary",
    "reindex-chapter": "Reindex chapter memory", "sync-revised-chapter": "Sync revised chapter", "extract-events": "Extract narrative events", "rebuild-narrative": "Rebuild narrative memory", "recheck-conflicts": "Recheck memory conflicts", "context-preview": "Generate context preview",
}


class JobError(RuntimeError):
    code = "JOB_ERROR"


class JobNotFoundError(JobError):
    code = "JOB_NOT_FOUND"


class JobAlreadyRunningError(JobError):
    code = "JOB_ALREADY_RUNNING"
    def __init__(self, job_id: str):
        self.job_id = job_id
        super().__init__("A chapter generation job is already running for this project.")


class JobStateError(JobError):
    code = "JOB_STATE_INVALID"


class JobManager:
    """Small, persistent, per-project job runner for the local application."""

    def __init__(self, max_workers: int = 2, runner: Callable[..., dict[str, Any]] | None = None):
        self.max_workers = max_workers
        self._runner = runner
        self._executor: ThreadPoolExecutor | None = None
        self._futures: dict[str, Future[Any]] = {}
        self._lock = threading.RLock()
        self._accepting = False

    def startup(self) -> None:
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="storyos-job")
            self._accepting = True
        self.mark_interrupted_jobs()

    def shutdown(self) -> None:
        with self._lock:
            self._accepting = False
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=False)

    def ensure_started(self) -> None:
        if self._executor is None:
            self.startup()

    def create_job(self, job_type: str, parameters: dict[str, Any] | None = None,
                   *, context: ProjectContext | None = None, retry_of: str | None = None,
                   attempt: int = 1) -> dict[str, Any]:
        if job_type not in SUPPORTED_JOB_TYPES:
            raise JobStateError(f"Unsupported job type: {job_type}")
        if job_type == "run_chapter":
            try:
                from system.narrative_memory_service import NarrativeMemoryService
                result = NarrativeMemoryService(context or get_project_context()).preflight(int((parameters or {}).get("chapter_id", 1)))
                if result.get("status") == "blocked":
                    raise JobStateError("PREFLIGHT_BLOCKED")
            except JobStateError:
                raise
            except Exception:
                pass  # Legacy projects without narrative memory retain the established writing fallback.
        self.ensure_started()
        context = context or get_project_context()
        parameters = dict(parameters or {})
        if job_type == "run_chapter" and parameters.get("chapter_id") is None:
            plan = DataStore(context).read_json("data/next_chapter_plan.json", default={}, expected_type=dict) or {}
            state = DataStore(context).read_json("data/state.json", default={}, expected_type=dict) or {}
            parameters["chapter_id"] = int(plan.get("chapter_id", int(state.get("current_chapter", 0) or 0) + 1) or 1)
        with self._lock:
            if not self._accepting:
                raise JobStateError("The job runner is stopping.")
            if job_type == "run_chapter":
                existing = self._active_matching(context, job_type)
                if existing:
                    raise JobAlreadyRunningError(existing["job_id"])
            chapter_id = parameters.get("chapter_id")
            if job_type in {"run_chapter", "apply_revision", "restore_canon_version"} and chapter_id is not None:
                conflict = self._active_chapter_operation(context, int(chapter_id))
                if conflict:
                    raise JobStateError(f"CHAPTER_OPERATION_CONFLICT:{conflict['job_id']}")
            job = make_job(
                project_id=self._project_id(context), project_root=self._project_root(context),
                job_type=job_type, parameters=parameters, retry_of=retry_of, attempt=attempt,
            )
            job["steps"] = self._initial_steps(job_type)
            job["progress"] = {"current": 0, "total": len(job["steps"]), "percent": 0}
            self._save(context, job)
            self._submit(context, job["job_id"])
            return public_job(job)

    def get_job(self, job_id: str, *, context: ProjectContext | None = None, include_logs: bool = True) -> dict[str, Any]:
        context = context or get_project_context()
        return public_job(self._load(context, job_id), include_logs=include_logs)

    def list_jobs(self, *, context: ProjectContext | None = None, status: str | None = None,
                  job_type: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        context = context or get_project_context()
        jobs = self._all_jobs(context)
        if status:
            jobs = [job for job in jobs if job.get("status") == status]
        if job_type:
            jobs = [job for job in jobs if job.get("job_type") == job_type]
        jobs.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        return [public_job(job) for job in jobs[:max(1, min(limit, 100))]]

    def active_jobs(self, *, context: ProjectContext | None = None) -> list[dict[str, Any]]:
        context = context or get_project_context()
        return [public_job(job) for job in self._all_jobs(context) if job.get("status") in ACTIVE_JOB_STATUSES]

    def cancel_job(self, job_id: str, *, context: ProjectContext | None = None) -> dict[str, Any]:
        context = context or get_project_context()
        with self._lock:
            job = self._load(context, job_id)
            if job.get("status") not in ACTIVE_JOB_STATUSES:
                raise JobStateError("This job is no longer cancellable.")
            job["cancel_requested"] = True
            job["status"] = "cancel_requested"
            job["message"] = "Cancellation requested; waiting for the current safe point."
            self._log(job, "info", job.get("current_step", ""), job["message"])
            self._save(context, job)
            return public_job(job)

    def retry_job(self, job_id: str, *, context: ProjectContext | None = None) -> dict[str, Any]:
        context = context or get_project_context()
        source = self._load(context, job_id)
        if source.get("status") not in RETRYABLE_JOB_STATUSES:
            raise JobStateError("Only failed, cancelled, interrupted, or warning jobs can be retried.")
        attempt = int(source.get("attempt", 1) or 1) + 1
        new_job = self.create_job(str(source["job_type"]), dict(source.get("parameters") or {}),
                                  context=context, retry_of=source["job_id"], attempt=attempt)
        with self._lock:
            created = self._load(context, new_job["job_id"])
            reason = "Retry starts the full workflow because no safe checkpoint was proven."
            created.setdefault("warnings", []).append(reason)
            self._log(created, "info", "", reason)
            self._save(context, created)
            return public_job(created)

    def get_logs(self, job_id: str, *, context: ProjectContext | None = None, after: int = 0,
                 limit: int = 100) -> dict[str, Any]:
        context = context or get_project_context()
        job = self._load(context, job_id)
        entries = list(job.get("logs", []))
        start = max(0, after)
        size = max(1, min(limit, 200))
        return {"entries": entries[start:start + size], "next": min(len(entries), start + size), "total": len(entries)}

    def mark_interrupted_jobs(self) -> None:
        """Never resume external model calls after a process restart."""
        roots = {Path.cwd().resolve()}
        workspace = Path.cwd().resolve()
        projects_dir = workspace / "projects"
        if projects_dir.exists():
            roots.update(path.resolve() for path in projects_dir.iterdir() if path.is_dir())
        for root in roots:
            try:
                context = get_project_context(root)
                for job in self._all_jobs(context):
                    if job.get("status") in ACTIVE_JOB_STATUSES:
                        job["status"] = "interrupted"
                        job["finished_at"] = now_iso()
                        job["message"] = "Task stopped because the Story OS service restarted or was interrupted."
                        self._log(job, "warning", job.get("current_step", ""), job["message"])
                        self._save(context, job)
            except Exception:
                continue

    def _submit(self, context: ProjectContext, job_id: str) -> None:
        assert self._executor is not None
        self._futures[job_id] = self._executor.submit(self._run, context, job_id)

    def _run(self, context: ProjectContext, job_id: str) -> None:
        with bind_project_context(context):
            with self._lock:
                job = self._load(context, job_id)
                if job.get("cancel_requested"):
                    self._finish_cancelled(context, job, "Cancelled before execution started.")
                    return
                job["status"] = "running"
                job["started_at"] = now_iso()
                job["message"] = "Task is running."
                self._log(job, "info", "", job["message"])
                self._save(context, job)
            try:
                runner = self._runner
                if runner is None:
                    from system.job_handlers import run_job
                    runner = run_job
                result = runner(job, context, lambda event: self._progress(context, job_id, event),
                                lambda: self._cancel_requested(context, job_id))
                with self._lock:
                    current = self._load(context, job_id)
                    if current.get("cancel_requested") or (isinstance(result, dict) and result.get("cancelled")):
                        self._finish_cancelled(context, current, "Task cancelled at a safe point.")
                    else:
                        self._finish_success(context, current, result if isinstance(result, dict) else {})
            except Exception as exc:
                with self._lock:
                    current = self._load(context, job_id)
                    if current.get("cancel_requested"):
                        self._finish_cancelled(context, current, "Task cancelled after the current operation returned.")
                    else:
                        message = self._safe_error(exc)
                        current["status"] = "failed"
                        current["finished_at"] = now_iso()
                        current["message"] = message
                        current.setdefault("errors", []).append(message)
                        self._log(current, "error", current.get("current_step", ""), message)
                        self._save(context, current)
            finally:
                with self._lock:
                    self._futures.pop(job_id, None)

    def _progress(self, context: ProjectContext, job_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            job = self._load(context, job_id)
            name = str(event.get("name", ""))
            label = str(event.get("label") or STEP_LABELS.get(name, name))
            status = str(event.get("status", "running"))
            step = next((item for item in job["steps"] if item.get("name") == name), None)
            if step is None:
                step = make_step(name, label)
                job["steps"].append(step)
            if status == "running":
                step["started_at"] = step.get("started_at") or now_iso()
                job["current_step"] = name
                job["message"] = str(event.get("message") or label)
            else:
                step["finished_at"] = now_iso()
            step["status"] = status
            step["message"] = str(event.get("message") or step.get("message", ""))[:500]
            if event.get("outputs"):
                step["outputs"] = event["outputs"]
            if event.get("warnings"):
                step["warnings"] = list(event["warnings"])
                job["warnings"].extend(str(x) for x in event["warnings"])
            if status == "failed":
                step["errors"].append(step["message"])
            job["progress"] = {"current": sum(1 for item in job["steps"] if item.get("status") in {"completed", "completed_with_warnings"}), "total": len(job["steps"]), "percent": 0}
            self._log(job, "error" if status == "failed" else "info", name, step["message"] or status)
            self._save(context, job)

    def _finish_success(self, context: ProjectContext, job: dict[str, Any], result: dict[str, Any]) -> None:
        report = result.get("pipeline_report", {}) if isinstance(result, dict) else {}
        pipeline_status = report.get("status") if isinstance(report, dict) else None
        job["result"] = result
        job["finished_at"] = now_iso()
        if pipeline_status == "waiting_for_review":
            job["status"] = "waiting_for_review"
            review = report.get("review", {})
            job["message"] = "Draft generated and waiting for human review."
            job["result"].update({"draft_version": 1, "review_status": review.get("status", "pending"), "next_action": "open_review"})
        elif pipeline_status == "success_with_warnings" or job.get("warnings"):
            job["status"] = "completed_with_warnings"
            job["message"] = "Task completed with warnings."
        elif pipeline_status == "failed":
            job["status"] = "failed"
            job["message"] = str(report.get("errors", ["Pipeline failed."])[0])
            job.setdefault("errors", []).append(job["message"])
        else:
            job["status"] = "completed"
            job["message"] = "Task completed."
        self._log(job, "info", job.get("current_step", ""), job["message"])
        self._save(context, job)

    def _finish_cancelled(self, context: ProjectContext, job: dict[str, Any], message: str) -> None:
        job["status"] = "cancelled"
        job["finished_at"] = now_iso()
        job["message"] = message
        self._log(job, "info", job.get("current_step", ""), message)
        self._save(context, job)

    def _cancel_requested(self, context: ProjectContext, job_id: str) -> bool:
        return bool(self._load(context, job_id).get("cancel_requested"))

    def _active_matching(self, context: ProjectContext, job_type: str) -> dict[str, Any] | None:
        return next((job for job in self._all_jobs(context) if job.get("job_type") == job_type and job.get("status") in ACTIVE_JOB_STATUSES), None)

    def _active_chapter_operation(self, context: ProjectContext, chapter_id: int) -> dict[str, Any] | None:
        protected = {"run_chapter", "apply_revision", "restore_canon_version"}
        return next((job for job in self._all_jobs(context) if job.get("job_type") in protected and int((job.get("parameters") or {}).get("chapter_id", -1)) == chapter_id and job.get("status") in ACTIVE_JOB_STATUSES), None)

    def _all_jobs(self, context: ProjectContext) -> list[dict[str, Any]]:
        if not context.jobs_dir.exists():
            return []
        jobs: list[dict[str, Any]] = []
        for path in context.jobs_dir.glob("job_*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    jobs.append(data)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
        return jobs

    def _load(self, context: ProjectContext, job_id: str) -> dict[str, Any]:
        path = context.jobs_dir / f"{job_id}.json"
        data: dict[str, Any] | None = None
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                candidate = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(candidate, dict):
                    data = candidate
                    break
            except FileNotFoundError as exc:
                raise JobNotFoundError("Job not found in the current project.") from exc
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.01)
        if data is None:
            raise JobNotFoundError("Job record is unreadable.") from last_error
        if data.get("project_root") != self._project_root(context):
            raise JobNotFoundError("Job does not belong to the current project.")
        return data

    def _save(self, context: ProjectContext, job: dict[str, Any]) -> None:
        context.jobs_dir.mkdir(parents=True, exist_ok=True)
        job["updated_at"] = now_iso()
        store = DataStore(context)
        store.write_json(context.jobs_dir / f"{job['job_id']}.json", job, backup=False)
        log_lines = "\n".join(json.dumps(entry, ensure_ascii=False) for entry in job.get("logs", []))
        store.write_text(context.jobs_dir / "logs" / f"{job['job_id']}.log", log_lines + ("\n" if log_lines else ""), backup=False)
        index_path = context.jobs_dir / "index.json"
        index = {"schema_version": "1.0", "jobs": []}
        if index_path.exists():
            try:
                index = json.loads(index_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                pass
        summaries = [item for item in index.get("jobs", []) if item.get("job_id") != job["job_id"]]
        summaries.append({key: job.get(key) for key in ("job_id", "job_type", "status", "created_at", "updated_at", "project_id")})
        summaries.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        index["jobs"] = summaries[:200]
        store.write_json(index_path, index, backup=False)

    def _log(self, job: dict[str, Any], level: str, step: str, message: str) -> None:
        entry = {"timestamp": now_iso(), "level": level, "step": step, "message": str(message)[:500]}
        logs = list(job.get("logs", []))
        logs.append(entry)
        job["logs"] = logs[-200:]

    @staticmethod
    def _initial_steps(job_type: str) -> list[dict[str, Any]]:
        names = {
            "run_chapter": ["build-context", "plan-next", "write-draft", "prepare-review"],
            "index_vault": ["index-vault"], "sync_obsidian": ["sync-obsidian"],
            "quality_check": ["quality-check"], "memory_health": ["memory-health"],
            "revision_quality_check": ["revision-quality"], "revision_continuity_check": ["revision-continuity"],
            "revision_impact_analysis": ["revision-impact"], "apply_revision": ["apply-revision"],
            "restore_canon_version": ["restore-canon"], "rebuild_chapter_summary": ["rebuild-summary"],
            "reindex_chapter_memory": ["reindex-chapter"], "sync_revised_chapter_to_obsidian": ["sync-revised-chapter"], "extract_narrative_events":["extract-events"], "rebuild_narrative_memory":["rebuild-narrative"], "recheck_memory_conflicts":["recheck-conflicts"], "generate_context_preview":["context-preview"],
        }[job_type]
        return [make_step(name, STEP_LABELS[name]) for name in names]

    @staticmethod
    def _project_root(context: ProjectContext) -> str:
        try:
            return context.root.resolve().relative_to(Path.cwd().resolve()).as_posix()
        except ValueError:
            return context.root.resolve().as_posix()

    @staticmethod
    def _project_id(context: ProjectContext) -> str:
        return context.root.name or "story-os"

    @staticmethod
    def _safe_error(error: Exception) -> str:
        message = str(error).strip() or error.__class__.__name__
        return message.replace("\\", "/")[:500]


_manager: JobManager | None = None
_manager_lock = threading.Lock()


def get_job_manager() -> JobManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = JobManager()
        return _manager


def reset_job_manager_for_tests() -> None:
    global _manager
    with _manager_lock:
        if _manager is not None:
            _manager.shutdown()
        _manager = None
