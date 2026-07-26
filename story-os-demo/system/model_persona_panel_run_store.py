"""Immutable, project-local storage for multi-persona execution records."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.contracts.model_persona_execution import ExecutionMode
from core.contracts.model_persona_panel_execution import (
    MODEL_PERSONA_PANEL_RUN_SCHEMA_VERSION,
    ModelPersonaPanelExecutionResult,
    ModelPersonaPanelState,
    ModelPersonaPanelStatus,
    ModelPersonaPanelUsage,
)
from core.project_context import ProjectContext, get_project_context


class ModelPersonaPanelRunStore:
    def __init__(self, context: Optional[ProjectContext] = None) -> None:
        self.context = context or get_project_context()
        self.runs_dir = self.context.data_dir / "simulator" / "model_persona_panel_runs"

    def save_run(self, run: ModelPersonaPanelExecutionResult) -> Path:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        path = self.runs_dir / f"{run.panel_execution_id}.json"
        if path.exists():
            raise ValueError("Panel execution records are immutable")
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._to_dict(run), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        return path

    def load_run(self, panel_execution_id: str) -> Optional[ModelPersonaPanelExecutionResult]:
        path = self.runs_dir / f"{panel_execution_id}.json"
        if not path.exists():
            return None
        try:
            return self._from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def list_runs(self, chapter_id: Optional[int] = None) -> list[ModelPersonaPanelExecutionResult]:
        if not self.runs_dir.exists():
            return []
        runs: list[ModelPersonaPanelExecutionResult] = []
        for path in sorted(self.runs_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                run = self._from_dict(json.loads(path.read_text(encoding="utf-8")))
                if chapter_id is None or run.chapter_id == chapter_id:
                    runs.append(run)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return runs

    def _to_dict(self, run: ModelPersonaPanelExecutionResult) -> dict:
        # Deliberately no prompt, chapter text, provider request/response, secrets, or paths.
        return {
            "panel_execution_id": run.panel_execution_id,
            "schema_version": MODEL_PERSONA_PANEL_RUN_SCHEMA_VERSION,
            "created_at": run.created_at.isoformat(),
            "project_id": run.project_id,
            "timeline_id": run.timeline_id,
            "chapter_id": run.chapter_id,
            "source_version_id": run.source_version_id,
            "status": run.status.value,
            "execution_mode": run.execution_mode.value,
            "execution_profile": run.execution_profile,
            "execution_profile_version": run.execution_profile_version,
            "authoritative_panel": {
                "ordered_persona_ids": run.ordered_persona_ids,
                "fingerprint": run.authoritative_panel_fingerprint,
            },
            "model_persona_runs": {
                "child_execution_ids": run.child_execution_ids,
                "child_statuses": run.child_statuses,
            },
            "panel_execution_fingerprint": run.panel_execution_fingerprint,
            "source_hash": run.source_hash,
            "context_hash": run.context_hash,
            "reader_evaluator_version": run.reader_evaluator_version,
            "child_input_fingerprints": run.child_input_fingerprints,
            "expected_provider_call_count": run.expected_provider_call_count,
            "actual_provider_call_count": run.actual_provider_call_count,
            "cache_hit_count": run.cache_hit_count,
            "cache_miss_count": run.cache_miss_count,
            "usage": run.usage.to_dict() if run.usage else None,
            "usage_completeness": run.usage_completeness,
            "error_code": run.error_code,
            "staleness": run.staleness.value,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "live_ticket_id": run.live_ticket_id,
            "profile_registry_revision": run.profile_registry_revision,
            "budget_policy_id": run.budget_policy_id,
            "budget_policy_revision": run.budget_policy_revision,
            "counter_id": run.counter_id,
            "counter_revision": run.counter_revision,
            "counter_scope": run.counter_scope,
            "canonical_payload_hash": run.canonical_payload_hash,
            "thinking_mode": run.thinking_mode,
            "structured_output_mode": run.structured_output_mode,
        }

    def _from_dict(self, data: dict) -> ModelPersonaPanelExecutionResult:
        authoritative = data.get("authoritative_panel", {})
        children = data.get("model_persona_runs", {})
        usage_data = data.get("usage")
        usage = ModelPersonaPanelUsage(**usage_data) if isinstance(usage_data, dict) else None
        return ModelPersonaPanelExecutionResult(
            panel_execution_id=str(data["panel_execution_id"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            project_id=str(data["project_id"]), timeline_id=str(data["timeline_id"]),
            chapter_id=int(data["chapter_id"]), source_version_id=data.get("source_version_id"),
            status=ModelPersonaPanelStatus(data["status"]), execution_mode=ExecutionMode(data["execution_mode"]),
            execution_profile=str(data.get("execution_profile", "default")),
            execution_profile_version=str(data.get("execution_profile_version", "1.0")),
            ordered_persona_ids=list(authoritative.get("ordered_persona_ids", [])),
            child_execution_ids=dict(children.get("child_execution_ids", {})),
            child_statuses=dict(children.get("child_statuses", {})),
            authoritative_panel_fingerprint=str(authoritative.get("fingerprint", "")),
            panel_execution_fingerprint=str(data.get("panel_execution_fingerprint", "")),
            source_hash=str(data.get("source_hash", "")), context_hash=str(data.get("context_hash", "")),
            reader_evaluator_version=str(data.get("reader_evaluator_version", "")),
            child_input_fingerprints=dict(data.get("child_input_fingerprints", {})),
            expected_provider_call_count=int(data.get("expected_provider_call_count", 0)),
            actual_provider_call_count=int(data.get("actual_provider_call_count", 0)),
            cache_hit_count=int(data.get("cache_hit_count", 0)), cache_miss_count=int(data.get("cache_miss_count", 0)),
            usage=usage, usage_completeness=str(data.get("usage_completeness", "not_applicable")),
            error_code=data.get("error_code"), staleness=ModelPersonaPanelState(data.get("staleness", "current")),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            live_ticket_id=data.get("live_ticket_id"),
            profile_registry_revision=data.get("profile_registry_revision"),
            budget_policy_id=data.get("budget_policy_id"),
            budget_policy_revision=data.get("budget_policy_revision"),
            counter_id=data.get("counter_id"),
            counter_revision=data.get("counter_revision"),
            counter_scope=data.get("counter_scope"),
            canonical_payload_hash=data.get("canonical_payload_hash"),
            thinking_mode=data.get("thinking_mode"),
            structured_output_mode=data.get("structured_output_mode"),
        )
