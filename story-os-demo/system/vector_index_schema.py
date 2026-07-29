"""Vector index schema definitions for Phase 0C1 — project/timeline/canon isolation."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class CanonStatus(str, Enum):
    ACTIVE = "active"
    STALE = "stale"
    ARCHIVED = "archived"


class SourceType(str, Enum):
    CHAPTER = "chapter"
    SUMMARY = "summary"
    CHARACTER = "character"
    WORLD_BIBLE = "world_bible"


@dataclass(frozen=True)
class VectorScope:
    project_id: str
    timeline_id: str
    branch_id: str
    canon_revision_id: str

    def __post_init__(self) -> None:
        for name, value in (("project_id", self.project_id), ("timeline_id", self.timeline_id), ("branch_id", self.branch_id), ("canon_revision_id", self.canon_revision_id)):
            if not isinstance(value, str) or not value or value == ".." or "/" in value or "\\" in value:
                raise ValueError(f"VECTOR_SCOPE_REQUIRED:{name}")


@dataclass(frozen=True)
class VectorMetadata:
    schema_version: int = 2
    project_id: str = ""
    timeline_id: str = "main"
    branch_id: str = ""
    source_type: SourceType = SourceType.CHAPTER
    source_identity: str = ""
    source_path: str = ""
    chapter_id: int | None = None
    character_name: str = ""
    canon_status: CanonStatus = CanonStatus.ACTIVE
    canon_revision_id: str | None = None
    branch_lifecycle_status: str = "open"
    source_version_id: str = ""
    source_fingerprint: str = ""
    record_fingerprint: str = ""
    content_hash: str = ""
    indexed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        result = {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "timeline_id": self.timeline_id,
            "branch_id": self.branch_id,
            "source_type": self.source_type.value,
            "source_identity": self.source_identity,
            "source_path": self.source_path,
            "canon_status": self.canon_status.value,
            "content_hash": self.content_hash,
            "indexed_at": self.indexed_at,
            "branch_lifecycle_status": self.branch_lifecycle_status,
            "source_version_id": self.source_version_id,
            "source_fingerprint": self.source_fingerprint or self.content_hash,
            "record_fingerprint": self.record_fingerprint,
        }
        if self.chapter_id is not None:
            result["chapter_id"] = self.chapter_id
        if self.character_name:
            result["character_name"] = self.character_name
        if self.canon_revision_id:
            result["canon_revision_id"] = self.canon_revision_id
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VectorMetadata":
        return cls(
            schema_version=data.get("schema_version", 2),
            project_id=data.get("project_id", ""),
            timeline_id=data.get("timeline_id", "main"),
            branch_id=data.get("branch_id", ""),
            source_type=SourceType(data.get("source_type", "chapter")),
            source_identity=data.get("source_identity", ""),
            source_path=data.get("source_path", ""),
            chapter_id=data.get("chapter_id"),
            character_name=data.get("character_name", ""),
            canon_status=CanonStatus(data.get("canon_status", "active")),
            canon_revision_id=data.get("canon_revision_id"),
            branch_lifecycle_status=data.get("branch_lifecycle_status", "open"),
            source_version_id=data.get("source_version_id", ""),
            source_fingerprint=data.get("source_fingerprint", ""),
            record_fingerprint=data.get("record_fingerprint", ""),
            content_hash=data.get("content_hash", ""),
            indexed_at=data.get("indexed_at", ""),
        )


@dataclass(frozen=True)
class IndexManifest:
    schema_version: int = 2
    project_id: str = ""
    timeline_id: str = "main"
    last_rebuilt_at: str = ""
    document_count: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "timeline_id": self.timeline_id,
            "last_rebuilt_at": self.last_rebuilt_at,
            "document_count": self.document_count,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IndexManifest":
        return cls(
            schema_version=data.get("schema_version", 0),
            project_id=data.get("project_id", ""),
            timeline_id=data.get("timeline_id", "main"),
            last_rebuilt_at=data.get("last_rebuilt_at", ""),
            document_count=data.get("document_count", 0),
            warnings=data.get("warnings", []),
        )


_TIMELINE_ID_REGEX = re.compile(r"^[a-z0-9_][a-z0-9_-]{0,63}$")


def validate_timeline_id(timeline_id: str) -> bool:
    if not timeline_id or timeline_id == "..":
        return False
    if "/" in timeline_id or "\\" in timeline_id:
        return False
    if not _TIMELINE_ID_REGEX.match(timeline_id):
        return False
    return True


def compute_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def generate_document_id(
    project_id: str,
    timeline_id: str,
    source_type: SourceType,
    source_identity: str,
    chunk_index: int,
    content_hash: str,
) -> str:
    base = f"{project_id}/{timeline_id}/{source_type.value}/{source_identity}/{chunk_index}"
    h = hashlib.sha256(base.encode("utf-8")).hexdigest()[:12]
    return f"{source_type.value}_{h}_{content_hash[:8]}"


def generate_scoped_document_id(scope: VectorScope, source_type: SourceType, source_identity: str, chunk_index: int, source_fingerprint: str) -> str:
    authority = f"{scope.project_id}/{scope.timeline_id}/{scope.branch_id}/{scope.canon_revision_id}/{source_type.value}/{source_identity}/{chunk_index}"
    return f"{source_type.value}_{hashlib.sha256(authority.encode('utf-8')).hexdigest()[:20]}_{source_fingerprint[:8]}"


def branch_manifest_path(data_dir: Path, scope: VectorScope) -> Path:
    return data_dir / "chroma" / "manifests" / scope.timeline_id / f"{scope.branch_id}.json"


def manifest_path(data_dir: Path, timeline_id: str = "main") -> Path:
    return data_dir / "chroma" / f"index_manifest_{timeline_id}.json"


def load_manifest(data_dir: Path, timeline_id: str = "main") -> IndexManifest | None:
    path = manifest_path(data_dir, timeline_id)
    if not path.exists():
        return None
    try:
        content = path.read_text(encoding="utf-8")
        return IndexManifest.from_dict(json.loads(content))
    except (OSError, json.JSONDecodeError):
        return None


def save_manifest(data_dir: Path, manifest: IndexManifest, timeline_id: str = "main") -> None:
    path = manifest_path(data_dir, timeline_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def is_legacy_index(data_dir: Path) -> bool:
    manifest = load_manifest(data_dir)
    if manifest is None:
        return True
    if manifest.schema_version < 2:
        return True
    if not manifest.project_id:
        return True
    return False


def validate_project_match(
    context_project_id: str, manifest_project_id: str
) -> bool:
    return context_project_id == manifest_project_id
