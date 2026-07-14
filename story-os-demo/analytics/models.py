"""Typed names shared by the analytics package.

The persisted payloads intentionally remain ordinary JSON dictionaries so a
writer can inspect and edit them outside the application.
"""

from typing import Literal, TypedDict


MetricSource = Literal["rule_based", "ai_simulation", "manual_input"]


class StoryScore(TypedDict):
    total: int
    hook_score: int
    emotion_score: int
    conflict_score: int
    character_score: int
    world_score: int
    pacing_score: int
    ending_hook_score: int
    weak_points: list[str]
    suggestions: list[str]
    source: MetricSource
