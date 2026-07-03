from __future__ import annotations

from typing import Any

from core.blueprint_generator import generate_blueprint
from core.character_builder import generate_characters, render_characters_markdown
from core.setup_wizard import build_initial_state
from core.world_builder import generate_world_bible, render_world_bible_markdown


def make_story_spec(character_structure: str = "单男主") -> dict[str, Any]:
    return {
        "title": "未命名小说",
        "genre": "末世",
        "length_type": "长篇",
        "target_word_count": 300000,
        "world_style": "近未来末世",
        "tone": "灰暗但不绝望",
        "writing_style": "电影感",
        "narration": "第三人称有限视角",
        "character_structure": character_structure,
        "romance_level": "轻微",
        "focus": ["生存", "人物成长"],
        "avoid": ["不要流水账"],
        "anti_ai_style_rules": ["减少破折号"],
        "need_outline": True,
    }


def make_inputs(character_structure: str = "单男主") -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    story_spec = make_story_spec(character_structure)
    blueprint = generate_blueprint(story_spec)
    state = build_initial_state(story_spec)
    return story_spec, blueprint, state


def test_generate_characters_returns_dict() -> None:
    story_spec, blueprint, state = make_inputs()

    characters = generate_characters(story_spec, blueprint, state)

    assert isinstance(characters, dict)


def test_main_characters_has_at_least_one_character() -> None:
    story_spec, blueprint, state = make_inputs()

    characters = generate_characters(story_spec, blueprint, state)

    assert len(characters["main_characters"]) >= 1


def test_each_main_character_contains_voice_profile() -> None:
    story_spec, blueprint, state = make_inputs()

    characters = generate_characters(story_spec, blueprint, state)

    assert all("voice_profile" in character for character in characters["main_characters"])


def test_ensemble_story_generates_at_least_three_main_characters() -> None:
    story_spec, blueprint, state = make_inputs("群像文")

    characters = generate_characters(story_spec, blueprint, state)

    assert len(characters["main_characters"]) >= 3


def test_render_characters_markdown_contains_title() -> None:
    story_spec, blueprint, state = make_inputs()
    characters = generate_characters(story_spec, blueprint, state)

    markdown = render_characters_markdown(characters)

    assert "# 角色卡" in markdown


def test_generate_world_bible_returns_dict() -> None:
    story_spec, blueprint, state = make_inputs()

    world_bible = generate_world_bible(story_spec, blueprint, state)

    assert isinstance(world_bible, dict)


def test_world_bible_has_core_rules() -> None:
    story_spec, blueprint, state = make_inputs()

    world_bible = generate_world_bible(story_spec, blueprint, state)

    assert len(world_bible["core_rules"]) >= 1


def test_world_bible_has_locations() -> None:
    story_spec, blueprint, state = make_inputs()

    world_bible = generate_world_bible(story_spec, blueprint, state)

    assert len(world_bible["locations"]) >= 1


def test_world_bible_has_at_least_three_continuity_rules() -> None:
    story_spec, blueprint, state = make_inputs()

    world_bible = generate_world_bible(story_spec, blueprint, state)

    assert len(world_bible["continuity_rules"]) >= 3


def test_render_world_bible_markdown_contains_title() -> None:
    story_spec, blueprint, state = make_inputs()
    world_bible = generate_world_bible(story_spec, blueprint, state)

    markdown = render_world_bible_markdown(world_bible)

    assert "# 世界观设定集" in markdown
