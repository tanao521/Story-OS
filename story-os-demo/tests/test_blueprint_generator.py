from __future__ import annotations

from typing import Any

from core.blueprint_generator import generate_blueprint, render_blueprint_markdown


def make_story_spec(length_type: str = "长篇") -> dict[str, Any]:
    word_counts = {
        "短篇": 8000,
        "中篇": 60000,
        "长篇": 300000,
        "超长篇": 1000000,
    }
    return {
        "title": "未命名小说",
        "genre": "末世",
        "length_type": length_type,
        "target_word_count": word_counts[length_type],
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


def test_generate_blueprint_returns_dict() -> None:
    blueprint = generate_blueprint(make_story_spec())

    assert isinstance(blueprint, dict)


def test_generate_blueprint_does_not_create_chapters() -> None:
    blueprint = generate_blueprint(make_story_spec())

    assert "chapters" not in blueprint or blueprint["chapters"] == []


def test_generate_blueprint_contains_story_phases() -> None:
    blueprint = generate_blueprint(make_story_spec())

    assert blueprint["story_phases"]


def test_short_story_has_three_phases() -> None:
    blueprint = generate_blueprint(make_story_spec("短篇"))

    assert len(blueprint["story_phases"]) == 3


def test_medium_story_has_four_phases() -> None:
    blueprint = generate_blueprint(make_story_spec("中篇"))

    assert len(blueprint["story_phases"]) == 4


def test_long_and_extra_long_story_have_five_phases() -> None:
    long_blueprint = generate_blueprint(make_story_spec("长篇"))
    extra_long_blueprint = generate_blueprint(make_story_spec("超长篇"))

    assert len(long_blueprint["story_phases"]) == 5
    assert len(extra_long_blueprint["story_phases"]) == 5


def test_rolling_generation_policy_is_chapter_by_chapter() -> None:
    blueprint = generate_blueprint(make_story_spec())

    assert blueprint["rolling_generation_policy"]["mode"] == "chapter_by_chapter"
    assert blueprint["rolling_generation_policy"]["plan_next_chapter_only"] is True


def test_render_blueprint_markdown_mentions_rolling_policy() -> None:
    blueprint = generate_blueprint(make_story_spec())

    markdown = render_blueprint_markdown(blueprint)

    assert "滚动式逐章生成策略" in markdown
