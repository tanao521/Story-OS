"""Recoverable branch-memory continuity snapshots for chapter transitions.

The snapshot is an immutable transition artifact. Branch memory and the
chapter commit remain source authorities; vector state is explicitly a
rebuildable cache and is never included as source authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from core.project_context import ProjectContext


_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_SCHEMA_VERSION = "1.0"


class BranchMemoryContinuityError(RuntimeError):
    code = "BRANCH_MEMORY_CONTINUITY_ERROR"


class ContinuityScopeError(BranchMemoryContinuityError):
    code = "CONTINUITY_SCOPE_MISMATCH"


class ContinuityConflictError(BranchMemoryContinuityError):
    code = "CONTINUITY_SOURCE_CONFLICT"


class ContinuityRecoveryRequiredError(BranchMemoryContinuityError):
    code = "CONTINUITY_RECOVERY_REQUIRED"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


class BranchMemoryContinuityService:
    """Create and audit one immutable snapshot per main-timeline transition."""

    def __init__(
        self,
        context: ProjectContext,
        *,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self.context = context
        self.storage_project_id = context.root.name or "default"
        self.root = context.narrative_memory_dir / "continuity"
        self._fault_injector = fault_injector

    def _fault(self, point: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(point)

    @staticmethod
    def _validate_id(value: str, name: str) -> None:
        if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
            raise ContinuityScopeError(f"Invalid {name}")

    def _assert_contained(self, path: Path) -> None:
        root = self.context.root.resolve()
        try:
            path.resolve(strict=False).relative_to(root)
        except (OSError, ValueError) as exc:
            raise ContinuityScopeError("Continuity path escapes project") from exc
        current = path.parent
        while current != root and current != current.parent:
            if current.exists() and current.is_symlink():
                raise ContinuityScopeError("Continuity path contains a symlink")
            current = current.parent

    def _path(
        self,
        timeline_id: str,
        branch_id: str,
        previous_chapter_id: int,
        successor_chapter_id: int,
    ) -> Path:
        self._validate_id(timeline_id, "timeline_id")
        self._validate_id(branch_id, "branch_id")
        if timeline_id != "main":
            raise ContinuityScopeError("Only the main timeline is supported")
        if (
            type(previous_chapter_id) is not int
            or type(successor_chapter_id) is not int
            or previous_chapter_id < 1
            or successor_chapter_id != previous_chapter_id + 1
        ):
            raise ContinuityScopeError("Invalid chapter transition")
        path = (
            self.root
            / timeline_id
            / branch_id
            / f"chapter_{previous_chapter_id:03d}_to_{successor_chapter_id:03d}.json"
        )
        self._assert_contained(path)
        return path

    def _read_json(self, path: Path, expected: type) -> Any:
        self._assert_contained(path)
        if not path.exists():
            return expected()
        if path.is_symlink():
            raise ContinuityScopeError("Memory source must not be a symlink")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContinuityRecoveryRequiredError("Memory source is unreadable") from exc
        if not isinstance(value, expected):
            raise ContinuityRecoveryRequiredError("Memory source has an invalid shape")
        return value

    def _source_authority(
        self,
        *,
        timeline_id: str,
        branch_id: str,
        previous_chapter_id: int,
    ) -> dict[str, Any]:
        event_path = (
            self.context.narrative_memory_dir
            / "events"
            / timeline_id
            / branch_id
            / f"chapter_{previous_chapter_id:03d}.json"
        )
        state_path = (
            self.context.narrative_memory_dir
            / "state"
            / timeline_id
            / branch_id
            / "current.json"
        )
        events = self._read_json(event_path, list)
        state = self._read_json(state_path, dict)
        for row in events:
            if not isinstance(row, dict):
                raise ContinuityRecoveryRequiredError("Memory event must be an object")
            if any(
                row.get(key) != expected
                for key, expected in (
                    ("project_id", self.storage_project_id),
                    ("timeline_id", timeline_id),
                    ("branch_id", branch_id),
                    ("chapter_id", previous_chapter_id),
                )
            ):
                raise ContinuityScopeError("Memory event scope does not match transition")
            expected_fingerprint = _fingerprint(
                {key: value for key, value in row.items() if key != "record_fingerprint"}
            )
            if row.get("record_fingerprint") != expected_fingerprint:
                raise ContinuityRecoveryRequiredError("Memory event fingerprint is invalid")
        if state and any(
            state.get(key) not in (None, expected)
            for key, expected in (
                ("project_id", self.storage_project_id),
                ("timeline_id", timeline_id),
                ("branch_id", branch_id),
            )
        ):
            raise ContinuityScopeError("Memory state scope does not match transition")
        authority = {
            "kind": "branch_narrative_memory",
            "chapter_id": previous_chapter_id,
            "event_record_fingerprints": [
                row["record_fingerprint"] for row in events
            ],
            "events_fingerprint": _fingerprint(events),
            "state_fingerprint": _fingerprint(state),
        }
        authority["source_fingerprint"] = _fingerprint(authority)
        return authority

    @staticmethod
    def _atomic_create(path: Path, payload: dict[str, Any]) -> bool:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent), text=True
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(str(temp_path), str(path))
                return True
            except FileExistsError:
                return False
        finally:
            temp_path.unlink(missing_ok=True)

    def create(
        self,
        *,
        operation_id: str,
        project_id: str,
        timeline_id: str,
        branch_id: str,
        branch_revision: str,
        previous_chapter_id: int,
        successor_chapter_id: int,
        completion_authority: dict[str, Any],
    ) -> dict[str, Any]:
        self._validate_id(operation_id, "operation_id")
        if project_id != self.storage_project_id:
            raise ContinuityScopeError("Project ID mismatch")
        path = self._path(
            timeline_id, branch_id, previous_chapter_id, successor_chapter_id
        )
        source = self._source_authority(
            timeline_id=timeline_id,
            branch_id=branch_id,
            previous_chapter_id=previous_chapter_id,
        )
        identity = {
            "project_id": project_id,
            "timeline_id": timeline_id,
            "branch_id": branch_id,
            "previous_chapter_id": previous_chapter_id,
            "successor_chapter_id": successor_chapter_id,
        }
        snapshot = {
            "schema_version": _SCHEMA_VERSION,
            "snapshot_id": f"continuity_{_fingerprint(identity)[:24]}",
            **identity,
            "branch_revision": str(branch_revision),
            "source_authority": source,
            "source_fingerprint": source["source_fingerprint"],
            "completion_authority": completion_authority,
            "creation_state": "completed",
            "completion_state": "complete",
            "recovery_operation_id": operation_id,
            "idempotency_fingerprint": _fingerprint(identity),
            "vector_role": "REBUILDABLE_CACHE",
            "vector_authority_included": False,
            "created_at": _now(),
        }
        snapshot["record_fingerprint"] = _fingerprint(
            {key: value for key, value in snapshot.items() if key != "record_fingerprint"}
        )
        created = self._atomic_create(path, snapshot)
        self._fault("after_snapshot_publication")
        result = self.read(
            project_id=project_id,
            timeline_id=timeline_id,
            branch_id=branch_id,
            previous_chapter_id=previous_chapter_id,
            successor_chapter_id=successor_chapter_id,
        )
        if result["source_fingerprint"] != source["source_fingerprint"]:
            raise ContinuityConflictError("Continuity source changed after snapshot")
        if result["completion_authority"] != completion_authority:
            raise ContinuityConflictError("Completion authority differs from snapshot")
        if result["branch_revision"] != str(branch_revision):
            raise ContinuityConflictError("Branch authority differs from snapshot")
        return {**result, "idempotent_replay": not created}

    def read(
        self,
        *,
        project_id: str,
        timeline_id: str,
        branch_id: str,
        previous_chapter_id: int,
        successor_chapter_id: int,
    ) -> dict[str, Any]:
        if project_id != self.storage_project_id:
            raise ContinuityScopeError("Project ID mismatch")
        path = self._path(
            timeline_id, branch_id, previous_chapter_id, successor_chapter_id
        )
        if not path.exists():
            raise ContinuityRecoveryRequiredError("Continuity snapshot is missing")
        if path.is_symlink():
            raise ContinuityScopeError("Continuity snapshot must not be a symlink")
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContinuityRecoveryRequiredError("Continuity snapshot is unreadable") from exc
        if not isinstance(snapshot, dict) or snapshot.get("schema_version") != _SCHEMA_VERSION:
            raise ContinuityRecoveryRequiredError("Continuity snapshot schema is incompatible")
        expected_scope = {
            "project_id": project_id,
            "timeline_id": timeline_id,
            "branch_id": branch_id,
            "previous_chapter_id": previous_chapter_id,
            "successor_chapter_id": successor_chapter_id,
        }
        if any(snapshot.get(key) != value for key, value in expected_scope.items()):
            raise ContinuityScopeError("Continuity snapshot scope does not match path")
        expected_record = _fingerprint(
            {key: value for key, value in snapshot.items() if key != "record_fingerprint"}
        )
        if (
            snapshot.get("record_fingerprint") != expected_record
            or snapshot.get("creation_state") != "completed"
            or snapshot.get("completion_state") != "complete"
            or snapshot.get("vector_role") != "REBUILDABLE_CACHE"
            or snapshot.get("vector_authority_included") is not False
        ):
            raise ContinuityRecoveryRequiredError("Continuity snapshot is incomplete or corrupt")
        current_source = self._source_authority(
            timeline_id=timeline_id,
            branch_id=branch_id,
            previous_chapter_id=previous_chapter_id,
        )
        if snapshot.get("source_fingerprint") != current_source["source_fingerprint"]:
            raise ContinuityConflictError("Continuity source no longer matches snapshot")
        return snapshot
