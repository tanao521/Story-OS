"""Service layer for Stage 15.1. It aggregates persisted evidence and never calls a model."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.project_context import ProjectContext
from system.data_store import DataStore
from system.quality_checker import load_quality_report
from system.continuity_checker import load_continuity_report
from system.version_manager import list_versions, read_version_payload
from planning_engine import PlanningControlError, PlanningDependencyService
from planning_engine.rolling_service import RollingWindowService
from planning_engine.scheduling_service import NarrativeSchedulingService

from .adapters import character_state_adapter, continuity_adapter, plan_completion_adapter, planning_health_adapter, quality_report_adapter, reader_simulation_adapter
from .gates import evaluate_gates
from .models import DimensionScore, EvaluationTarget, public
from .profiles import profile, profiles
from .scoring import weighted_score


class EvaluationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class EvaluationService:
    def __init__(self, context: ProjectContext) -> None:
        self.context, self.store = context, DataStore(context)

    def overview(self) -> dict[str, Any]:
        chapter = self._current_chapter()
        try:
            selected = self._resolve_target(EvaluationTarget("chapter_draft", chapter)) if chapter else None
        except EvaluationError:
            selected = None
        reports = self.list_reports(chapter_number=chapter, limit=1)
        latest = reports[0] if reports else None
        health, health_issues = self._planning_health()
        return {
            "current_chapter": chapter,
            "target": selected.reference() if selected else {},
            "latest_report": self._public_report(latest) if latest else None,
            "latest_report_stale": bool(latest and self._status(latest) == "stale"),
            "available_evidence": self._available_evidence(selected) if selected else [],
            "missing_evidence": self._missing_evidence(selected) if selected else ["chapter_draft"],
            "planning_gate_summary": {"health": health, "issue_count": len(health_issues)},
        }

    def generate(self, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        target_type = str(payload.get("target_type", "chapter_draft"))
        if target_type != "chapter_draft":
            raise EvaluationError("EVALUATION_INSUFFICIENT_EVIDENCE", "Stage 15.1 only produces chapter_draft reports.")
        profile_id = str(payload.get("profile_id", "chapter-default-v1"))
        selected_profile = profile(profile_id)
        if not selected_profile:
            raise EvaluationError("EVALUATION_PROFILE_NOT_FOUND", "Evaluation profile was not found.")
        chapter = self._integer(payload.get("chapter_number")) or self._current_chapter()
        target = self._resolve_target(EvaluationTarget(target_type, chapter, str(payload.get("source_type", "")), self._integer(payload.get("source_version"))))
        snapshots = self._snapshots(target)
        operation_id = str(payload.get("operation_id", "")).strip()
        if operation_id:
            replay = self._find_operation(operation_id)
            if replay:
                if replay.get("source_snapshots", {}).get("chapter_content_hash") != snapshots.get("chapter_content_hash"):
                    raise EvaluationError("EVALUATION_TARGET_CHANGED", "The target content changed after this operation was first evaluated.")
                return self._public_report(replay), True
        report = self._build_report(target, selected_profile, snapshots, operation_id)
        self._persist(report)
        return self._public_report(report), False

    def list_reports(self, *, target_type: str = "", chapter_number: int | None = None, status: str = "", limit: int = 30) -> list[dict[str, Any]]:
        index = self.store.read_json("data/evaluations/index.json", default={"reports": []}, expected_type=dict) or {"reports": []}
        rows = list(index.get("reports", [])) if isinstance(index.get("reports"), list) else []
        output = []
        for row in rows:
            if not isinstance(row, dict): continue
            if target_type and row.get("target_type") != target_type: continue
            if chapter_number and int(row.get("chapter_number", 0) or 0) != chapter_number: continue
            detail = self._read_report(str(row.get("evaluation_id", "")), int(row.get("chapter_number", 0) or 0))
            if not detail: continue
            report_status = self._status(detail)
            if status and report_status != status: continue
            output.append(self._public_report(detail, status=report_status, compact=True))
        return sorted(output, key=lambda item: str(item.get("created_at", "")), reverse=True)[:max(1, min(limit, 100))]

    def detail(self, evaluation_id: str) -> dict[str, Any]:
        index = self.store.read_json("data/evaluations/index.json", default={"reports": []}, expected_type=dict) or {}
        for row in index.get("reports", []) if isinstance(index.get("reports"), list) else []:
            if isinstance(row, dict) and row.get("evaluation_id") == evaluation_id:
                report = self._read_report(evaluation_id, int(row.get("chapter_number", 0) or 0))
                if report: return self._public_report(report)
        raise EvaluationError("EVALUATION_TARGET_NOT_FOUND", "Evaluation report was not found.")

    def _build_report(self, target: EvaluationTarget, selected_profile: dict[str, Any], snapshots: dict[str, Any], operation_id: str) -> dict[str, Any]:
        source = self._source(target)
        quality = load_quality_report(target.chapter_number or 1, target.source_type, target.source_version or 0, self.context.data_dir)
        continuity = load_continuity_report(target.chapter_number or 1, target.source_type, target.source_version or 0, self.context.data_dir, snapshots["chapter_content_hash"], snapshots.get("previous_chapter_content_hash", ""))
        plan = self.store.read_json("data/next_chapter_plan.json", default={}, expected_type=dict) or {}
        characters = self.store.read_json("data/characters.json", default={}, expected_type=dict) or {}
        quality_rows = quality_report_adapter.adapt(quality, "quality_report")
        continuity_rows = continuity_adapter.adapt(continuity, "continuity_report")
        plan_row = plan_completion_adapter.adapt(plan, "next_chapter_plan")
        character_row = character_state_adapter.adapt(characters, "characters")
        reader_rows = reader_simulation_adapter.adapt(quality.get("reader_simulation", {}) if quality else {}, "quality_report")
        all_rows: dict[str, dict[str, Any]] = {**quality_rows, **continuity_rows, **reader_rows}
        if plan_row: all_rows["plan_completion"] = plan_row
        if character_row and "character_consistency" not in all_rows: all_rows["character_consistency"] = character_row
        dimensions = []
        for spec in selected_profile["dimensions"]:
            row = all_rows.get(spec["dimension_id"], {})
            dimensions.append(DimensionScore(dimension_id=spec["dimension_id"], display_name=spec["display_name"], weight=float(spec["weight"]), score=row.get("score"), confidence=float(row.get("confidence", 0)), status="available" if row.get("score") is not None else "insufficient_evidence", source_type=str(row.get("source_type", "existing_report")), evidence=row.get("evidence", []), issues=row.get("issues", []), suggestions=row.get("suggestions", [])))
        health, health_issues = self._planning_health()
        issues = [issue for dimension in dimensions for issue in dimension.issues] + health_issues
        gate = evaluate_gates(issues)
        score, confidence = weighted_score(dimensions)
        return {
            "evaluation_id": f"evaluation_{uuid4().hex}", "project_id": self.context.root.name,
            "target_type": target.target_type, "target_ref": target.reference(), "profile_id": selected_profile["profile_id"],
            "profile_version": selected_profile["version"], "operation_id": operation_id, "gate_status": gate.status,
            "gate_reasons": gate.reasons, "overall_score": score, "confidence": confidence,
            "dimensions": public(dimensions), "hard_issues": public([item for item in issues if item.severity == "blocking"]),
            "priority_issues": public([item for item in issues if item.severity in {"blocking", "high", "medium"}]),
            "suggestions": list(dict.fromkeys(suggestion for dimension in dimensions for suggestion in dimension.suggestions if suggestion)),
            "source_snapshots": snapshots, "planning_health": health, "model_usage_refs": [],
            "created_at": datetime.now(timezone.utc).isoformat(), "created_by": "user",
        }

    def _resolve_target(self, requested: EvaluationTarget) -> EvaluationTarget:
        chapter = requested.chapter_number or self._current_chapter()
        if chapter < 1: raise EvaluationError("EVALUATION_TARGET_NOT_FOUND", "No current chapter is available for evaluation.")
        source_type, source_version = requested.source_type, requested.source_version
        if not source_type or not source_version:
            versions = list_versions(chapter, self.context.data_dir)
            selected_ref = versions.get("selected", {}) if isinstance(versions.get("selected"), dict) else {}
            selected = next((row for key in ("drafts", "edited", "manual") for row in versions.get(key, []) if str(row.get("source_type")) == str(selected_ref.get("source_type")) and int(row.get("version", 0) or 0) == self._integer(selected_ref.get("version"))), None)
            if not selected:
                selected = next((rows[-1] for rows in (versions.get("manual", []), versions.get("edited", []), versions.get("drafts", [])) if rows), None)
            if not selected: raise EvaluationError("EVALUATION_TARGET_NOT_FOUND", "No draft, edited, or manual chapter version is available.")
            source_type, source_version = str(selected["source_type"]), int(selected["version"])
        if source_type not in {"draft", "edited", "manual"}: raise EvaluationError("EVALUATION_TARGET_NOT_FOUND", "Only local chapter versions can be evaluated in Stage 15.1.")
        return EvaluationTarget("chapter_draft", chapter, source_type, source_version)

    def _source(self, target: EvaluationTarget) -> dict[str, Any]:
        versions = list_versions(target.chapter_number or 1, self.context.data_dir)
        collection = {"draft": "drafts", "edited": "edited", "manual": "manual"}[target.source_type]
        item = next((row for row in versions.get(collection, []) if int(row.get("version", 0) or 0) == target.source_version), None)
        if not item: raise EvaluationError("EVALUATION_TARGET_NOT_FOUND", "Requested chapter version was not found.")
        return read_version_payload(item)

    def _snapshots(self, target: EvaluationTarget) -> dict[str, Any]:
        source = self._source(target)
        text = str(source.get("manual_text") or source.get("edited_text") or source.get("draft_text") or "")
        chapter = target.chapter_number or 1
        previous = self.store.read_text(f"data/chapters/chapter_{chapter - 1:03d}.md", default="") if chapter > 1 else ""
        def file_hash(path: str) -> str:
            content = self.store.read_text(path, default="") or ""
            return sha256(content.encode("utf-8")).hexdigest() if content else ""
        return {"chapter_content_hash": sha256(text.encode("utf-8")).hexdigest(), "previous_chapter_content_hash": sha256(previous.encode("utf-8")).hexdigest() if previous else "", "next_chapter_plan_hash": file_hash("data/next_chapter_plan.json"), "quality_report_hash": file_hash(f"data/quality_reports/chapter_{chapter:03d}_{target.source_type}_v{target.source_version:03d}_quality.json"), "continuity_report_hash": file_hash(f"data/continuity_reports/chapter_{chapter:03d}_{target.source_type}_v{target.source_version:03d}_continuity.json"), "character_state_hash": file_hash("data/characters.json"), "narrative_memory_hash": file_hash("data/narrative_memory/state/state.json"), "evaluation_profile_version": 1}

    def _planning_health(self) -> tuple[dict[str, Any], list[Any]]:
        health: dict[str, Any] = {}
        for name, factory, method in [("rolling_window", RollingWindowService, "check_window_health"), ("dependencies", PlanningDependencyService, "health"), ("schedule", NarrativeSchedulingService, "health")]:
            try: health[name] = getattr(factory(self.context), method)()
            except (PlanningControlError, OSError, ValueError): health[name] = {"status": "unknown"}
        _, issues = planning_health_adapter.adapt(health)
        return health, issues

    def _persist(self, report: dict[str, Any]) -> None:
        chapter = int(report["target_ref"].get("chapter_number", 0) or 0)
        path = f"data/evaluations/chapter_{chapter:03d}/{report['evaluation_id']}.json"
        self.store.write_json(path, report)
        index = self.store.read_json("data/evaluations/index.json", default={"reports": []}, expected_type=dict) or {"reports": []}
        rows = [row for row in index.get("reports", []) if isinstance(row, dict)]
        for row in rows:
            if int(row.get("chapter_number", 0) or 0) == chapter and row.get("evaluation_id") != report["evaluation_id"]:
                previous = self._read_report(str(row.get("evaluation_id", "")), chapter)
                if previous and self._status(previous) == "current": previous["status_override"] = "superseded"; self.store.write_json(f"data/evaluations/chapter_{chapter:03d}/{previous['evaluation_id']}.json", previous)
        rows.append({"evaluation_id": report["evaluation_id"], "chapter_number": chapter, "target_type": report["target_type"], "created_at": report["created_at"], "path": path})
        self.store.write_json("data/evaluations/index.json", {"reports": rows})

    def _status(self, report: dict[str, Any]) -> str:
        if report.get("status_override") == "superseded": return "superseded"
        try:
            target = EvaluationTarget(**{key: report.get("target_ref", {}).get(key) for key in ("target_type", "chapter_number", "source_type", "source_version")})
            if self._snapshots(target).get("chapter_content_hash") != report.get("source_snapshots", {}).get("chapter_content_hash"): return "stale"
        except (EvaluationError, TypeError): return "invalid"
        return "current"

    def _read_report(self, evaluation_id: str, chapter: int) -> dict[str, Any]:
        return self.store.read_json(f"data/evaluations/chapter_{chapter:03d}/{evaluation_id}.json", default={}, expected_type=dict) or {}

    def _find_operation(self, operation_id: str) -> dict[str, Any] | None:
        for item in self.list_reports(limit=100):
            if item.get("operation_id") == operation_id:
                return self._read_report(str(item["evaluation_id"]), int(item.get("target_ref", {}).get("chapter_number", 0) or 0))
        return None

    def _public_report(self, report: dict[str, Any] | None, *, status: str | None = None, compact: bool = False) -> dict[str, Any] | None:
        if not report: return None
        value = dict(report); value["status"] = status or self._status(value)
        if compact:
            return {key: value.get(key) for key in ("evaluation_id", "project_id", "target_type", "target_ref", "profile_id", "gate_status", "overall_score", "confidence", "created_at", "operation_id", "status")}
        return value

    def _available_evidence(self, target: EvaluationTarget) -> list[str]:
        snapshots = self._snapshots(target)
        return [key for key, value in snapshots.items() if value and key != "evaluation_profile_version"]

    def _missing_evidence(self, target: EvaluationTarget) -> list[str]:
        snapshots = self._snapshots(target)
        return [label for label, key in (("quality_report", "quality_report_hash"), ("continuity_report", "continuity_report_hash"), ("reader_simulation", "quality_report_hash"), ("plan_completion_report", "next_chapter_plan_hash")) if not snapshots.get(key, "")]

    def _current_chapter(self) -> int:
        state = self.store.read_json("data/state.json", default={}, expected_type=dict) or {}
        plan = self.store.read_json("data/next_chapter_plan.json", default={}, expected_type=dict) or {}
        return self._integer(plan.get("chapter_id")) or self._integer(state.get("current_chapter")) or 0

    @staticmethod
    def _integer(value: Any) -> int | None:
        try: return int(value) if value not in (None, "") else None
        except (TypeError, ValueError): return None
