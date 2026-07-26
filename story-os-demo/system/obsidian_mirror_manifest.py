from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST_FILENAME = ".storyos-sync-manifest.json"
MANIFEST_SCHEMA_VERSION = "1.0"


@dataclass
class MirrorManifestEntry:
    source_id: str
    content_hash: str
    size_bytes: int
    last_synced_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MirrorManifestEntry":
        return cls(
            source_id=data["source_id"],
            content_hash=data["content_hash"],
            size_bytes=data["size_bytes"],
            last_synced_at=data["last_synced_at"],
        )


@dataclass
class MirrorManifest:
    schema_version: str
    binding_id: str
    project_id: str
    timeline_id: str
    generated_at: str
    files: dict[str, MirrorManifestEntry] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "binding_id": self.binding_id,
            "project_id": self.project_id,
            "timeline_id": self.timeline_id,
            "generated_at": self.generated_at,
            "files": {k: v.to_dict() for k, v in self.files.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MirrorManifest":
        files = {
            k: MirrorManifestEntry.from_dict(v)
            for k, v in data.get("files", {}).items()
        }
        return cls(
            schema_version=data.get("schema_version", ""),
            binding_id=data.get("binding_id", ""),
            project_id=data.get("project_id", ""),
            timeline_id=data.get("timeline_id", ""),
            generated_at=data.get("generated_at", ""),
            files=files,
        )

    def validate_identity(self, binding_id: str, project_id: str, timeline_id: str) -> bool:
        return (
            self.binding_id == binding_id
            and self.project_id == project_id
            and self.timeline_id == timeline_id
        )


class MirrorManifestStore:
    def __init__(self, target_dir: Path) -> None:
        self.target_dir = target_dir
        self.manifest_path = target_dir / MANIFEST_FILENAME

    def load(self) -> MirrorManifest | None:
        if not self.manifest_path.exists():
            return None
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            return MirrorManifest.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

    def save(self, manifest: MirrorManifest) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.manifest_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(self.manifest_path)

    def delete(self) -> None:
        if self.manifest_path.exists():
            self.manifest_path.unlink()


class ManifestValidationError(Exception):
    pass


def compute_content_hash(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def build_empty_manifest(binding_id: str, project_id: str, timeline_id: str) -> MirrorManifest:
    return MirrorManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        binding_id=binding_id,
        project_id=project_id,
        timeline_id=timeline_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        files={},
    )