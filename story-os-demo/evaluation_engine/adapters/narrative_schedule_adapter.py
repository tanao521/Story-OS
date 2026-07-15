"""Expose schedule service results; validation remains the scheduler's job."""
from __future__ import annotations

from typing import Any


def adapt(description: dict[str, Any], health: dict[str, Any]) -> dict[str, Any]:
    return {"description": description if isinstance(description, dict) else {}, "health": health if isinstance(health, dict) else {}}
