from __future__ import annotations

from typing import Any

import config
from llm.openai_compatible_client import OpenAICompatibleClient


def should_use_local_model_for_draft() -> bool:
    return (
        config.USE_LOCAL_MODEL_FOR_DRAFT
        and bool(config.LOCAL_MODEL_BASE_URL)
        and bool(config.LOCAL_MODEL_NAME)
    )


def local_model_draft_warnings() -> list[str]:
    warnings: list[str] = []
    if not config.USE_LOCAL_MODEL_FOR_DRAFT:
        return warnings
    if not config.LOCAL_MODEL_BASE_URL:
        warnings.append("已启用本地模型写草稿，但 LOCAL_MODEL_BASE_URL 未配置，已回退 mock。")
    if not config.LOCAL_MODEL_NAME:
        warnings.append("已启用本地模型写草稿，但 LOCAL_MODEL_NAME 未配置，已回退 mock。")
    return warnings


def create_local_model_client() -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        api_key=config.LOCAL_MODEL_API_KEY,
        base_url=config.LOCAL_MODEL_BASE_URL,
        model=config.LOCAL_MODEL_NAME,
    )


def generate_draft_with_local_model(
    prompt: str,
    client: OpenAICompatibleClient,
) -> tuple[str, list[str]]:
    try:
        text = client.chat_text(prompt, temperature=0.7, max_tokens=2400)
    except Exception as exc:
        return "", [f"本地模型调用失败，已回退 mock：{_error_summary(exc)}"]
    return text.strip(), []


def _error_summary(error: Exception) -> str:
    message = str(error).strip()
    return message[:200] if message else error.__class__.__name__
