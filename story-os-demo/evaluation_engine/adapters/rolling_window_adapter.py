"""Expose rolling-window service output as planning-evaluation evidence."""
from __future__ import annotations

from typing import Any


def adapt(window: dict[str, Any] | None, health: dict[str, Any]) -> dict[str, Any]:
    return {"window": window if isinstance(window, dict) else {}, "health": health if isinstance(health, dict) else {}}
