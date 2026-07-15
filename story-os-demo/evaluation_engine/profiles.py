"""Versioned system profiles; no per-page configuration state is required."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


CHAPTER_DIMENSIONS = (
    ("plan_completion", "本章目标完成度", 0.12),
    ("continuity", "剧情连贯性", 0.15),
    ("character_consistency", "人物一致性", 0.12),
    ("causal_logic", "因果逻辑", 0.12),
    ("plot_progression", "情节推进力", 0.10),
    ("pacing_tension", "节奏与张力", 0.10),
    ("information_control", "信息控制", 0.08),
    ("prose_readability", "文笔与可读性", 0.08),
    ("scene_dialogue", "场景与对话表现", 0.07),
    ("ending_drive", "章末驱动力", 0.06),
)

PLANNING_DIMENSIONS = (
    ("structural_completeness", "战略与结构完整度", .12),
    ("causal_dependency", "因果与依赖一致性", .16),
    ("plot_progression", "主线推进覆盖度", .14),
    ("pacing_tension", "节奏与张力分布", .14),
    ("character_arc", "角色弧光完整度", .12),
    ("foreshadowing", "伏笔闭环度", .12),
    ("chapter_load", "章节承载均衡度", .10),
    ("milestone_alignment", "里程碑与契约对齐度", .10),
)


def chapter_default_profile() -> dict[str, Any]:
    return {
        "profile_id": "chapter-default-v1",
        "name": "章节默认评分",
        "target_type": "chapter_draft",
        "version": 1,
        "dimensions": [
            {"dimension_id": key, "display_name": name, "weight": weight}
            for key, name, weight in CHAPTER_DIMENSIONS
        ],
        "gate_rules": ["canon_conflict", "knowledge_boundary", "cross_project_reference", "source_invalid"],
        "minimum_confidence": 0.6,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def planning_default_profile() -> dict[str, Any]:
    return {
        "profile_id": "planning-default-v1", "name": "长篇规划综合评估",
        "target_type": "planning", "version": 1,
        "dimensions": [{"dimension_id": key, "display_name": name, "weight": weight} for key, name, weight in PLANNING_DIMENSIONS],
        "gate_rules": ["dependency_cycle", "hard_dependency_order", "payoff_before_plant", "reanchor_required", "locked_contract_conflict", "invalid_reference"],
        "minimum_confidence": .6, "created_at": datetime.now(timezone.utc).isoformat(),
        "scoring_rules_version": "planning-rubric-v1",
    }


def profiles() -> list[dict[str, Any]]:
    return [chapter_default_profile(), planning_default_profile()]


def profile(profile_id: str) -> dict[str, Any] | None:
    return next((item for item in profiles() if item["profile_id"] == profile_id), None)
