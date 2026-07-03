from __future__ import annotations

from typing import Any

import config


def mask_secret(value: str) -> str:
    if not value:
        return "未配置"
    if len(value) <= 8:
        return "已配置，但过短，已隐藏"
    return f"{value[:4]}****{value[-4:]}"


def check_llm_config() -> dict[str, Any]:
    warnings: list[str] = []

    if not config.DEEPSEEK_API_KEY:
        warnings.append("DeepSeek API Key 未配置。")
    if not config.DEEPSEEK_MODEL:
        warnings.append("DeepSeek 模型名未配置。")
    if not config.DEEPSEEK_BASE_URL:
        warnings.append("DeepSeek Base URL 未配置。")
    if not config.LOCAL_MODEL_BASE_URL:
        warnings.append("本地模型地址 LOCAL_MODEL_BASE_URL 未配置。")
    if not config.LOCAL_MODEL_NAME:
        warnings.append("本地模型名称 LOCAL_MODEL_NAME 未配置。")

    return {
        "deepseek": {
            "api_key_present": bool(config.DEEPSEEK_API_KEY),
            "api_key_masked": mask_secret(config.DEEPSEEK_API_KEY),
            "model": config.DEEPSEEK_MODEL,
            "base_url": config.DEEPSEEK_BASE_URL,
        },
        "local_model": {
            "api_key_present": bool(config.LOCAL_MODEL_API_KEY),
            "api_key_masked": mask_secret(config.LOCAL_MODEL_API_KEY),
            "model": config.LOCAL_MODEL_NAME,
            "base_url": config.LOCAL_MODEL_BASE_URL,
        },
        "warnings": warnings,
    }
