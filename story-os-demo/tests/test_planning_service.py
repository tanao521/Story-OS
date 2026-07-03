from __future__ import annotations

from typing import Any

import config
from llm.deepseek_client import DeepSeekError
from llm.planning_service import (
    generate_blueprint_with_deepseek,
    generate_story_spec_with_deepseek,
    plan_next_chapter_with_deepseek,
    should_use_deepseek_for_planning,
)


class FakeClient:
    def __init__(self, payload: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        self.payload = payload or {}
        self.error = error
        self.calls = 0

    def chat_json(self, prompt: str, temperature: float = 0.4) -> dict[str, Any]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.payload


def test_should_use_deepseek_requires_switch_and_api_key(monkeypatch: Any) -> None:
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "")
    assert should_use_deepseek_for_planning({"use_deepseek_for_planning": True}) is False

    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "sk-test")
    assert should_use_deepseek_for_planning({}) is False
    assert should_use_deepseek_for_planning({"use_deepseek_for_planning": True}) is True


def test_generate_story_spec_fills_missing_fields_from_mock() -> None:
    mock = {
        "title": "Mock Title",
        "genre": "悬疑",
        "length_type": "短篇",
        "target_word_count": 8000,
        "world_style": "现实",
        "tone": "冷峻",
        "writing_style": "电影感",
        "narration": "第三人称有限视角",
        "character_structure": "单女主",
        "romance_level": "无",
        "focus": ["谜团"],
        "avoid": [],
        "anti_ai_style_rules": [],
        "need_outline": True,
    }

    result, warnings = generate_story_spec_with_deepseek(
        {"title": "raw"},
        mock,
        FakeClient({"title": "DeepSeek Title"}),
    )

    assert result["title"] == "DeepSeek Title"
    assert result["genre"] == "悬疑"
    assert warnings


def test_generate_blueprint_removes_chapters_and_keeps_rolling_policy() -> None:
    mock = {
        "title": "Mock",
        "blueprint_version": "0.2",
        "genre": "都市",
        "length_type": "中篇",
        "target_word_count": 60000,
        "core_premise": "premise",
        "main_arc": "arc",
        "core_conflict": "conflict",
        "ending_direction": "ending",
        "world_direction": {"world_style": "现实"},
        "story_phases": [{"phase_id": 1}],
        "initial_foreshadow_pool": [],
        "rolling_generation_policy": {
            "mode": "chapter_by_chapter",
            "plan_next_chapter_only": True,
        },
    }
    payload = {
        "title": "DeepSeek",
        "chapters": [{"chapter_id": 1}],
        "rolling_generation_policy": {"mode": "chapter_by_chapter"},
    }

    result, warnings = generate_blueprint_with_deepseek({}, mock, FakeClient(payload))

    assert result["title"] == "DeepSeek"
    assert "chapters" not in result
    assert result["story_phases"] == [{"phase_id": 1}]
    assert result["rolling_generation_policy"]["plan_next_chapter_only"] is True
    assert warnings


def test_plan_next_chapter_corrects_chapter_id_and_empty_scene_plan() -> None:
    mock_plan = {
        "plan_version": "0.4",
        "chapter_id": 2,
        "chapter_title": "Mock",
        "estimated_word_count": 3000,
        "chapter_goal": "goal",
        "phase_position": {},
        "required_context": {},
        "scene_plan": [{"scene_id": 1}],
        "conflict_design": {},
        "pacing_design": {},
        "climax_design": {},
        "voice_requirements": {},
        "style_requirements": [],
        "continuity_constraints": [],
        "state_updates_expected": [],
    }
    payload = {
        "plan_version": "1.0",
        "chapter_id": 99,
        "chapter_title": "DeepSeek",
        "scene_plan": [],
    }

    result, warnings = plan_next_chapter_with_deepseek(
        {},
        {},
        {},
        {},
        {"current_chapter": 1},
        None,
        mock_plan,
        FakeClient(payload),
    )

    assert result["chapter_id"] == 2
    assert result["chapter_title"] == "DeepSeek"
    assert result["scene_plan"] == [{"scene_id": 1}]
    assert warnings


def test_deepseek_error_returns_mock_plan() -> None:
    mock_plan = {"chapter_id": 1, "scene_plan": [{"scene_id": 1}]}

    result, warnings = plan_next_chapter_with_deepseek(
        {},
        {},
        {},
        {},
        {"current_chapter": 0},
        None,
        mock_plan,
        FakeClient(error=DeepSeekError("boom")),
    )

    assert result is mock_plan
    assert warnings
