"""Validated creative-loop lifecycle transitions with project-local audit trails."""
from __future__ import annotations

from typing import Any

from core.project_context import ProjectContext
from creative_loop.models import new_id, now_iso
from system.data_store import DataStore


REFLECTION_STATUSES = {"pending", "running", "completed", "failed", "expired"}
PROPOSAL_STATUSES = {"pending", "reviewing", "modified", "accepted", "partially_accepted", "rejected", "expired", "applied", "cancelled"}
EXPERIMENT_STATUSES = {"draft", "generating", "evaluating", "waiting_author", "selected", "archived", "failed", "cancelled"}

TRANSITIONS = {
    "reflection": {"pending": {"running", "failed", "expired"}, "running": {"completed", "failed", "expired"}, "completed": set(), "failed": set(), "expired": set()},
    "proposal": {"pending": {"reviewing", "modified", "accepted", "partially_accepted", "rejected", "expired", "cancelled"}, "reviewing": {"modified", "accepted", "partially_accepted", "rejected", "expired", "cancelled"}, "modified": {"reviewing", "accepted", "partially_accepted", "rejected", "expired", "cancelled"}, "accepted": {"applied", "cancelled"}, "partially_accepted": {"applied", "cancelled"}, "rejected": set(), "expired": set(), "applied": set(), "cancelled": set()},
    "experiment": {"draft": {"generating", "cancelled", "archived"}, "generating": {"evaluating", "waiting_author", "failed", "cancelled"}, "evaluating": {"waiting_author", "failed", "cancelled"}, "waiting_author": {"selected", "archived", "cancelled"}, "selected": {"archived"}, "archived": set(), "failed": set(), "cancelled": set()},
}


class LifecycleError(ValueError):
    code = "CREATIVE_LOOP_STATE_INVALID"


class LifecycleService:
    def __init__(self, context: ProjectContext) -> None:
        self.context, self.store = context, DataStore(context)

    def transition(self, record: dict[str, Any], entity_type: str, new_status: str, *, operator: str, reason: str = "") -> dict[str, Any]:
        allowed = TRANSITIONS.get(entity_type, {})
        old_status = str(record.get("status") or "")
        if old_status not in allowed or new_status not in allowed.get(old_status, set()):
            raise LifecycleError(f"Illegal {entity_type} transition: {old_status} -> {new_status}")
        event = {"id": new_id("event"), "entity_type": entity_type, "entity_id": str(record.get(f"{entity_type}_id") or record.get("reflection_id") or ""), "old_status": old_status, "new_status": new_status, "operator": operator, "time": now_iso(), "reason": reason[:1000]}
        record["status"] = new_status
        record["updated_at"] = event["time"]
        record.setdefault("status_history", []).append(event)
        self.store.ensure_directory(self.context.creative_events_dir)
        self.store.write_json(self.context.creative_events_dir / f"{event['id']}.json", event, backup=False)
        return event

    def audit(self, action: str, *, entity_type: str, entity_id: str, operator: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
        row = {"audit_id": new_id("audit"), "action": action, "entity_type": entity_type, "entity_id": entity_id, "operator": operator, "time": now_iso(), "details": details or {}}
        self.store.ensure_directory(self.context.creative_audit_dir)
        self.store.write_json(self.context.creative_audit_dir / f"{row['audit_id']}.json", row, backup=False)
        return row
