"""Read-only source projections for the planning control layer."""
from __future__ import annotations

from typing import Any

from core.project_context import ProjectContext
from system.data_store import DataStore

from .models import SOURCE_TYPES, content_hash

AUTHORITY_ORDER = (
    "confirmed_canon",
    "author_lock",
    "author_confirmed_planning_control",
    "story_blueprint",
    "state",
    "creative_loop_proposal",
    "inference",
)


class SourceService:
    def __init__(self, context: ProjectContext) -> None:
        self.context, self.store = context, DataStore(context)

    def ref(self, source_type: str, source_path: str, entity_type: str = "", entity_id: str = "", field: str = "", value: Any = None) -> dict[str, Any]:
        if source_type not in SOURCE_TYPES:
            raise ValueError("PLANNING_SOURCE_NOT_FOUND")
        return {"source_type": source_type, "source_path": source_path, "entity_type": entity_type, "entity_id": str(entity_id), "field": field, "content_hash": content_hash(value), "canon_version_id": None, "proposal_id": None, "status": "current"}

    @staticmethod
    def authority_order() -> list[str]:
        """Public, deterministic precedence without granting automatic write authority."""
        return list(AUTHORITY_ORDER)

    def blueprint_projection(self) -> dict[str, Any]:
        blueprint = self.store.read_json(self.context.data_dir / "story_blueprint.json", default={}, expected_type=dict) or {}
        fields = {key: blueprint.get(key) for key in ("core_conflict", "ending_direction", "main_arc", "title") if blueprint.get(key) not in (None, "")}
        return {"fields": fields, "story_phases": blueprint.get("story_phases", []) or [], "volumes": blueprint.get("volumes", []) or [], "source_ref": self.ref("story_blueprint", "data/story_blueprint.json", value=blueprint)}

    def phase_exists(self, reference: dict[str, Any]) -> bool:
        if reference.get("source_type") != "story_blueprint" or reference.get("entity_type") != "story_phase":
            return bool(reference.get("manual_scope"))
        target = str(reference.get("entity_id"))
        return any(str(item.get("phase_id", item.get("id", ""))) == target for item in self.blueprint_projection()["story_phases"] if isinstance(item, dict))

    def volume_exists(self, reference: dict[str, Any]) -> bool:
        if reference.get("manual_scope"):
            return True
        target = str(reference.get("entity_id", reference.get("volume_id", "")))
        return any(str(item.get("volume_id", item.get("id", ""))) == target for item in self.blueprint_projection()["volumes"] if isinstance(item, dict))
