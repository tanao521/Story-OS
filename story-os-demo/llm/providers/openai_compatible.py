from __future__ import annotations

import os
from typing import Any, Callable

import requests

from llm.model_models import ModelDefinition, ModelGatewayError, ModelRequest, ModelResponse


class OpenAICompatibleProvider:
    def __init__(self, post: Callable[..., Any] | None = None) -> None:
        self.post = post or requests.post

    def generate(self, definition: ModelDefinition, request: ModelRequest) -> ModelResponse:
        key = os.getenv(definition.api_key_env, "") if definition.api_key_env else ""
        if not key and definition.model_key == "write_model":
            key = next((os.getenv(name, "") for name in ("MODEL_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY") if os.getenv(name, "")), "")
        if not definition.base_url or not definition.model:
            raise ModelGatewayError("Model endpoint is not configured.", code="MODEL_NOT_CONFIGURED")
        if definition.api_key_env and not key:
            raise ModelGatewayError("Model API key is not configured in the environment.", code="MODEL_KEY_MISSING")
        url = self._url(definition.base_url)
        payload: dict[str, Any] = {"model": definition.model, "messages": [{"role": "user", "content": request.prompt}], "stream": False, "temperature": request.temperature}
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        try:
            response = self.post(url, json=payload, headers=headers, timeout=definition.timeout_seconds)
        except Exception as exc:
            raise ModelGatewayError("Model network request failed.", code="NETWORK_ERROR", recoverable=True) from exc
        status = int(getattr(response, "status_code", 200) or 200)
        if status >= 400:
            recoverable = status in {429, 502, 503, 504}
            raise ModelGatewayError(f"Model returned HTTP {status}.", code=f"HTTP_{status}", recoverable=recoverable)
        try:
            payload_data = response.json()
            text = self._extract_text(payload_data)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ModelGatewayError("Model response format was invalid.", code="INVALID_RESPONSE") from exc
        usage = payload_data.get("usage") if isinstance(payload_data, dict) else {}
        return ModelResponse(text=text, provider=definition.provider, model=definition.model, usage=usage if isinstance(usage, dict) else {}, raw_status=status)

    def health_check(self, definition: ModelDefinition) -> dict[str, Any]:
        key = os.getenv(definition.api_key_env, "") if definition.api_key_env else ""
        return {"status": "configured" if definition.base_url and (not definition.api_key_env or key) else "missing_configuration", "provider": definition.provider, "model": definition.model}

    @staticmethod
    def _url(base_url: str) -> str:
        root = base_url.rstrip("/")
        return root if root.endswith("/chat/completions") else f"{root}/chat/completions" if root.endswith("/v1") else f"{root}/v1/chat/completions"

    @staticmethod
    def _extract_text(data: Any) -> str:
        if isinstance(data, dict):
            choices = data.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                message = choices[0].get("message")
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    return message["content"]
            message = data.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]
            if isinstance(data.get("response"), str):
                return data["response"]
        raise KeyError("content")
