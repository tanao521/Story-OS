"""Contracts for model-backed single Reader Persona execution.

Model output only supplements deterministic Persona results with natural-language
reader feedback. It must never override authoritative scores, priority flags,
or Panel aggregation.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


PROMPT_TEMPLATE_VERSION = "model-persona-v1"
MODEL_PERSONA_RUN_SCHEMA_VERSION = "1.1"


class ExecutionMode(str, Enum):
    MOCK = "mock"
    LIVE = "live"


class ModelRunStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    INVALID_OUTPUT = "invalid_output"
    BLOCKED = "blocked"


MODEL_ERROR_CODES: list[str] = [
    "MODEL_CALL_BLOCKED",
    "PROVIDER_NOT_CONFIGURED",
    "PROVIDER_AUTH_ERROR",
    "PROVIDER_RATE_LIMITED",
    "PROVIDER_TIMEOUT",
    "PROVIDER_ERROR",
    "MODEL_OUTPUT_INVALID",
    "MODEL_EVIDENCE_INVALID",
    "RUN_NOT_FOUND",
    "UNKNOWN_PERSONA",
    "DISABLED_PERSONA",
    "INVALID_MODE",
    "INVALID_PROFILE",
    "PROJECT_MISMATCH",
    "TIMELINE_MISMATCH",
    "INPUT_TOKEN_BUDGET_UNAVAILABLE",
    "INPUT_TOKEN_BUDGET_EXCEEDED",
    "MODEL_TOKENIZER_UNSUPPORTED",
    "SOURCE_CHANGED_AFTER_CONSENT",
    "CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE",
    "CONSERVATIVE_TOKEN_BUDGET_EXCEEDED",
    "CONSERVATIVE_POLICY_REVISION_CHANGED",
    "CONSERVATIVE_COUNTER_ASSET_UNAVAILABLE",
    "CONSERVATIVE_COUNTER_ASSET_MISMATCH",
]


class ModelRunState(str, Enum):
    CURRENT = "current"
    STALE = "stale"
    SOURCE_MISSING = "source_missing"


class ModelStaleReason(str, Enum):
    SOURCE_CHANGED = "source_changed"
    CONTEXT_CHANGED = "context_changed"
    READER_EVALUATOR_CHANGED = "reader_evaluator_changed"
    PERSONA_CHANGED = "persona_changed"
    PROMPT_TEMPLATE_CHANGED = "prompt_template_changed"
    PROVIDER_CHANGED = "provider_changed"
    MODEL_CHANGED = "model_changed"
    GENERATION_PARAMETERS_CHANGED = "generation_parameters_changed"
    PROVIDER_CONFIG_CHANGED = "provider_config_changed"


class StructuredOutputMode(str, Enum):
    NONE = "none"
    JSON = "json"


class ConfidenceLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class GenerationParameters:
    temperature: float = 0.0
    max_output_tokens: int = 1024
    timeout_seconds: int = 60

    def to_dict(self) -> dict[str, Any]:
        return {
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "timeout_seconds": self.timeout_seconds,
        }

    def fingerprint_payload(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class ExecutionProfile:
    profile_id: str
    profile_version: str = "1.0"
    provider_type: str = "mock"
    provider_id: str = "mock"
    model_id: str = "mock-model"
    generation_parameters: GenerationParameters = field(default_factory=GenerationParameters)
    timeout_seconds: int = 60
    structured_output_mode: StructuredOutputMode = StructuredOutputMode.NONE
    enabled: bool = True
    endpoint_identity: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "provider_type": self.provider_type,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "generation_parameters": self.generation_parameters.to_dict(),
            "timeout_seconds": self.timeout_seconds,
            "structured_output_mode": self.structured_output_mode.value,
            "enabled": self.enabled,
            "endpoint_identity": self.endpoint_identity,
        }


@dataclass(frozen=True)
class ModelPersonaExecutionRequest:
    project_id: str
    timeline_id: str
    chapter_id: int
    persona_id: str
    source_version_id: Optional[str] = None
    execution_mode: ExecutionMode = ExecutionMode.MOCK
    execution_profile: str = "default"
    allow_model_call: bool = False
    force: bool = False
    expected_source_hash: Optional[str] = None
    expected_context_hash: Optional[str] = None
    max_input_tokens_per_call: Optional[int] = None


@dataclass(frozen=True)
class FeedbackItem:
    message: str
    evidence_refs: list[str] = field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM


@dataclass(frozen=True)
class ModelPersonaFeedback:
    reader_reaction: str
    strengths: list[FeedbackItem] = field(default_factory=list)
    concerns: list[FeedbackItem] = field(default_factory=list)
    reader_questions: list[FeedbackItem] = field(default_factory=list)
    optimization_directions: list[FeedbackItem] = field(default_factory=list)
    overall_impression: str = ""


@dataclass(frozen=True)
class AuthoritativeScores:
    engagement_score: float
    retention_risk: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "engagement_score": self.engagement_score,
            "retention_risk": self.retention_risk,
        }


@dataclass(frozen=True)
class GroundingReport:
    valid_reference_count: int
    invalid_reference_count: int
    unsupported_item_count: int
    grounding_coverage: float
    invalid_refs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True)
class ModelPersonaExecutionResult:
    execution_id: str
    run_schema_version: str
    status: ModelRunStatus
    persona_id: str
    persona_version: str
    persona_fingerprint: str
    base_simulation_run_id: str
    source_hash: str
    context_hash: str
    reader_evaluator_version: str
    prompt_template_version: str
    provider_id: str
    model_id: str
    generation_parameters: GenerationParameters
    input_fingerprint: str
    authoritative_scores: AuthoritativeScores
    execution_mode: ExecutionMode = ExecutionMode.MOCK
    execution_profile: str = "default"
    execution_profile_version: str = "1.0"
    provider_config_fingerprint: str = ""
    provider_request_id: Optional[str] = None
    error_code: Optional[str] = None
    model_feedback: Optional[ModelPersonaFeedback] = None
    grounding_report: Optional[GroundingReport] = None
    usage: Optional[TokenUsage] = None
    cache_status: str = "miss"
    warnings: list[str] = field(default_factory=list)
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None


def compute_provider_config_fingerprint(
    provider_type: str,
    profile_id: str,
    profile_version: str,
    provider_id: str,
    model_id: str,
    protocol_version: str,
    structured_output_mode: str,
    normalized_endpoint_identity: str,
    generation_parameters: GenerationParameters,
    timeout_policy_version: str = "1.0",
) -> str:
    payload = json.dumps(
        {
            "provider_type": provider_type,
            "profile_id": profile_id,
            "profile_version": profile_version,
            "provider_id": provider_id,
            "model_id": model_id,
            "protocol_version": protocol_version,
            "structured_output_mode": structured_output_mode,
            "normalized_endpoint_identity": normalized_endpoint_identity,
            "generation_parameters": generation_parameters.to_dict(),
            "timeout_policy_version": timeout_policy_version,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_input_fingerprint(
    source_hash: str,
    context_hash: str,
    reader_evaluator_version: str,
    persona_fingerprint: str,
    prompt_template_version: str,
    provider_id: str,
    model_id: str,
    generation_parameters: GenerationParameters,
    provider_config_fingerprint: str = "",
) -> str:
    payload = json.dumps(
        {
            "source_hash": source_hash,
            "context_hash": context_hash,
            "reader_evaluator_version": reader_evaluator_version,
            "persona_fingerprint": persona_fingerprint,
            "prompt_template_version": prompt_template_version,
            "provider_id": provider_id,
            "model_id": model_id,
            "generation_parameters": generation_parameters.to_dict(),
            "provider_config_fingerprint": provider_config_fingerprint,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ModelStalenessResult:
    state: ModelRunState
    stale_reasons: list[ModelStaleReason] = field(default_factory=list)
