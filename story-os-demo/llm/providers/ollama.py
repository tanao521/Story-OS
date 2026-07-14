from __future__ import annotations

from typing import Any

from llm.model_models import ModelDefinition, ModelGatewayError, ModelRequest, ModelResponse
from llm.providers.openai_compatible import OpenAICompatibleProvider


class OllamaProvider(OpenAICompatibleProvider):
    def generate(self, definition: ModelDefinition, request: ModelRequest) -> ModelResponse:
        root = definition.base_url.rstrip("/")
        if root.endswith("/v1"):
            root = root[:-3]
        url = f"{root}/chat" if root.endswith("/api") else f"{root}/api/chat"
        payload: dict[str, Any] = {"model": definition.model, "messages": [{"role": "user", "content": request.prompt}], "stream": False, "think": False, "options": {"temperature": request.temperature}}
        if request.max_tokens is not None:
            payload["options"]["num_predict"] = request.max_tokens
        try:
            response = self.post(url, json=payload, timeout=definition.timeout_seconds)
        except Exception as exc:
            raise ModelGatewayError("Ollama network request failed.", code="NETWORK_ERROR", recoverable=True) from exc
        status = int(getattr(response, "status_code", 200) or 200)
        if status >= 400:
            raise ModelGatewayError(f"Ollama returned HTTP {status}.", code=f"HTTP_{status}", recoverable=status in {429, 502, 503, 504})
        try:
            data = response.json(); text = str(data["message"]["content"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelGatewayError("Ollama response format was invalid.", code="INVALID_RESPONSE") from exc
        usage = {"prompt_tokens": data.get("prompt_eval_count"), "completion_tokens": data.get("eval_count")}
        usage = {key: value for key, value in usage.items() if isinstance(value, int)}
        if usage: usage["total_tokens"] = sum(usage.values())
        return ModelResponse(text=text, provider=definition.provider, model=definition.model, usage=usage, raw_status=status)
