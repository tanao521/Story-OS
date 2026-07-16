"""Production hardening helpers for the Stage 15 evaluation boundary.

All read endpoints in this module are deliberately side-effect free.  The only
mutating operation is explicit, idempotent deletion of expired previews after a
matching dry-run preview has been confirmed by the caller.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from core.contracts import HashExpectation, HashGuard, OperationEnvelope, ProjectRef
from core.project_context import ProjectContext
from llm.run_recorder import RunRecorder
from system.data_store import DataStore
from system.safe_write import DataStoreWriteFacade

from .planning_comparison import PlanningEvaluationComparisonService
from .planning_evaluation import PlanningEvaluationService
from .service import EvaluationError, EvaluationService


class EvaluationProductionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_limit(value: int | None, default: int = 20) -> int:
    return max(1, min(int(value or default), 100))


def _cursor(row: dict[str, Any]) -> str:
    return f"{row.get('created_at') or row.get('started_at') or ''}|{row.get('evaluation_id') or row.get('run_id') or row.get('improvement_id') or ''}"


def _paginate(rows: list[dict[str, Any]], cursor: str = "", limit: int = 20) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda item: _cursor(item), reverse=True)
    if cursor:
        ordered = [item for item in ordered if _cursor(item) < cursor]
    page = ordered[:_safe_limit(limit)]
    return {"items": page, "next_cursor": _cursor(page[-1]) if len(ordered) > len(page) and page else None, "limit": _safe_limit(limit)}


class EvaluationProductionService:
    def __init__(self, context: ProjectContext) -> None:
        self.context, self.store = context, DataStore(context)
        self.writer = DataStoreWriteFacade(context)

    def usage_events(self, *, cursor: str = "", limit: int = 20, **filters: Any) -> dict[str, Any]:
        rows = []
        for run in RunRecorder(self.context).list(limit=200):
            if filters.get("chapter_number") not in (None, "") and int(run.get("chapter_id") or 0) != int(filters["chapter_number"]):
                continue
            if filters.get("evaluation_id") and run.get("evaluation_id") != filters["evaluation_id"]:
                continue
            if filters.get("improvement_request_id") and run.get("improvement_request_id") != filters["improvement_request_id"]:
                continue
            if filters.get("candidate_id") and run.get("candidate_id") != filters["candidate_id"]:
                continue
            created = str(run.get("started_at") or "")
            if filters.get("date_from") and created < str(filters["date_from"]):
                continue
            if filters.get("date_to") and created > str(filters["date_to"]):
                continue
            usage, cost = run.get("usage") or {}, run.get("cost") or {}
            rows.append({"run_id": run.get("run_id"), "provider": run.get("provider"), "model": run.get("model"), "task_type": run.get("task_type"), "project_id": self.context.root.name, "job_id": run.get("job_id"), "evaluation_id": run.get("evaluation_id"), "improvement_request_id": run.get("improvement_request_id"), "candidate_id": run.get("candidate_id"), "input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens"), "token_status": "estimated" if usage.get("estimated") else "available" if usage else "unavailable", "estimated_cost": cost.get("amount"), "cost_status": "available" if cost.get("amount") is not None else "unavailable", "latency_ms": run.get("latency_ms"), "fallback_used": run.get("status") == "completed_with_fallback", "success": str(run.get("status", "")).startswith("completed"), "error_type": run.get("error_code") or ("MODEL_ERROR" if run.get("error") else None), "created_at": created})
        return _paginate(rows, cursor, limit)

    def usage_summary(self, **filters: Any) -> dict[str, Any]:
        events = self.usage_events(limit=100, **filters)["items"]
        totals: dict[str, Any] = {"call_count": len(events), "input_tokens": 0, "output_tokens": 0, "estimated_cost": 0.0, "fallback_count": 0, "failure_count": 0, "average_latency_ms": None, "token_status": "available", "cost_status": "available"}
        latency = []
        for item in events:
            if item["token_status"] == "unavailable": totals["token_status"] = "unavailable"
            else:
                totals["input_tokens"] += int(item["input_tokens"] or 0); totals["output_tokens"] += int(item["output_tokens"] or 0)
            if item["cost_status"] == "unavailable": totals["cost_status"] = "unavailable"
            else: totals["estimated_cost"] += float(item["estimated_cost"] or 0)
            totals["fallback_count"] += int(bool(item["fallback_used"])); totals["failure_count"] += int(not bool(item["success"]))
            if isinstance(item["latency_ms"], (int, float)): latency.append(item["latency_ms"])
        if totals["token_status"] == "unavailable": totals["input_tokens"] = totals["output_tokens"] = None
        if totals["cost_status"] == "unavailable": totals["estimated_cost"] = None
        else: totals["estimated_cost"] = round(totals["estimated_cost"], 8)
        if latency: totals["average_latency_ms"] = round(sum(latency) / len(latency), 1)
        return {"scope": {key: value for key, value in filters.items() if value not in (None, "")}, "totals": totals}

    def export(self, evaluation_id: str, format: str, *, comparison: bool = False) -> tuple[str, str]:
        if format not in {"json", "markdown"}:
            raise EvaluationProductionError("EVALUATION_EXPORT_FORMAT_INVALID", "format must be json or markdown.")
        try:
            report = EvaluationService(self.context).detail(evaluation_id)
        except EvaluationError:
            try: report = PlanningEvaluationService(self.context).detail(evaluation_id)
            except Exception as exc: raise EvaluationProductionError("EVALUATION_EXPORT_NOT_FOUND", "Evaluation report was not found.") from exc
        payload: dict[str, Any] = self._safe_export(report)
        if comparison:
            payload["comparison"] = PlanningEvaluationComparisonService(self.context).comparison(evaluation_id)
        if format == "json": return "application/json", json.dumps(payload, ensure_ascii=False, indent=2)
        lines = [f"# Evaluation {payload.get('evaluation_id')}", "", f"- Gate: {payload.get('gate_status')}", f"- Score: {payload.get('overall_score')}", f"- Created: {payload.get('created_at')}", "", "## Dimensions"]
        lines.extend(f"- {item.get('display_name') or item.get('dimension_id')}: {item.get('score')} ({item.get('status')})" for item in payload.get("dimensions", []))
        lines += ["", "## Issues"] + [f"- [{item.get('severity')}] {item.get('title')}" for item in payload.get("priority_issues", [])]
        if payload.get("suggestions"): lines += ["", "## Suggestions"] + [f"- {item}" for item in payload["suggestions"]]
        return "text/markdown; charset=utf-8", "\n".join(lines) + "\n"

    def maintenance_preview(self) -> dict[str, Any]:
        items = []
        root = self.context.data_dir / "evaluations" / "improvements"
        if root.exists():
            for path in root.rglob("*.json"):
                if path.parent.name not in {"previews", "partial_previews"}: continue
                value = self.store.read_json(path, default={}, expected_type=dict) or {}
                try: expired = datetime.fromisoformat(str(value.get("expires_at", "")).replace("Z", "+00:00")) <= datetime.now(timezone.utc)
                except ValueError: expired = False
                if expired:
                    items.append({"item_id": sha256(path.relative_to(self.context.root).as_posix().encode()).hexdigest()[:20], "kind": path.parent.name, "created_at": value.get("created_at"), "expires_at": value.get("expires_at"), "path": path.relative_to(self.context.root).as_posix()})
        items.sort(key=lambda item: str(item.get("expires_at") or ""))
        preview_id = sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()[:20]
        return {"preview_id": preview_id, "items": items, "count": len(items)}

    def cleanup(self, payload: dict[str, Any]) -> dict[str, Any]:
        expected = sorted(map(str, payload.get("expected_item_ids") or []))
        if not str(payload.get("operation_id") or "").strip(): raise EvaluationProductionError("EVALUATION_MAINTENANCE_OPERATION_REQUIRED", "operation_id is required.")
        audit_path = "data/evaluations/maintenance_audit.json"; audit = self.store.read_json(audit_path, default=[], expected_type=list) or []
        operation_id = str(payload["operation_id"])
        request_hash = HashGuard.sha256_json({"preview_id": str(payload.get("preview_id") or ""), "expected_item_ids": expected})
        previous = next((item for item in audit if item.get("operation_id") == operation_id), None)
        if previous:
            if previous.get("request_fingerprint") == request_hash:
                return {"deleted_item_ids": previous.get("deleted_item_ids", []), "replayed": True}
            raise EvaluationProductionError("EVALUATION_MAINTENANCE_OPERATION_CONFLICT", "operation_id was already used for a different cleanup request.")
        preview = self.maintenance_preview()
        if payload.get("preview_id") != preview["preview_id"] or expected != sorted(item["item_id"] for item in preview["items"]):
            raise EvaluationProductionError("EVALUATION_MAINTENANCE_PREVIEW_STALE", "The cleanup preview no longer matches the expired previews.")
        for item in preview["items"]: self.store.path(item["path"]).unlink(missing_ok=True)
        project = ProjectRef.from_context(self.context)
        operation = OperationEnvelope(
            operation_id=operation_id,
            operation_type="maintenance_cleanup",
            project_id=project.project_id,
            target_type="maintenance_audit",
            target_id="evaluation_maintenance",
            expected_hashes={"cleanup_request": request_hash},
            confirmed=True,
            reason="expired_preview_cleanup",
        )
        audit_file = self.store.path(audit_path)
        before_hash = HashGuard.file_sha256(audit_file) if audit_file.exists() else None
        next_audit = (audit + [{"operation_id": operation_id, "preview_id": preview["preview_id"], "deleted_item_ids": expected, "created_at": _now(), "request_fingerprint": request_hash}])[-200:]
        expectation = HashExpectation(
            expected_sha256=before_hash,
            candidate_sha256=HashGuard.sha256_json(next_audit),
            allow_missing_target=before_hash is None,
        )
        write = self.writer.replace_json(project=project, target_path=audit_path, payload=next_audit, operation=operation, expectation=expectation)
        return {"deleted_item_ids": expected, "replayed": False, "audit": write.public_view()}

    def health(self) -> dict[str, Any]:
        index = self.store.read_json("data/evaluations/index.json", default={"reports": []}, expected_type=dict)
        index_ok = isinstance(index, dict) and isinstance(index.get("reports", []), list)
        missing = []
        for row in (index or {}).get("reports", []) if index_ok else []:
            if isinstance(row, dict) and row.get("path") and not self.store.exists(str(row["path"])): missing.append(str(row.get("evaluation_id") or "unknown"))
        previews = self.maintenance_preview()["count"]
        interrupted = [job.get("job_id") for job in __import__("system.job_manager", fromlist=["get_job_manager"]).get_job_manager().list_jobs(context=self.context, status="interrupted", limit=100)]
        return {"status": "warning" if missing or interrupted else "ok", "index_parseable": index_ok, "missing_report_references": missing, "expired_preview_count": previews, "interrupted_job_count": len(interrupted), "usage_parseable": isinstance(RunRecorder(self.context).usage_summary(), dict)}

    @staticmethod
    def _safe_export(report: dict[str, Any]) -> dict[str, Any]:
        allowed = {"evaluation_id", "project_id", "target_type", "target_ref", "profile_id", "profile_version", "gate_status", "gate_reasons", "overall_score", "overall_coverage", "overall_confidence", "confidence", "dimensions", "hard_issues", "priority_issues", "suggestions", "created_at", "status"}
        return {key: report.get(key) for key in allowed if key in report}
