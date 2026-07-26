"""Server-owned safety contracts for controlled Live panel execution.

These records deliberately contain no credential, endpoint, prompt, chapter
text, absolute path, or raw provider exception.  They are independent from
the immutable model/panel Run records so a response-loss recovery does not
need to repeat a provider call.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


LIVE_CONSENT_SCHEMA_VERSION = "1.0"
LIVE_ATTEMPT_SCHEMA_VERSION = "1.0"


class LiveExecutionStatus(str, Enum):
    ISSUED = "issued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    EXPIRED = "expired"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    REJECTED = "rejected"


@dataclass(frozen=True)
class LiveExecutionBudgetPolicy:
    policy_id: str
    policy_revision: str
    max_provider_calls: int
    max_input_tokens: Optional[int]
    max_output_tokens: int
    max_total_tokens: Optional[int]
    timeout_seconds: int
    cost_estimate_available: bool
    currency: Optional[str]
    max_estimated_cost: Optional[float]
    estimate_source: str
    estimate_timestamp: Optional[str]
    retry_policy: str = "0"
    fallback_policy: str = "none"

    def to_public_dict(self) -> dict:
        return {
            "policy_id": self.policy_id,
            "policy_revision": self.policy_revision,
            "max_provider_calls": self.max_provider_calls,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "max_total_tokens": self.max_total_tokens,
            "timeout_seconds": self.timeout_seconds,
            "cost_estimate_available": self.cost_estimate_available,
            "currency": self.currency,
            "max_estimated_cost": self.max_estimated_cost,
            "estimate_source": self.estimate_source,
            "estimate_timestamp": self.estimate_timestamp,
            "retry_policy": self.retry_policy,
            "fallback_policy": self.fallback_policy,
        }


@dataclass(frozen=True)
class PublicExecutionProfile:
    profile_id: str
    display_name: str
    provider_label: str
    model_label: str
    timeout_seconds: int
    max_output_tokens: int
    max_provider_calls: int
    retry_policy: str
    fallback_policy: str
    enabled: bool
    registry_revision: str
    max_input_tokens: Optional[int] = None
    max_total_tokens: Optional[int] = None
    cost_estimate_available: bool = False
    currency: Optional[str] = None
    max_estimated_cost: Optional[float] = None
    token_counter_available: bool = False
    ready_for_consent: bool = False
    readiness_code: Optional[str] = None
    exact_token_counter_available: bool = False
    counter_label: Optional[str] = None
    counter_revision_short: Optional[str] = None
    budget_policy_supported: bool = True
    structured_output_supported: bool = True
    ready_for_live_execution: bool = False
    safe_readiness_code: Optional[str] = None
    token_budget_mode: str = "exact"
    conservative_token_budget_available: bool = False
    conservative_policy_label: Optional[str] = None
    conservative_policy_revision: Optional[str] = None
    text_counter_label: Optional[str] = None
    text_counter_revision: Optional[str] = None
    max_text_tokens: Optional[int] = None
    max_conservative_input_tokens: Optional[int] = None
    thinking_mode: Optional[str] = None
    structured_output_mode: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "display_name": self.display_name,
            "provider_label": self.provider_label,
            "model_label": self.model_label,
            "timeout_seconds": self.timeout_seconds,
            "max_output_tokens": self.max_output_tokens,
            "max_provider_calls": self.max_provider_calls,
            "retry_policy": self.retry_policy,
            "fallback_policy": self.fallback_policy,
            "enabled": self.enabled,
            "registry_revision": self.registry_revision,
            "max_input_tokens": self.max_input_tokens,
            "max_total_tokens": self.max_total_tokens,
            "cost_estimate_available": self.cost_estimate_available,
            "currency": self.currency,
            "max_estimated_cost": self.max_estimated_cost,
            "token_counter_available": self.token_counter_available,
            "ready_for_consent": self.ready_for_consent,
            "readiness_code": self.readiness_code,
            "exact_token_counter_available": self.exact_token_counter_available,
            "counter_label": self.counter_label,
            "counter_revision_short": self.counter_revision_short,
            "budget_policy_supported": self.budget_policy_supported,
            "structured_output_supported": self.structured_output_supported,
            "ready_for_live_execution": self.ready_for_live_execution,
            "safe_readiness_code": self.safe_readiness_code or self.readiness_code,
            "token_budget_mode": self.token_budget_mode,
            "conservative_token_budget_available": self.conservative_token_budget_available,
            "conservative_policy_label": self.conservative_policy_label,
            "conservative_policy_revision": self.conservative_policy_revision,
            "text_counter_label": self.text_counter_label,
            "text_counter_revision": self.text_counter_revision,
            "max_text_tokens": self.max_text_tokens,
            "max_conservative_input_tokens": self.max_conservative_input_tokens,
            "thinking_mode": self.thinking_mode,
            "structured_output_mode": self.structured_output_mode,
        }


@dataclass(frozen=True)
class LiveExecutionConsentTicket:
    ticket_id: str
    project_id: str
    timeline_id: str
    chapter_id: int
    source_version_id: Optional[str]
    source_fingerprint: str
    context_fingerprint: str
    ordered_persona_ids: list[str]
    execution_profile_id: str
    profile_registry_revision: str
    max_provider_calls: int
    token_budget: LiveExecutionBudgetPolicy
    consent_text_version: str
    issued_at: datetime
    expires_at: datetime
    idempotency_key: str
    request_fingerprint: str
    counter_id: Optional[str] = None
    counter_revision: Optional[str] = None
    counter_scope: Optional[str] = None
    canonical_payload_hash: Optional[str] = None
    thinking_mode: Optional[str] = None
    structured_output_mode: Optional[str] = None
    status: LiveExecutionStatus = LiveExecutionStatus.ISSUED

    def to_dict(self) -> dict:
        return {
            "ticket_id": self.ticket_id,
            "project_id": self.project_id,
            "timeline_id": self.timeline_id,
            "chapter_id": self.chapter_id,
            "source_version_id": self.source_version_id,
            "source_fingerprint": self.source_fingerprint,
            "context_fingerprint": self.context_fingerprint,
            "ordered_persona_ids": self.ordered_persona_ids,
            "execution_profile_id": self.execution_profile_id,
            "profile_registry_revision": self.profile_registry_revision,
            "max_provider_calls": self.max_provider_calls,
            "token_budget": self.token_budget.to_public_dict(),
            "consent_text_version": self.consent_text_version,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "idempotency_key": self.idempotency_key,
            "request_fingerprint": self.request_fingerprint,
            "counter_id": self.counter_id,
            "counter_revision": self.counter_revision,
            "counter_scope": self.counter_scope,
            "canonical_payload_hash": self.canonical_payload_hash,
            "thinking_mode": self.thinking_mode,
            "structured_output_mode": self.structured_output_mode,
            "status": self.status.value,
        }


@dataclass(frozen=True)
class LiveExecutionAttemptAudit:
    audit_id: str
    ticket_id: str
    idempotency_key: str
    request_fingerprint: str
    project_id: str
    timeline_id: str
    chapter_id: int
    source_version_id: Optional[str]
    source_fingerprint: str
    ordered_persona_ids: list[str]
    profile_id: str
    profile_registry_revision: str
    budget_policy_id: str
    max_provider_calls: int
    consent_text_version: str
    consent_issued_at: datetime
    consent_accepted_at: Optional[datetime]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    status: LiveExecutionStatus
    panel_execution_id: Optional[str]
    safe_error_code: Optional[str]
    actual_provider_calls: int
    usage_completeness: str
    counter_id: Optional[str] = None
    counter_revision: Optional[str] = None
    counter_scope: Optional[str] = None
    canonical_payload_hash: Optional[str] = None
    thinking_mode: Optional[str] = None
    structured_output_mode: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "audit_id": self.audit_id,
            "ticket_id": self.ticket_id,
            "idempotency_key": self.idempotency_key,
            "request_fingerprint": self.request_fingerprint,
            "project_id": self.project_id,
            "timeline_id": self.timeline_id,
            "chapter_id": self.chapter_id,
            "source_version_id": self.source_version_id,
            "source_fingerprint": self.source_fingerprint,
            "ordered_persona_ids": self.ordered_persona_ids,
            "profile_id": self.profile_id,
            "profile_registry_revision": self.profile_registry_revision,
            "budget_policy_id": self.budget_policy_id,
            "max_provider_calls": self.max_provider_calls,
            "consent_text_version": self.consent_text_version,
            "consent_issued_at": self.consent_issued_at.isoformat(),
            "consent_accepted_at": self.consent_accepted_at.isoformat() if self.consent_accepted_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "status": self.status.value,
            "panel_execution_id": self.panel_execution_id,
            "safe_error_code": self.safe_error_code,
            "actual_provider_calls": self.actual_provider_calls,
            "usage_completeness": self.usage_completeness,
            "counter_id": self.counter_id,
            "counter_revision": self.counter_revision,
            "counter_scope": self.counter_scope,
            "canonical_payload_hash": self.canonical_payload_hash,
            "thinking_mode": self.thinking_mode,
            "structured_output_mode": self.structured_output_mode,
        }
