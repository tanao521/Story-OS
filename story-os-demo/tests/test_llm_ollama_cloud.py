from __future__ import annotations

from typing import Any

import config
import pytest

from core.llm_api_model import generate_with_api_model


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any] | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.ok = 200 <= status_code < 300

    def json(self) -> dict[str, Any]:
        return self._payload


def _configure_api_model(monkeypatch: pytest.MonkeyPatch, api_key: str = "test-key") -> None:
    monkeypatch.setenv("WRITE_MODEL_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("WRITE_MODEL_NAME", "gpt-4o")
    monkeypatch.setenv("WRITE_MODEL_API_KEY", api_key)
    monkeypatch.setenv("WRITE_MODEL_TIMEOUT_SECONDS", "180")
    monkeypatch.setattr(config, "WRITE_MODEL_BASE_URL", "https://api.openai.com/v1", raising=False)
    monkeypatch.setattr(config, "WRITE_MODEL_NAME", "gpt-4o", raising=False)
    monkeypatch.setattr(config, "WRITE_MODEL_API_KEY", api_key, raising=False)
    monkeypatch.setattr(config, "WRITE_MODEL_TIMEOUT_SECONDS", 180, raising=False)


def test_generate_with_api_model_uses_message_content(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_api_model(monkeypatch)
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        calls.append({"url": url, **kwargs})
        return FakeResponse(200, {"message": {"content": "\u4e2d\u6587\u6b63\u6587" * 60}})

    import requests

    monkeypatch.setattr(requests, "post", fake_post)

    text = generate_with_api_model([{"role": "user", "content": "\u6d4b\u8bd5"}])

    assert text.startswith("\u4e2d\u6587\u6b63\u6587")
    assert calls[0]["url"] == "https://api.openai.com/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer test-key"
    assert calls[0]["json"]["model"] == "gpt-4o"
    assert calls[0]["json"]["stream"] is False


def test_generate_with_api_model_falls_back_to_response_field(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_api_model(monkeypatch)

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        return FakeResponse(200, {"response": "\u5907\u7528\u6b63\u6587" * 60})

    import requests

    monkeypatch.setattr(requests, "post", fake_post)

    text = generate_with_api_model([{"role": "user", "content": "\u6d4b\u8bd5"}])

    assert text.startswith("\u5907\u7528\u6b63\u6587")


def test_generate_with_api_model_rejects_auth_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_api_model(monkeypatch)

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        return FakeResponse(403, text="Forbidden")

    import requests

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(RuntimeError, match="API"):
        generate_with_api_model([{"role": "user", "content": "\u6d4b\u8bd5"}])


def test_generate_with_api_model_accepts_model_api_key_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WRITE_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("MODEL_API_KEY", "alias-key")
    monkeypatch.setattr(config, "WRITE_MODEL_API_KEY", "", raising=False)
    monkeypatch.setattr(config, "MODEL_API_KEY", "alias-key", raising=False)

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        assert kwargs["headers"]["Authorization"] == "Bearer alias-key"
        return FakeResponse(200, {"message": {"content": "\u4e2d\u6587\u6b63\u6587" * 60}})

    import requests

    monkeypatch.setattr(requests, "post", fake_post)

    text = generate_with_api_model([{"role": "user", "content": "\u6d4b\u8bd5"}])

    assert len(text) >= 100


def test_generate_with_api_model_rejects_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WRITE_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(config, "WRITE_MODEL_API_KEY", "", raising=False)
    monkeypatch.setattr(config, "MODEL_API_KEY", "", raising=False)
    monkeypatch.setattr(config, "OPENAI_API_KEY", "", raising=False)
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "", raising=False)

    with pytest.raises(RuntimeError, match="WRITE_MODEL_API_KEY"):
        generate_with_api_model([{"role": "user", "content": "\u6d4b\u8bd5"}])


def test_generate_with_api_model_rejects_short_output(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_api_model(monkeypatch)

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        return FakeResponse(200, {"message": {"content": "\u592a\u77ed"}})

    import requests

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(RuntimeError, match="API"):
        generate_with_api_model([{"role": "user", "content": "\u6d4b\u8bd5"}])
