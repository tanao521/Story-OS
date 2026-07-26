from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.contracts.reader_persona import (
    AgreementLevel,
    PanelAgreement,
    PanelConsensusFlag,
    PanelDisagreement,
    PanelMinorityFlag,
    PanelMode,
    PanelSuggestion,
    PanelStaleReason,
    PersonaObservation,
    PersonaOptimizationPriority,
    PersonaPriorityFlag,
    PersonaResult,
    ReaderPanelRequest,
    ReaderPanelResult,
    ReaderPanelRun,
    ResultState,
    RunStatus,
    StalenessResult,
)
from core.project_context import ProjectContext, get_project_context
from system.data_store import DataStore


PANEL_RUN_SCHEMA_VERSION = "1.0"
PANEL_EVALUATOR_VERSION = "panel-rule-v1"


class ReaderPanelStore:
    def __init__(self, context: Optional[ProjectContext] = None) -> None:
        self.context = context or get_project_context()
        self.store = DataStore(self.context)
        self.runs_dir = self.store.path("data/simulator/reader_panels")

    def save_run(self, run: ReaderPanelRun) -> str:
        self.runs_dir.mkdir(parents=True, exist_ok=True)

        data = self._run_to_dict(run)
        file_path = self.runs_dir / f"{run.panel_run_id}.json"

        temp_path = file_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp_path.replace(file_path)

        return file_path.as_posix()

    def load_run(self, panel_run_id: str) -> Optional[ReaderPanelRun]:
        file_path = self.runs_dir / f"{panel_run_id}.json"
        if not file_path.exists():
            return None

        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            return self._dict_to_run(data)
        except (json.JSONDecodeError, OSError):
            return None

    def list_runs(self, chapter_id: Optional[int] = None) -> list[ReaderPanelRun]:
        runs: list[ReaderPanelRun] = []
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

    def check_run_staleness(self, panel_run_id: str) -> StalenessResult:
        run = self.load_run(panel_run_id)
        if not run or not run.result:
            return StalenessResult(ResultState.SOURCE_MISSING)

        stale_reasons: list[PanelStaleReason] = []

        try:
            from system.reader_persona_registry import ReaderPersonaRegistry

            if run.panel_evaluator_version != PANEL_EVALUATOR_VERSION:
                stale_reasons.append(PanelStaleReason.PANEL_EVALUATOR_CHANGED)

            persona_registry = ReaderPersonaRegistry()
            current_fingerprint = persona_registry.calculate_persona_set_fingerprint(list(run.persona_versions.keys()))
            if current_fingerprint != run.persona_set_fingerprint:
                stale_reasons.append(PanelStaleReason.PERSONA_SET_CHANGED)

            current_versions = persona_registry.get_persona_versions(list(run.persona_versions.keys()))
            if current_versions != run.persona_versions:
                stale_reasons.append(PanelStaleReason.PERSONA_CHANGED)

            try:
                from system.reader_simulation_store import ReaderSimulationStore

                sim_store = ReaderSimulationStore(self.context)
                sim_run = sim_store.load_run(run.base_simulation_run_id)

                if sim_run is not None:
                    sim_staleness = sim_store.check_run_staleness(run.base_simulation_run_id)

                    if sim_staleness.state == ResultState.STALE:
                        if PanelStaleReason.SOURCE_CHANGED.value in [r.value for r in sim_staleness.stale_reasons]:
                            stale_reasons.append(PanelStaleReason.SOURCE_CHANGED)
                        if PanelStaleReason.CONTEXT_CHANGED.value in [r.value for r in sim_staleness.stale_reasons]:
                            stale_reasons.append(PanelStaleReason.CONTEXT_CHANGED)
                        if PanelStaleReason.READER_EVALUATOR_CHANGED.value in [r.value for r in sim_staleness.stale_reasons]:
                            stale_reasons.append(PanelStaleReason.READER_EVALUATOR_CHANGED)

            except Exception:
                pass

            if stale_reasons:
                return StalenessResult(ResultState.STALE, stale_reasons)

            return StalenessResult(ResultState.CURRENT)

        except Exception:
            return StalenessResult(ResultState.STALE, [PanelStaleReason.SOURCE_CHANGED])

    def _run_to_dict(self, run: ReaderPanelRun) -> dict[str, Any]:
        return {
            "panel_run_id": run.panel_run_id,
            "panel_run_schema_version": run.panel_run_schema_version,
            "status": run.status.value,
            "request": {
                "project_id": run.request.project_id,
                "timeline_id": run.request.timeline_id,
                "chapter_id": run.request.chapter_id,
                "source_version_id": run.request.source_version_id,
                "persona_ids": run.request.persona_ids,
                "mode": run.request.mode.value,
            },
            "base_simulation_run_id": run.base_simulation_run_id,
            "snapshot_id": run.snapshot_id,
            "source_hash": run.source_hash,
            "context_hash": run.context_hash,
            "reader_evaluator_version": run.reader_evaluator_version,
            "panel_evaluator_version": run.panel_evaluator_version,
            "persona_set_fingerprint": run.persona_set_fingerprint,
            "persona_versions": run.persona_versions,
            "result": self._result_to_dict(run.result) if run.result else None,
            "warnings": run.warnings,
            "error": run.error,
            "created_at": run.created_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }

    def _dict_to_run(self, data: dict[str, Any]) -> ReaderPanelRun:
        request_data = data.get("request", {})
        request = ReaderPanelRequest(
            project_id=request_data.get("project_id", ""),
            timeline_id=request_data.get("timeline_id", ""),
            chapter_id=request_data.get("chapter_id", 0),
            source_version_id=request_data.get("source_version_id"),
            persona_ids=request_data.get("persona_ids", []),
            mode=PanelMode(request_data.get("mode", "deterministic")),
        )

        result_data = data.get("result")
        result = self._dict_to_result(result_data) if result_data else None

        return ReaderPanelRun(
            panel_run_id=data.get("panel_run_id", ""),
            panel_run_schema_version=data.get("panel_run_schema_version", PANEL_RUN_SCHEMA_VERSION),
            status=RunStatus(data.get("status", "completed")),
            request=request,
            base_simulation_run_id=data.get("base_simulation_run_id", ""),
            snapshot_id=data.get("snapshot_id", ""),
            source_hash=data.get("source_hash", ""),
            context_hash=data.get("context_hash", ""),
            reader_evaluator_version=data.get("reader_evaluator_version", ""),
            panel_evaluator_version=data.get("panel_evaluator_version", PANEL_EVALUATOR_VERSION),
            persona_set_fingerprint=data.get("persona_set_fingerprint", ""),
            persona_versions=data.get("persona_versions", {}),
            result=result,
            warnings=data.get("warnings", []),
            error=data.get("error"),
            created_at=datetime.fromisoformat(data.get("created_at", datetime.now().isoformat())),
            completed_at=datetime.fromisoformat(data.get("completed_at", datetime.now().isoformat())) if data.get("completed_at") else None,
        )

    def _result_to_dict(self, result: ReaderPanelResult) -> dict[str, Any]:
        return {
            "panel_score": result.panel_score,
            "panel_retention_risk": result.panel_retention_risk,
            "persona_results": [self._persona_result_to_dict(pr) for pr in result.persona_results],
            "agreement": {
                "score_spread": result.agreement.score_spread,
                "score_stddev": result.agreement.score_stddev,
                "agreement_level": result.agreement.agreement_level.value,
                "shared_flag_codes": result.agreement.shared_flag_codes,
            },
            "disagreements": [
                {
                    "topic": d.topic,
                    "persona_positions": d.persona_positions,
                    "score_range": list(d.score_range),
                    "evidence_refs": d.evidence_refs,
                    "explanation": d.explanation,
                }
                for d in result.disagreements
            ],
            "consensus_flags": [
                {
                    "flag_code": f.flag_code,
                    "severity": f.severity,
                    "supporting_personas": f.supporting_personas,
                    "evidence_refs": f.evidence_refs,
                }
                for f in result.consensus_flags
            ],
            "minority_flags": [
                {
                    "flag_code": f.flag_code,
                    "severity": f.severity,
                    "supporting_personas": f.supporting_personas,
                    "opposing_or_neutral_personas": f.opposing_or_neutral_personas,
                    "evidence_refs": f.evidence_refs,
                }
                for f in result.minority_flags
            ],
            "panel_suggestions": [
                {
                    "target": s.target,
                    "priority": s.priority,
                    "reason": s.reason,
                    "source_personas": s.source_personas,
                    "evidence_refs": s.evidence_refs,
                }
                for s in result.panel_suggestions
            ],
            "panel_evaluator_version": result.panel_evaluator_version,
            "persona_set_fingerprint": result.persona_set_fingerprint,
            "evaluated_at": result.evaluated_at.isoformat(),
        }

    def _dict_to_result(self, data: dict[str, Any]) -> ReaderPanelResult:
        agreement_data = data.get("agreement", {})
        agreement = PanelAgreement(
            score_spread=agreement_data.get("score_spread", 0.0),
            score_stddev=agreement_data.get("score_stddev", 0.0),
            agreement_level=AgreementLevel(agreement_data.get("agreement_level", "moderate")),
            shared_flag_codes=agreement_data.get("shared_flag_codes", []),
        )

        disagreements = []
        for d in data.get("disagreements", []):
            disagreements.append(PanelDisagreement(
                topic=d.get("topic", ""),
                persona_positions=d.get("persona_positions", {}),
                score_range=tuple(d.get("score_range", [0, 0])),
                evidence_refs=d.get("evidence_refs", []),
                explanation=d.get("explanation", ""),
            ))

        consensus_flags = []
        for f in data.get("consensus_flags", []):
            consensus_flags.append(PanelConsensusFlag(
                flag_code=f.get("flag_code", ""),
                severity=f.get("severity", "low"),
                supporting_personas=f.get("supporting_personas", []),
                evidence_refs=f.get("evidence_refs", []),
            ))

        minority_flags = []
        for f in data.get("minority_flags", []):
            minority_flags.append(PanelMinorityFlag(
                flag_code=f.get("flag_code", ""),
                severity=f.get("severity", "low"),
                supporting_personas=f.get("supporting_personas", []),
                opposing_or_neutral_personas=f.get("opposing_or_neutral_personas", []),
                evidence_refs=f.get("evidence_refs", []),
            ))

        panel_suggestions = []
        for s in data.get("panel_suggestions", []):
            panel_suggestions.append(PanelSuggestion(
                target=s.get("target", ""),
                priority=s.get("priority", 0),
                reason=s.get("reason", ""),
                source_personas=s.get("source_personas", []),
                evidence_refs=s.get("evidence_refs", []),
            ))

        persona_results = [self._dict_to_persona_result(pr) for pr in data.get("persona_results", [])]

        return ReaderPanelResult(
            panel_score=data.get("panel_score", 0.0),
            panel_retention_risk=data.get("panel_retention_risk", 0.0),
            persona_results=persona_results,
            agreement=agreement,
            disagreements=disagreements,
            consensus_flags=consensus_flags,
            minority_flags=minority_flags,
            panel_suggestions=panel_suggestions,
            panel_evaluator_version=data.get("panel_evaluator_version", PANEL_EVALUATOR_VERSION),
            persona_set_fingerprint=data.get("persona_set_fingerprint", ""),
            evaluated_at=datetime.fromisoformat(data.get("evaluated_at", datetime.now().isoformat())),
        )

    def _persona_result_to_dict(self, result: PersonaResult) -> dict[str, Any]:
        return {
            "persona_id": result.persona_id,
            "persona_version": result.persona_version,
            "persona_fingerprint": result.persona_fingerprint,
            "engagement_score": result.engagement_score,
            "retention_risk": result.retention_risk,
            "priority_flags": [
                {
                    "flag_code": f.flag_code,
                    "base_severity": f.base_severity,
                    "persona_severity": f.persona_severity,
                    "priority": f.priority,
                    "reason": f.reason,
                    "evidence_refs": f.evidence_refs,
                }
                for f in result.priority_flags
            ],
            "persona_observations": [
                {"category": o.category, "message": o.message, "evidence_refs": o.evidence_refs}
                for o in result.persona_observations
            ],
            "optimization_priorities": [
                {"target": o.target, "priority": o.priority, "reason": o.reason, "evidence_refs": o.evidence_refs}
                for o in result.optimization_priorities
            ],
            "evidence_refs": result.evidence_refs,
        }

    def _dict_to_persona_result(self, data: dict[str, Any]) -> PersonaResult:
        priority_flags = []
        for f in data.get("priority_flags", []):
            priority_flags.append(PersonaPriorityFlag(
                flag_code=f.get("flag_code", ""),
                base_severity=f.get("base_severity", "low"),
                persona_severity=f.get("persona_severity", "low"),
                priority=f.get("priority", 0),
                reason=f.get("reason", ""),
                evidence_refs=f.get("evidence_refs", []),
            ))

        observations = []
        for o in data.get("persona_observations", []):
            observations.append(PersonaObservation(
                category=o.get("category", ""),
                message=o.get("message", ""),
                evidence_refs=o.get("evidence_refs", []),
            ))

        optimization_priorities = []
        for o in data.get("optimization_priorities", []):
            optimization_priorities.append(PersonaOptimizationPriority(
                target=o.get("target", ""),
                priority=o.get("priority", 0),
                reason=o.get("reason", ""),
                evidence_refs=o.get("evidence_refs", []),
            ))

        return PersonaResult(
            persona_id=data.get("persona_id", ""),
            persona_version=data.get("persona_version", ""),
            persona_fingerprint=data.get("persona_fingerprint", ""),
            engagement_score=data.get("engagement_score", 0.0),
            retention_risk=data.get("retention_risk", 0.0),
            priority_flags=priority_flags,
            persona_observations=observations,
            optimization_priorities=optimization_priorities,
            evidence_refs=data.get("evidence_refs", []),
        )