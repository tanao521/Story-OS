"""Hard boundaries for Stage 15.2A restricted quality refreshes."""
from __future__ import annotations

from typing import Any

POLICY_ID = "chapter-low-risk-v1"
ALLOWED_ACTIONS = {
    "compress", "clarify", "smooth_transition", "remove_repetition",
    "tighten_dialogue", "strengthen_existing_emotion", "improve_readability",
    "strengthen_existing_hook", "add_existing_fact_reminder",
}
PROHIBITED_ACTIONS = {"rewrite_chapter", "change_outcome", "change_title", "add_new_fact", "add_named_entity", "change_world_setting"}
BUDGETS = {
    "conservative": {"max_changed_paragraphs": 4, "max_changed_ratio": .06, "max_added_ratio": .04, "max_deleted_ratio": .04, "max_patch_count": 6},
    "standard": {"max_changed_paragraphs": 8, "max_changed_ratio": .12, "max_added_ratio": .08, "max_deleted_ratio": .08, "max_patch_count": 10},
    "enhanced": {"max_changed_paragraphs": 12, "max_changed_ratio": .18, "max_added_ratio": .12, "max_deleted_ratio": .12, "max_patch_count": 10},
}


class ImprovementPolicyError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def budget(name: str = "standard") -> dict[str, Any]:
    value = BUDGETS.get(str(name), BUDGETS["standard"])
    return {"profile": str(name) if name in BUDGETS else "standard", **value,
            "disallow": ["title", "ending", "facts", "new_named_entity", "new_world_setting"]}


def selectable_issues(report: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = report.get("priority_issues", []) if isinstance(report.get("priority_issues"), list) else []
    selectable, disabled = [], []
    for item in rows:
        if not isinstance(item, dict):
            continue
        target = {key: item.get(key) for key in ("issue_id", "title", "description", "severity", "fixability", "location_refs", "evidence_refs", "suggestion", "affected_dimensions")}
        if item.get("fixability") == "auto_low_risk" and item.get("severity") in {"high", "medium", "low"}:
            selectable.append(target)
        else:
            target["disabled_reason"] = "需要作者决定，不能用于受限自动修订。"
            disabled.append(target)
    return selectable, disabled


def validate_actions(patches: list[dict[str, Any]], limits: dict[str, Any]) -> None:
    if not patches or len(patches) > int(limits["max_patch_count"]):
        raise ImprovementPolicyError("IMPROVEMENT_BUDGET_EXCEEDED", "Patch count exceeds the selected improvement budget.")
    for patch in patches:
        action = str(patch.get("action", ""))
        if action in PROHIBITED_ACTIONS or action not in ALLOWED_ACTIONS:
            raise ImprovementPolicyError("IMPROVEMENT_ACTION_FORBIDDEN", f"Action is not allowed: {action}")
        if not str(patch.get("anchor", "")).strip():
            raise ImprovementPolicyError("IMPROVEMENT_PLAN_INVALID", "Every patch requires a source anchor.")
