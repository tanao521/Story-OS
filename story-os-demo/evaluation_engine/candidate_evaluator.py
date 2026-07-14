"""Local candidate re-evaluation; it never reuses baseline scores as candidate scores."""
from __future__ import annotations

from typing import Any

from system.quality_checker import build_quality_report
from .adapters import quality_report_adapter
from .models import DimensionScore, public
from .profiles import profile
from .scoring import weighted_score


def evaluate_candidate(context: Any, chapter_id: int, text: str, profile_id: str) -> dict[str, Any]:
    store = __import__("system.data_store", fromlist=["DataStore"]).DataStore(context)
    plan = store.read_json("data/next_chapter_plan.json", default={}, expected_type=dict) or {}
    load = lambda name: store.read_json(f"data/{name}.json", default={}, expected_type=dict) or {}
    quality = build_quality_report({"chapter_id": chapter_id, "manual_text": text}, "improvement_candidate", 1,
                                   "candidate", plan, load("story_spec"), load("characters"), load("world_bible"), load("state"), use_llm=False)
    selected = profile(profile_id) or profile("chapter-default-v1")
    rows = quality_report_adapter.adapt(quality, "candidate_local_quality")
    dimensions = []
    for spec in selected["dimensions"]:
        row = rows.get(spec["dimension_id"], {})
        dimensions.append(DimensionScore(dimension_id=spec["dimension_id"], display_name=spec["display_name"], weight=float(spec["weight"]), score=row.get("score"), confidence=float(row.get("confidence", 0)), status="available" if row.get("score") is not None else "not_recomputed", source_type=str(row.get("source_type", "not_recomputed")), evidence=row.get("evidence", []), issues=row.get("issues", []), suggestions=row.get("suggestions", [])))
    score, confidence = weighted_score(dimensions)
    return {"target_type": "chapter_candidate", "profile_id": selected["profile_id"], "overall_score": score,
            "confidence": confidence, "dimensions": public(dimensions), "quality_report": quality,
            "unavailable_dimensions": [item.dimension_id for item in dimensions if item.status != "available"],
            "recomputed_with": "local_quality_rules"}
