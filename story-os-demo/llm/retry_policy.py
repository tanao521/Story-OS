"""Small bounded retry policy; never retry authentication or invalid requests."""
from __future__ import annotations

import time
from typing import Callable, TypeVar

from llm.model_models import ModelGatewayError

T = TypeVar("T")


def is_recoverable(error: Exception) -> bool:
    if isinstance(error, ModelGatewayError):
        return bool(error.recoverable)
    text = str(error).lower()
    return any(token in text for token in ("timeout", "timed out", "connection", "429", "502", "503", "504")) and not any(token in text for token in ("401", "403", "404", "invalid", "context length", "cancel"))


def retry_call(call: Callable[[], T], *, attempts: int = 2, on_retry: Callable[[int, Exception], None] | None = None) -> T:
    last: Exception | None = None
    for index in range(max(1, attempts)):
        try:
            return call()
        except Exception as exc:
            last = exc
            if index + 1 >= max(1, attempts) or not is_recoverable(exc):
                raise
            if on_retry:
                on_retry(index + 1, exc)
            time.sleep(min(0.25 * (2 ** index), 1.0))
    assert last is not None
    raise last
