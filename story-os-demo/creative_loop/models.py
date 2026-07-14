"""Shared serialisation helpers and lifecycle constants for the creative loop."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

ISSUE_SEVERITIES = {"critical", "high", "medium", "low", "info"}
ISSUE_STATUSES = {"open", "resolved", "ignored"}
PROPOSAL_STATUSES = {"pending", "reviewing", "modified", "accepted", "partially_accepted", "rejected", "expired", "applied", "cancelled"}
EXPERIMENT_STATUSES = {"draft", "generating", "evaluating", "waiting_author", "selected", "archived", "failed", "cancelled"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def score_100(value: Any) -> int | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if 0 <= number <= 1:
        number *= 100
    return max(0, min(100, round(number)))
