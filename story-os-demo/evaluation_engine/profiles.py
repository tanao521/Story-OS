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


def profiles() -> list[dict[str, Any]]:
    return [chapter_default_profile()]


def profile(profile_id: str) -> dict[str, Any] | None:
    return next((item for item in profiles() if item["profile_id"] == profile_id), None)
