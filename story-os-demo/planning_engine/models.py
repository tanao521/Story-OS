"""Small schema helpers shared by the planning control services."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = "1.0"
MILESTONE_TYPES = {"plot", "character", "relationship", "world", "mystery", "antagonist", "power_progression", "foreshadowing", "emotional", "ending", "custom"}
MILESTONE_STATUSES = {"planned", "prepared", "achieved", "delayed", "cancelled", "replaced"}
SOURCE_TYPES = {"story_blueprint", "state", "structured_planning", "confirmed_narrative_memory", "creative_loop_proposal", "manual"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def content_hash(value: Any) -> str:
    import json
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def base_entity(project_id: str, entity_id: str | None = None) -> dict[str, Any]:
    stamp = now()
    return {"schema_version": SCHEMA_VERSION, "project_id": project_id, "id": entity_id or new_id("pc"), "created_at": stamp, "updated_at": stamp, "created_by": "user", "source_refs": [], "author_confirmed_at": None, "version_id": ""}
