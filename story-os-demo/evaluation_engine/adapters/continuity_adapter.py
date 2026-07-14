from __future__ import annotations

from typing import Any
from .common import evidence, issue


def adapt(report: dict[str, Any], source_ref: str) -> dict[str, dict[str, Any]]:
    if not report: return {}
    try: score = max(0.0, min(100.0, float(report.get("score")) * 100))
    except (TypeError, ValueError): return {}
    raw_issues = report.get("issues", []) if isinstance(report.get("issues"), list) else []
    severity = "blocking" if str(report.get("verdict")) == "fail" else "medium"
    issues = [issue("continuity", {"message": item, "severity": severity, "type": "canon_conflict" if str(report.get("verdict")) == "fail" else "continuity"}, dimension="continuity", default_type="continuity", default_severity=severity) for item in raw_issues]
    payload = {"score": score, "confidence": .9, "source_type": "continuity_check", "evidence": [evidence("continuity_check", source_ref, str(report.get("summary", "existing continuity report")), reliability=.9)], "issues": issues, "suggestions": [str(item) for item in report.get("suggestions", []) if str(item).strip()]}
    return {"continuity": payload, "causal_logic": {**payload, "confidence": .72}}
