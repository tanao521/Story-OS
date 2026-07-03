from __future__ import annotations

from typing import Any

import requests

from llm.json_utils import extract_json_from_text


class DeepSeekError(Exception):
    pass


class DeepSeekClient:
    def __init__(self, api_key: str, model: str, base_url: str = "https://api.deepseek.com") -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    def chat_text(self, prompt: str, temperature: float = 0.4) -> str:
        if not self.api_key:
            raise DeepSeekError("DEEPSEEK_API_KEY 未配置。")
        if not self.model:
            raise DeepSeekError("DEEPSEEK_MODEL 未配置。")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        try:
            response = requests.post(self._chat_url(), headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            return str(data["choices"][0]["message"]["content"])
        except Exception as exc:
            raise DeepSeekError(f"DeepSeek 请求失败：{exc}") from exc

    def chat_json(self, prompt: str, temperature: float = 0.4) -> dict[str, Any]:
        text = self.chat_text(prompt, temperature=temperature)
        data = extract_json_from_text(text)
        if not data:
            raise DeepSeekError("DeepSeek 返回内容不是可解析 JSON。")
        return data

    def _chat_url(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"
