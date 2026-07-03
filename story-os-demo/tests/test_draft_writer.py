from __future__ import annotations

from typing import Any

from core.blueprint_generator import generate_blueprint
from core.character_builder import generate_characters
from core.draft_writer import (
    clean_ai_style,
    render_draft_markdown,
    self_check_draft,
    write_chapter_draft,
)
from core.next_chapter_planner import plan_next_chapter
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


def make_inputs() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    story_spec = make_story_spec()
    blueprint = generate_blueprint(story_spec)
    state = build_initial_state(story_spec)
    characters = generate_characters(story_spec, blueprint, state)
    world_bible = generate_world_bible(story_spec, blueprint, state)
    chapter_plan = plan_next_chapter(story_spec, blueprint, characters, world_bible, state)
    return story_spec, blueprint, characters, world_bible, state, chapter_plan


def test_write_chapter_draft_returns_dict() -> None:
    story_spec, blueprint, characters, world_bible, state, chapter_plan = make_inputs()

    draft = write_chapter_draft(story_spec, blueprint, characters, world_bible, state, chapter_plan)

    assert isinstance(draft, dict)


def test_write_chapter_draft_contains_draft_text() -> None:
    story_spec, blueprint, characters, world_bible, state, chapter_plan = make_inputs()

    draft = write_chapter_draft(story_spec, blueprint, characters, world_bible, state, chapter_plan)

    assert draft["draft_text"]


def test_draft_text_length_is_more_than_500_chars() -> None:
    story_spec, blueprint, characters, world_bible, state, chapter_plan = make_inputs()

    draft = write_chapter_draft(story_spec, blueprint, characters, world_bible, state, chapter_plan)

    assert len(draft["draft_text"]) > 500


def test_draft_chapter_id_matches_plan() -> None:
    story_spec, blueprint, characters, world_bible, state, chapter_plan = make_inputs()

    draft = write_chapter_draft(story_spec, blueprint, characters, world_bible, state, chapter_plan)

    assert draft["chapter_id"] == chapter_plan["chapter_id"]


def test_draft_status_is_draft() -> None:
    story_spec, blueprint, characters, world_bible, state, chapter_plan = make_inputs()

    draft = write_chapter_draft(story_spec, blueprint, characters, world_bible, state, chapter_plan)

    assert draft["status"] == "draft"


def test_draft_contains_self_check() -> None:
    story_spec, blueprint, characters, world_bible, state, chapter_plan = make_inputs()

    draft = write_chapter_draft(story_spec, blueprint, characters, world_bible, state, chapter_plan)

    assert "self_check" in draft


def test_render_draft_markdown_contains_title_prefix() -> None:
    story_spec, blueprint, characters, world_bible, state, chapter_plan = make_inputs()
    draft = write_chapter_draft(story_spec, blueprint, characters, world_bible, state, chapter_plan)

    markdown = render_draft_markdown(draft)

    assert "# 第" in markdown


def test_clean_ai_style_removes_summary_words() -> None:
    text = "显然，他不是害怕，而是谨慎。总之，可以看出他停下了。"

    cleaned = clean_ai_style(text)

    assert "显然" not in cleaned
    assert "总之" not in cleaned
    assert "可以看出" not in cleaned


def test_self_check_draft_returns_warnings_list() -> None:
    story_spec, blueprint, characters, world_bible, state, chapter_plan = make_inputs()

    result = self_check_draft("太短。", chapter_plan)

    assert isinstance(result["warnings"], list)


def test_write_chapter_draft_does_not_modify_current_chapter() -> None:
    story_spec, blueprint, characters, world_bible, state, chapter_plan = make_inputs()
    before = state["current_chapter"]

    write_chapter_draft(story_spec, blueprint, characters, world_bible, state, chapter_plan)

    assert state["current_chapter"] == before
