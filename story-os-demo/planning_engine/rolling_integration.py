"""Best-effort notifications from canon operations into rolling planning."""
from __future__ import annotations

from core.project_context import ProjectContext


def mark_anchor_changed(context: ProjectContext, reason: str) -> dict[str, object]:
    """Never raise into a canon operation; the rolling window is advisory only."""
    try:
        from .rolling_service import RollingWindowService
        return RollingWindowService(context).mark_anchor_changed(reason)
    except Exception as exc:
        return {"changed": False, "warning": f"Rolling window status check failed: {str(exc)[:160]}"}


def mark_rolling_window_dirty(context: ProjectContext, reason: str) -> dict[str, object]:
    """Lifecycle name for canon hooks; only records a health-derived status."""
    return mark_anchor_changed(context, reason)
