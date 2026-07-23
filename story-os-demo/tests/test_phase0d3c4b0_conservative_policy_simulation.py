"""Pure-offline B0 policy simulation.

This is design evidence only.  It deliberately does not import or register a
production counter and its inputs are Layer-A fixture token counts, not claims
about DeepSeek V4 request or billed-token exactness.
"""
from __future__ import annotations

import hashlib
import json
import math
import socket
from dataclasses import asdict, dataclass, replace


@dataclass(frozen=True)
class StrictPolicy:
    policy_id: str = "deepseek-v4-flash-conservative-strict"
    policy_revision: str = "owner-proposal-1"
    provider_id: str = "deepseek"
    model_id: str = "deepseek-v4-flash"
    text_counter_id: str = "deepseek-v3-archive-layer-a"
    text_counter_revision: str = "sha256-c954ca6f6e54"
    text_token_limit: int = 2048
    fixed_base_reserve: int = 512
    per_message_reserve: int = 64
    uncertainty_ratio: float = 0.25
    structured_output_reserve: int = 256
    thinking_reserve: int = 0
    max_conservative_input_tokens: int = 3584
    max_output_tokens: int = 512
    max_total_tokens: int = 4096
    max_provider_calls: int = 1
    timeout_seconds: int = 60
    post_call_reconciliation_required: bool = True
    cost_estimate_available: bool = False
    retry_policy: str = "0"
    fallback_policy: str = "none"
    thinking_mode: str = "disabled"
    structured_output_mode: str = "json_object"


def estimate(policy: StrictPolicy, *, text_tokens: int, message_count: int) -> int:
    if policy.provider_id != "deepseek" or policy.model_id != "deepseek-v4-flash":
        raise ValueError("unknown model")
    if text_tokens < 0 or message_count < 1:
        raise ValueError("invalid input")
    return (
        text_tokens
        + policy.fixed_base_reserve
        + policy.per_message_reserve * message_count
        + math.ceil(text_tokens * policy.uncertainty_ratio)
        + policy.structured_output_reserve
        + policy.thinking_reserve
    )


def decision(policy: StrictPolicy, *, text_tokens: int, message_count: int = 2) -> str:
    if text_tokens > policy.text_token_limit:
        return "CONSERVATIVE_TOKEN_BUDGET_EXCEEDED"
    conservative = estimate(
        policy, text_tokens=text_tokens, message_count=message_count
    )
    if (
        conservative > policy.max_conservative_input_tokens
        or conservative + policy.max_output_tokens > policy.max_total_tokens
    ):
        return "CONSERVATIVE_TOKEN_BUDGET_EXCEEDED"
    return "CONSERVATIVE_TOKEN_BUDGET_AVAILABLE"


def fingerprint(policy: StrictPolicy, *, text_tokens: int, message_count: int) -> str:
    payload = {
        "policy": asdict(policy),
        "text_tokens": text_tokens,
        "message_count": message_count,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def client_effective_limit(policy: StrictPolicy, requested: int | None) -> int:
    if requested is None:
        return policy.text_token_limit
    return min(policy.text_token_limit, max(0, requested))


LAYER_A_FIXTURES = {
    "short_chinese": 2,
    "short_english": 2,
    "mixed_emoji": 7,
    "multiple_newlines": 8,
    "json_text": 13,
    "long_persona_prompt": 800,
    "long_chapter_excerpt": 2048,
}


def test_strict_hybrid_policy_is_deterministic_for_all_offline_fixtures():
    policy = StrictPolicy()
    first = {
        name: (
            estimate(policy, text_tokens=count, message_count=2),
            decision(policy, text_tokens=count),
        )
        for name, count in LAYER_A_FIXTURES.items()
    }
    second = {
        name: (
            estimate(policy, text_tokens=count, message_count=2),
            decision(policy, text_tokens=count),
        )
        for name, count in LAYER_A_FIXTURES.items()
    }
    assert first == second
    assert all(code == "CONSERVATIVE_TOKEN_BUDGET_AVAILABLE" for _, code in first.values())
    assert first["long_chapter_excerpt"][0] == 3456


def test_policy_revision_changes_fingerprint_without_changing_fixture():
    policy = StrictPolicy()
    changed = replace(policy, policy_revision="owner-proposal-2")
    assert fingerprint(policy, text_tokens=800, message_count=2) != fingerprint(
        changed, text_tokens=800, message_count=2
    )


def test_client_can_only_lower_server_owned_text_limit():
    policy = StrictPolicy()
    assert client_effective_limit(policy, None) == 2048
    assert client_effective_limit(policy, 9999) == 2048
    assert client_effective_limit(policy, 1024) == 1024


def test_over_budget_and_unknown_model_fail_closed_before_provider():
    provider_calls = 0
    policy = StrictPolicy()
    assert decision(policy, text_tokens=2049) == "CONSERVATIVE_TOKEN_BUDGET_EXCEEDED"
    assert provider_calls == 0
    try:
        estimate(
            replace(policy, model_id="unknown"),
            text_tokens=2,
            message_count=2,
        )
    except ValueError as exc:
        assert str(exc) == "unknown model"
    else:
        raise AssertionError("unknown model must fail closed")
    assert provider_calls == 0


def test_five_personas_use_five_independent_child_budgets():
    policy = StrictPolicy()
    child_results = [
        decision(policy, text_tokens=LAYER_A_FIXTURES["long_persona_prompt"])
        for _ in range(5)
    ]
    assert child_results == ["CONSERVATIVE_TOKEN_BUDGET_AVAILABLE"] * 5
    assert policy.max_provider_calls == 1


def test_structured_and_thinking_reserves_are_explicit_not_hidden_facts():
    policy = StrictPolicy()
    base = estimate(policy, text_tokens=13, message_count=2)
    no_json = estimate(
        replace(policy, structured_output_reserve=0),
        text_tokens=13,
        message_count=2,
    )
    hypothetical_thinking = estimate(
        replace(policy, thinking_mode="enabled", thinking_reserve=1024),
        text_tokens=13,
        message_count=2,
    )
    assert base - no_json == 256
    assert hypothetical_thinking - base == 1024
    assert policy.thinking_mode == "disabled"
    assert policy.thinking_reserve == 0


def test_simulation_does_not_open_network(monkeypatch):
    attempts: list[tuple] = []

    def deny(*args, **kwargs):
        attempts.append((args, kwargs))
        raise AssertionError("network forbidden")

    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)
    policy = StrictPolicy()
    assert decision(policy, text_tokens=800) == "CONSERVATIVE_TOKEN_BUDGET_AVAILABLE"
    assert attempts == []
