"""Small explainable creative evaluation helpers; no model call is required."""
from __future__ import annotations

from typing import Any


class CreativeEvaluator:
    dimensions = ("logic", "hook", "emotion", "innovation", "commercial", "character_consistency")

    def evaluate(self, text: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        content = str(text or "")
        length = len(content)
        punctuation = sum(content.count(mark) for mark in "!?！？")
        score = min(100, 35 + min(35, length // 80) + min(10, punctuation * 2))
        values = {
            "logic": min(100, score + (5 if "because" in content.lower() or "因为" in content else 0)),
            "hook": min(100, score + min(8, punctuation * 2)),
            "emotion": min(100, score + (6 if any(x in content for x in ("爱", "害怕", "痛", "泪", "fear")) else 0)),
            "innovation": max(20, score - 4),
            "commercial": min(100, score + 2),
            "character_consistency": min(100, score + (4 if (context or {}).get("characters") else 0)),
        }
        return {
            "scores": values,
            "average": round(sum(values.values()) / len(values), 1),
            "method": "规则评分",
            "notes": ["评分只用于辅助审核，不会自动认可或提交内容。"],
        }
