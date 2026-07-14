"""Immutable snapshots for planning-control data only."""
from __future__ import annotations

from typing import Any

from core.project_context import ProjectContext
from system.data_store import DataStore

from .models import new_id, now


class VersionService:
    def __init__(self, context: ProjectContext) -> None:
        self.context, self.store = context, DataStore(context)

    def create(self, project_id: str, reason: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        version_id = new_id("planning_control")
        record = {"schema_version": "1.0", "project_id": project_id, "version_id": version_id, "created_at": now(), "reason": reason, "snapshot": snapshot}
        self.store.write_json(self.context.planning_control_versions_dir / f"{version_id}.json", record)
        return record

    def list(self) -> list[dict[str, Any]]:
        directory = self.context.planning_control_versions_dir
        if not directory.exists():
            return []
        values = [self.store.read_json(path, default={}, expected_type=dict) or {} for path in directory.glob("planning_control_*.json")]
        return sorted(({key: item.get(key) for key in ("version_id", "project_id", "created_at", "reason")} for item in values), key=lambda item: item.get("created_at", ""), reverse=True)

    def get(self, version_id: str) -> dict[str, Any] | None:
        return self.store.read_json(self.context.planning_control_versions_dir / f"{version_id}.json", default=None, expected_type=dict)
