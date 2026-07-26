from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"
MARKER_FILENAME = ".storyos-binding.json"


class BindingStatus(Enum):
    UNBOUND = "unbound"
    BOUND = "bound"
    INVALID = "invalid"
    CONFLICT = "conflict"
    MISSING_VAULT = "missing_vault"
    MISSING_TARGET = "missing_target"
    MARKER_MISMATCH = "marker_mismatch"


@dataclass(frozen=True)
class ObsidianBinding:
    binding_id: str
    project_id: str
    timeline_id: str
    vault_root: Path
    target_relative_path: str
    status: BindingStatus
    created_at: datetime
    updated_at: datetime
    schema_version: str = SCHEMA_VERSION

    @property
    def target_full_path(self) -> Path:
        return self.vault_root / self.target_relative_path

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "project_id": self.project_id,
            "timeline_id": self.timeline_id,
            "vault_root": self.vault_root.as_posix(),
            "target_relative_path": self.target_relative_path,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ObsidianBinding:
        return cls(
            binding_id=data["binding_id"],
            project_id=data["project_id"],
            timeline_id=data["timeline_id"],
            vault_root=Path(data["vault_root"]).resolve(),
            target_relative_path=data["target_relative_path"],
            status=BindingStatus(data["status"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class BindingMarker:
    managed_by: str = "story-os"
    project_id: str = ""
    timeline_id: str = ""
    binding_id: str = ""
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "managed_by": self.managed_by,
            "project_id": self.project_id,
            "timeline_id": self.timeline_id,
            "binding_id": self.binding_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BindingMarker:
        return cls(
            managed_by=data.get("managed_by", "story-os"),
            project_id=data.get("project_id", ""),
            timeline_id=data.get("timeline_id", ""),
            binding_id=data.get("binding_id", ""),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )