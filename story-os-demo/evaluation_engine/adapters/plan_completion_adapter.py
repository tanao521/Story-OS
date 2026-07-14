from __future__ import annotations

from typing import Any
from .common import evidence


def adapt(plan: dict[str, Any], source_ref: str) -> dict[str, Any]:
    if not plan or not (plan.get("chapter_goal") or plan.get("goal") or plan.get("objectives")): return {}
    return {"score": None, "confidence": .35, "source_type": "next_chapter_plan", "evidence": [evidence("next_chapter_plan", source_ref, "Chapter plan is available but no existing completion report exists.", reliability=.5)], "issues": [], "suggestions": ["尚无既有计划完成度检查结果；本报告不新增 LLM 判断。"]}
