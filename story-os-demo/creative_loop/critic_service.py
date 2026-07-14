"""Structured critic compiled from persisted evidence rather than autonomous edits."""
from __future__ import annotations

from typing import Any


class CriticService:
    def critique(self, reflection: dict[str, Any], health: dict[str, Any], issues: list[dict[str, Any]]) -> dict[str, Any]:
        open_issues = [item for item in issues if item.get("status") == "open"]
        ranked = sorted(open_issues, key=lambda item: {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}.get(item.get("severity"), 5))
        return {"strengths": reflection.get("strengths", []), "weaknesses": [item.get("title") for item in ranked], "priority_issues": [{"issue_id": item["issue_id"], "title": item["title"], "severity": item["severity"], "evidence": item.get("evidence", [])} for item in ranked[:5]], "preserve_elements": reflection.get("strengths", []), "revision_recommendations": [suggestion for item in ranked[:3] for suggestion in item.get("suggestions", [])], "future_strategy_recommendations": [suggestion for item in ranked[:3] for suggestion in item.get("suggestions", [])], "health_reference": health.get("health_id"), "disclaimer": "批评仅用于辅助作者判断，不会修改正史、计划或设定。"}
