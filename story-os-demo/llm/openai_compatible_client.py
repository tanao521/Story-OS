from __future__ import annotations

from typing import Any


class OpenAICompatibleClient:
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def chat_text(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        if not self.base_url:
            raise ValueError("OpenAI-compatible base_url 未配置。")
        if not self.model:
            raise ValueError("OpenAI-compatible model 未配置。")

        try:
            import requests
        except ImportError as exc:
            raise RuntimeError("缺少 requests 依赖，请先安装 requirements.txt。") from exc

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        try:
            response = requests.post(
                self._chat_completions_url(),
                headers=headers,
                json=payload,
                timeout=120,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise RuntimeError(f"OpenAI-compatible 请求失败：{exc}") from exc

        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("OpenAI-compatible 响应格式不符合预期。") from exc

    def _chat_completions_url(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"
