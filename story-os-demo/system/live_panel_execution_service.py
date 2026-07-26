"""Consent-bound, idempotent server entry for Live Panel execution.

No UI calls this service in 0D3C2-A.  It is intentionally the only supported
public Live path: old direct Live routes are rejected before they can resolve
a project or provider.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from core.contracts.live_panel_execution import (
    LiveExecutionAttemptAudit,
    LiveExecutionBudgetPolicy,
    LiveExecutionConsentTicket,
    LiveExecutionStatus,
    PublicExecutionProfile,
)
from core.contracts.model_persona_execution import ExecutionMode, ExecutionProfile
from core.contracts.model_persona_panel_execution import ModelPersonaPanelExecutionRequest, ModelPersonaPanelStatus
from core.project_context import ProjectContext
from system.live_panel_execution_store import LivePanelExecutionStore
from system.model_persona_panel_execution_service import ModelPersonaPanelExecutionService
from system.conservative_token_budget import (
    CONSERVATIVE_COUNTER_ASSET_UNAVAILABLE,
    CONSERVATIVE_TOKEN_BUDGET_AVAILABLE,
    ConservativeTextCounter,
    strict_deepseek_policy,
)


CONSENT_TTL_SECONDS = 300
RECONCILIATION_GRACE_SECONDS = 90
LIVE_BUDGET_POLICY_ID = "live-panel-server-policy"
LIVE_BUDGET_POLICY_REVISION = "1.0"
LIVE_EXECUTION_CAPABILITY_ENV = "STORYOS_LIVE_EXECUTION_UI_ENABLED"


def live_execution_ui_enabled() -> bool:
    """Server-owned capability switch; production defaults to disabled."""
    value = os.environ.get(LIVE_EXECUTION_CAPABILITY_ENV, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def public_live_capability() -> dict:
    enabled = live_execution_ui_enabled()
    return {
        "enabled": enabled,
        "status": "enabled" if enabled else "disabled",
        "safe_error_code": None if enabled else "LIVE_EXECUTION_DISABLED",
    }


class LivePanelExecutionService:
    """Owns consent, budget, idempotency, recovery, and safe audit records."""

    def __init__(
        self, context: ProjectContext, *, provider=None,
        profiles: Optional[dict[str, ExecutionProfile]] = None,
        conservative_counter: Optional[ConservativeTextCounter] = None,
        conservative_provisioning_enabled: bool = False,
    ) -> None:
        self.context = context
        conservative_policy = None
        if conservative_counter is not None:
            try:
                conservative_policy = strict_deepseek_policy(
                    counter_id=str(getattr(conservative_counter, "counter_id", "")),
                    counter_revision=str(getattr(conservative_counter, "counter_revision", "")),
                )
            except ValueError:
                conservative_policy = None
        self.panel = ModelPersonaPanelExecutionService(
            context, provider=provider, profiles=profiles,
            conservative_counter=conservative_counter if conservative_provisioning_enabled else None,
            conservative_policy=conservative_policy if conservative_provisioning_enabled else None,
        )
        self.store = LivePanelExecutionStore(context)
        self._conservative_counter = conservative_counter
        self._conservative_provisioning_enabled = bool(conservative_provisioning_enabled)

    def list_public_profiles(self) -> list[dict]:
        revision = self.profile_registry_revision()
        profiles: list[dict] = []
        provider = self.panel.child_service._provider
        base_token_counter_available = callable(getattr(provider, "count_request_tokens", None)) or callable(getattr(provider, "count_input_tokens", None))
        base_counter_id = str(getattr(provider, "counter_id", "")) or ("injected-exact-counter" if base_token_counter_available else "")
        base_counter_revision = str(getattr(provider, "counter_revision", "")) or ("legacy-test-interface" if base_token_counter_available else "")
        for profile_id, profile in sorted(self.panel.child_service._profiles.items()):
            if profile_id != profile.profile_id or profile.provider_type == "mock":
                continue
            is_conservative = self._is_conservative_profile(profile)
            conservative_ready = self._conservative_ready(profile)
            token_counter_available = base_token_counter_available
            counter_id = base_counter_id
            counter_revision = base_counter_revision
            if is_conservative:
                token_counter_available = False
                counter_id = ""
                counter_revision = ""
            max_provider_calls = 1 if is_conservative else 5
            max_input_tokens = 3584 if is_conservative else 4096 * max_provider_calls
            max_output_tokens = profile.generation_parameters.max_output_tokens
            readiness_code = None
            if not profile.enabled:
                readiness_code = "PROVIDER_NOT_CONFIGURED"
            elif is_conservative and not conservative_ready:
                readiness_code = CONSERVATIVE_COUNTER_ASSET_UNAVAILABLE
            elif not is_conservative and not token_counter_available:
                readiness_code = "INPUT_TOKEN_BUDGET_UNAVAILABLE"
            profiles.append(PublicExecutionProfile(
                profile_id=profile.profile_id,
                display_name=profile.profile_id.replace("-", " ").replace("_", " ").title(),
                provider_label=self._provider_label(profile),
                model_label=profile.model_id,
                timeout_seconds=profile.timeout_seconds,
                max_output_tokens=512 if is_conservative else max_output_tokens,
                max_provider_calls=max_provider_calls,
                retry_policy="0",
                fallback_policy="none",
                enabled=bool(profile.enabled),
                registry_revision=revision,
                max_input_tokens=max_input_tokens,
                max_total_tokens=4096 if is_conservative else (4096 + max_output_tokens) * max_provider_calls,
                token_counter_available=token_counter_available,
                ready_for_consent=bool(profile.enabled and (conservative_ready if is_conservative else token_counter_available)),
                readiness_code=readiness_code,
                exact_token_counter_available=False if is_conservative else token_counter_available,
                counter_label=counter_id or None,
                counter_revision_short=counter_revision[:12] or None,
                budget_policy_supported=True,
                structured_output_supported=profile.structured_output_mode.value == "json",
                ready_for_live_execution=bool(
                    profile.enabled
                    and (conservative_ready if is_conservative else token_counter_available)
                    and live_execution_ui_enabled()
                ),
                safe_readiness_code=(
                    readiness_code
                    or (None if live_execution_ui_enabled() else "PROFILE_READY_CAPABILITY_DISABLED")
                ),
                token_budget_mode="conservative" if is_conservative else "exact",
                conservative_token_budget_available=conservative_ready,
                conservative_policy_label=(
                    "DeepSeek V4 Flash Strict Conservative" if is_conservative else None
                ),
                conservative_policy_revision="1.0" if is_conservative else None,
                text_counter_label=(
                    "DeepSeek-provided Layer-A text asset" if is_conservative else None
                ),
                text_counter_revision=(
                    str(getattr(self._conservative_counter, "counter_revision", ""))
                    if is_conservative and conservative_ready else None
                ),
                max_text_tokens=2048 if is_conservative else None,
                max_conservative_input_tokens=3584 if is_conservative else None,
                thinking_mode="disabled" if is_conservative else None,
                structured_output_mode="json_object" if is_conservative else None,
            ).to_dict())
        return profiles

    def profile_registry_revision(self) -> str:
        provider = self.panel.child_service._provider
        counter_id = str(getattr(provider, "counter_id", "")) or ("injected-exact-counter" if callable(getattr(provider, "count_input_tokens", None)) else "")
        counter_revision = str(getattr(provider, "counter_revision", "")) or ("legacy-test-interface" if counter_id else "")
        conservative_counter_id = str(getattr(self._conservative_counter, "counter_id", ""))
        conservative_counter_revision = str(getattr(self._conservative_counter, "counter_revision", ""))
        rows = []
        for profile_id, profile in sorted(self.panel.child_service._profiles.items()):
            rows.append({
                "profile_id": profile_id,
                "profile_version": profile.profile_version,
                "provider_type": profile.provider_type,
                "provider_id": profile.provider_id,
                "model_id": profile.model_id,
                "generation_parameters": profile.generation_parameters.to_dict(),
                "timeout_seconds": profile.timeout_seconds,
                "structured_output_mode": profile.structured_output_mode.value,
                "enabled": profile.enabled,
                "counter_id": counter_id,
                "counter_revision": counter_revision,
                "conservative_provisioning_enabled": self._conservative_provisioning_enabled,
                "conservative_counter_id": conservative_counter_id,
                "conservative_counter_revision": conservative_counter_revision,
                "conservative_policy_revision": "1.0",
            })
        encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:20]

    def issue_consent(
        self,
        *,
        project_id: str,
        timeline_id: str,
        chapter_id: int,
        source_version_id: Optional[str],
        persona_ids: list[str],
        profile_id: str,
        requested_max_provider_calls: int,
        consent_text_version: str,
        now: Optional[datetime] = None,
    ) -> tuple[Optional[LiveExecutionConsentTicket], Optional[str]]:
        if not isinstance(consent_text_version, str) or not consent_text_version.strip():
            return None, "INVALID_CONSENT_TEXT_VERSION"
        profile = self.panel.child_service._profiles.get(profile_id)
        if profile is None or profile.provider_type == "mock":
            return None, "INVALID_PROFILE"
        if not profile.enabled:
            return None, "PROVIDER_NOT_CONFIGURED"
        if self._is_conservative_profile(profile) and not self._conservative_ready(profile):
            return None, CONSERVATIVE_COUNTER_ASSET_UNAVAILABLE
        policy = self._budget_policy(profile, requested_max_provider_calls)
        if not isinstance(requested_max_provider_calls, int) or requested_max_provider_calls < 0:
            return None, "INVALID_BUDGET"
        if requested_max_provider_calls > policy.max_provider_calls:
            return None, "MAX_CALLS_EXCEEDS_POLICY"
        request = ModelPersonaPanelExecutionRequest(
            project_id=project_id, timeline_id=timeline_id, chapter_id=chapter_id,
            persona_ids=list(persona_ids), source_version_id=source_version_id,
            execution_mode=ExecutionMode.LIVE, execution_profile=profile_id,
            allow_model_call=True, max_provider_calls=requested_max_provider_calls,
            force=False,
        )
        plan = self.panel.plan(request)
        if not plan.can_execute:
            return None, plan.error_code or "LIVE_CONSENT_REJECTED"
        if plan.expected_provider_calls > policy.max_provider_calls:
            return None, "MAX_CALLS_EXCEEDS_POLICY"

        issued_at = (now or _utcnow()).astimezone(timezone.utc)
        revision = self.profile_registry_revision()
        provider = self.panel.child_service._provider
        counter_id = str(getattr(provider, "counter_id", "")) or ("injected-exact-counter" if callable(getattr(provider, "count_input_tokens", None)) else "")
        counter_revision = str(getattr(provider, "counter_revision", "")) or ("legacy-test-interface" if counter_id else "")
        counter_scope = None
        thinking_mode = None
        structured_output_mode = None
        if self._is_conservative_profile(profile):
            counter_id = str(getattr(self._conservative_counter, "counter_id", ""))
            counter_revision = str(getattr(self._conservative_counter, "counter_revision", ""))
            counter_scope = str(getattr(self._conservative_counter, "counter_scope", ""))
            thinking_mode = "disabled"
            structured_output_mode = "json_object"
        ticket_id = secrets.token_urlsafe(24)
        idempotency_key = secrets.token_urlsafe(32)
        fingerprint = self._request_fingerprint(
            project_id=project_id, timeline_id=timeline_id, chapter_id=chapter_id,
            source_version_id=source_version_id, source_fingerprint=plan.source_hash,
            context_fingerprint=plan.context_hash, ordered_persona_ids=plan.ordered_persona_ids,
            profile_id=profile_id, profile_registry_revision=revision,
            max_provider_calls=requested_max_provider_calls, ticket_id=ticket_id,
            policy_id=policy.policy_id, policy_revision=policy.policy_revision,
            counter_id=counter_id, counter_revision=counter_revision,
            counter_scope=counter_scope, thinking_mode=thinking_mode,
            structured_output_mode=structured_output_mode,
            max_input_tokens=policy.max_input_tokens,
            max_output_tokens=policy.max_output_tokens,
            max_total_tokens=policy.max_total_tokens,
        )
        canonical_payload_hash = hashlib.sha256(json.dumps({
            "provider_id": profile.provider_id,
            "model_id": profile.model_id,
            "profile_revision": profile.profile_version,
            "policy_revision": policy.policy_revision,
            "counter_id": counter_id,
            "counter_revision": counter_revision,
            "counter_scope": counter_scope,
            "thinking_mode": thinking_mode,
            "structured_output_mode": structured_output_mode,
            "source_fingerprint": plan.source_hash,
            "context_fingerprint": plan.context_hash,
            "ordered_persona_ids": plan.ordered_persona_ids,
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        ticket = LiveExecutionConsentTicket(
            ticket_id=ticket_id, project_id=project_id, timeline_id=timeline_id,
            chapter_id=chapter_id, source_version_id=source_version_id,
            source_fingerprint=plan.source_hash, context_fingerprint=plan.context_hash,
            ordered_persona_ids=plan.ordered_persona_ids, execution_profile_id=profile_id,
            profile_registry_revision=revision, max_provider_calls=requested_max_provider_calls,
            token_budget=policy, consent_text_version=consent_text_version.strip(),
            issued_at=issued_at, expires_at=issued_at + timedelta(seconds=CONSENT_TTL_SECONDS),
            idempotency_key=idempotency_key, request_fingerprint=fingerprint,
            counter_id=counter_id or None, counter_revision=counter_revision or None,
            counter_scope=counter_scope, canonical_payload_hash=canonical_payload_hash,
            thinking_mode=thinking_mode, structured_output_mode=structured_output_mode,
        )
        self.store.save_ticket(ticket)
        return ticket, None

    def execute_ticket(self, ticket_id: str, idempotency_key: Optional[str]) -> dict:
        ticket = self.store.load_ticket(ticket_id)
        if ticket is None:
            return self._status(None, LiveExecutionStatus.REJECTED, safe_error_code="LIVE_TICKET_NOT_FOUND")
        if not secrets.compare_digest(idempotency_key or "", ticket.idempotency_key):
            self._append_audit(ticket, LiveExecutionStatus.REJECTED, safe_error_code="IDEMPOTENCY_KEY_MISMATCH")
            return self._status(ticket, LiveExecutionStatus.REJECTED, safe_error_code="IDEMPOTENCY_KEY_MISMATCH")
        if self._is_expired(ticket):
            self._append_audit(ticket, LiveExecutionStatus.EXPIRED, safe_error_code="LIVE_CONSENT_EXPIRED")
            return self._status(ticket, LiveExecutionStatus.EXPIRED, safe_error_code="LIVE_CONSENT_EXPIRED")
        if ticket.profile_registry_revision != self.profile_registry_revision():
            self._append_audit(ticket, LiveExecutionStatus.REJECTED, safe_error_code="PROFILE_REGISTRY_CHANGED")
            return self._status(ticket, LiveExecutionStatus.REJECTED, safe_error_code="PROFILE_REGISTRY_CHANGED")

        request = self._request_from_ticket(ticket)
        plan = self.panel.plan(request)
        if plan.source_hash != ticket.source_fingerprint or plan.context_hash != ticket.context_fingerprint:
            self._append_audit(ticket, LiveExecutionStatus.BLOCKED, safe_error_code="SOURCE_CHANGED_AFTER_CONSENT")
            return self._status(ticket, LiveExecutionStatus.BLOCKED, safe_error_code="SOURCE_CHANGED_AFTER_CONSENT")
        if not plan.can_execute:
            code = plan.error_code or "LIVE_EXECUTION_REJECTED"
            self._append_audit(ticket, LiveExecutionStatus.BLOCKED, safe_error_code=code)
            return self._status(ticket, LiveExecutionStatus.BLOCKED, safe_error_code=code)

        owner, existing = self.store.reserve(ticket)
        if not owner:
            return self.recover(ticket.ticket_id, ticket.idempotency_key)

        self._append_audit(ticket, LiveExecutionStatus.IN_PROGRESS, started_at=_utcnow(), consent_accepted_at=_utcnow())
        try:
            result = self.panel.execute(request)
        except Exception:
            # The provider may already have received the request.  Never retry
            # automatically; force explicit reconciliation instead.
            record = self.store.finish_ownership(
                ticket.ticket_id, status=LiveExecutionStatus.RECONCILIATION_REQUIRED,
                panel_execution_id=None, safe_error_code="LIVE_RECONCILIATION_REQUIRED",
                actual_provider_calls=0, usage_completeness="unknown",
            )
            self._append_audit(ticket, LiveExecutionStatus.RECONCILIATION_REQUIRED, finished_at=_utcnow(), safe_error_code="LIVE_RECONCILIATION_REQUIRED")
            return self._public_record(record)

        status = self._status_from_panel(result.status)
        record = self.store.finish_ownership(
            ticket.ticket_id, status=status, panel_execution_id=result.panel_execution_id,
            safe_error_code=result.error_code, actual_provider_calls=result.actual_provider_call_count,
            usage_completeness=result.usage_completeness,
        )
        self._append_audit(
            ticket, status, finished_at=_utcnow(), panel_execution_id=result.panel_execution_id,
            safe_error_code=result.error_code, actual_provider_calls=result.actual_provider_call_count,
            usage_completeness=result.usage_completeness,
        )
        return self._public_record(record)

    def recover(self, ticket_id: str, idempotency_key: Optional[str]) -> dict:
        ticket = self.store.load_ticket(ticket_id)
        if ticket is None:
            return self._status(None, LiveExecutionStatus.REJECTED, safe_error_code="LIVE_TICKET_NOT_FOUND")
        if not secrets.compare_digest(idempotency_key or "", ticket.idempotency_key):
            return self._status(ticket, LiveExecutionStatus.REJECTED, safe_error_code="IDEMPOTENCY_KEY_MISMATCH")
        record = self.store.load_ownership(ticket.ticket_id)
        if record is None:
            if self._is_expired(ticket):
                return self._status(ticket, LiveExecutionStatus.EXPIRED, safe_error_code="LIVE_CONSENT_EXPIRED")
            return self._status(ticket, LiveExecutionStatus.ISSUED)
        if record.get("status") == LiveExecutionStatus.IN_PROGRESS.value and self._needs_reconciliation(record):
            derived = dict(record)
            derived["status"] = LiveExecutionStatus.RECONCILIATION_REQUIRED.value
            derived["safe_error_code"] = "LIVE_RECONCILIATION_REQUIRED"
            return self._public_record(derived)
        return self._public_record(record)

    def request_cancellation(self, ticket_id: str, idempotency_key: Optional[str]) -> dict:
        """Cancel only before provider ownership begins; never pretend to stop a remote call."""
        ticket = self.store.load_ticket(ticket_id)
        if ticket is None:
            return self._status(None, LiveExecutionStatus.REJECTED, safe_error_code="LIVE_TICKET_NOT_FOUND")
        if not secrets.compare_digest(idempotency_key or "", ticket.idempotency_key):
            return self._status(ticket, LiveExecutionStatus.REJECTED, safe_error_code="IDEMPOTENCY_KEY_MISMATCH")
        owner, record = self.store.reserve(ticket)
        if owner:
            record = self.store.finish_ownership(
                ticket.ticket_id, status=LiveExecutionStatus.CANCELLED, panel_execution_id=None,
                safe_error_code="LIVE_CANCELLED_BEFORE_EXECUTION", actual_provider_calls=0,
                usage_completeness="not_applicable",
            )
            self._append_audit(ticket, LiveExecutionStatus.CANCELLED, finished_at=_utcnow(), safe_error_code="LIVE_CANCELLED_BEFORE_EXECUTION")
            return self._public_record(record)
        if record.get("status") == LiveExecutionStatus.IN_PROGRESS.value:
            record = self.store.finish_ownership(
                ticket.ticket_id, status=LiveExecutionStatus.CANCEL_REQUESTED,
                panel_execution_id=record.get("panel_execution_id"), safe_error_code="LIVE_CANCEL_REQUESTED",
                actual_provider_calls=int(record.get("actual_provider_calls", 0) or 0),
                usage_completeness=str(record.get("usage_completeness", "not_applicable")),
            )
            self._append_audit(ticket, LiveExecutionStatus.CANCEL_REQUESTED, safe_error_code="LIVE_CANCEL_REQUESTED")
            return self._public_record(record)
        return self._public_record(record)

    def _request_from_ticket(self, ticket: LiveExecutionConsentTicket) -> ModelPersonaPanelExecutionRequest:
        return ModelPersonaPanelExecutionRequest(
            project_id=ticket.project_id, timeline_id=ticket.timeline_id, chapter_id=ticket.chapter_id,
            persona_ids=list(ticket.ordered_persona_ids), source_version_id=ticket.source_version_id,
            execution_mode=ExecutionMode.LIVE, execution_profile=ticket.execution_profile_id,
            allow_model_call=True, max_provider_calls=ticket.max_provider_calls, force=False,
            expected_source_hash=ticket.source_fingerprint, expected_context_hash=ticket.context_fingerprint,
            live_ticket_id=ticket.ticket_id, profile_registry_revision=ticket.profile_registry_revision,
            budget_policy_id=ticket.token_budget.policy_id,
            budget_policy_revision=ticket.token_budget.policy_revision,
            counter_id=ticket.counter_id, counter_revision=ticket.counter_revision,
            counter_scope=ticket.counter_scope,
            canonical_payload_hash=ticket.canonical_payload_hash,
            thinking_mode=ticket.thinking_mode,
            structured_output_mode=ticket.structured_output_mode,
            max_input_tokens_per_call=ticket.token_budget.max_input_tokens // ticket.max_provider_calls,
        )

    def _budget_policy(self, profile: ExecutionProfile, max_provider_calls: int) -> LiveExecutionBudgetPolicy:
        if self._is_conservative_profile(profile):
            conservative = strict_deepseek_policy(
                counter_id=str(getattr(self._conservative_counter, "counter_id", "")),
                counter_revision=str(getattr(self._conservative_counter, "counter_revision", "")),
            )
            return LiveExecutionBudgetPolicy(
                policy_id=conservative.policy_id,
                policy_revision=conservative.policy_revision,
                max_provider_calls=conservative.max_provider_calls,
                max_input_tokens=conservative.max_conservative_input_tokens,
                max_output_tokens=conservative.max_output_tokens,
                max_total_tokens=conservative.max_total_tokens,
                timeout_seconds=conservative.timeout_seconds,
                cost_estimate_available=False, currency=None, max_estimated_cost=None,
                estimate_source="server_conservative_non_exact",
                estimate_timestamp=None, retry_policy="0", fallback_policy="none",
            )
        # No price is invented and there is no character-count token surrogate.
        # Live execution requires a provider-owned exact token counter before
        # a call; the fixed input cap is therefore a real pre-call gate.
        input_per_call = 4096
        output_per_call = profile.generation_parameters.max_output_tokens
        return LiveExecutionBudgetPolicy(
            policy_id=LIVE_BUDGET_POLICY_ID, policy_revision=LIVE_BUDGET_POLICY_REVISION,
            max_provider_calls=5, max_input_tokens=input_per_call * max_provider_calls,
            max_output_tokens=output_per_call * max_provider_calls,
            max_total_tokens=(input_per_call + output_per_call) * max_provider_calls,
            timeout_seconds=profile.timeout_seconds,
            cost_estimate_available=False, currency=None, max_estimated_cost=None,
            estimate_source="unavailable", estimate_timestamp=None,
        )

    @staticmethod
    def _provider_label(profile: ExecutionProfile) -> str:
        return "OpenAI-compatible" if profile.provider_type == "openai_compatible" else "Unavailable"

    @staticmethod
    def _request_fingerprint(**payload: object) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _status_from_panel(status: ModelPersonaPanelStatus) -> LiveExecutionStatus:
        return {
            ModelPersonaPanelStatus.COMPLETED: LiveExecutionStatus.COMPLETED,
            ModelPersonaPanelStatus.PARTIALLY_COMPLETED: LiveExecutionStatus.PARTIALLY_COMPLETED,
            ModelPersonaPanelStatus.BLOCKED: LiveExecutionStatus.BLOCKED,
        }.get(status, LiveExecutionStatus.FAILED)

    def _append_audit(
        self, ticket: LiveExecutionConsentTicket, status: LiveExecutionStatus, *,
        consent_accepted_at: Optional[datetime] = None, started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None, panel_execution_id: Optional[str] = None,
        safe_error_code: Optional[str] = None, actual_provider_calls: int = 0,
        usage_completeness: str = "not_applicable",
    ) -> None:
        self.store.append_audit(LiveExecutionAttemptAudit(
            audit_id=secrets.token_urlsafe(18), ticket_id=ticket.ticket_id,
            idempotency_key=ticket.idempotency_key, request_fingerprint=ticket.request_fingerprint,
            project_id=ticket.project_id, timeline_id=ticket.timeline_id, chapter_id=ticket.chapter_id,
            source_version_id=ticket.source_version_id, source_fingerprint=ticket.source_fingerprint,
            ordered_persona_ids=list(ticket.ordered_persona_ids), profile_id=ticket.execution_profile_id,
            profile_registry_revision=ticket.profile_registry_revision,
            budget_policy_id=ticket.token_budget.policy_id, max_provider_calls=ticket.max_provider_calls,
            consent_text_version=ticket.consent_text_version, consent_issued_at=ticket.issued_at,
            consent_accepted_at=consent_accepted_at, started_at=started_at, finished_at=finished_at,
            status=status, panel_execution_id=panel_execution_id, safe_error_code=safe_error_code,
            actual_provider_calls=actual_provider_calls, usage_completeness=usage_completeness,
            counter_id=ticket.counter_id, counter_revision=ticket.counter_revision,
            counter_scope=ticket.counter_scope,
            canonical_payload_hash=ticket.canonical_payload_hash,
            thinking_mode=ticket.thinking_mode,
            structured_output_mode=ticket.structured_output_mode,
        ))

    @staticmethod
    def _is_conservative_profile(profile: ExecutionProfile) -> bool:
        return profile.provider_id == "deepseek" and profile.model_id == "deepseek-v4-flash"

    def _conservative_ready(self, profile: ExecutionProfile) -> bool:
        counter = self._conservative_counter
        return bool(
            self._is_conservative_profile(profile)
            and self._conservative_provisioning_enabled
            and counter is not None
            and not bool(getattr(counter, "exact", False))
            and str(getattr(counter, "counter_scope", "")) == "layer_a_text_only_non_exact"
            and str(getattr(counter, "counter_id", ""))
            and str(getattr(counter, "counter_revision", ""))
            and counter.supports("deepseek", "deepseek-v4-flash")
        )

    @staticmethod
    def _is_expired(ticket: LiveExecutionConsentTicket) -> bool:
        return _utcnow() >= ticket.expires_at.astimezone(timezone.utc)

    @staticmethod
    def _needs_reconciliation(record: dict) -> bool:
        try:
            updated = datetime.fromisoformat(str(record["updated_at"])).astimezone(timezone.utc)
        except (KeyError, TypeError, ValueError):
            return True
        return _utcnow() - updated > timedelta(seconds=RECONCILIATION_GRACE_SECONDS)

    @staticmethod
    def _status(ticket: Optional[LiveExecutionConsentTicket], status: LiveExecutionStatus, *, safe_error_code: Optional[str] = None) -> dict:
        return {
            "ticket_id": ticket.ticket_id if ticket else None,
            "status": status.value,
            "panel_execution_id": None,
            "safe_error_code": safe_error_code,
            "actual_provider_calls": 0,
            "usage_completeness": "not_applicable",
            "updated_at": _utcnow().isoformat(),
        }

    @staticmethod
    def _public_record(record: dict) -> dict:
        return {
            "ticket_id": record.get("ticket_id"),
            "status": record.get("status"),
            "panel_execution_id": record.get("panel_execution_id"),
            "safe_error_code": record.get("safe_error_code"),
            "actual_provider_calls": int(record.get("actual_provider_calls", 0) or 0),
            "usage_completeness": record.get("usage_completeness", "not_applicable"),
            "updated_at": record.get("updated_at"),
        }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
