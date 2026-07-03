from __future__ import annotations

from typing import Any

import config
from llm.deepseek_client import DeepSeekClient, DeepSeekError
from llm.json_utils import deep_merge_missing, ensure_required_keys
from llm.prompts import (
    STORY_SPEC_SCHEMA,
    build_blueprint_prompt,
    build_next_chapter_plan_prompt,
    build_story_spec_prompt,
)


BLUEPRINT_REQUIRED_KEYS = [
    "title",
    "blueprint_version",
    "genre",
    "length_type",
    "target_word_count",
    "core_premise",
    "main_arc",
    "core_conflict",
    "ending_direction",
    "world_direction",
    "story_phases",
    "initial_foreshadow_pool",
    "rolling_generation_policy",
]

PLAN_REQUIRED_KEYS = [
    "plan_version",
    "chapter_id",
    "chapter_title",
    "estimated_word_count",
    "chapter_goal",
    "phase_position",
    "required_context",
    "scene_plan",
    "conflict_design",
    "pacing_design",
    "climax_design",
    "voice_requirements",
    "style_requirements",
    "continuity_constraints",
    "state_updates_expected",
]


def should_use_deepseek_for_planning(local_config: dict[str, Any]) -> bool:
    return bool(local_config.get("use_deepseek_for_planning")) and bool(config.DEEPSEEK_API_KEY)


def create_deepseek_client() -> DeepSeekClient:
    return DeepSeekClient(
        api_key=config.DEEPSEEK_API_KEY,
        model=config.DEEPSEEK_MODEL,
        base_url=config.DEEPSEEK_BASE_URL,
    )


def generate_story_spec_with_deepseek(
    raw_answers: dict[str, Any],
    mock_story_spec: dict[str, Any],
    client: DeepSeekClient,
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    try:
        data = client.chat_json(build_story_spec_prompt(raw_answers))
    except DeepSeekError as exc:
        return mock_story_spec, [f"DeepSeek story_spec 失败，已使用 mock：{exc}"]
    missing = ensure_required_keys(data, list(STORY_SPEC_SCHEMA.keys()))
    if missing:
        warnings.append(f"DeepSeek story_spec 缺少字段，已用 mock 补齐：{', '.join(missing)}")
    return deep_merge_missing(mock_story_spec, data), warnings


def generate_blueprint_with_deepseek(
    story_spec: dict[str, Any],
    mock_blueprint: dict[str, Any],
    client: DeepSeekClient,
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    try:
        data = client.chat_json(build_blueprint_prompt(story_spec))
    except DeepSeekError as exc:
        return mock_blueprint, [f"DeepSeek blueprint 失败，已使用 mock：{exc}"]
    if "chapters" in data:
        data.pop("chapters", None)
        warnings.append("DeepSeek blueprint 输出 chapters 字段，已删除。")
    missing = ensure_required_keys(data, BLUEPRINT_REQUIRED_KEYS)
    if missing:
        warnings.append(f"DeepSeek blueprint 缺少字段，已用 mock 补齐：{', '.join(missing)}")
    merged = deep_merge_missing(mock_blueprint, data)
    policy = merged.setdefault("rolling_generation_policy", {})
    policy["plan_next_chapter_only"] = True
    policy.setdefault("mode", "chapter_by_chapter")
    merged["blueprint_version"] = str(merged.get("blueprint_version", "1.0"))
    return merged, warnings


def plan_next_chapter_with_deepseek(
    story_spec: dict[str, Any],
    blueprint: dict[str, Any],
    characters: dict[str, Any],
    world_bible: dict[str, Any],
    state: dict[str, Any],
    working_context: dict[str, Any] | None,
    mock_plan: dict[str, Any],
    client: DeepSeekClient,
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    state_snapshot = _state_snapshot(state)
    try:
        data = client.chat_json(
            build_next_chapter_plan_prompt(
                story_spec,
                blueprint,
                characters,
                world_bible,
                state_snapshot,
                working_context,
            )
        )
    except DeepSeekError as exc:
        return mock_plan, [f"DeepSeek plan-next 失败，已使用 mock：{exc}"]
    missing = ensure_required_keys(data, PLAN_REQUIRED_KEYS)
    if missing:
        warnings.append(f"DeepSeek plan-next 缺少字段，已用 mock 补齐：{', '.join(missing)}")
    merged = deep_merge_missing(mock_plan, data)
    expected_chapter_id = int(state.get("current_chapter", 0) or 0) + 1
    if merged.get("chapter_id") != expected_chapter_id:
        warnings.append("DeepSeek plan-next chapter_id 错误，已强制修正。")
    merged["chapter_id"] = expected_chapter_id
    if not merged.get("scene_plan"):
        merged["scene_plan"] = mock_plan.get("scene_plan", [])
        warnings.append("DeepSeek plan-next scene_plan 为空，已使用 mock scene_plan。")
    merged["plan_version"] = str(merged.get("plan_version", "1.0"))
    return merged, warnings


def _state_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    foreshadows = state.get("foreshadows", [])
    return {
        "current_chapter": state.get("current_chapter", 0),
        "current_stage": state.get("current_stage", ""),
        "characters": state.get("characters", {}),
        "world": state.get("world", {}),
        "plot": state.get("plot", {}),
        "open_foreshadows": [
            item
            for item in foreshadows
            if isinstance(item, dict) and item.get("status") in {"open", "planned"}
        ] if isinstance(foreshadows, list) else [],
        "memory_policy": state.get("memory_policy", {}),
    }
