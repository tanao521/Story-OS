"""Small read-only scope classification helper for Phase 0D6-B authority scans."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


CURRENT = "current"
UNRELATED = "unrelated"
AMBIGUOUS = "ambiguous"
CORRUPT = "corrupt"


@dataclass(frozen=True)
class ScopeTarget:
    project_id: str
    timeline_id: str
    branch_id: str
    previous_chapter_id: int | None = None
    successor_chapter_id: int | None = None


def classify_scope_fields(
    fields: Mapping[str, Any],
    target: ScopeTarget,
    *,
    required: tuple[str, ...] = ("project_id",),
) -> str:
    """Classify already-extracted scope fields without reading or writing state.

    A mismatch is safely unrelated only after every supplied field is valid.
    Missing required fields are ambiguous, while malformed values are corrupt.
    Callers can use a narrower required set for orphan records whose schema
    carries only project/timeline scope.
    """
    if not isinstance(fields, Mapping):
        return CORRUPT
    validators = {
        "project_id": lambda value: isinstance(value, str) and bool(value),
        "timeline_id": lambda value: isinstance(value, str) and bool(value),
        "branch_id": lambda value: isinstance(value, str) and bool(value),
        "previous_chapter_id": lambda value: type(value) is int and value > 0,
        "successor_chapter_id": lambda value: type(value) is int and value > 0,
    }
    expected = {
        "project_id": target.project_id,
        "timeline_id": target.timeline_id,
        "branch_id": target.branch_id,
        "previous_chapter_id": target.previous_chapter_id,
        "successor_chapter_id": target.successor_chapter_id,
    }
    for key, value in fields.items():
        if key not in validators:
            continue
        if value is None:
            return CORRUPT
        if not validators[key](value):
            return CORRUPT
    for key, value in fields.items():
        if key not in validators:
            continue
        if expected[key] is not None and value != expected[key]:
            return UNRELATED
    for key in required:
        if key not in fields:
            return AMBIGUOUS
    return CURRENT
