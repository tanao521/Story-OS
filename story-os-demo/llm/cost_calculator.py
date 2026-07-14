"""Deterministic, optional token cost estimates.  Unknown prices remain unknown."""
from __future__ import annotations

from typing import Any


def estimate_tokens(text: str) -> int:
    """Conservative local estimate; CJK text is approximately one token per character."""
    return max(1, int(len(str(text or "")) / 1.8))


def calculate_cost(usage: dict[str, Any], pricing: dict[str, Any] | None) -> dict[str, Any]:
    prompt = int(usage.get("prompt_tokens", 0) or 0)
    completion = int(usage.get("completion_tokens", 0) or 0)
    total = int(usage.get("total_tokens", prompt + completion) or 0)
    if not pricing:
        return {"currency": "USD", "amount": None, "known": False, "prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}
    try:
        amount = prompt / 1_000_000 * float(pricing.get("input_per_million", 0)) + completion / 1_000_000 * float(pricing.get("output_per_million", 0))
    except (TypeError, ValueError):
        amount = None
    return {"currency": str(pricing.get("currency", "USD")), "amount": round(amount, 8) if amount is not None else None, "known": amount is not None, "prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}
