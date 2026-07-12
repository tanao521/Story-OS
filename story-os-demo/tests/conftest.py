from __future__ import annotations

import pytest

import config


@pytest.fixture(autouse=True)
def disable_real_model_calls_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", "mock", raising=False)
    monkeypatch.setattr(config, "USE_LOCAL_MODEL_FOR_DRAFT", False, raising=False)
    monkeypatch.setattr(config, "USE_DEEPSEEK_FOR_EDITING", False, raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OLLAMA_CLOUD_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_CLOUD_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_CLOUD_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_TIMEOUT_SECONDS", raising=False)
