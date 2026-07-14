"""Health score derived from reflections and existing local reports, never market data."""
from __future__ import annotations

from typing import Any

from core.project_context import ProjectContext
from creative_loop.models import now_iso, score_100
from creative_loop.lifecycle import LifecycleService
from system.data_store import DataStore


class HealthService:
    DIMENSIONS = ("narrative_consistency", "character_consistency", "world_rule_stability", "plot_momentum", "conflict_effectiveness", "pacing_balance", "foreshadowing_health", "reader_engagement", "planning_alignment", "author_style_alignment")
    def __init__(self, context: ProjectContext) -> None: self.context, self.store = context, DataStore(context)

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.store.read_json("data/creative_loop/health/history.json", default=[], expected_type=list) or []
        return list(rows)[-max(1, min(limit, 100)):]

    def latest(self) -> dict[str, Any] | None:
        rows = self.history(1)
        return rows[-1] if rows else None

    def calculate(self, reflection: dict[str, Any]) -> dict[str, Any]:
        chapter = int(reflection["chapter_id"]); analytics = self.store.read_json(f"data/story_analytics/chapters/chapter_{chapter:03d}.json", default={}, expected_type=dict) or {}
        score = analytics.get("score", {}) if isinstance(analytics.get("score"), dict) else {}
        quality = score_100(reflection.get("goal_completion", {}).get("score"))
        values: dict[str, int | None] = {
            "narrative_consistency": quality, "character_consistency": score_100(score.get("character_score")),
            "world_rule_stability": score_100(score.get("world_score")), "plot_momentum": score_100(score.get("pacing_score")),
            "conflict_effectiveness": score_100(score.get("conflict_score")), "pacing_balance": score_100(score.get("pacing_score")),
            "foreshadowing_health": None, "reader_engagement": score_100(score.get("hook_score")),
            "planning_alignment": quality, "author_style_alignment": None,
        }
        known = [value for value in values.values() if value is not None]
        overall = round(sum(known) / len(known)) if known else None
        confidence = round(len(known) / len(values), 2)
        source_map = {
            "narrative_consistency": ["chapter_reflection"], "character_consistency": ["chapter_reflection", "chapter_analytics"],
            "world_rule_stability": ["chapter_reflection", "chapter_analytics"], "plot_momentum": ["chapter_reflection", "chapter_analytics"],
            "conflict_effectiveness": ["chapter_analytics"], "pacing_balance": ["chapter_analytics"],
            "reader_engagement": ["chapter_analytics"], "planning_alignment": ["chapter_reflection"],
        }
        dimension_details = {key: {"score": value, "source": source_map.get(key, []), "confidence": (round(0.8 * confidence, 2) if value is not None else 0.0)} for key, value in values.items()}
        health = {"schema_version": "13.1", "health_id": f"health_{reflection['reflection_id']}", "project_id": self.context.root.name, "chapter_id": chapter, "canon_version_id": reflection["canon_version_id"], "overall": overall, "confidence": confidence, "available_dimensions": len(known), "missing_dimensions": [key for key, value in values.items() if value is None], "status": "ok" if overall is not None else "insufficient_data", "dimensions": values, "dimension_details": dimension_details, "dimension_sources": {key: detail["source"] for key, detail in dimension_details.items()}, "warnings": [f"{key} 数据不足" for key, value in values.items() if value is None], "data_quality": {"available_dimensions": len(known), "total_dimensions": len(values), "confidence": confidence}, "created_at": now_iso()}
        rows = self.store.read_json("data/creative_loop/health/history.json", default=[], expected_type=list) or []
        rows = [row for row in rows if row.get("canon_version_id") != health["canon_version_id"]] + [health]
        self.store.write_json("data/creative_loop/health/history.json", rows, backup=True)
        self.store.write_json(f"data/creative_loop/health/chapter_{chapter:03d}.json", health, backup=True)
        LifecycleService(self.context).audit("health_updated", entity_type="health", entity_id=health["health_id"], operator="system", details={"chapter_id": chapter, "confidence": confidence})
        return health
