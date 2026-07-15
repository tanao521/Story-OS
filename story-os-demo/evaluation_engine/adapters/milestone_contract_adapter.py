"""Normalize control-service milestones and contracts for evidence consumers."""
from __future__ import annotations

from typing import Any


def adapt(control: dict[str, Any]) -> dict[str, Any]:
    def rows(key: str) -> list[dict[str, Any]]:
        value = control.get(key)
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    return {"milestones": rows("milestones"), "volume_contracts": rows("volume_contracts"), "phase_contracts": rows("phase_contracts")}
