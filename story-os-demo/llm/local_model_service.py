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
    target_chars: int = 3000,
) -> tuple[str, list[str]]:
    max_tokens = _draft_max_tokens(target_chars)
    try:
        text = client.chat_text(prompt, temperature=0.7, max_tokens=max_tokens)
    except Exception as exc:
        return "", [f"\u672c\u5730\u6a21\u578b\u8c03\u7528\u5931\u8d25\uff0c\u5df2\u56de\u9000 mock\uff1a{_error_summary(exc)}"]
    stripped = text.strip()
    if not stripped:
        return "", [
            f"\u672c\u5730\u6a21\u578b\u8fd4\u56de\u7a7a\u6b63\u6587\uff0c\u53ef\u80fd\u662f\u601d\u8003\u6a21\u578b\u8017\u5c3d\u4e86\u8f93\u51fa token\uff1b\u5df2\u8bf7\u6c42 max_tokens={max_tokens}\u3002"
            "\u8bf7\u6362\u7528\u975e\u601d\u8003\u6a21\u578b\u3001\u5173\u95ed thinking\uff0c\u6216\u7ee7\u7eed\u63d0\u9ad8\u6a21\u578b\u4e0a\u4e0b\u6587/\u8f93\u51fa\u4e0a\u9650\u3002"
        ]
    return stripped, []


def _draft_max_tokens(target_chars: int) -> int:
    try:
        chars = int(target_chars)
    except (TypeError, ValueError):
        chars = 3000
    chars = max(chars, 1200)
    return max(4096, min(16000, chars * 4))


def _error_summary(error: Exception) -> str:
    message = str(error).strip()
    return message[:200] if message else error.__class__.__name__
