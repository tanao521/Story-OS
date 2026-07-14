"""Explain priority and surface conflicts without choosing for the author."""
from __future__ import annotations

from typing import Any


def resolve_preferences(author_preferences: list[dict[str, Any]], project_rules: list[str]) -> dict[str, Any]:
    explicit = [str(x.get("content", "")) for x in author_preferences if x.get("priority") == "author_explicit"]
    conflicts = []
    for author_rule in explicit:
        for project_rule in project_rules:
            if ("慢" in author_rule and any(word in project_rule for word in ("快速", "高密度"))) or ("第一人称" in author_rule and "第一人称" not in project_rule and "不要" in author_rule):
                conflicts.append({"author_preference": author_rule, "project_rule": project_rule, "choices": ["保持作者风格", "优化商业节奏", "折中方案"]})
    return {"priority_order": ["author_explicit", "project_rule", "chapter_requirement", "ai_default"], "author_rules": explicit, "conflicts": conflicts, "auto_override": False}
