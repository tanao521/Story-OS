from __future__ import annotations

from typing import Any

import config
from core.blueprint_generator import generate_blueprint
from core.character_builder import generate_characters
from core.draft_writer import (
    _draft_constraint_violations,
    build_draft_prompt,
    is_valid_draft_text,
    write_chapter_draft,
)
from core.next_chapter_planner import plan_next_chapter
from core.setup_wizard import build_initial_state
from core.world_builder import generate_world_bible


def make_story_spec() -> dict[str, Any]:
    return {
        "title": "????",
        "genre": "??",
        "length_type": "??",
        "target_word_count": 300000,
        "world_style": "?????",
        "tone": "??????",
        "writing_style": "???",
        "narration": "????????",
        "character_structure": "???",
        "romance_level": "??",
        "focus": ["??", "????"],
        "avoid": ["???"],
        "anti_ai_style_rules": ["?????"],
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


def configure_cloud_provider(monkeypatch: Any) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "api")
    monkeypatch.setenv("WRITE_MODEL_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("WRITE_MODEL_NAME", "gpt-4o")
    monkeypatch.setenv("WRITE_MODEL_API_KEY", "test-key")
    monkeypatch.setattr(config, "LLM_PROVIDER", "api", raising=False)
    monkeypatch.setattr(config, "WRITE_MODEL_BASE_URL", "https://api.openai.com/v1", raising=False)
    monkeypatch.setattr(config, "WRITE_MODEL_NAME", "gpt-4o", raising=False)
    monkeypatch.setattr(config, "WRITE_MODEL_API_KEY", "test-key", raising=False)


def test_write_chapter_draft_falls_back_when_cloud_model_fails(monkeypatch: Any) -> None:
    story_spec, blueprint, characters, world_bible, state, chapter_plan = make_inputs()
    configure_cloud_provider(monkeypatch)

    def fake_generate(messages: list[dict[str, Any]]) -> str:
        raise RuntimeError("HTTP 403 Forbidden")

    monkeypatch.setattr("core.draft_writer.generate_with_api_model", fake_generate)

    draft = write_chapter_draft(story_spec, blueprint, characters, world_bible, state, chapter_plan)

    assert draft["generation"]["mode"] == "mock"
    assert draft["generation"]["fallback_used"] is True
    assert any("API" in warning for warning in draft["generation"]["warnings"])


def test_write_chapter_draft_uses_valid_cloud_text(monkeypatch: Any) -> None:
    story_spec, blueprint, characters, world_bible, state, chapter_plan = make_inputs()
    configure_cloud_provider(monkeypatch)
    story_spec["writing_constraints"] = {"chapter_word_count": {"min": 3000, "max": 4000}}
    chapter_plan["word_count_constraints"] = {"min": 3000, "max": 4000}
    cloud_text = "\u8fd9\u662f\u4e91\u7aef\u6a21\u578b\u5199\u51fa\u7684\u5f53\u524d\u7ae0\u6b63\u6587\u3002" * 250

    monkeypatch.setattr("core.draft_writer.generate_with_api_model", lambda messages: cloud_text)

    draft = write_chapter_draft(story_spec, blueprint, characters, world_bible, state, chapter_plan)

    assert draft["generation"]["mode"] == "api_model"
    assert draft["generation"]["fallback_used"] is False
    assert draft["generation"]["model"] == "gpt-4o"
    assert draft["draft_text"] == cloud_text


def test_write_chapter_draft_repairs_cloud_output_that_violates_constraints(monkeypatch: Any) -> None:
    story_spec, blueprint, characters, world_bible, state, chapter_plan = make_inputs()
    story_spec["writing_constraints"] = {
        "chapter_word_count": {"min": 3000, "max": 10000},
        "must_follow": ["Final Life Pro"],
        "must_avoid": ["forbidden-token"],
    }
    chapter_plan["word_count_constraints"] = {"min": 3000, "max": 10000}
    configure_cloud_provider(monkeypatch)
    bad_text = "This draft is in English and ignores the panel constraints. " * 5
    repaired_text = ("\u4e3b\u89d2\u5148\u786e\u8ba4\u7535\u91cf\u3001\u95e8\u7f1d\u548c\u697c\u9053\u811a\u6b65\u58f0\uff0c\u7136\u540e\u6309\u4f4f\u547c\u5438\uff0c\u7ee7\u7eed\u8d34\u8fd1\u73b0\u5b9e\u3002" * 110) + "Final Life Pro"
    prompts: list[list[dict[str, Any]]] = []
    outputs = [bad_text, repaired_text]

    def fake_generate(messages: list[dict[str, Any]]) -> str:
        prompts.append(messages)
        return outputs.pop(0)

    monkeypatch.setattr("core.draft_writer.generate_with_api_model", fake_generate)

    draft = write_chapter_draft(story_spec, blueprint, characters, world_bible, state, chapter_plan)

    assert len(prompts) == 2
    assert draft["generation"]["mode"] == "api_model"
    assert draft["generation"]["constraint_repair_used"] is True
    assert draft["draft_text"] == repaired_text
    assert "must_follow" in prompts[1][1]["content"]


def test_draft_constraint_violations_do_not_require_literal_must_follow_terms() -> None:
    story_spec = {
        "writing_constraints": {
            "chapter_word_count": {"min": 20, "max": 120},
            "must_follow": ["保持第三人称有限视角"],
            "must_avoid": ["forbidden-token"],
        },
        "avoid": [],
    }
    chapter_plan = {"word_count_constraints": {"min": 20, "max": 120}}
    text = "他站在门边，观察走廊里的人影变化，也留意着房间里的灯光和呼吸节奏。" * 5 + " forbidden-token"

    violations = _draft_constraint_violations(text, story_spec, chapter_plan)

    assert any("forbidden-token" in violation for violation in violations)
    assert not any("保持第三人称有限视角" in violation for violation in violations)
    assert is_valid_draft_text("这是一个合格的中文正文。" * 60)



def test_word_count_allows_small_overflow_within_tolerance() -> None:
    story_spec = {
        "writing_constraints": {
            "chapter_word_count": {"min": 3000, "max": 4500},
            "must_follow": [],
            "must_avoid": [],
        },
        "avoid": [],
    }
    chapter_plan = {"word_count_constraints": {"min": 3000, "max": 4500}}
    draft_text = "这" * 5157
    violations = _draft_constraint_violations(draft_text, story_spec, chapter_plan)
    assert not any("超过约束上限" in violation for violation in violations)
    assert not any("5157" in violation and "4500" in violation for violation in violations)
