from __future__ import annotations

import os
from typing import Any

import config


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return default


def load_api_model_settings() -> dict[str, Any]:
    base_url = _env_first(
        "WRITE_MODEL_BASE_URL",
        "MODEL_BASE_URL",
        "OPENAI_API_BASE",
        "OPENAI_BASE_URL",
        "DEEPSEEK_BASE_URL",
        default=getattr(config, "WRITE_MODEL_BASE_URL", "https://api.openai.com/v1"),
    )
    model = _env_first(
        "WRITE_MODEL_NAME",
        "MODEL_NAME",
        "OPENAI_MODEL",
        "DEEPSEEK_MODEL",
        default=getattr(config, "WRITE_MODEL_NAME", "gpt-4o"),
    )
    api_key = _env_first(
        "WRITE_MODEL_API_KEY",
        "MODEL_API_KEY",
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        default=getattr(config, "WRITE_MODEL_API_KEY", ""),
    )
    timeout_value = _env_first(
        "WRITE_MODEL_TIMEOUT_SECONDS",
        "MODEL_TIMEOUT_SECONDS",
        "LLM_TIMEOUT_SECONDS",
        default=str(getattr(config, "WRITE_MODEL_TIMEOUT_SECONDS", 180)),
    )
    try:
        timeout = int(timeout_value or "180")
    except (TypeError, ValueError):
        timeout = 180
    if timeout <= 0:
        timeout = 180
    return {"provider": "api", "base_url": base_url, "model": model, "api_key": api_key, "timeout_seconds": timeout}


def should_use_api_model_for_draft() -> bool:
    provider = str(getattr(config, "LLM_PROVIDER", "") or "").strip().lower()
    settings = load_api_model_settings()
    if provider in {"mock", "local", "ollama", "ollama_cloud"}:
        return False
    return bool(settings["api_key"]) and bool(settings["base_url"]) and bool(settings["model"])


def generate_with_api_model(messages: list[dict[str, Any]]) -> str:
    settings = load_api_model_settings()
    if not settings["api_key"]:
        raise RuntimeError("缺少 API 模型密钥，请在 .env 中配置 WRITE_MODEL_API_KEY / MODEL_API_KEY / OPENAI_API_KEY / DEEPSEEK_API_KEY。")
    if not isinstance(messages, list) or not messages:
        raise RuntimeError("API 模型 messages 不能为空。")

    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("缺少 requests 依赖，无法调用 API 模型。") from exc

    url = _chat_completions_url(settings["base_url"])
    payload: dict[str, Any] = {"model": settings["model"], "messages": messages, "stream": False, "temperature": 0.7}
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {settings['api_key']}"}

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=settings["timeout_seconds"])
    except Exception as exc:
        raise RuntimeError(f"API 模型请求失败：{exc}") from exc

    if response.status_code in {401, 403}:
        raise RuntimeError("API 模型鉴权失败。请检查 .env 中的 key 是否正确，账号是否有模型权限，模型名和 base_url 是否可用。")
    if response.status_code == 404:
        raise RuntimeError("API 模型或接口不存在，请检查模型名和 base_url。")
    if not response.ok:
        detail = response.text.strip()
        suffix = f": {detail[:200]}" if detail else ""
        raise RuntimeError(f"API 模型请求失败：HTTP {response.status_code}{suffix}")

    try:
        data = response.json()
    except Exception as exc:
        raise RuntimeError("API 模型响应不是有效 JSON。") from exc

    text = _extract_response_text(data)
    stripped = text.strip()
    if not stripped:
        raise RuntimeError("API 模型返回空文本，已拒绝保存。")
    if len(stripped) < 100:
        raise RuntimeError("API 模型输出过短，拒绝保存。")
    return stripped


def _chat_completions_url(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/chat/completions"):
        return root
    if root.endswith("/v1"):
        return f"{root}/chat/completions"
    return f"{root}/v1/chat/completions"


def _extract_response_text(data: Any) -> str:
    if isinstance(data, dict):
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str):
                        return content
        message = data.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content
        response_text = data.get("response")
        if isinstance(response_text, str):
            return response_text
    return ""
