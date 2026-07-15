"""Persistent, sanitized project-scoped model run traces."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.project_context import ProjectContext, get_project_context
from system.data_store import DataStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sanitize(value: Any, limit: int = 500) -> str:
    text = str(value or "").replace("\n", " ").replace("\r", " ")
    for marker in ("Bearer ", "sk-", "api_key", "authorization"):
        position = text.lower().find(marker.lower())
        if position >= 0:
            text = text[:position] + "[redacted]"
    return text[:limit]


class RunRecorder:
    def __init__(self, context: ProjectContext | None = None) -> None:
        self.context = context or get_project_context()
        self.store = DataStore(self.context)

    def start(self, *, task_type: str, model_key: str, provider: str, model: str, prompt_id: str, prompt_version: str, prompt_hash: str, job_id: str | None, chapter_id: int | None, route_snapshot: dict[str, Any]) -> dict[str, Any]:
        run = {"schema_version": "1.0", "run_id": f"run_{uuid4().hex}", "project_id": self.context.root.name, "project_root": self.context.relative_path(self.context.root), "job_id": job_id, "chapter_id": chapter_id, "task_type": task_type, "model_key": model_key, "provider": provider, "model": model, "prompt_id": prompt_id, "prompt_version": prompt_version, "prompt_hash": prompt_hash, "route_snapshot": route_snapshot, "status": "running", "started_at": _now(), "finished_at": None, "attempts": [], "usage": {}, "cost": {}, "warnings": [], "error": ""}
        self._save(run)
        return run

    def finish(self, run: dict[str, Any], *, status: str, usage: dict[str, Any], cost: dict[str, Any], warnings: list[str] | None = None, error: str = "", latency_ms: float | None = None) -> dict[str, Any]:
        run.update({"status": status, "finished_at": _now(), "usage": usage, "cost": cost, "warnings": [sanitize(item, 300) for item in (warnings or [])], "error": sanitize(error) if error else "", "latency_ms": round(float(latency_ms), 1) if latency_ms is not None else None})
        self._save(run)
        return run

    def attempt(self, run: dict[str, Any], *, model_key: str, status: str, message: str = "") -> None:
        run.setdefault("attempts", []).append({"at": _now(), "model_key": model_key, "status": status, "message": sanitize(message, 250)})
        self._save(run)

    def get(self, run_id: str) -> dict[str, Any] | None:
        return self.store.read_json(self._path(run_id), default=None, expected_type=dict)

    def list(self, *, task_type: str | None = None, model_key: str | None = None, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        directory = self.context.model_runs_dir / "runs"
        runs = [self.store.read_json(path, default={}, expected_type=dict) or {} for path in directory.glob("run_*.json")] if directory.exists() else []
        runs = [run for run in runs if run and (not task_type or run.get("task_type") == task_type) and (not model_key or run.get("model_key") == model_key) and (not status or run.get("status") == status)]
        return sorted(runs, key=lambda item: str(item.get("started_at", "")), reverse=True)[:max(1, min(limit, 200))]

    def usage_summary(self) -> dict[str, Any]:
        runs = self.list(limit=200)
        totals = {"runs": len(runs), "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": 0.0, "unknown_cost_runs": 0}
        by_model: dict[str, dict[str, Any]] = {}
        for run in runs:
            usage = run.get("usage") or {}; cost = run.get("cost") or {}; key = str(run.get("model_key", "unknown"))
            bucket = by_model.setdefault(key, {"runs": 0, "total_tokens": 0, "cost": 0.0, "unknown_cost_runs": 0})
            bucket["runs"] += 1
            for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = int(usage.get(name, 0) or 0); totals[name] += value
                if name == "total_tokens": bucket[name] += value
            if cost.get("amount") is None:
                totals["unknown_cost_runs"] += 1; bucket["unknown_cost_runs"] += 1
            else:
                totals["cost"] += float(cost["amount"]); bucket["cost"] += float(cost["amount"])
        totals["cost"] = round(totals["cost"], 8)
        return {"totals": totals, "by_model": by_model}

    def _path(self, run_id: str) -> Path:
        return self.context.model_runs_dir / "runs" / f"{run_id}.json"

    def _save(self, run: dict[str, Any]) -> None:
        self.store.write_json(self._path(str(run["run_id"])), run, backup=False)
