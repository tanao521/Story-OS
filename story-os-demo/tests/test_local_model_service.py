from __future__ import annotations

from typing import Any

import config
from llm.local_model_service import (
    generate_draft_with_local_model,
    local_model_draft_warnings,
    should_use_local_model_for_draft,
)


class FakeClient:
    def __init__(self, text: str = "", error: Exception | None = None) -> None:
        self.text = text
        self.error = error

    def chat_text(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        if self.error is not None:
            raise self.error
        return self.text


def test_should_not_use_local_model_without_base_url(monkeypatch: Any) -> None:
    monkeypatch.setattr(config, "USE_LOCAL_MODEL_FOR_DRAFT", True)
    monkeypatch.setattr(config, "LOCAL_MODEL_BASE_URL", "")
    monkeypatch.setattr(config, "LOCAL_MODEL_NAME", "qwen")

    assert should_use_local_model_for_draft() is False
    assert local_model_draft_warnings()


def test_should_not_use_local_model_without_model_name(monkeypatch: Any) -> None:
    monkeypatch.setattr(config, "USE_LOCAL_MODEL_FOR_DRAFT", True)
    monkeypatch.setattr(config, "LOCAL_MODEL_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setattr(config, "LOCAL_MODEL_NAME", "")

    assert should_use_local_model_for_draft() is False
    assert local_model_draft_warnings()


def test_should_not_use_local_model_when_switch_is_false(monkeypatch: Any) -> None:
    monkeypatch.setattr(config, "USE_LOCAL_MODEL_FOR_DRAFT", False)
    monkeypatch.setattr(config, "LOCAL_MODEL_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setattr(config, "LOCAL_MODEL_NAME", "qwen")

    assert should_use_local_model_for_draft() is False
    assert local_model_draft_warnings() == []


def test_generate_draft_with_local_model_returns_warning_on_failure() -> None:
    text, warnings = generate_draft_with_local_model("prompt", FakeClient(error=RuntimeError("boom")))

    assert text == ""
    assert warnings


def test_generate_draft_with_local_model_returns_text_without_network() -> None:
    text, warnings = generate_draft_with_local_model("prompt", FakeClient(text="正文内容"))

    assert text == "正文内容"
    assert warnings == []
