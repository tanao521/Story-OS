from __future__ import annotations

from typing import Any


REQUIRED_STORY_SPEC_FIELDS = [
    "title",
    "genre",
    "length_type",
    "target_word_count",
    "world_style",
    "tone",
    "writing_style",
    "narration",
    "character_structure",
    "romance_level",
    "focus",
    "avoid",
    "anti_ai_style_rules",
    "need_outline",
]


def validate_story_spec(story_spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    for field_name in REQUIRED_STORY_SPEC_FIELDS:
        if field_name not in story_spec:
            errors.append(f"缺少必填字段：{field_name}")

    return errors
