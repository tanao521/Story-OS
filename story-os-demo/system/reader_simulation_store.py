from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.contracts.reader_simulation import (
    ReaderSimulationRun,
    ResultState,
    RunStatus,
    StaleReason,
)
from core.project_context import ProjectContext, get_project_context
from system.data_store import DataStore


RUN_SCHEMA_VERSION = "1.1"


class StalenessResult:
    def __init__(
        self,
        state: ResultState,
        stale_reasons: list[StaleReason] | None = None,
    ) -> None:
        self.state = state
        self.stale_reasons = stale_reasons or []


class ReaderSimulationStore:
    def __init__(self, context: Optional[ProjectContext] = None) -> None:
        self.context = context or get_project_context()
        self.store = DataStore(self.context)
        self.runs_dir = self.store.path("data/simulator/reader_runs")

    def save_run(self, run: ReaderSimulationRun) -> str:
        self.runs_dir.mkdir(parents=True, exist_ok=True)

        data = self._run_to_dict(run)
        file_path = self.runs_dir / f"{run.run_id}.json"

        temp_path = file_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp_path.replace(file_path)

        return file_path.as_posix()

    def load_run(self, run_id: str) -> Optional[ReaderSimulationRun]:
        file_path = self.runs_dir / f"{run_id}.json"
        if not file_path.exists():
            return None

        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            return self._dict_to_run(data)
        except (json.JSONDecodeError, OSError):
            return None

    def list_runs(self, chapter_id: Optional[int] = None) -> list[ReaderSimulationRun]:
        runs: list[ReaderSimulationRun] = []
        if not self.runs_dir.exists():
            return runs

        for path in sorted(self.runs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                run = self._dict_to_run(data)
                if chapter_id is None or run.request.chapter_id == chapter_id:
                    runs.append(run)
            except (json.JSONDecodeError, OSError):
                continue

        return runs

    def check_run_state(self, run_id: str) -> ResultState:
        return self.check_run_staleness(run_id).state

    def check_run_staleness(self, run_id: str) -> StalenessResult:
        run = self.load_run(run_id)
        if not run or not run.result:
            return StalenessResult(ResultState.SOURCE_MISSING)

        source_version_id = run.snapshot.source.source_version_id
        chapter_id = run.snapshot.chapter_id

        try:
            from system.version_manager import list_versions, read_version_payload

            versions = list_versions(chapter_id, self.context.data_dir)
            parts = source_version_id.split("_v")
            if len(parts) != 2:
                return StalenessResult(ResultState.SOURCE_MISSING)

            source_type, version_str = parts
            version = int(version_str)

            found = None
            for key in ("drafts", "edited", "manual"):
                for item in versions.get(key, []):
                    if item.get("source_type") == source_type and item.get("version") == version:
                        found = item
                        break
                if found:
                    break

            if found is None:
                return StalenessResult(ResultState.SOURCE_MISSING)

            payload = read_version_payload(found)
            text = payload.get("manual_text") or payload.get("edited_text") or payload.get("draft_text") or ""
            current_source_hash = self._hash_text(text)

            stale_reasons: list[StaleReason] = []

            if current_source_hash != run.snapshot.source.source_hash:
                stale_reasons.append(StaleReason.SOURCE_CHANGED)

            current_context_hash = self._recompute_context_hash(run, found, text)
            if current_context_hash != run.snapshot.context_hash:
                stale_reasons.append(StaleReason.CONTEXT_CHANGED)

            if run.result.evaluator_version != self._current_evaluator_version():
                stale_reasons.append(StaleReason.EVALUATOR_CHANGED)

            if stale_reasons:
                return StalenessResult(ResultState.STALE, stale_reasons)

            return StalenessResult(ResultState.CURRENT)

        except Exception:
            return StalenessResult(ResultState.SOURCE_MISSING)

    def _recompute_context_hash(
        self, run: ReaderSimulationRun, version_info: dict[str, Any], text: str
    ) -> str:
        try:
            from system.reader_simulator import ReaderSimulatorService

            simulator = ReaderSimulatorService(self.context)
            content_hash = self._hash_text(text)

            missing_inputs: list[str] = []
            story_spec = simulator._load_story_spec(missing_inputs)
            chapter_plan = simulator._load_chapter_plan(run.snapshot.chapter_id, missing_inputs)
            chapter_summary = simulator._load_chapter_summary(run.snapshot.chapter_id, missing_inputs)
            pacing_data = simulator._load_pacing_data(run.snapshot.chapter_id, missing_inputs)
            climax_data = simulator._load_climax_data(run.snapshot.chapter_id, missing_inputs)
            conflict_data = simulator._load_conflict_data(run.snapshot.chapter_id, missing_inputs)
            continuity_state = simulator._load_continuity_state(run.snapshot.chapter_id, missing_inputs)
            context_refs = simulator._build_context_refs(run.snapshot.chapter_id)

            return simulator._compute_context_hash(
                request=run.request,
                source_hash=content_hash,
                source_type=version_info.get("source_type", ""),
                title=version_info.get("chapter_title", ""),
                story_spec=story_spec,
                chapter_plan=chapter_plan,
                chapter_summary=chapter_summary,
                pacing_data=pacing_data,
                climax_data=climax_data,
                conflict_data=conflict_data,
                continuity_state=continuity_state,
                context_refs=context_refs,
                missing_inputs=missing_inputs,
            )
        except Exception:
            return run.snapshot.context_hash

    def _current_evaluator_version(self) -> str:
        try:
            from system.reader_simulator import EVALUATOR_VERSION
            return EVALUATOR_VERSION
        except Exception:
            return "reader-rule-v1"

    def _run_to_dict(self, run: ReaderSimulationRun) -> dict[str, Any]:
        return {
            "run_id": run.run_id,
            "run_schema_version": run.run_schema_version,
            "status": run.status.value,
            "request": {
                "project_id": run.request.project_id,
                "timeline_id": run.request.timeline_id,
                "chapter_id": run.request.chapter_id,
                "source_version_id": run.request.source_version_id,
                "source_type": run.request.source_type,
                "mode": run.request.mode.value,
            },
            "snapshot": {
                "snapshot_id": run.snapshot.snapshot_id,
                "snapshot_schema_version": run.snapshot.snapshot_schema_version,
                "project_id": run.snapshot.project_id,
                "timeline_id": run.snapshot.timeline_id,
                "chapter_id": run.snapshot.chapter_id,
                "source": {
                    "chapter_id": run.snapshot.source.chapter_id,
                    "source_version_id": run.snapshot.source.source_version_id,
                    "source_type": run.snapshot.source.source_type,
                    "source_path": run.snapshot.source.source_path,
                    "source_hash": run.snapshot.source.source_hash,
                    "title": run.snapshot.source.title,
                    "character_count": run.snapshot.source.character_count,
                    "resolved_at": run.snapshot.source.resolved_at.isoformat(),
                },
                "story_spec": run.snapshot.story_spec,
                "chapter_plan": run.snapshot.chapter_plan,
                "chapter_summary": run.snapshot.chapter_summary,
                "pacing_data": run.snapshot.pacing_data,
                "climax_data": run.snapshot.climax_data,
                "conflict_data": run.snapshot.conflict_data,
                "continuity_state": run.snapshot.continuity_state,
                "quality_evidence": run.snapshot.quality_evidence,
                "context_refs": run.snapshot.context_refs,
                "context_hash": run.snapshot.context_hash,
                "missing_inputs": run.snapshot.missing_inputs,
                "created_at": run.snapshot.created_at.isoformat(),
            },
            "result": self._result_to_dict(run.result) if run.result else None,
            "warnings": run.warnings,
            "error": run.error,
            "created_at": run.created_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }

    def _dict_to_run(self, data: dict[str, Any]) -> ReaderSimulationRun:
        from core.contracts.reader_simulation import (
            EmotionCurveNode,
            EngagementScore,
            FlagCategory,
            FlagSeverity,
            OptimizationSuggestion,
            ProblemFlag,
            ReaderSimulationResult,
            ReaderSimulationSnapshot,
            ReaderSimulationSource,
            ReaderSimulationRequest,
            RetentionLevel,
            RetentionRisk,
            SimulationMode,
            NovelHealth,
        )

        request_data = data.get("request", {})
        request = ReaderSimulationRequest(
            project_id=request_data.get("project_id", ""),
            timeline_id=request_data.get("timeline_id", ""),
            chapter_id=request_data.get("chapter_id", 0),
            source_version_id=request_data.get("source_version_id"),
            source_type=request_data.get("source_type"),
            mode=SimulationMode(request_data.get("mode", "rule")),
        )

        snapshot_data = data.get("snapshot", {})
        source_data = snapshot_data.get("source", {})
        source = ReaderSimulationSource(
            chapter_id=source_data.get("chapter_id", 0),
            source_version_id=source_data.get("source_version_id", ""),
            source_type=source_data.get("source_type", ""),
            source_path=source_data.get("source_path", ""),
            source_hash=source_data.get("source_hash", ""),
            title=source_data.get("title", ""),
            character_count=source_data.get("character_count", 0),
            resolved_at=datetime.fromisoformat(source_data.get("resolved_at", datetime.now().isoformat())),
        )

        snapshot = ReaderSimulationSnapshot(
            snapshot_id=snapshot_data.get("snapshot_id", ""),
            snapshot_schema_version=snapshot_data.get("snapshot_schema_version", "1.0"),
            project_id=snapshot_data.get("project_id", ""),
            timeline_id=snapshot_data.get("timeline_id", ""),
            chapter_id=snapshot_data.get("chapter_id", 0),
            source=source,
            story_spec=snapshot_data.get("story_spec", {}),
            chapter_plan=snapshot_data.get("chapter_plan", {}),
            chapter_summary=snapshot_data.get("chapter_summary", {}),
            pacing_data=snapshot_data.get("pacing_data", {}),
            climax_data=snapshot_data.get("climax_data", {}),
            conflict_data=snapshot_data.get("conflict_data", {}),
            continuity_state=snapshot_data.get("continuity_state", {}),
            quality_evidence=snapshot_data.get("quality_evidence", {}),
            context_refs=snapshot_data.get("context_refs", {}),
            context_hash=snapshot_data.get("context_hash", ""),
            missing_inputs=snapshot_data.get("missing_inputs", []),
            created_at=datetime.fromisoformat(snapshot_data.get("created_at", datetime.now().isoformat())),
        )

        result_data = data.get("result")
        result = self._dict_to_result(result_data) if result_data else None

        return ReaderSimulationRun(
            run_id=data.get("run_id", ""),
            run_schema_version=data.get("run_schema_version", RUN_SCHEMA_VERSION),
            status=RunStatus(data.get("status", "completed")),
            request=request,
            snapshot=snapshot,
            result=result,
            warnings=data.get("warnings", []),
            error=data.get("error"),
            created_at=datetime.fromisoformat(data.get("created_at", datetime.now().isoformat())),
            completed_at=datetime.fromisoformat(data.get("completed_at")) if data.get("completed_at") else None,
        )

    def _result_to_dict(self, result: ReaderSimulationResult) -> dict[str, Any]:
        return {
            "engagement_score": {
                "score": result.engagement_score.score,
                "level": result.engagement_score.level,
                "reasons": result.engagement_score.reasons,
                "evidence": result.engagement_score.evidence,
            },
            "retention_risk": {
                "score": result.retention_risk.score,
                "level": result.retention_risk.level.value,
                "risk_points": result.retention_risk.risk_points,
            },
            "reader_emotion_curve": [
                {
                    "position": node.position,
                    "segment_label": node.segment_label,
                    "tension": node.tension,
                    "curiosity": node.curiosity,
                    "emotional_intensity": node.emotional_intensity,
                    "payoff": node.payoff,
                    "evidence": node.evidence,
                }
                for node in result.reader_emotion_curve
            ],
            "problem_flags": [
                {
                    "code": flag.code,
                    "severity": flag.severity.value,
                    "category": flag.category.value,
                    "message": flag.message,
                    "evidence": flag.evidence,
                    "source_span": flag.source_span,
                }
                for flag in result.problem_flags
            ],
            "optimization_suggestions": [
                {
                    "priority": suggestion.priority,
                    "target": suggestion.target,
                    "reason": suggestion.reason,
                    "expected_effect": suggestion.expected_effect,
                    "related_flag_codes": suggestion.related_flag_codes,
                }
                for suggestion in result.optimization_suggestions
            ],
            "novel_health": {
                "overall_score": result.novel_health.overall_score,
                "pacing": result.novel_health.pacing,
                "clarity": result.novel_health.clarity,
                "continuity": result.novel_health.continuity,
                "conflict": result.novel_health.conflict,
                "payoff": result.novel_health.payoff,
                "style_stability": result.novel_health.style_stability,
                "warnings": result.novel_health.warnings,
            },
            "evaluator_version": result.evaluator_version,
            "evaluated_at": result.evaluated_at.isoformat(),
        }

    def _dict_to_result(self, data: dict[str, Any]) -> ReaderSimulationResult:
        from core.contracts.reader_simulation import (
            EmotionCurveNode,
            EngagementScore,
            FlagCategory,
            FlagSeverity,
            OptimizationSuggestion,
            ProblemFlag,
            ReaderSimulationResult,
            RetentionLevel,
            RetentionRisk,
            NovelHealth,
        )

        engagement_data = data.get("engagement_score", {})
        engagement = EngagementScore(
            score=engagement_data.get("score", 0.0),
            level=engagement_data.get("level", ""),
            reasons=engagement_data.get("reasons", []),
            evidence=engagement_data.get("evidence", []),
        )

        retention_data = data.get("retention_risk", {})
        retention = RetentionRisk(
            score=retention_data.get("score", 0.0),
            level=RetentionLevel(retention_data.get("level", "low")),
            risk_points=retention_data.get("risk_points", []),
        )

        emotion_nodes = []
        for node_data in data.get("reader_emotion_curve", []):
            emotion_nodes.append(
                EmotionCurveNode(
                    position=node_data.get("position", 0.0),
                    segment_label=node_data.get("segment_label", ""),
                    tension=node_data.get("tension", 0.0),
                    curiosity=node_data.get("curiosity", 0.0),
                    emotional_intensity=node_data.get("emotional_intensity", 0.0),
                    payoff=node_data.get("payoff", 0.0),
                    evidence=node_data.get("evidence", []),
                )
            )

        problem_flags = []
        for flag_data in data.get("problem_flags", []):
            problem_flags.append(
                ProblemFlag(
                    code=flag_data.get("code", ""),
                    severity=FlagSeverity(flag_data.get("severity", "low")),
                    category=FlagCategory(flag_data.get("category", "content")),
                    message=flag_data.get("message", ""),
                    evidence=flag_data.get("evidence", []),
                    source_span=flag_data.get("source_span"),
                )
            )

        suggestions = []
        for suggestion_data in data.get("optimization_suggestions", []):
            suggestions.append(
                OptimizationSuggestion(
                    priority=suggestion_data.get("priority", 0),
                    target=suggestion_data.get("target", ""),
                    reason=suggestion_data.get("reason", ""),
                    expected_effect=suggestion_data.get("expected_effect", ""),
                    related_flag_codes=suggestion_data.get("related_flag_codes", []),
                )
            )

        health_data = data.get("novel_health", {})
        health = NovelHealth(
            overall_score=health_data.get("overall_score", 0.0),
            pacing=health_data.get("pacing", 0.0),
            clarity=health_data.get("clarity", 0.0),
            continuity=health_data.get("continuity", 0.0),
            conflict=health_data.get("conflict", 0.0),
            payoff=health_data.get("payoff", 0.0),
            style_stability=health_data.get("style_stability", 0.0),
            warnings=health_data.get("warnings", []),
        )

        return ReaderSimulationResult(
            engagement_score=engagement,
            retention_risk=retention,
            reader_emotion_curve=emotion_nodes,
            problem_flags=problem_flags,
            optimization_suggestions=suggestions,
            novel_health=health,
            evaluator_version=data.get("evaluator_version", "reader-rule-v1"),
            evaluated_at=datetime.fromisoformat(data.get("evaluated_at", datetime.now().isoformat())),
        )

    def _hash_text(self, text: str) -> str:
        import hashlib

        return hashlib.sha256(str(text).encode()).hexdigest()