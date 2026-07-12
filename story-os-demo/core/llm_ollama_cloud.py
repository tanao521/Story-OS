from __future__ import annotations

import os
from typing import Any

import config


def load_ollama_cloud_settings() -> dict[str, Any]:
    base_url = str(os.getenv("OLLAMA_CLOUD_BASE_URL", config.OLLAMA_CLOUD_BASE_URL) or "https://ollama.com/api").strip()
    model = str(os.getenv("OLLAMA_CLOUD_MODEL", config.OLLAMA_CLOUD_MODEL) or "deepseek-v4-pro:cloud").strip()
    api_key = str(
        os.getenv("OLLAMA_CLOUD_API_KEY", "")
        or os.getenv("OLLAMA_API_KEY", "")
        or getattr(config, "OLLAMA_CLOUD_API_KEY", "")
        or getattr(config, "OLLAMA_API_KEY", "")
        or ""
    ).strip()
    timeout_value = os.getenv("OLLAMA_TIMEOUT_SECONDS", str(getattr(config, "OLLAMA_TIMEOUT_SECONDS", 180)))
    try:
        timeout = int(timeout_value or "180")
    except (TypeError, ValueError):
        timeout = 180
    if timeout <= 0:
        timeout = 180
    return {
        "provider": "ollama_cloud",
        "base_url": base_url or "https://ollama.com/api",
        "model": model or "deepseek-v4-pro:cloud",
        "api_key": api_key,
        "timeout_seconds": timeout,
    }


def should_use_ollama_cloud_for_draft() -> bool:
    settings = load_ollama_cloud_settings()
    return (
        str(getattr(config, "LLM_PROVIDER", "") or "").strip().lower() == "ollama_cloud"
        and bool(settings["base_url"])
        and bool(settings["model"])
        and bool(settings["api_key"])
    )


def generate_with_ollama_cloud(messages: list[dict[str, Any]]) -> str:
    settings = load_ollama_cloud_settings()
    if not settings["api_key"]:
        raise RuntimeError("缺少 Ollama Cloud API Key，请在 .env 中配置 OLLAMA_CLOUD_API_KEY 或 OLLAMA_API_KEY。")
    if not isinstance(messages, list) or not messages:
        raise RuntimeError("Ollama Cloud messages 不能为空。")

    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("缺少 requests 依赖，无法调用 Ollama Cloud。") from exc

    base_url = settings["base_url"].rstrip("/")
    url = f"{base_url}/chat"
    payload: dict[str, Any] = {
        "model": settings["model"],
        "messages": messages,
        "stream": False,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings['api_key']}",
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=settings["timeout_seconds"])
    except Exception as exc:
        raise RuntimeError(f"Ollama Cloud 请求失败：{exc}") from exc

    if response.status_code in {401, 403}:
        raise RuntimeError(
            "Ollama Cloud 鉴权失败。请检查 OLLAMA_CLOUD_API_KEY 或 OLLAMA_API_KEY 是否正确，账号是否有 cloud 模型权限，模型名是否可用。"
        )
    if response.status_code == 404:
        raise RuntimeError("Ollama Cloud 模型或接口不存在，请检查模型名和 base_url。")
    if not response.ok:
        detail = response.text.strip()
        suffix = f": {detail[:200]}" if detail else ""
        raise RuntimeError(f"Ollama Cloud 请求失败：HTTP {response.status_code}{suffix}")

    try:
        data = response.json()
    except Exception as exc:
        raise RuntimeError("Ollama Cloud 响应不是有效 JSON。") from exc

    text = _extract_response_text(data)
    stripped = text.strip()
    if not stripped:
        raise RuntimeError("Ollama Cloud 返回空文本，已拒绝保存。")
    if len(stripped) < 100:
        raise RuntimeError("Ollama Cloud 输出过短，拒绝保存。")
    return stripped


def _extract_response_text(data: Any) -> str:
    if isinstance(data, dict):
        message = data.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content
        response_text = data.get("response")
        if isinstance(response_text, str):
            return response_text
    return ""
