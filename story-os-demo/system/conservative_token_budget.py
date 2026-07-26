"""Strict, non-exact token-budget infrastructure for DeepSeek V4 Flash.

This module is deliberately offline.  It never discovers, downloads, copies,
or executes tokenizer assets.  Production callers must explicitly inject a
validated Layer-A text counter.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, Sequence


CONSERVATIVE_TOKEN_BUDGET_AVAILABLE = "CONSERVATIVE_TOKEN_BUDGET_AVAILABLE"
CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE = "CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE"
CONSERVATIVE_TOKEN_BUDGET_EXCEEDED = "CONSERVATIVE_TOKEN_BUDGET_EXCEEDED"
CONSERVATIVE_POLICY_REVISION_CHANGED = "CONSERVATIVE_POLICY_REVISION_CHANGED"
CONSERVATIVE_COUNTER_ASSET_UNAVAILABLE = "CONSERVATIVE_COUNTER_ASSET_UNAVAILABLE"
CONSERVATIVE_COUNTER_ASSET_MISMATCH = "CONSERVATIVE_COUNTER_ASSET_MISMATCH"
MAX_CONSERVATIVE_ASSET_BYTES = 64 * 1024 * 1024
_UNSERIALIZABLE_PAYLOAD_HASH = hashlib.sha256(
    b"storyos-conservative-unserializable-payload-v1"
).hexdigest()


class ConservativeTextCounter(Protocol):
    """Layer-A text-only counter.  It is intentionally not an exact counter."""

    counter_id: str
    counter_revision: str
    counter_scope: str

    def supports(self, provider_id: str, model_id: str) -> bool: ...

    def count_text_tokens(self, texts: Sequence[str]) -> int: ...


@dataclass(frozen=True)
class ConservativeTokenBudgetPolicy:
    policy_id: str
    policy_revision: str
    provider_id: str
    model_id: str
    text_counter_id: str
    text_counter_revision: str
    text_counter_scope: str
    text_token_limit: int
    fixed_base_reserve: int
    per_message_reserve: int
    uncertainty_ratio: Decimal
    structured_output_reserve_tokens: int
    thinking_reserve_tokens: int
    max_conservative_input_tokens: int
    max_output_tokens: int
    max_total_tokens: int
    max_provider_calls: int
    timeout_seconds: int
    post_call_reconciliation_required: bool
    cost_estimate_available: bool
    retry_policy: str
    fallback_policy: str

    def __post_init__(self) -> None:
        required = (
            self.policy_id, self.policy_revision, self.provider_id, self.model_id,
            self.text_counter_id, self.text_counter_revision, self.text_counter_scope,
        )
        if any(not str(value).strip() for value in required):
            raise ValueError(CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE)
        if self.provider_id != "deepseek" or self.model_id != "deepseek-v4-flash":
            raise ValueError(CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE)
        if self.text_counter_scope != "layer_a_text_only_non_exact":
            raise ValueError(CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE)
        expected = (2048, 512, 64, Decimal("0.25"), 256, 0, 3584, 512, 4096, 1, 60)
        actual = (
            self.text_token_limit, self.fixed_base_reserve, self.per_message_reserve,
            self.uncertainty_ratio, self.structured_output_reserve_tokens,
            self.thinking_reserve_tokens, self.max_conservative_input_tokens,
            self.max_output_tokens, self.max_total_tokens, self.max_provider_calls,
            self.timeout_seconds,
        )
        integer_values = (
            self.text_token_limit, self.fixed_base_reserve, self.per_message_reserve,
            self.structured_output_reserve_tokens, self.thinking_reserve_tokens,
            self.max_conservative_input_tokens, self.max_output_tokens,
            self.max_total_tokens, self.max_provider_calls, self.timeout_seconds,
        )
        if (
            any(type(value) is not int for value in integer_values)
            or type(self.uncertainty_ratio) is not Decimal
            or actual != expected
        ):
            raise ValueError(CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE)
        if (
            not self.post_call_reconciliation_required
            or self.cost_estimate_available
            or self.retry_policy != "0"
            or self.fallback_policy != "none"
            or self.max_conservative_input_tokens + self.max_output_tokens > self.max_total_tokens
        ):
            raise ValueError(CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE)

    def estimate_input(self, text_tokens: int, message_count: int) -> int:
        if (
            type(text_tokens) is not int or type(message_count) is not int
            or text_tokens < 0 or message_count < 1
        ):
            raise ValueError(CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE)
        uncertainty = (Decimal(text_tokens) * self.uncertainty_ratio).to_integral_value(
            rounding=ROUND_CEILING
        )
        return (
            text_tokens
            + self.fixed_base_reserve
            + self.per_message_reserve * message_count
            + int(uncertainty)
            + self.structured_output_reserve_tokens
            + self.thinking_reserve_tokens
        )

    def fingerprint(self) -> str:
        payload = {
            key: (str(value) if isinstance(value, Decimal) else value)
            for key, value in self.__dict__.items()
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


def strict_deepseek_policy(
    *,
    counter_id: str,
    counter_revision: str,
) -> ConservativeTokenBudgetPolicy:
    return ConservativeTokenBudgetPolicy(
        policy_id="deepseek-v4-flash-strict-conservative",
        policy_revision="1.0",
        provider_id="deepseek",
        model_id="deepseek-v4-flash",
        text_counter_id=counter_id,
        text_counter_revision=counter_revision,
        text_counter_scope="layer_a_text_only_non_exact",
        text_token_limit=2048,
        fixed_base_reserve=512,
        per_message_reserve=64,
        uncertainty_ratio=Decimal("0.25"),
        structured_output_reserve_tokens=256,
        thinking_reserve_tokens=0,
        max_conservative_input_tokens=3584,
        max_output_tokens=512,
        max_total_tokens=4096,
        max_provider_calls=1,
        timeout_seconds=60,
        post_call_reconciliation_required=True,
        cost_estimate_available=False,
        retry_policy="0",
        fallback_policy="none",
    )


@dataclass(frozen=True)
class ConservativeAssetResult:
    available: bool
    safe_code: str
    counter: Optional[ConservativeTextCounter] = None


def provision_external_text_counter(
    *,
    enabled: bool,
    trusted_path: Optional[Path],
    expected_sha256: str,
    loader: Optional[Callable[[bytes, dict[str, Any]], ConservativeTextCounter]] = None,
) -> ConservativeAssetResult:
    """Validate one explicitly named local file; never search or auto-load."""
    if not enabled or trusted_path is None or loader is None:
        return ConservativeAssetResult(False, CONSERVATIVE_COUNTER_ASSET_UNAVAILABLE)
    path = Path(trusted_path)
    if (
        not path.is_absolute() or path.suffix.lower() != ".json"
        or len(expected_sha256) != 64
        or any(char not in "0123456789abcdefABCDEF" for char in expected_sha256)
    ):
        return ConservativeAssetResult(False, CONSERVATIVE_COUNTER_ASSET_MISMATCH)
    try:
        if path.is_symlink():
            raise OSError
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_size <= 0
                or metadata.st_size > MAX_CONSERVATIVE_ASSET_BYTES
            ):
                raise OSError
            chunks: list[bytes] = []
            remaining = metadata.st_size
            while remaining:
                chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                if not chunk:
                    raise OSError
                chunks.append(chunk)
                remaining -= len(chunk)
            asset_bytes = b"".join(chunks)
        finally:
            os.close(descriptor)
        parsed = json.loads(asset_bytes.decode("utf-8"))
        if not isinstance(parsed, dict) or not parsed:
            raise ValueError
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return ConservativeAssetResult(False, CONSERVATIVE_COUNTER_ASSET_MISMATCH)
    digest = hashlib.sha256(asset_bytes).hexdigest()
    if digest.lower() != expected_sha256.lower():
        return ConservativeAssetResult(False, CONSERVATIVE_COUNTER_ASSET_MISMATCH)
    try:
        counter = loader(asset_bytes, parsed)
    except Exception:
        return ConservativeAssetResult(False, CONSERVATIVE_COUNTER_ASSET_MISMATCH)
    scope = str(getattr(counter, "counter_scope", ""))
    if (
        scope != "layer_a_text_only_non_exact"
        or bool(getattr(counter, "exact", False))
        or not str(getattr(counter, "counter_id", ""))
        or not str(getattr(counter, "counter_revision", ""))
    ):
        return ConservativeAssetResult(False, CONSERVATIVE_COUNTER_ASSET_MISMATCH)
    return ConservativeAssetResult(True, CONSERVATIVE_TOKEN_BUDGET_AVAILABLE, counter)


@dataclass(frozen=True)
class ConservativeBudgetEvaluation:
    safe_code: str
    allowed: bool
    local_text_tokens: Optional[int]
    conservative_estimated_tokens: Optional[int]
    canonical_payload_hash: str


def _evaluate_conservative_request(
    *,
    canonical_payload: dict[str, Any],
    provider_id: str,
    policy: ConservativeTokenBudgetPolicy,
    counter: ConservativeTextCounter,
    client_text_limit: Optional[int] = None,
    client_input_limit: Optional[int] = None,
    client_call_limit: Optional[int] = None,
) -> ConservativeBudgetEvaluation:
    try:
        encoded = json.dumps(
            canonical_payload, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        )
    except (TypeError, ValueError):
        return ConservativeBudgetEvaluation(
            CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE, False, None, None,
            _UNSERIALIZABLE_PAYLOAD_HASH,
        )
    fingerprint = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    if not isinstance(canonical_payload, dict):
        return ConservativeBudgetEvaluation(
            CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE, False, None, None, fingerprint
        )
    messages = canonical_payload.get("messages")
    response_format = canonical_payload.get("response_format")
    thinking = canonical_payload.get("thinking")
    if (
        provider_id != policy.provider_id
        or canonical_payload.get("model") != policy.model_id
        or canonical_payload.get("max_tokens") != policy.max_output_tokens
        or canonical_payload.get("stream") is not False
        or thinking != {"type": "disabled"}
        or response_format != {"type": "json_object"}
        or not isinstance(messages, list)
        or not messages
        or str(getattr(counter, "counter_id", "")) != policy.text_counter_id
        or str(getattr(counter, "counter_revision", "")) != policy.text_counter_revision
        or str(getattr(counter, "counter_scope", "")) != policy.text_counter_scope
        or bool(getattr(counter, "exact", False))
    ):
        return ConservativeBudgetEvaluation(
            CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE, False, None, None, fingerprint
        )
    text_limit = policy.text_token_limit if client_text_limit is None else client_text_limit
    input_limit = (
        policy.max_conservative_input_tokens
        if client_input_limit is None else client_input_limit
    )
    call_limit = policy.max_provider_calls if client_call_limit is None else client_call_limit
    if (
        type(text_limit) is not int
        or text_limit < 0
        or text_limit > policy.text_token_limit
        or type(input_limit) is not int
        or input_limit < 0
        or input_limit > policy.max_conservative_input_tokens
        or type(call_limit) is not int
        or call_limit < 0
        or call_limit > policy.max_provider_calls
    ):
        return ConservativeBudgetEvaluation(
            CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE, False, None, None, fingerprint
        )
    contents: list[str] = []
    for message in messages:
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            return ConservativeBudgetEvaluation(
                CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE, False, None, None, fingerprint
            )
        contents.append(message["content"])
    if not any("json" in text.lower() for text in contents):
        return ConservativeBudgetEvaluation(
            CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE, False, None, None, fingerprint
        )
    try:
        if not counter.supports(provider_id, policy.model_id):
            raise ValueError
        text_tokens = counter.count_text_tokens(tuple(contents))
    except Exception:
        text_tokens = None
    if type(text_tokens) is not int or text_tokens < 0:
        return ConservativeBudgetEvaluation(
            CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE, False, None, None, fingerprint
        )
    try:
        estimate = policy.estimate_input(text_tokens, len(messages))
    except Exception:
        return ConservativeBudgetEvaluation(
            CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE, False, None, None, fingerprint
        )
    allowed = (
        text_tokens <= text_limit
        and estimate <= input_limit
        and estimate + policy.max_output_tokens <= policy.max_total_tokens
        and call_limit >= 1
    )
    return ConservativeBudgetEvaluation(
        CONSERVATIVE_TOKEN_BUDGET_AVAILABLE if allowed else CONSERVATIVE_TOKEN_BUDGET_EXCEEDED,
        allowed,
        text_tokens,
        estimate,
        fingerprint,
    )


def evaluate_conservative_request(
    *,
    canonical_payload: dict[str, Any],
    provider_id: str,
    policy: ConservativeTokenBudgetPolicy,
    counter: ConservativeTextCounter,
    client_text_limit: Optional[int] = None,
    client_input_limit: Optional[int] = None,
    client_call_limit: Optional[int] = None,
) -> ConservativeBudgetEvaluation:
    """Public fail-closed boundary; never expose malformed-input exceptions."""
    try:
        return _evaluate_conservative_request(
            canonical_payload=canonical_payload,
            provider_id=provider_id,
            policy=policy,
            counter=counter,
            client_text_limit=client_text_limit,
            client_input_limit=client_input_limit,
            client_call_limit=client_call_limit,
        )
    except Exception:
        return ConservativeBudgetEvaluation(
            CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE,
            False,
            None,
            None,
            _UNSERIALIZABLE_PAYLOAD_HASH,
        )
