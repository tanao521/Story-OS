"""Public, serialisable data structures for unified narrative evaluation."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class EvaluationTarget:
    target_type: str
    chapter_number: int | None = None
    source_type: str = ""
    source_version: int | None = None

    def reference(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value not in (None, "")}


@dataclass
class EvaluationEvidence:
    evidence_id: str
    source_type: str
    source_ref: str
    summary: str
    reliability: float
    location: dict[str, Any] = field(default_factory=dict)
    captured_at: str = ""


@dataclass
class EvaluationIssue:
    issue_id: str
    issue_type: str
    severity: str
    title: str
    description: str
    source_adapter: str
    fixability: str = "not_actionable"
    evidence_refs: list[str] = field(default_factory=list)
    location_refs: list[dict[str, Any]] = field(default_factory=list)
    affected_dimensions: list[str] = field(default_factory=list)
    suggestion: str = ""
    fingerprint: str = ""


@dataclass
class DimensionScore:
    dimension_id: str
    display_name: str
    weight: float
    score: float | None = None
    confidence: float = 0.0
    status: str = "insufficient_evidence"
    source_type: str = "existing_report"
    evidence: list[EvaluationEvidence] = field(default_factory=list)
    issues: list[EvaluationIssue] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


@dataclass
class GateResult:
    status: str = "attention"
    reasons: list[str] = field(default_factory=list)


def public(value: Any) -> Any:
    """Convert nested evaluation dataclasses to JSON-safe dictionaries."""
    if hasattr(value, "__dataclass_fields__"):
        return {key: public(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [public(item) for item in value]
    if isinstance(value, dict):
        return {str(key): public(item) for key, item in value.items()}
    return value
