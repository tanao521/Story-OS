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

        if self._is_ollama_base_url():
            return self._ollama_chat_text(requests, prompt, temperature, max_tokens)

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
            raise RuntimeError(f"OpenAI-compatible \u8bf7\u6c42\u5931\u8d25\uff1a{exc}") from exc

        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("OpenAI-compatible \u54cd\u5e94\u683c\u5f0f\u4e0d\u7b26\u5408\u9884\u671f\u3002") from exc

    def _ollama_chat_text(
        self,
        requests_module: Any,
        prompt: str,
        temperature: float,
        max_tokens: int | None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
            "options": {"temperature": temperature},
        }
        if max_tokens is not None:
            payload["options"]["num_predict"] = max_tokens
        try:
            response = requests_module.post(
                self._ollama_chat_url(),
                json=payload,
                timeout=600,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise RuntimeError(f"Ollama \u8bf7\u6c42\u5931\u8d25\uff1a{exc}") from exc
        try:
            return str(data["message"]["content"])
        except (KeyError, TypeError) as exc:
            raise RuntimeError("Ollama \u54cd\u5e94\u683c\u5f0f\u4e0d\u7b26\u5408\u9884\u671f\u3002") from exc

    def _is_ollama_base_url(self) -> bool:
        return "11434" in self.base_url or self.base_url.rstrip("/").endswith("/api")

    def _ollama_chat_url(self) -> str:
        root = self.base_url
        if root.endswith("/v1"):
            root = root[:-3]
        if root.endswith("/api"):
            return f"{root}/chat"
        return f"{root}/api/chat"

    def _chat_completions_url(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"
