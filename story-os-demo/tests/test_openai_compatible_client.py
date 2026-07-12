from __future__ import annotations

from typing import Any

from llm.openai_compatible_client import OpenAICompatibleClient


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


def test_ollama_base_url_uses_native_chat_with_think_disabled(monkeypatch: Any) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        calls.append({"url": url, **kwargs})
        return FakeResponse({"message": {"content": "??"}})

    import requests

    monkeypatch.setattr(requests, "post", fake_post)
    client = OpenAICompatibleClient("ollama", "http://localhost:11434/v1", "qwen3.5:9b")

    text = client.chat_text("prompt", temperature=0.2, max_tokens=12000)

    assert text == "??"
    assert calls[0]["url"] == "http://localhost:11434/api/chat"
    assert calls[0]["json"]["think"] is False
    assert calls[0]["json"]["stream"] is False
    assert calls[0]["json"]["options"]["num_predict"] == 12000


def test_openai_base_url_still_uses_chat_completions(monkeypatch: Any) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        calls.append({"url": url, **kwargs})
        return FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    import requests

    monkeypatch.setattr(requests, "post", fake_post)
    client = OpenAICompatibleClient("key", "https://example.test/v1", "model")

    assert client.chat_text("prompt") == "ok"
    assert calls[0]["url"] == "https://example.test/v1/chat/completions"
    assert "think" not in calls[0]["json"]
