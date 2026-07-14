"""Gate status is independent from aggregate score."""
from __future__ import annotations

from .models import EvaluationIssue, GateResult


BLOCKING_TYPES = {"canon_conflict", "continuity_knowledge_boundary", "cross_project_reference", "planning_reference_broken", "source_invalid"}


def evaluate_gates(issues: list[EvaluationIssue]) -> GateResult:
    invalid = [item for item in issues if item.issue_type in {"cross_project_reference", "source_invalid"}]
    blocked = [item for item in issues if item.severity == "blocking" or item.issue_type in BLOCKING_TYPES]
    high = [item for item in issues if item.severity == "high"]
    if invalid:
        return GateResult("invalid", [item.title for item in invalid])
    if blocked:
        return GateResult("blocked", [item.title for item in blocked])
    if high:
        return GateResult("attention", [item.title for item in high])
    return GateResult("pass", [])
