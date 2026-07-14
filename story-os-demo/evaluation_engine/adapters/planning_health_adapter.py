from __future__ import annotations

from typing import Any
from .common import evidence, issue


def adapt(health: dict[str, Any]) -> tuple[list[Any], list[Any]]:
    evidence_items, issues = [], []
    for name, payload in health.items():
        if not isinstance(payload, dict):
            continue
        status = str(payload.get("status") or payload.get("overall_status") or payload.get("health") or "unknown").lower()
        evidence_items.append(evidence("planning_health", name, f"{name}: {status}", reliability=.75))
        if status in {"error", "invalid", "blocked", "fail"}:
            issues.append(issue("planning_health", {"type": "planning_reference_broken", "severity": "blocking", "title": f"规划健康异常：{name}"}, dimension="plan_completion", default_type="planning_reference_broken", default_severity="blocking"))
        elif status in {"warning", "attention"}:
            issues.append(issue("planning_health", {"type": "planning_health_attention", "severity": "high", "title": f"规划健康需要关注：{name}"}, dimension="plan_completion", default_type="planning_health_attention", default_severity="high"))
    return evidence_items, issues
