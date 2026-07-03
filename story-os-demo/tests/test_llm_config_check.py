from __future__ import annotations

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


def test_check_llm_config_returns_deepseek_and_local_model() -> None:
    result = check_llm_config()

    assert "deepseek" in result
    assert "local_model" in result


def test_check_llm_config_without_env_does_not_crash(monkeypatch) -> None:
    for key in [
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_BASE_URL",
        "LOCAL_MODEL_API_KEY",
        "LOCAL_MODEL_BASE_URL",
        "LOCAL_MODEL_NAME",
    ]:
        monkeypatch.delenv(key, raising=False)

    result = check_llm_config()

    assert "warnings" in result
