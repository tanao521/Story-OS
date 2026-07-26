"""OpenAI-compatible adapter for Model Persona execution.

Exactly one HTTP request per call. No retry, no fallback, no second JSON-repair call.
Does NOT receive ProjectContext. Does NOT read files.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional
from urllib.parse import urlsplit, urlunsplit

from core.contracts.model_persona_execution import GenerationParameters


class OpenAIProviderAuthError(Exception):
    code = "PROVIDER_AUTH_ERROR"


class OpenAIProviderRateLimitError(Exception):
    code = "PROVIDER_RATE_LIMITED"


class OpenAIProviderTimeoutError(Exception):
    code = "PROVIDER_TIMEOUT"


class OpenAIProviderError(Exception):
    code = "PROVIDER_ERROR"


def _chat_url_for_base(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/chat/completions"):
        return root
    if root.endswith("/v1"):
        return f"{root}/chat/completions"
    return f"{root}/v1/chat/completions"


def normalized_endpoint_identity(base_url: str) -> str:
    """Return a non-reversible identity for the effective chat endpoint."""
    parsed = urlsplit(_chat_url_for_base(base_url))
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    rendered_host = f"[{hostname}]" if ":" in hostname else hostname
    port = parsed.port
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        rendered_host = f"{rendered_host}:{port}"
    normalized = urlunsplit(
        (scheme, rendered_host, parsed.path.rstrip("/"), "", "")
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class OpenAIProviderResponse:
    text: str
    usage: Optional[dict[str, Any]] = None
    duration_ms: Optional[int] = None
    provider_request_id: Optional[str] = None


class OpenAICompatibleModelPersonaProvider:
    """Single-request OpenAI-compatible provider for model persona feedback.

    Guarantees: exactly one HTTP request, no retry, no fallback, no second call.
    Never receives ProjectContext. Never reads project files.
    """

    provider_type = "openai_compatible"
    protocol_version = "chat-completions-v1"

    def __init__(
        self,
        *,
        provider_id: str,
        model_id: str,
        api_key: str,
        base_url: str,
        post: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.provider_id = provider_id
        self.model_id = model_id
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._post = post or self._default_post

    @staticmethod
    def _default_post(*args: Any, **kwargs: Any) -> Any:
        try:
            import requests
        except ImportError as exc:
            raise OpenAIProviderError(
                "requests library not available"
            ) from exc
        return requests.post(*args, **kwargs)

    @property
    def endpoint_identity(self) -> str:
        return normalized_endpoint_identity(self._base_url)

    def generate(self, request: Any) -> OpenAIProviderResponse:
        """Send exactly one chat completions request.

        ``request`` follows the structural ProviderRequest contract owned by the
        execution service. The adapter never receives project context or paths.
        """
        url = self._chat_url()
        system_prompt = request.system_prompt
        user_prompt = request.user_prompt
        generation_parameters: GenerationParameters = request.generation_parameters
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = request.canonical_payload()

        timeout = generation_parameters.timeout_seconds

        started = time.perf_counter()
        try:
            response = self._post(
                url,
                json=payload,
                headers=headers,
                timeout=timeout,
                allow_redirects=False,
            )
        except Exception as exc:
            text = str(exc).lower()
            if "timeout" in text or "timed out" in text:
                raise OpenAIProviderTimeoutError("Provider request timed out") from exc
            raise OpenAIProviderError("Provider network request failed") from exc

        duration_ms = int((time.perf_counter() - started) * 1000)

        status_code = int(getattr(response, "status_code", 200) or 200)
        if status_code < 200 or status_code >= 300:
            self._raise_for_status(status_code, response)

        try:
            data = response.json()
        except (ValueError, AttributeError) as exc:
            raise OpenAIProviderError("Provider returned non-JSON response") from exc

        content = self._extract_content(data)
        usage = self._extract_usage(data)
        request_id = self._extract_request_id(response, data)

        return OpenAIProviderResponse(
            text=content,
            usage=usage,
            duration_ms=duration_ms,
            provider_request_id=request_id,
        )

    def _chat_url(self) -> str:
        return _chat_url_for_base(self._base_url)

    @staticmethod
    def _raise_for_status(status_code: int, response: Any) -> None:
        if status_code == 401 or status_code == 403:
            raise OpenAIProviderAuthError(f"Provider authentication failed (HTTP {status_code})")
        if status_code == 429:
            raise OpenAIProviderRateLimitError(f"Provider rate limited (HTTP {status_code})")
        if status_code in (502, 503, 504):
            raise OpenAIProviderError(f"Provider upstream error (HTTP {status_code})")
        if status_code >= 500:
            raise OpenAIProviderError(f"Provider server error (HTTP {status_code})")
        raise OpenAIProviderError(f"Provider request failed (HTTP {status_code})")

    @staticmethod
    def _extract_content(data: Any) -> str:
        if not isinstance(data, dict):
            raise OpenAIProviderError("Provider response is not a dict")
        choices = data.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]
        raise OpenAIProviderError("Provider response has no message content")

    @staticmethod
    def _extract_usage(data: Any) -> Optional[dict[str, Any]]:
        if not isinstance(data, dict):
            return None
        usage = data.get("usage")
        if not isinstance(usage, dict):
            return None
        result: dict[str, Any] = {}
        if isinstance(usage.get("prompt_tokens"), int):
            result["input_tokens"] = usage["prompt_tokens"]
        if isinstance(usage.get("completion_tokens"), int):
            result["output_tokens"] = usage["completion_tokens"]
        if isinstance(usage.get("total_tokens"), int):
            result["total_tokens"] = usage["total_tokens"]
        if not result:
            return None
        return result

    @staticmethod
    def _extract_request_id(response: Any, data: Any) -> Optional[str]:
        headers = getattr(response, "headers", None)
        if headers:
            rid = headers.get("x-request-id") or headers.get("x-ratelimit-request-id")
            if isinstance(rid, str) and rid:
                return rid[:64]
        if isinstance(data, dict):
            rid = data.get("id")
            if isinstance(rid, str) and rid:
                return rid[:64]
        return None
