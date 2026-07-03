from __future__ import annotations

from typing import Any

import config
from core.blueprint_generator import generate_blueprint
from core.character_builder import generate_characters
from core.draft_writer import build_draft_prompt, is_valid_draft_text, write_chapter_draft
from core.next_chapter_planner import plan_next_chapter
from core.setup_wizard import build_initial_state
from core.world_builder import generate_world_bible


def make_story_spec() -> dict[str, Any]:
    return {
        "title": "测试小说",
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
        "avoid": ["流水账"],
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


def test_build_draft_prompt_returns_string() -> None:
    story_spec, blueprint, characters, world_bible, state, chapter_plan = make_inputs()

    prompt = build_draft_prompt(story_spec, blueprint, characters, world_bible, state, chapter_plan)

    assert isinstance(prompt, str)


def test_build_draft_prompt_contains_current_chapter_boundary() -> None:
    story_spec, blueprint, characters, world_bible, state, chapter_plan = make_inputs()

    prompt = build_draft_prompt(story_spec, blueprint, characters, world_bible, state, chapter_plan)

    assert "只写当前章" in prompt
    assert "不要输出 JSON" in prompt


def test_is_valid_draft_text_rejects_empty_text() -> None:
    assert is_valid_draft_text("") is False


def test_is_valid_draft_text_rejects_json_text() -> None:
    assert is_valid_draft_text('{"draft_text": "不是正文"}') is False


def test_write_chapter_draft_falls_back_when_local_model_fails(monkeypatch: Any) -> None:
    story_spec, blueprint, characters, world_bible, state, chapter_plan = make_inputs()
    before = state["current_chapter"]

    monkeypatch.setattr(config, "USE_LOCAL_MODEL_FOR_DRAFT", True)
    monkeypatch.setattr(config, "LOCAL_MODEL_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setattr(config, "LOCAL_MODEL_NAME", "qwen-test")

    def fake_generate(prompt: str, client: Any) -> tuple[str, list[str]]:
        return "", ["本地模型调用失败，已回退 mock：boom"]

    monkeypatch.setattr("core.draft_writer.generate_draft_with_local_model", fake_generate)

    draft = write_chapter_draft(story_spec, blueprint, characters, world_bible, state, chapter_plan)

    assert "generation" in draft
    assert draft["generation"]["mode"] == "mock"
    assert draft["generation"]["fallback_used"] is True
    assert draft["generation"]["warnings"]
    assert state["current_chapter"] == before


def test_write_chapter_draft_uses_valid_local_model_text(monkeypatch: Any) -> None:
    story_spec, blueprint, characters, world_bible, state, chapter_plan = make_inputs()
    local_text = "这是本地模型写出的当前章正文。" * 80

    monkeypatch.setattr(config, "USE_LOCAL_MODEL_FOR_DRAFT", True)
    monkeypatch.setattr(config, "LOCAL_MODEL_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setattr(config, "LOCAL_MODEL_NAME", "qwen-test")

    def fake_generate(prompt: str, client: Any) -> tuple[str, list[str]]:
        return local_text, []

    monkeypatch.setattr("core.draft_writer.generate_draft_with_local_model", fake_generate)

    draft = write_chapter_draft(story_spec, blueprint, characters, world_bible, state, chapter_plan)

    assert draft["generation"]["mode"] == "local_model"
    assert draft["generation"]["model"] == "qwen-test"
    assert draft["generation"]["fallback_used"] is False
    assert draft["draft_text"] == local_text
