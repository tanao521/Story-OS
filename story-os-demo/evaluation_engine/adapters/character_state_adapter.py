from __future__ import annotations

from typing import Any
from .common import evidence


def adapt(state: dict[str, Any], source_ref: str) -> dict[str, Any]:
    if not state: return {}
    return {"score": None, "confidence": .35, "source_type": "character_state", "evidence": [evidence("character_state", source_ref, "Confirmed character state is available; no standalone score is inferred.", reliability=.65)], "issues": [], "suggestions": []}
