from __future__ import annotations

import config
from llm.config_check import check_llm_config, mask_secret


def test_mask_secret_empty_returns_unconfigured() -> None:
    assert mask_secret("") == "未配置"


def test_mask_secret_short_value_does_not_leak_plaintext() -> None:
    masked = mask_secret("123456")

    assert masked != "123456"
    assert "123456" not in masked


def test_mask_secret_long_value_shows_only_edges() -> None:
    masked = mask_secret("sk-1234567890abcd")

    assert masked == "sk-1****abcd"
    assert "234567890" not in masked


def test_check_llm_config_returns_write_model_section(monkeypatch) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", "api", raising=False)
    monkeypatch.setattr(config, "WRITE_MODEL_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(config, "WRITE_MODEL_NAME", "gpt-4o", raising=False)
    monkeypatch.setattr(config, "WRITE_MODEL_BASE_URL", "https://api.openai.com/v1", raising=False)

    result = check_llm_config()

    assert result["provider"] == "api"
    assert result["write_model"]["api_key_present"] is True
    assert result["write_model"]["model"] == "gpt-4o"
    assert result["write_model"]["base_url"] == "https://api.openai.com/v1"



def test_check_llm_config_accepts_write_model_aliases(monkeypatch) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", "api", raising=False)
    monkeypatch.setattr(config, "WRITE_MODEL_API_KEY", "", raising=False)
    monkeypatch.setattr(config, "MODEL_API_KEY", "alias-key", raising=False)
    monkeypatch.setattr(config, "WRITE_MODEL_NAME", "gpt-4o", raising=False)
    monkeypatch.setattr(config, "WRITE_MODEL_BASE_URL", "https://api.openai.com/v1", raising=False)

    result = check_llm_config()

    assert result["write_model"]["api_key_present"] is True
    assert result["write_model"]["api_key_masked"] == "alia****-key"

def test_check_llm_config_without_env_does_not_crash(monkeypatch) -> None:
    for key in [
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_BASE_URL",
        "LOCAL_MODEL_API_KEY",
        "LOCAL_MODEL_BASE_URL",
        "LOCAL_MODEL_NAME",
        "WRITE_MODEL_API_KEY",
        "WRITE_MODEL_NAME",
        "WRITE_MODEL_BASE_URL",
        "WRITE_MODEL_TIMEOUT_SECONDS",
    ]:
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setattr(config, "LLM_PROVIDER", "mock", raising=False)
    monkeypatch.setattr(config, "WRITE_MODEL_API_KEY", "", raising=False)
    monkeypatch.setattr(config, "WRITE_MODEL_NAME", "", raising=False)
    monkeypatch.setattr(config, "WRITE_MODEL_BASE_URL", "", raising=False)

    result = check_llm_config()

    assert "warnings" in result
    assert "write_model" in result
