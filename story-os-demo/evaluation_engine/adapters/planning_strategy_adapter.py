"""Normalize existing planning strategy output without re-evaluating it."""
from __future__ import annotations

from typing import Any


def adapt(control: dict[str, Any]) -> dict[str, Any]:
    strategy = control.get("strategy")
    return {"strategy": strategy if isinstance(strategy, dict) else {}}
