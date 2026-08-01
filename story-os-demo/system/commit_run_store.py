"""Persistent commit run records for cross-process recovery."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.project_context import ProjectContext
from system.data_store import DataStore


@dataclass
class PostCommitTaskState:
    status: str = "not_required"  # success | failed | skipped | deferred | not_required
    attempts: int = 0
    last_error: str | None = None
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "attempts": self.attempts,
            "last_error": self.last_error,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PostCommitTaskState":
        return cls(
            status=data.get("status", "not_required"),
            attempts=data.get("attempts", 0),
            last_error=data.get("last_error"),
            completed_at=data.get("completed_at"),
        )


@dataclass
class CommitRun:
    commit_id: str
    project_id: str
    chapter_id: int
    source_hash: str
    source_version_id: str | None
    post_commit_policy: str
    status: str = "core_committed"  # core_committed | completed | completed_with_warnings | failed
    canon_revision_id: str | None = None
    chapter_path: str | None = None
    summary_path: str | None = None
    timeline_id: str = "main"
    approval_provenance: dict[str, Any] = field(default_factory=dict)
    core_commit: dict[str, Any] = field(default_factory=dict)
    post_commit: dict[str, PostCommitTaskState] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: _now())
    updated_at: str = field(default_factory=lambda: _now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "commit_id": self.commit_id,
            "project_id": self.project_id,
            "chapter_id": self.chapter_id,
            "source_hash": self.source_hash,
            "source_version_id": self.source_version_id,
            "post_commit_policy": self.post_commit_policy,
            "status": self.status,
            "canon_revision_id": self.canon_revision_id,
            "chapter_path": self.chapter_path,
            "summary_path": self.summary_path,
            "timeline_id": self.timeline_id,
            "approval_provenance": self.approval_provenance,
            "core_commit": self.core_commit,
            "post_commit": {k: v.to_dict() for k, v in self.post_commit.items()},
            "warnings": self.warnings,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CommitRun":
        post_commit_raw = data.get("post_commit", {})
        post_commit = {}
        for k, v in post_commit_raw.items():
            if isinstance(v, dict):
                post_commit[k] = PostCommitTaskState.from_dict(v)
            else:
                post_commit[k] = PostCommitTaskState(status=str(v))
        return cls(
            commit_id=data["commit_id"],
            project_id=data.get("project_id", ""),
            chapter_id=data.get("chapter_id", 0),
            source_hash=data.get("source_hash", ""),
            source_version_id=data.get("source_version_id"),
            post_commit_policy=data.get("post_commit_policy", "local_only"),
            status=data.get("status", "core_committed"),
            canon_revision_id=data.get("canon_revision_id"),
            chapter_path=data.get("chapter_path"),
            summary_path=data.get("summary_path"),
            timeline_id=data.get("timeline_id", "main"),
            approval_provenance=data.get("approval_provenance", {}) if isinstance(data.get("approval_provenance", {}), dict) else {},
            core_commit=data.get("core_commit", {}),
            post_commit=post_commit,
            warnings=data.get("warnings", []),
            created_at=data.get("created_at", _now()),
            updated_at=data.get("updated_at", _now()),
        )

    def task_status(self, task_name: str) -> str:
        return self.post_commit.get(task_name, PostCommitTaskState()).status

    def all_tasks_success(self, policy: str) -> bool:
        if policy == "full":
            required = ["context_refresh", "version_archive", "obsidian_sync",
                        "chroma_index", "reflection_job", "planning_anchor"]
        elif policy == "local_only":
            required = ["context_refresh"]
        else:
            return True
        for name in required:
            st = self.task_status(name)
            if st not in ("success", "skipped", "not_required"):
                return False
        return True

    def has_failed_tasks(self) -> bool:
        for task in self.post_commit.values():
            if task.status == "failed":
                return True
        return False

    def pending_tasks(self, policy: str) -> list[str]:
        if policy == "full":
            candidates = ["context_refresh", "version_archive", "obsidian_sync",
                          "chroma_index", "reflection_job", "planning_anchor"]
        elif policy == "local_only":
            candidates = ["context_refresh"]
        else:
            return []
        pending = []
        for name in candidates:
            st = self.task_status(name)
            if st in ("failed", "deferred"):
                pending.append(name)
        return pending


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CommitRunStore:
    def __init__(self, context: ProjectContext) -> None:
        self.context = context
        self.data_store = DataStore(context)
        self._dir = self.context.root / "data" / "commit_runs"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, commit_id: str) -> Path:
        return self._dir / f"{commit_id}.json"

    def save(self, run: CommitRun) -> None:
        run.updated_at = _now()
        self.data_store.write_json(self._path(run.commit_id), run.to_dict())

    def load(self, commit_id: str) -> CommitRun | None:
        data = self.data_store.read_json(self._path(commit_id), default=None)
        if isinstance(data, dict):
            return CommitRun.from_dict(data)
        return None

    def find_by_chapter_and_hash(self, chapter_id: int, source_hash: str) -> CommitRun | None:
        if not self._dir.exists():
            return None
        for path in sorted(self._dir.glob("*.json"), reverse=True):
            data = self.data_store.read_json(path, default=None)
            if isinstance(data, dict):
                if data.get("chapter_id") == chapter_id and data.get("source_hash") == source_hash:
                    return CommitRun.from_dict(data)
        return None

    def list_all(self) -> list[CommitRun]:
        if not self._dir.exists():
            return []
        runs = []
        for path in sorted(self._dir.glob("*.json")):
            data = self.data_store.read_json(path, default=None)
            if isinstance(data, dict):
                runs.append(CommitRun.from_dict(data))
        return runs
