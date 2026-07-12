from __future__ import annotations

from typing import Any

from core.llm_api_model import generate_with_api_model, load_api_model_settings


def build_llm_health_report() -> dict[str, Any]:
    settings = load_api_model_settings()
    report: dict[str, Any] = {
        "provider": settings["provider"],
        "base_url": settings["base_url"],
        "model": settings["model"],
        "has_api_key": bool(settings["api_key"]),
        "ok": False,
        "test_generation_ok": False,
        "error_message": "",
    }
    if not settings["api_key"]:
        report["error_message"] = "缺少 API 模型密钥，请在 .env 中配置 WRITE_MODEL_API_KEY / MODEL_API_KEY / OPENAI_API_KEY / DEEPSEEK_API_KEY。"
        return report

    try:
        generate_with_api_model([
            {"role": "system", "content": "你是 Story OS 的 API 模型健康检查器，只输出一段中文测试文本。"},
            {"role": "user", "content": "请输出一段至少 120 个中文字符的测试文本，证明 API 模型可正常响应。"},
        ])
    except Exception as exc:
        report["error_message"] = str(exc)
        return report

    report["ok"] = True
    report["test_generation_ok"] = True
    return report
