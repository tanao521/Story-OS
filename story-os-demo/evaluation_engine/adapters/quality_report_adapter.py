from __future__ import annotations

from typing import Any
from .common import evidence, issue


QUALITY_MAP = {
    "story_goal_alignment": "plan_completion", "continuity": "continuity", "character_voice": "character_consistency",
    "style_naturalness": "prose_readability", "anti_ai_style": "prose_readability", "pacing": "pacing_tension",
    "hook_strength": "ending_drive", "readability": "prose_readability",
}


def adapt(report: dict[str, Any], source_ref: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    scores = report.get("scores", {}) if isinstance(report.get("scores"), dict) else {}
    flags = report.get("flags", []) if isinstance(report.get("flags"), list) else []
    suggestions = [str(item) for item in report.get("suggestions", []) if str(item).strip()]
    for source_key, value in scores.items():
        dimension = QUALITY_MAP.get(str(source_key))
        if not dimension:
            continue
        try: score = max(0.0, min(100.0, float(value) * 100))
        except (TypeError, ValueError): continue
        matched = [issue("quality_report", flag, dimension=dimension, default_type=str(source_key)) for flag in flags if str((flag or {}).get("type", "")) == str(source_key)]
        result[dimension] = {"score": score, "confidence": 0.78, "source_type": "quality_report", "evidence": [evidence("quality_report", source_ref, f"{source_key}={score:.1f}")], "issues": matched, "suggestions": suggestions}
    reader = report.get("reader_simulation", {}) if isinstance(report.get("reader_simulation"), dict) else {}
    mapping = {"plot_progression": reader.get("engagement_score"), "pacing_tension": reader.get("engagement_score"), "ending_drive": report.get("scores", {}).get("hook_strength") if isinstance(report.get("scores"), dict) else None}
    for dimension, value in mapping.items():
        if dimension in result or value is None: continue
        try: score = max(0.0, min(100.0, float(value) * 100))
        except (TypeError, ValueError): continue
        result[dimension] = {"score": score, "confidence": 0.62, "source_type": "reader_simulation", "evidence": [evidence("reader_simulation", source_ref, f"existing reader signal={score:.1f}", reliability=.62)], "issues": [], "suggestions": []}
    return result
