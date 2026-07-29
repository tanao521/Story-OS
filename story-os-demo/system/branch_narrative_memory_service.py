"""Branch-scoped NarrativeMemory contract for Phase 0D4-E2.

This module deliberately does not import or touch any vector implementation.
Legacy flat files are read only by :class:`NarrativeMemoryMigrationService`.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.contracts.narrative_turn import BranchLifecycleStatus, NarrativeTurnError, TimelineContext
from core.project_context import ProjectContext
from system.narrative_branch_store import NarrativeBranchStore
from system.narrative_branch_lifecycle_service import BranchLifecycleService


_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_SCHEMA_VERSION = "2.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


class BranchNarrativeMemoryError(RuntimeError):
    code = "BRANCH_MEMORY_ERROR"


class BranchMemoryScopeError(BranchNarrativeMemoryError):
    code = "BRANCH_MEMORY_SCOPE_REQUIRED"


class BranchMemoryNotFound(BranchNarrativeMemoryError):
    code = "BRANCH_MEMORY_NOT_FOUND"


class BranchMemoryArchived(BranchNarrativeMemoryError):
    code = "BRANCH_MEMORY_ARCHIVED"


class BranchMemoryInactive(BranchNarrativeMemoryError):
    code = "BRANCH_MEMORY_INACTIVE"


class BranchMemoryConflict(BranchNarrativeMemoryError):
    code = "BRANCH_MEMORY_CONFLICT"


class MigrationError(BranchNarrativeMemoryError):
    code = "NARRATIVE_MEMORY_MIGRATION_ERROR"


class BranchMemoryService:
    """Explicitly scoped, branch-isolated NarrativeMemory operations."""

    def __init__(self, context: ProjectContext) -> None:
        self.context = context
        self.project_id = context.root.name or "default"
        self.store = NarrativeBranchStore(context)
        self.lifecycle = BranchLifecycleService(context)
        self.root = context.narrative_memory_dir

    def scope(self, project_id: str, timeline_id: str, branch_id: str) -> TimelineContext:
        if not all(isinstance(value, str) and value for value in (project_id, timeline_id, branch_id)):
            raise BranchMemoryScopeError("project_id, timeline_id, and branch_id are required")
        if project_id != self.project_id or _ID_RE.fullmatch(timeline_id) is None or _ID_RE.fullmatch(branch_id) is None:
            raise BranchMemoryScopeError("NarrativeMemory scope is invalid")
        if timeline_id != "main" and not (self.context.data_dir / "branches" / timeline_id).exists():
            raise BranchMemoryNotFound("Timeline not found")
        timeline = TimelineContext(project_id=project_id, timeline_id=timeline_id)
        branch = self.store.get_branch(timeline, branch_id)
        if branch is None:
            raise BranchMemoryNotFound("Branch not found")
        return timeline

    def _branch(self, timeline: TimelineContext, branch_id: str):
        branch = self.store.get_branch(timeline, branch_id)
        if branch is None:
            raise BranchMemoryNotFound("Branch not found")
        return branch

    def _assert_mutable(self, timeline: TimelineContext, branch_id: str):
        branch = self._branch(timeline, branch_id)
        if branch.lifecycle_status == BranchLifecycleStatus.ARCHIVED:
            raise BranchMemoryArchived("Archived branches reject NarrativeMemory mutation")
        return branch

    def _path(self, kind: str, timeline: TimelineContext, branch_id: str, *parts: str) -> Path:
        if kind not in {"events", "snapshots", "overrides", "retrieval", "conflicts", "state"}:
            raise BranchMemoryScopeError("Invalid NarrativeMemory path kind")
        values = (timeline.timeline_id, branch_id, *parts)
        if any(not isinstance(value, str) or not _ID_RE.fullmatch(value.replace(".", "_")) for value in values):
            raise BranchMemoryScopeError("Invalid NarrativeMemory path component")
        path = self.root / kind / timeline.timeline_id / branch_id
        for part in parts:
            path = path / part
        try:
            path.resolve().relative_to(self.context.root.resolve())
        except ValueError as exc:
            raise BranchMemoryScopeError("NarrativeMemory path escapes project") from exc
        return path

    @staticmethod
    def _read(path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BranchNarrativeMemoryError("NarrativeMemory artifact is unreadable") from exc

    @staticmethod
    def _write(path: Path, payload: Any, *, immutable: bool = False) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if immutable and path.exists():
            if path.read_text(encoding="utf-8") != encoded:
                raise BranchMemoryConflict("Immutable NarrativeMemory artifact differs")
            return
        temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temp.write_text(encoded, encoding="utf-8")
            with temp.open("r+", encoding="utf-8") as handle:
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)

    def events(self, scope: TimelineContext, branch_id: str, chapter_id: int | None = None, *, administrative: bool = False) -> list[dict[str, Any]]:
        branch = self._branch(scope, branch_id)
        if branch.lifecycle_status == BranchLifecycleStatus.ARCHIVED and not administrative:
            raise BranchMemoryArchived("Archived branch reads require administrative=true")
        active_branch_id = self.store.get_active_branch_id(scope)
        if not administrative and active_branch_id is not None and active_branch_id != branch_id:
            raise BranchMemoryInactive("Inactive branch reads require administrative=true")
        base = self._path("events", scope, branch_id)
        paths = [base / f"chapter_{chapter_id:03d}.json"] if chapter_id is not None else sorted(base.glob("chapter_*.json"))
        result: list[dict[str, Any]] = []
        for path in paths:
            rows = self._read(path, [])
            if not isinstance(rows, list):
                raise BranchNarrativeMemoryError("Event artifact must be a list")
            for row in rows:
                if row.get("project_id") != scope.project_id or row.get("timeline_id") != scope.timeline_id or row.get("branch_id") != branch_id:
                    raise BranchMemoryConflict("Event scope does not match path")
                transition = self._read(base / "transitions" / f"{row.get('event_id')}.json", None)
                if transition:
                    row = {**row, **transition.get("patch", {}), "status": transition.get("status", row.get("status")), "status_transition_fingerprint": transition.get("record_fingerprint")}
                result.append(row)
        return sorted(result, key=lambda row: (row.get("chapter_id", 0), row.get("created_at", ""), row.get("event_id", "")))

    def append_event(self, scope: TimelineContext, branch_id: str, payload: dict[str, Any], *, operation_id: str | None = None) -> dict[str, Any]:
        self._assert_mutable(scope, branch_id)
        if not isinstance(payload, dict) or not isinstance(payload.get("chapter_id"), int) or not isinstance(payload.get("event_type"), str):
            raise BranchNarrativeMemoryError("chapter_id and event_type are required")
        chapter_id = payload["chapter_id"]
        with self.lifecycle._registry_lock(scope.timeline_id):
            current = self.events(scope, branch_id, chapter_id, administrative=True)
            event_id = payload.get("event_id") or f"mev_{uuid.uuid4().hex[:16]}"
            if any(row.get("event_id") == event_id for row in current):
                existing = next(row for row in current if row.get("event_id") == event_id)
                if _fingerprint(existing) == _fingerprint(payload):
                    return existing
                raise BranchMemoryConflict("event_id already exists with different content")
            event = {
                "schema_version": _SCHEMA_VERSION,
                "event_id": event_id,
                "project_id": scope.project_id,
                "timeline_id": scope.timeline_id,
                "branch_id": branch_id,
                "chapter_id": chapter_id,
                "source_version_id": payload.get("source_version_id"),
                "canon_revision_id": payload.get("canon_revision_id"),
                "event_type": payload["event_type"],
                "payload": payload.get("payload", {}),
                "status": payload.get("status", "confirmed"),
                "created_at": payload.get("created_at", _now()),
                "migration_provenance": payload.get("migration_provenance"),
            }
            event["record_fingerprint"] = _fingerprint({key: value for key, value in event.items() if key != "record_fingerprint"})
            path = self._path("events", scope, branch_id, f"chapter_{chapter_id:03d}.json")
            self._write(path, current + [event])
            return event

    def confirm_event(self, scope: TimelineContext, branch_id: str, event_id: str, status: str = "confirmed", patch: dict[str, Any] | None = None) -> dict[str, Any]:
        self._assert_mutable(scope, branch_id)
        if status not in {"confirmed", "corrected", "rejected"}:
            raise BranchNarrativeMemoryError("Invalid event status")
        events = self.events(scope, branch_id, administrative=True)
        event = next((row for row in events if row.get("event_id") == event_id), None)
        if event is None:
            raise BranchMemoryNotFound("Branch memory event not found")
        transition = {"event_id": event_id, "from_status": event.get("status"), "status": status, "patch": patch or {}, "created_at": _now(), "project_id": scope.project_id, "timeline_id": scope.timeline_id, "branch_id": branch_id}
        transition["record_fingerprint"] = _fingerprint(transition)
        path = self._path("events", scope, branch_id, "transitions", f"{event_id}.json")
        self._write(path, transition, immutable=True)
        event = {**event, **(patch or {}), "status": status, "status_transition_fingerprint": transition["record_fingerprint"]}
        return event

    def snapshot(self, scope: TimelineContext, branch_id: str, chapter_id: int, *, state_revision: str | None = None, administrative: bool = False) -> dict[str, Any]:
        branch = self._branch(scope, branch_id)
        if branch.lifecycle_status == BranchLifecycleStatus.ARCHIVED and not administrative:
            raise BranchMemoryArchived("Archived branch reads require administrative=true")
        events = self.events(scope, branch_id, chapter_id, administrative=True)
        snapshot = {
            "schema_version": _SCHEMA_VERSION,
            "project_id": scope.project_id,
            "timeline_id": scope.timeline_id,
            "branch_id": branch_id,
            "chapter_id": chapter_id,
            "source_event_fingerprints": [row["record_fingerprint"] for row in events],
            "state_revision": state_revision or _fingerprint(events),
            "created_at": _now(),
        }
        snapshot["record_fingerprint"] = _fingerprint({key: value for key, value in snapshot.items() if key != "record_fingerprint"})
        path = self._path("snapshots", scope, branch_id, f"chapter_{chapter_id:03d}.json")
        existing = self._read(path, None)
        if existing is not None:
            if existing.get("project_id") != scope.project_id or existing.get("timeline_id") != scope.timeline_id or existing.get("branch_id") != branch_id or existing.get("chapter_id") != chapter_id:
                raise BranchMemoryConflict("Snapshot scope collision")
            return existing
        self._write(path, snapshot, immutable=True)
        return snapshot

    def override(self, scope: TimelineContext, branch_id: str, kind: str, value: Any) -> dict[str, Any]:
        self._assert_mutable(scope, branch_id)
        if kind not in {"pins", "exclusions", "corrections"}:
            raise BranchNarrativeMemoryError("Invalid override kind")
        path = self._path("overrides", scope, branch_id, f"{kind}.json")
        rows = self._read(path, [])
        record = {"project_id": scope.project_id, "timeline_id": scope.timeline_id, "branch_id": branch_id, "kind": kind, "value": value, "created_at": _now()}
        record["record_fingerprint"] = _fingerprint(record)
        rows.append(record)
        self._write(path, rows)
        return record

    def retrieval_history(self, scope: TimelineContext, branch_id: str, *, chapter_id: int | None = None, selected: list[Any] | None = None, administrative: bool = False) -> dict[str, Any]:
        branch = self._branch(scope, branch_id)
        if branch.lifecycle_status == BranchLifecycleStatus.ARCHIVED and not administrative:
            raise BranchMemoryArchived("Archived branch reads require administrative=true")
        path = self._path("retrieval", scope, branch_id, "history.json")
        rows = self._read(path, [])
        if selected is None:
            return {"entries": rows}
        record = {"project_id": scope.project_id, "timeline_id": scope.timeline_id, "branch_id": branch_id, "chapter_id": chapter_id, "selected": selected, "created_at": _now()}
        record["record_fingerprint"] = _fingerprint(record)
        self._write(path, rows + [record])
        return record

    def project_state(self, scope: TimelineContext, branch_id: str) -> dict[str, Any]:
        """Read the single 0D4-D state authority; E2 never projects into it."""
        self._branch(scope, branch_id)
        current_path = self._path("state", scope, branch_id, "current.json")
        state = self._read(current_path, {}) or {}
        if state and any(state.get(key) not in (None, value) for key, value in (("project_id", scope.project_id), ("timeline_id", scope.timeline_id), ("branch_id", branch_id))):
            raise BranchMemoryConflict("Shared branch state scope does not match path")
        return state


class NarrativeMemoryMigrationService:
    """Explicit, dry-run-first, copy-only migration of flat legacy files."""

    def __init__(self, context: ProjectContext, *, fault_injector=None) -> None:
        self.context = context
        self.memory = BranchMemoryService(context)
        self.root = context.narrative_memory_dir
        self._fault_injector = fault_injector

    def _fault(self, point: str) -> None:
        if self._fault_injector:
            self._fault_injector(point)

    def _legacy_files(self) -> list[Path]:
        candidates = [*self.root.glob("events/chapter_*.json"), self.root / "state" / "current.json", self.root / "state" / "timeline.json", *self.root.glob("snapshots/chapter_*.json"), self.root / "retrieval" / "retrieval_history.json", *self.root.glob("overrides/*.json"), self.root / "conflicts" / "conflicts.json"]
        return sorted(path for path in candidates if path.is_file() and not any(part in {"main", "branches"} for part in path.parts[-3:-1]))

    def plan(self, *, operation_id: str, project_id: str, timeline_id: str, target_branch_id: str, mode: str = "dry_run", legacy_scope_acknowledged: bool = False) -> dict[str, Any]:
        if mode not in {"dry_run", "execute"} or not legacy_scope_acknowledged:
            raise MigrationError("Explicit legacy_scope_acknowledged and valid mode are required")
        scope = self.memory.scope(project_id, timeline_id, target_branch_id)
        files = []
        for path in self._legacy_files():
            raw = path.read_bytes()
            target = self._target_for(path, scope, target_branch_id)
            files.append({"source_path": self.context.relative_path(path), "source_path_hash": _fingerprint(self.context.relative_path(path)), "source_fingerprint": hashlib.sha256(raw).hexdigest(), "size": len(raw), "supported": target is not None, "reason_code": None if target else "LEGACY_STATE_AUTHORITY_UNSUPPORTED", "target_path": self.context.relative_path(target) if target else None})
        manifest = {"operation_id": operation_id, "project_id": project_id, "timeline_id": timeline_id, "target_branch_id": target_branch_id, "mode": mode, "legacy_scope_acknowledged": True, "files": files}
        manifest["source_manifest_fingerprint"] = _fingerprint(files)
        manifest["dry_run_plan_fingerprint"] = _fingerprint(manifest)
        manifest["plan_fingerprint"] = manifest["dry_run_plan_fingerprint"]
        return manifest

    def _target_for(self, source: Path, scope: TimelineContext, branch_id: str) -> Path | None:
        if source.name.startswith("chapter_") and source.parent.name == "events":
            return self.memory._path("events", scope, branch_id, source.name)
        if source.parent.name == "state":
            return None
        if source.parent.name == "snapshots":
            return self.memory._path("snapshots", scope, branch_id, source.name)
        if source.parent.name == "retrieval":
            return self.memory._path("retrieval", scope, branch_id, "history.json")
        return self.memory._path("overrides", scope, branch_id, source.name)

    def execute(self, plan: dict[str, Any], *, operation_id: str, dry_run_plan_fingerprint: str | None = None) -> dict[str, Any]:
        required = {"operation_id", "project_id", "timeline_id", "target_branch_id", "source_manifest_fingerprint", "plan_fingerprint", "files"}
        if not required.issubset(plan) or plan.get("operation_id") != operation_id or dry_run_plan_fingerprint != plan.get("dry_run_plan_fingerprint"):
            raise MigrationError("Migration plan is incomplete")
        scope = self.memory.scope(plan["project_id"], plan["timeline_id"], plan["target_branch_id"])
        authority_path = self.root / "migrations" / f"{operation_id}.json"
        authority = {key: plan[key] for key in ("operation_id", "project_id", "timeline_id", "target_branch_id", "source_manifest_fingerprint", "dry_run_plan_fingerprint")}
        authority["canonical_request_fingerprint"] = _fingerprint(authority)
        authority["created_at"] = _now()
        authority["record_fingerprint"] = _fingerprint(authority)
        if authority_path.exists():
            existing = self.memory._read(authority_path, {})
            if existing.get("canonical_request_fingerprint") != authority["canonical_request_fingerprint"]:
                raise MigrationError("Migration operation collision")
            phase = self.memory._read(self.root / "migrations" / f"{operation_id}.phase.json", {})
            if phase.get("phase") == "completed":
                return {"operation_id": operation_id, "idempotent_replay": True, "copied": phase.get("copied", [])}
        else:
            self.memory._write(authority_path, authority, immutable=True)
        self._fault("after_immutable_authority_claim")
        copied = []
        reused = []
        with self.memory.lifecycle._registry_lock(scope.timeline_id):
         self.memory._assert_mutable(scope, plan["target_branch_id"])
         for index, item in enumerate(plan["files"]):
            if not item.get("supported"):
                continue
            source = self.context.root / item["source_path"]
            if not source.exists() or hashlib.sha256(source.read_bytes()).hexdigest() != item["source_fingerprint"]:
                raise MigrationError("Legacy source changed or is missing")
            target = self.context.root / str(item["target_path"])
            raw = source.read_bytes()
            migrated = self._migrated_bytes(source, raw, plan, item)
            if target.exists() and target.read_bytes() != migrated:
                raise MigrationError("Migration target differs; refusing overwrite")
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_bytes(migrated)
                if index == 0: self._fault("after_first_target_copy")
                if index == len(plan["files"]) // 2: self._fault("after_middle_target_copy")
            else:
                reused.append(item["target_path"])
            copied.append(item["target_path"])
         self._fault("after_all_target_copies")
        manifest_path = self.root / "migration_manifests" / plan["timeline_id"] / f"{plan['target_branch_id']}.json"
        self.memory._write(manifest_path, {"project_id": plan["project_id"], "timeline_id": plan["timeline_id"], "branch_id": plan["target_branch_id"], "operation_id": operation_id, "source_manifest_fingerprint": plan["source_manifest_fingerprint"], "copied": copied}, immutable=True)
        self._fault("after_migration_manifest_publication")
        self._fault("before_completed_marker")
        phase = {"operation_id": operation_id, "phase": "completed", "copied": copied, "source_manifest_fingerprint": plan["source_manifest_fingerprint"], "updated_at": _now()}
        self.memory._write(self.root / "migrations" / f"{operation_id}.phase.json", phase)
        return {"operation_id": operation_id, "idempotent_replay": False, "copied": copied, "reused": reused, "manifest_path": self.context.relative_path(manifest_path)}

    @staticmethod
    def _migrated_bytes(source: Path, raw: bytes, plan: dict[str, Any], item: dict[str, Any]) -> bytes:
        """Build branch-aware target bytes without changing the legacy source."""
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MigrationError("Legacy source is not valid JSON") from exc
        scope = {"project_id": plan["project_id"], "timeline_id": plan["timeline_id"], "branch_id": plan["target_branch_id"]}
        provenance = {"source_kind": "legacy_unscoped", "source_path_hash": item["source_path_hash"], "source_fingerprint": item["source_fingerprint"], "operation_id": plan["operation_id"], "target_scope": scope}
        if source.parent.name == "events" and isinstance(value, list):
            chapter_match = re.search(r"(\d+)", source.stem)
            chapter_id = int(chapter_match.group(1)) if chapter_match else 0
            rows = []
            for index, row in enumerate(value):
                row = dict(row) if isinstance(row, dict) else {"payload": row}
                row.update(scope)
                row.setdefault("schema_version", _SCHEMA_VERSION)
                row.setdefault("event_id", f"mig_{item['source_fingerprint'][:12]}_{index}")
                row.setdefault("chapter_id", chapter_id)
                row.setdefault("event_type", row.get("type", "legacy_event"))
                row.setdefault("payload", row.get("payload", row.get("summary", {})))
                row.setdefault("status", "confirmed")
                row["migration_provenance"] = provenance
                row["record_fingerprint"] = _fingerprint({key: value for key, value in row.items() if key != "record_fingerprint"})
                rows.append(row)
            value = rows
        elif isinstance(value, dict):
            value = {**value, **scope, "migration_provenance": provenance}
        else:
            value = {**scope, "value": value, "migration_provenance": provenance}
        return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
