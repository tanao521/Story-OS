"""Data rules for Stage 14.2 rolling planning windows."""
from __future__ import annotations

from typing import Any

from .models import base_entity, new_id, now

WINDOW_STATUSES = {"draft", "active", "needs_roll_forward", "stale", "reanchor_required", "archived", "invalid"}
SLOT_STATUSES = {"open", "outlined", "reviewed", "elapsed", "archived", "cancelled"}
DETAIL_LEVELS = {"placeholder", "outline", "detailed"}
SLOT_FUNCTIONS = {"setup", "escalation", "confrontation", "reveal", "payoff", "reversal", "character_development", "relationship", "exploration", "recovery", "transition", "climax", "aftermath", "mystery", "world_expansion", "custom"}


def make_slot(project_id: str, chapter: int, horizon: str) -> dict[str, Any]:
    item = base_entity(project_id, new_id("slot"))
    item.update({"slot_id": item["id"], "planned_chapter_number": chapter, "horizon": horizon, "detail_level": "outline" if horizon == "near" else "placeholder", "title_hint": "", "primary_function": "transition", "goal_summary": "", "main_event_intent": [], "conflict_intent": "", "character_focus_refs": [], "milestone_refs": [], "volume_contract_ref": None, "phase_contract_ref": None, "plot_thread_refs": [], "foreshadow_refs": [], "preserve_requirements": [], "avoid_requirements": [], "author_notes": "", "status": "open", "locked": False})
    if horizon == "mid":
        for key in ("main_event_intent", "conflict_intent", "volume_contract_ref", "phase_contract_ref", "foreshadow_refs", "preserve_requirements", "avoid_requirements"):
            item.pop(key, None)
    return item


def validate_configuration(near: Any, mid: Any) -> tuple[int, int]:
    try:
        near_value, mid_value = int(near), int(mid)
    except (TypeError, ValueError) as exc:
        raise ValueError("ROLLING_WINDOW_CONFIGURATION_INVALID") from exc
    if not 3 <= near_value <= 5 or not 6 <= mid_value <= 15:
        raise ValueError("ROLLING_WINDOW_CONFIGURATION_INVALID")
    return near_value, mid_value


def validate_slot(slot: dict[str, Any]) -> None:
    if slot.get("horizon") not in {"near", "mid"} or slot.get("status") not in SLOT_STATUSES:
        raise ValueError("CHAPTER_SLOT_INVALID")
    if slot.get("detail_level") not in DETAIL_LEVELS or slot.get("primary_function") not in SLOT_FUNCTIONS:
        raise ValueError("CHAPTER_SLOT_INVALID")
    if slot["horizon"] == "mid" and slot.get("detail_level") == "detailed":
        raise ValueError("CHAPTER_SLOT_DETAIL_LEVEL_INVALID")
    if int(slot.get("planned_chapter_number", 0) or 0) < 1:
        raise ValueError("CHAPTER_SLOT_INVALID")
    slot["updated_at"] = now()
