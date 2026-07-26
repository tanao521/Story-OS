"""Offline Provider readiness and exact-token counter contracts.

No production counter is registered implicitly. Unknown provider/model pairs
must remain blocked rather than fall back to character or heuristic counting.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol


class ProviderTokenCounter(Protocol):
    counter_id: str
    counter_revision: str

    def supports(self, *, provider_id: str, model_id: str) -> bool: ...

    def count_request_tokens(self, request: Any) -> int: ...


class ProviderTokenCounterRegistry:
    def __init__(self, counters: list[ProviderTokenCounter] | None = None) -> None:
        self._counters = list(counters or [])

    def resolve(self, *, provider_id: str, model_id: str) -> ProviderTokenCounter | None:
        for counter in self._counters:
            if counter.supports(provider_id=provider_id, model_id=model_id):
                return counter
        return None


@dataclass(frozen=True)
class ProviderOperationalReadiness:
    profile_id: str
    profile_revision: str
    provider_label: str
    model_label: str
    enabled: bool
    credential_configured: bool
    exact_token_counter_available: bool
    counter_id: str | None
    counter_revision: str | None
    request_serialization_supported: bool
    budget_policy_supported: bool
    structured_output_supported: bool
    live_capability_default_off: bool
    ready_for_consent: bool
    ready_for_live_execution: bool
    safe_readiness_code: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "display_name": self.profile_id.replace("-", " ").replace("_", " ").title(),
            "provider_label": self.provider_label,
            "model_label": self.model_label,
            "enabled": self.enabled,
            "exact_token_counter_available": self.exact_token_counter_available,
            "counter_label": self.counter_id,
            "counter_revision_short": (self.counter_revision or "")[:12] or None,
            "budget_policy_supported": self.budget_policy_supported,
            "structured_output_supported": self.structured_output_supported,
            "ready_for_consent": self.ready_for_consent,
            "ready_for_live_execution": self.ready_for_live_execution,
            "safe_readiness_code": self.safe_readiness_code,
        }


def request_fingerprint(request: Any) -> str:
    payload = request.canonical_payload()
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    metadata = {
        "provider_id": getattr(request, "provider_id", ""),
        "profile_revision": getattr(request, "profile_revision", ""),
        "counter_id": getattr(request, "counter_id", ""),
        "counter_revision": getattr(request, "counter_revision", ""),
        "payload": encoded,
    }
    return hashlib.sha256(json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def prepare_live_request_dry_run(
    *, request: Any, counter: ProviderTokenCounter | None, max_input_tokens: int
) -> dict[str, Any]:
    """Count one already-canonical request without Provider/network/persistence."""
    if counter is None or not counter.supports(
        provider_id=str(getattr(request, "provider_id", "")),
        model_id=str(getattr(request, "model_id", "")),
    ):
        return {
            "ready": False,
            "safe_readiness_code": "MODEL_TOKENIZER_UNSUPPORTED",
            "input_tokens": None,
            "request_fingerprint": request_fingerprint(request),
        }
    try:
        count = counter.count_request_tokens(request)
    except Exception:
        return {
            "ready": False,
            "safe_readiness_code": "INPUT_TOKEN_BUDGET_UNAVAILABLE",
            "input_tokens": None,
            "request_fingerprint": request_fingerprint(request),
        }
    if not isinstance(count, int) or count < 0:
        return {
            "ready": False,
            "safe_readiness_code": "INPUT_TOKEN_BUDGET_UNAVAILABLE",
            "input_tokens": None,
            "request_fingerprint": request_fingerprint(request),
        }
    return {
        "ready": count <= max_input_tokens,
        "safe_readiness_code": None if count <= max_input_tokens else "INPUT_TOKEN_BUDGET_EXCEEDED",
        "input_tokens": count,
        "request_fingerprint": request_fingerprint(request),
        "counter_id": counter.counter_id,
        "counter_revision": counter.counter_revision,
    }
