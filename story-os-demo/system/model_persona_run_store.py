"""Atomic persistence for Model Persona Execution runs.

Stores run records under data/simulator/model_persona_runs/.
Never saves full prompts, API keys, absolute paths, or raw provider responses.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.contracts.model_persona_execution import (
    MODEL_PERSONA_RUN_SCHEMA_VERSION,
    AuthoritativeScores,
    ConfidenceLevel,
    FeedbackItem,
    GenerationParameters,
    GroundingReport,
    ModelPersonaExecutionResult,
    ModelPersonaFeedback,
    ModelRunState,
    ModelRunStatus,
    ModelStaleReason,
    ModelStalenessResult,
    TokenUsage,
)
from core.project_context import ProjectContext, get_project_context
from system.data_store import DataStore


class ModelPersonaRunStoreError(Exception):
    pass


class ModelPersonaRunStore:
    def __init__(self, context: Optional[ProjectContext] = None) -> None:
        self.context = context or get_project_context()
        self.store = DataStore(self.context)
        self.runs_dir = self.store.path("data/simulator/model_persona_runs")

    def save_run(self, run: ModelPersonaExecutionResult) -> str:
        self.runs_dir.mkdir(parents=True, exist_ok=True)

        data = self._run_to_dict(run)
        file_path = self.runs_dir / f"{run.execution_id}.json"

        temp_path = file_path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(file_path)

        return run.execution_id

    def load_run(self, execution_id: str) -> Optional[ModelPersonaExecutionResult]:
        file_path = self.runs_dir / f"{execution_id}.json"
        if not file_path.exists():
            return None

        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            return self._dict_to_run(data)
        except (json.JSONDecodeError, OSError, KeyError, ValueError):
            return None

    def list_runs(
        self,
        chapter_id: Optional[int] = None,
        persona_id: Optional[str] = None,
    ) -> list[ModelPersonaExecutionResult]:
        runs: list[ModelPersonaExecutionResult] = []
        if not self.runs_dir.exists():
            return runs

        for path in sorted(
            self.runs_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                run = self._dict_to_run(data)
                if chapter_id is not None and run.chapter_id != chapter_id:
                    continue
                if persona_id is not None and run.persona_id != persona_id:
                    continue
                runs.append(run)
            except (json.JSONDecodeError, OSError, KeyError, ValueError):
                continue

        return runs

    def find_by_fingerprint(self, fingerprint: str) -> Optional[ModelPersonaExecutionResult]:
        for run in self.list_runs():
            if run.input_fingerprint == fingerprint and run.status == ModelRunStatus.COMPLETED:
                return run
        return None

    def check_staleness(
        self,
        execution_id: str,
        current_source_hash: str = "",
        current_context_hash: str = "",
        current_reader_evaluator_version: str = "",
        current_persona_fingerprint: str = "",
        current_prompt_template_version: str = "",
        current_provider_id: str = "",
        current_model_id: str = "",
        current_generation_parameters: Optional[GenerationParameters] = None,
        current_provider_config_fingerprint: str = "",
    ) -> ModelStalenessResult:
        run = self.load_run(execution_id)
        if run is None:
            return ModelStalenessResult(ModelRunState.SOURCE_MISSING)

        stale_reasons: list[ModelStaleReason] = []

        if current_source_hash and run.source_hash != current_source_hash:
            stale_reasons.append(ModelStaleReason.SOURCE_CHANGED)
        if current_context_hash and run.context_hash != current_context_hash:
            stale_reasons.append(ModelStaleReason.CONTEXT_CHANGED)
        if current_reader_evaluator_version and run.reader_evaluator_version != current_reader_evaluator_version:
            stale_reasons.append(ModelStaleReason.READER_EVALUATOR_CHANGED)
        if current_persona_fingerprint and run.persona_fingerprint != current_persona_fingerprint:
            stale_reasons.append(ModelStaleReason.PERSONA_CHANGED)
        if current_prompt_template_version and run.prompt_template_version != current_prompt_template_version:
            stale_reasons.append(ModelStaleReason.PROMPT_TEMPLATE_CHANGED)
        if current_provider_config_fingerprint:
            run_fingerprint = getattr(run, "provider_config_fingerprint", "")
            if run_fingerprint and run_fingerprint != current_provider_config_fingerprint:
                stale_reasons.append(ModelStaleReason.PROVIDER_CONFIG_CHANGED)
        else:
            if current_provider_id and run.provider_id != current_provider_id:
                stale_reasons.append(ModelStaleReason.PROVIDER_CHANGED)
            if current_model_id and run.model_id != current_model_id:
                stale_reasons.append(ModelStaleReason.MODEL_CHANGED)
            if current_generation_parameters and run.generation_parameters.to_dict() != current_generation_parameters.to_dict():
                stale_reasons.append(ModelStaleReason.GENERATION_PARAMETERS_CHANGED)

        if stale_reasons:
            return ModelStalenessResult(ModelRunState.STALE, stale_reasons)
        return ModelStalenessResult(ModelRunState.CURRENT)

    def _run_to_dict(self, run: ModelPersonaExecutionResult) -> dict[str, Any]:
        data: dict[str, Any] = {
            "execution_id": run.execution_id,
            "run_schema_version": run.run_schema_version,
            "status": run.status.value,
            "chapter_id": getattr(run, "chapter_id", 0),
            "persona_id": run.persona_id,
            "persona_version": run.persona_version,
            "persona_fingerprint": run.persona_fingerprint,
            "base_simulation_run_id": run.base_simulation_run_id,
            "source_hash": run.source_hash,
            "context_hash": run.context_hash,
            "reader_evaluator_version": run.reader_evaluator_version,
            "prompt_template_version": run.prompt_template_version,
            "provider_id": run.provider_id,
            "model_id": run.model_id,
            "generation_parameters": run.generation_parameters.to_dict(),
            "input_fingerprint": run.input_fingerprint,
            "authoritative_scores": run.authoritative_scores.to_dict(),
            "model_feedback": self._feedback_to_dict(run.model_feedback) if run.model_feedback else None,
            "grounding_report": self._grounding_to_dict(run.grounding_report) if run.grounding_report else None,
            "usage": run.usage.to_dict() if run.usage else None,
            "cache_status": run.cache_status,
            "warnings": run.warnings,
            "error": run.error,
            "created_at": run.created_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }
        if hasattr(run, "execution_mode") and run.execution_mode is not None:
            data["execution_mode"] = run.execution_mode.value
        if hasattr(run, "execution_profile"):
            data["execution_profile"] = run.execution_profile
        if hasattr(run, "execution_profile_version"):
            data["execution_profile_version"] = run.execution_profile_version
        if hasattr(run, "provider_config_fingerprint"):
            data["provider_config_fingerprint"] = run.provider_config_fingerprint
        if hasattr(run, "provider_request_id"):
            data["provider_request_id"] = run.provider_request_id
        if hasattr(run, "error_code"):
            data["error_code"] = run.error_code
        return data

    def _dict_to_run(self, data: dict[str, Any]) -> ModelPersonaExecutionResult:
        gen_params_data = data.get("generation_parameters", {})
        gen_params = GenerationParameters(
            temperature=float(gen_params_data.get("temperature", 0.0)),
            max_output_tokens=int(gen_params_data.get("max_output_tokens", 1024)),
            timeout_seconds=int(gen_params_data.get("timeout_seconds", 60)),
        )

        auth_scores_data = data.get("authoritative_scores", {})
        auth_scores = AuthoritativeScores(
            engagement_score=float(auth_scores_data.get("engagement_score", 0.0)),
            retention_risk=float(auth_scores_data.get("retention_risk", 0.0)),
        )

        feedback = self._dict_to_feedback(data.get("model_feedback"))
        grounding = self._dict_to_grounding(data.get("grounding_report"))
        usage_data = data.get("usage")
        usage = None
        if usage_data and isinstance(usage_data, dict):
            usage = TokenUsage(
                input_tokens=usage_data.get("input_tokens"),
                output_tokens=usage_data.get("output_tokens"),
                total_tokens=usage_data.get("total_tokens"),
            )

        from core.contracts.model_persona_execution import ExecutionMode

        execution_mode_str = data.get("execution_mode")
        execution_mode = None
        if execution_mode_str:
            try:
                execution_mode = ExecutionMode(execution_mode_str)
            except ValueError:
                execution_mode = None

        result = ModelPersonaExecutionResult(
            execution_id=data.get("execution_id", ""),
            run_schema_version=data.get("run_schema_version", MODEL_PERSONA_RUN_SCHEMA_VERSION),
            status=ModelRunStatus(data.get("status", "completed")),
            persona_id=data.get("persona_id", ""),
            persona_version=data.get("persona_version", ""),
            persona_fingerprint=data.get("persona_fingerprint", ""),
            base_simulation_run_id=data.get("base_simulation_run_id", ""),
            source_hash=data.get("source_hash", ""),
            context_hash=data.get("context_hash", ""),
            reader_evaluator_version=data.get("reader_evaluator_version", ""),
            prompt_template_version=data.get("prompt_template_version", ""),
            provider_id=data.get("provider_id", ""),
            model_id=data.get("model_id", ""),
            generation_parameters=gen_params,
            input_fingerprint=data.get("input_fingerprint", ""),
            authoritative_scores=auth_scores,
            execution_mode=execution_mode,
            execution_profile=data.get("execution_profile", ""),
            execution_profile_version=data.get("execution_profile_version", ""),
            provider_config_fingerprint=data.get("provider_config_fingerprint", ""),
            provider_request_id=data.get("provider_request_id"),
            error_code=data.get("error_code"),
            model_feedback=feedback,
            grounding_report=grounding,
            usage=usage,
            cache_status=data.get("cache_status", "miss"),
            warnings=data.get("warnings", []),
            error=data.get("error"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
        )
        object.__setattr__(result, "chapter_id", data.get("chapter_id", 0))
        return result

    def _feedback_to_dict(self, feedback: ModelPersonaFeedback) -> dict[str, Any]:
        return {
            "reader_reaction": feedback.reader_reaction,
            "strengths": [self._item_to_dict(i) for i in feedback.strengths],
            "concerns": [self._item_to_dict(i) for i in feedback.concerns],
            "reader_questions": [self._item_to_dict(i) for i in feedback.reader_questions],
            "optimization_directions": [self._item_to_dict(i) for i in feedback.optimization_directions],
            "overall_impression": feedback.overall_impression,
        }

    def _dict_to_feedback(self, data: Optional[dict[str, Any]]) -> Optional[ModelPersonaFeedback]:
        if not data:
            return None
        return ModelPersonaFeedback(
            reader_reaction=str(data.get("reader_reaction", "")),
            strengths=[self._dict_to_item(i) for i in data.get("strengths", [])],
            concerns=[self._dict_to_item(i) for i in data.get("concerns", [])],
            reader_questions=[self._dict_to_item(i) for i in data.get("reader_questions", [])],
            optimization_directions=[self._dict_to_item(i) for i in data.get("optimization_directions", [])],
            overall_impression=str(data.get("overall_impression", "")),
        )

    def _item_to_dict(self, item: FeedbackItem) -> dict[str, Any]:
        return {
            "message": item.message,
            "evidence_refs": item.evidence_refs,
            "confidence": item.confidence.value,
        }

    def _dict_to_item(self, data: dict[str, Any]) -> FeedbackItem:
        confidence_str = str(data.get("confidence", "medium"))
        try:
            confidence = ConfidenceLevel(confidence_str)
        except ValueError:
            confidence = ConfidenceLevel.MEDIUM
        return FeedbackItem(
            message=str(data.get("message", "")),
            evidence_refs=list(data.get("evidence_refs", [])),
            confidence=confidence,
        )

    def _grounding_to_dict(self, report: GroundingReport) -> dict[str, Any]:
        return {
            "valid_reference_count": report.valid_reference_count,
            "invalid_reference_count": report.invalid_reference_count,
            "unsupported_item_count": report.unsupported_item_count,
            "grounding_coverage": report.grounding_coverage,
            "invalid_refs": report.invalid_refs,
        }

    def _dict_to_grounding(self, data: Optional[dict[str, Any]]) -> Optional[GroundingReport]:
        if not data:
            return None
        return GroundingReport(
            valid_reference_count=int(data.get("valid_reference_count", 0)),
            invalid_reference_count=int(data.get("invalid_reference_count", 0)),
            unsupported_item_count=int(data.get("unsupported_item_count", 0)),
            grounding_coverage=float(data.get("grounding_coverage", 0.0)),
            invalid_refs=list(data.get("invalid_refs", [])),
        )
