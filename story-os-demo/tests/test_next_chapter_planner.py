from __future__ import annotations

from typing import Any

from core.blueprint_generator import generate_blueprint
from core.character_builder import generate_characters
from core.next_chapter_planner import (
    plan_next_chapter,
    render_next_chapter_plan_markdown,
)
from core.setup_wizard import build_initial_state
from core.world_builder import generate_world_bible


def make_story_spec() -> dict[str, Any]:
    return {
        "title": "未命名小说",
        "genre": "末世",
        "length_type": "长篇",
        "target_word_count": 300000,
        "world_style": "近未来末世",
        "tone": "灰暗但不绝望",
        "writing_style": "电影感",
        "narration": "第三人称有限视角",
        "character_structure": "群像文",
        "romance_level": "轻微",
        "focus": ["生存", "人物成长"],
        "avoid": ["不要流水账"],
        "anti_ai_style_rules": ["减少破折号"],
        "need_outline": True,
    }


def make_inputs(current_chapter: int = 0) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    story_spec = make_story_spec()
    blueprint = generate_blueprint(story_spec)
    state = build_initial_state(story_spec)
    state["current_chapter"] = current_chapter
    characters = generate_characters(story_spec, blueprint, state)
    world_bible = generate_world_bible(story_spec, blueprint, state)
    return story_spec, blueprint, characters, world_bible, state


def test_plan_next_chapter_returns_dict() -> None:
    story_spec, blueprint, characters, world_bible, state = make_inputs()

    plan = plan_next_chapter(story_spec, blueprint, characters, world_bible, state)

    assert isinstance(plan, dict)


def test_chapter_id_is_current_chapter_plus_one() -> None:
    story_spec, blueprint, characters, world_bible, state = make_inputs(8)

    plan = plan_next_chapter(story_spec, blueprint, characters, world_bible, state)

    assert plan["chapter_id"] == 9


def test_plan_contains_scene_plan() -> None:
    story_spec, blueprint, characters, world_bible, state = make_inputs()

    plan = plan_next_chapter(story_spec, blueprint, characters, world_bible, state)

    assert plan["scene_plan"]


def test_scene_plan_count_is_between_two_and_four() -> None:
    story_spec, blueprint, characters, world_bible, state = make_inputs()

    plan = plan_next_chapter(story_spec, blueprint, characters, world_bible, state)

    assert 2 <= len(plan["scene_plan"]) <= 4


def test_plan_contains_conflict_design() -> None:
    story_spec, blueprint, characters, world_bible, state = make_inputs()

    plan = plan_next_chapter(story_spec, blueprint, characters, world_bible, state)

    assert "conflict_design" in plan


def test_plan_contains_pacing_design() -> None:
    story_spec, blueprint, characters, world_bible, state = make_inputs()

    plan = plan_next_chapter(story_spec, blueprint, characters, world_bible, state)

    assert "pacing_design" in plan


def test_plan_contains_climax_design() -> None:
    story_spec, blueprint, characters, world_bible, state = make_inputs()

    plan = plan_next_chapter(story_spec, blueprint, characters, world_bible, state)

    assert "climax_design" in plan


def test_first_chapter_climax_level_is_minor() -> None:
    story_spec, blueprint, characters, world_bible, state = make_inputs(0)

    plan = plan_next_chapter(story_spec, blueprint, characters, world_bible, state)

    assert plan["climax_design"]["climax_level"] == "minor"


def test_fifth_chapter_climax_level_is_minor() -> None:
    story_spec, blueprint, characters, world_bible, state = make_inputs(4)

    plan = plan_next_chapter(story_spec, blueprint, characters, world_bible, state)

    assert plan["chapter_id"] == 5
    assert plan["climax_design"]["climax_level"] == "minor"


def test_tenth_chapter_climax_level_is_medium() -> None:
    story_spec, blueprint, characters, world_bible, state = make_inputs(9)

    plan = plan_next_chapter(story_spec, blueprint, characters, world_bible, state)

    assert plan["chapter_id"] == 10
    assert plan["climax_design"]["climax_level"] == "medium"


def test_render_next_chapter_plan_markdown_contains_title() -> None:
    story_spec, blueprint, characters, world_bible, state = make_inputs()
    plan = plan_next_chapter(story_spec, blueprint, characters, world_bible, state)

    markdown = render_next_chapter_plan_markdown(plan)

    assert "# 下一章计划" in markdown
