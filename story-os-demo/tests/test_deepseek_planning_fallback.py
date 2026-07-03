from __future__ import annotations

from typing import Any

import pytest

from llm.deepseek_client import DeepSeekClient, DeepSeekError
from llm.json_utils import deep_merge_missing
from llm.planning_service import generate_blueprint_with_deepseek


class BrokenJsonClient:
    def chat_json(self, prompt: str, temperature: float = 0.4) -> dict[str, Any]:
        raise DeepSeekError("invalid json")


def test_deepseek_client_chat_json_raises_for_non_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_chat_text(prompt: str, temperature: float = 0.4) -> str:
        return "this is not json"

    client = DeepSeekClient(api_key="sk-test", model="deepseek-chat")
    monkeypatch.setattr(client, "chat_text", fake_chat_text)

    with pytest.raises(DeepSeekError):
        client.chat_json("prompt")


def test_deepseek_invalid_json_path_falls_back_to_mock_blueprint() -> None:
    mock = {
        "title": "Mock",
        "blueprint_version": "0.2",
        "genre": "悬疑",
        "length_type": "短篇",
        "target_word_count": 8000,
        "core_premise": "premise",
        "main_arc": "arc",
        "core_conflict": "conflict",
        "ending_direction": "ending",
        "world_direction": {},
        "story_phases": [{"phase_id": 1}],
        "initial_foreshadow_pool": [],
        "rolling_generation_policy": {
            "mode": "chapter_by_chapter",
            "plan_next_chapter_only": True,
        },
    }

    result, warnings = generate_blueprint_with_deepseek({}, mock, BrokenJsonClient())

    assert result is mock
    assert warnings


def test_deep_merge_missing_does_not_overwrite_present_values() -> None:
    base = {"title": "Mock", "world_direction": {"world_style": "base", "rules": ["a"]}}
    patch = {"title": "DeepSeek", "world_direction": {"world_style": "patch"}}

    result = deep_merge_missing(base, patch)

    assert result["title"] == "DeepSeek"
    assert result["world_direction"]["world_style"] == "patch"
    assert result["world_direction"]["rules"] == ["a"]
