"""Read-only helpers for the rolling-window and schedule boundary."""
from __future__ import annotations

from typing import Any

from core.project_context import ProjectContext

from .scheduling_service import NarrativeSchedulingService


def slot_schedule_summary(context: ProjectContext, slot_id: str) -> dict[str, Any]:
    return NarrativeSchedulingService(context).by_slot(slot_id)
