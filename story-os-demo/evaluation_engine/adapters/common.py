from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from evaluation_engine.models import EvaluationEvidence, EvaluationIssue


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fingerprint(*parts: object) -> str:
    return sha256("|".join(str(item) for item in parts).encode("utf-8")).hexdigest()[:20]


def evidence(source_type: str, source_ref: str, summary: str, *, reliability: float = 0.8, location: dict[str, Any] | None = None) -> EvaluationEvidence:
    return EvaluationEvidence(
        evidence_id=fingerprint(source_type, source_ref, summary), source_type=source_type,
        source_ref=source_ref, summary=summary, reliability=reliability,
        location=location or {}, captured_at=now(),
    )


def fixability(issue_type: str, severity: str) -> str:
    if issue_type in {"canon_conflict", "continuity_knowledge_boundary", "character_state_conflict", "planning_reference_broken"}:
        return "author_decision_required"
    if severity in {"low", "medium"} and issue_type in {"repetition", "style_naturalness", "readability", "scene_dialogue", "hook_strength", "pacing"}:
        return "auto_low_risk"
    return "not_actionable"


def issue(source: str, raw: Any, *, dimension: str, default_type: str, default_severity: str = "medium") -> EvaluationIssue:
    data = raw if isinstance(raw, dict) else {"message": str(raw)}
    issue_type = str(data.get("type") or data.get("issue_type") or default_type)
    severity = str(data.get("severity") or default_severity).lower()
    if severity == "warning": severity = "medium"
    if severity == "fail": severity = "high"
    if severity not in {"blocking", "high", "medium", "low", "info"}: severity = default_severity
    title = str(data.get("title") or data.get("message") or data.get("summary") or issue_type)
    return EvaluationIssue(
        issue_id=fingerprint(source, issue_type, title), issue_type=issue_type, severity=severity,
        title=title, description=str(data.get("description") or title), source_adapter=source,
        fixability=fixability(issue_type, severity), affected_dimensions=[dimension],
        suggestion=str(data.get("suggestion") or ""), fingerprint=fingerprint(source, issue_type, title),
    )
