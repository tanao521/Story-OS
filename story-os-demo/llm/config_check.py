from __future__ import annotations

from typing import Any

import config


def mask_secret(value: str) -> str:
    if not value:
        return "未配置"
    if len(value) <= 8:
        return "已配置，但过短，已隐藏"
    return f"{value[:4]}****{value[-4:]}"


def _write_model_api_key() -> str:
    return str(
        getattr(config, "WRITE_MODEL_API_KEY", "")
        or getattr(config, "MODEL_API_KEY", "")
        or getattr(config, "OPENAI_API_KEY", "")
        or getattr(config, "DEEPSEEK_API_KEY", "")
        or ""
    )


def check_llm_config() -> dict[str, Any]:
    warnings: list[str] = []
    provider = str(getattr(config, "LLM_PROVIDER", "") or "").strip().lower() or "api"
    write_api_key = _write_model_api_key()
    write_model = {
        "provider": provider,
        "api_key_present": bool(write_api_key),
        "api_key_masked": mask_secret(write_api_key),
        "model": getattr(config, "WRITE_MODEL_NAME", ""),
        "base_url": getattr(config, "WRITE_MODEL_BASE_URL", ""),
        "timeout_seconds": getattr(config, "WRITE_MODEL_TIMEOUT_SECONDS", 180),
    }
    if provider in {"mock", "local", "ollama", "ollama_cloud"}:
        warnings.append("当前 LLM_PROVIDER 还是本地 / Ollama 路线，已不适用于正式写作。")
    if not write_model["api_key_present"]:
        warnings.append("API 写作密钥未配置，请设置 WRITE_MODEL_API_KEY / MODEL_API_KEY / OPENAI_API_KEY / DEEPSEEK_API_KEY。")
    if not write_model["model"]:
        warnings.append("API 写作模型名未配置。")
    if not write_model["base_url"]:
        warnings.append("API 写作 Base URL 未配置。")

    if not config.DEEPSEEK_API_KEY:
        warnings.append("DeepSeek API Key 未配置。")
    if not config.DEEPSEEK_MODEL:
        warnings.append("DeepSeek 模型名未配置。")
    if not config.DEEPSEEK_BASE_URL:
        warnings.append("DeepSeek Base URL 未配置。")

    return {
        "provider": provider,
        "write_model": write_model,
        "deepseek": {
            "api_key_present": bool(config.DEEPSEEK_API_KEY),
            "api_key_masked": mask_secret(config.DEEPSEEK_API_KEY),
            "model": config.DEEPSEEK_MODEL,
            "base_url": config.DEEPSEEK_BASE_URL,
        },
        "warnings": warnings,
    }
