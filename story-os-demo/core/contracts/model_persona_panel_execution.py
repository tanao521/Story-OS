"""Contracts for bounded, multi-persona model execution.

The deterministic Reader Persona panel remains authoritative.  This contract
only records the independently-produced model supplements for selected
personas; it intentionally has no aggregation or synthesis fields.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from core.contracts.model_persona_execution import ExecutionMode


MODEL_PERSONA_PANEL_RUN_SCHEMA_VERSION = "1.0"
MAX_PANEL_PERSONAS = 5
DEFAULT_MAX_PROVIDER_CALLS = 1


class ModelPersonaPanelStatus(str, Enum):
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    INVALID_OUTPUT = "invalid_output"


class ModelPersonaPanelState(str, Enum):
    CURRENT = "current"
    PARTIALLY_STALE = "partially_stale"
    STALE = "stale"
    SOURCE_MISSING = "source_missing"


@dataclass(frozen=True)
class ModelPersonaPanelExecutionRequest:
    project_id: str
    timeline_id: str
    chapter_id: int
    persona_ids: list[str]
    source_version_id: Optional[str] = None
    execution_mode: ExecutionMode = ExecutionMode.MOCK
    execution_profile: str = "default"
    allow_model_call: bool = False
    max_provider_calls: int = DEFAULT_MAX_PROVIDER_CALLS
    force: bool = False
    expected_source_hash: Optional[str] = None
    expected_context_hash: Optional[str] = None
    live_ticket_id: Optional[str] = None
    profile_registry_revision: Optional[str] = None
    budget_policy_id: Optional[str] = None
    budget_policy_revision: Optional[str] = None
    counter_id: Optional[str] = None
    counter_revision: Optional[str] = None
    counter_scope: Optional[str] = None
    canonical_payload_hash: Optional[str] = None
    thinking_mode: Optional[str] = None
    structured_output_mode: Optional[str] = None
    max_input_tokens_per_call: Optional[int] = None


@dataclass(frozen=True)
class ModelPersonaPanelExecutionPlan:
    requested_persona_ids: list[str]
    ordered_persona_ids: list[str]
    cache_hit_persona_ids: list[str]
    cache_miss_persona_ids: list[str]
    blocked_persona_ids: list[str]
    expected_provider_calls: int
    max_provider_calls: int
    execution_mode: ExecutionMode
    execution_profile: str
    can_execute: bool
    blocked_reason: Optional[str] = None
    error_code: Optional[str] = None
    source_hash: str = ""
    context_hash: str = ""
    reader_evaluator_version: str = ""
    authoritative_panel_fingerprint: str = ""
    child_input_fingerprints: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelPersonaPanelUsage:
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    duration_ms: Optional[int] = None

    def to_dict(self) -> dict[str, Optional[int]]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True)
class ModelPersonaPanelExecutionResult:
    panel_execution_id: str
    created_at: datetime
    project_id: str
    timeline_id: str
    chapter_id: int
    source_version_id: Optional[str]
    status: ModelPersonaPanelStatus
    execution_mode: ExecutionMode
    execution_profile: str
    execution_profile_version: str
    ordered_persona_ids: list[str]
    child_execution_ids: dict[str, str]
    child_statuses: dict[str, str]
    authoritative_panel_fingerprint: str
    panel_execution_fingerprint: str
    source_hash: str
    context_hash: str
    reader_evaluator_version: str
    child_input_fingerprints: dict[str, str]
    expected_provider_call_count: int
    actual_provider_call_count: int
    cache_hit_count: int
    cache_miss_count: int
    usage: Optional[ModelPersonaPanelUsage]
    usage_completeness: str
    error_code: Optional[str] = None
    staleness: ModelPersonaPanelState = ModelPersonaPanelState.CURRENT
    completed_at: Optional[datetime] = None
    live_ticket_id: Optional[str] = None
    profile_registry_revision: Optional[str] = None
    budget_policy_id: Optional[str] = None
    budget_policy_revision: Optional[str] = None
    counter_id: Optional[str] = None
    counter_revision: Optional[str] = None
    counter_scope: Optional[str] = None
    canonical_payload_hash: Optional[str] = None
    thinking_mode: Optional[str] = None
    structured_output_mode: Optional[str] = None


def compute_panel_execution_fingerprint(
    *, project_id: str, timeline_id: str, chapter_id: int,
    source_version_id: Optional[str], authoritative_panel_fingerprint: str,
    ordered_persona_ids: list[str], child_input_fingerprints: dict[str, str],
    execution_mode: ExecutionMode, execution_profile: str,
    max_provider_calls: int,
) -> str:
    payload: dict[str, Any] = {
        "project_id": project_id,
        "timeline_id": timeline_id,
        "chapter_id": chapter_id,
        "source_version_id": source_version_id,
        "authoritative_panel_fingerprint": authoritative_panel_fingerprint,
        "ordered_persona_ids": ordered_persona_ids,
        "child_input_fingerprints": child_input_fingerprints,
        "execution_mode": execution_mode.value,
        "execution_profile": execution_profile,
        "max_provider_calls": max_provider_calls,
        "schema_version": MODEL_PERSONA_PANEL_RUN_SCHEMA_VERSION,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
