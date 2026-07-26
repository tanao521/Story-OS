"""Vector Sync Run Store — Persistent, retryable vector sync operations."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.project_context import ProjectContext


class VectorSyncOperationType(str, Enum):
    COMMIT = "commit"
    CANON_RESTORE = "canon_restore"
    ARCHIVE = "archive"
    ARCHIVE_RESTORE = "archive_restore"
    REBUILD = "rebuild"
    REPAIR = "repair"
    CLONE = "clone"


class VectorSyncStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class VectorSyncRun:
    def __init__(
        self,
        operation_id: str,
        operation_type: VectorSyncOperationType,
        project_id: str,
        timeline_id: str,
        chapter_id: Optional[int] = None,
        canon_revision_id: Optional[str] = None,
        status: VectorSyncStatus = VectorSyncStatus.PENDING,
        attempts: int = 0,
        last_error: Optional[str] = None,
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
    ):
        self.operation_id = operation_id
        self.operation_type = operation_type
        self.project_id = project_id
        self.timeline_id = timeline_id
        self.chapter_id = chapter_id
        self.canon_revision_id = canon_revision_id
        self.status = status
        self.attempts = attempts
        self.last_error = last_error
        self.created_at = created_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.updated_at = updated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "operation_type": self.operation_type.value,
            "project_id": self.project_id,
            "timeline_id": self.timeline_id,
            "chapter_id": self.chapter_id,
            "canon_revision_id": self.canon_revision_id,
            "status": self.status.value,
            "attempts": self.attempts,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VectorSyncRun":
        return cls(
            operation_id=data["operation_id"],
            operation_type=VectorSyncOperationType(data["operation_type"]),
            project_id=data["project_id"],
            timeline_id=data["timeline_id"],
            chapter_id=data.get("chapter_id"),
            canon_revision_id=data.get("canon_revision_id"),
            status=VectorSyncStatus(data["status"]),
            attempts=data.get("attempts", 0),
            last_error=data.get("last_error"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


class VectorSyncRunStore:
    def __init__(self, context: ProjectContext):
        self.context = context
        self.base_dir = context.data_dir / "vector_sync_runs"
        self.base_dir.mkdir(parents=True, exist_ok=True)
    
    def _run_path(self, operation_id: str) -> Path:
        return self.base_dir / f"{operation_id}.json"
    
    def save(self, run: VectorSyncRun) -> None:
        run.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        path = self._run_path(run.operation_id)
        temp_path = path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(run.to_dict(), f, ensure_ascii=False, indent=2)
        temp_path.replace(path)
    
    def get(self, operation_id: str) -> Optional[VectorSyncRun]:
        path = self._run_path(operation_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return VectorSyncRun.from_dict(data)
        except Exception:
            return None
    
    def list_by_status(self, status: VectorSyncStatus) -> List[VectorSyncRun]:
        results: List[VectorSyncRun] = []
        for path in self.base_dir.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                run = VectorSyncRun.from_dict(data)
                if run.status == status:
                    results.append(run)
            except Exception:
                continue
        return results
    
    def list_by_project(self, project_id: str) -> List[VectorSyncRun]:
        results: List[VectorSyncRun] = []
        for path in self.base_dir.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                run = VectorSyncRun.from_dict(data)
                if run.project_id == project_id:
                    results.append(run)
            except Exception:
                continue
        return results
    
    def update_status(self, operation_id: str, status: VectorSyncStatus, last_error: Optional[str] = None) -> Optional[VectorSyncRun]:
        run = self.get(operation_id)
        if run is None:
            return None
        run.status = status
        run.last_error = last_error
        run.attempts += 1
        self.save(run)
        return run
    
    def delete(self, operation_id: str) -> None:
        path = self._run_path(operation_id)
        if path.exists():
            path.unlink()
    
    def create(
        self,
        operation_type: VectorSyncOperationType,
        project_id: str,
        timeline_id: str,
        chapter_id: Optional[int] = None,
        canon_revision_id: Optional[str] = None,
    ) -> VectorSyncRun:
        operation_id = f"vec_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{abs(hash((project_id, timeline_id, chapter_id, canon_revision_id))) % 1000000}"
        run = VectorSyncRun(
            operation_id=operation_id,
            operation_type=operation_type,
            project_id=project_id,
            timeline_id=timeline_id,
            chapter_id=chapter_id,
            canon_revision_id=canon_revision_id,
        )
        self.save(run)
        return run