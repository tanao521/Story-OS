"""Append-only branch registry store with lifecycle event journal.

Phase 0D4-A-FIX-RC2: sequence-only lifecycle filenames, deterministic
registry event journal, recoverable active-archive-with-replacement
operation, and projection-rebuildable registry snapshot.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from hashlib import sha256
from pathlib import Path
from typing import Any

from core.contracts.narrative_turn import (
    BranchLifecycleStatus,
    BranchLifecycleEvent,
    BranchOperationPhase,
    BranchOperationType,
    BranchOperationRecord,
    NarrativeBranch,
    NarrativeBranchIdentity,
    NarrativeTurnError,
    NarrativeScope,
    RegistryEvent,
    SCHEMA_VERSION,
    TimelineContext,
    new_id,
    now_utc,
)
from core.project_context import ProjectContext


_PATH_COMPONENT_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_SEQUENCE_FILENAME_PATTERN = re.compile(r"^\d{8}\.json$")


def _validate_path_component(value: str, component_name: str) -> None:
    if not isinstance(value, str) or _PATH_COMPONENT_PATTERN.fullmatch(value) is None:
        raise NarrativeTurnError(NarrativeTurnError.INVALID_ID, f"Invalid {component_name}: {value!r}")


def _validate_path_containment(base: Path, target: Path) -> None:
    try:
        resolved_base = base.resolve()
        resolved_target = target.resolve()
    except OSError as exc:
        raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, "Path resolution failed") from exc
    try:
        resolved_target.relative_to(resolved_base)
    except ValueError as exc:
        raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, "Path traversal detected") from exc


def _canonical_json(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, indent=2)


def _publish_immutable_json(target_path: Path, data: dict[str, Any]) -> None:
    parent = target_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    payload_text = _canonical_json(data)

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{target_path.name}.",
        suffix=".tmp",
        dir=str(parent),
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload_text)
                f.flush()
                os.fsync(f.fileno())
        except OSError as exc:
            raise NarrativeTurnError(
                NarrativeTurnError.INVALID_FIELD,
                f"Atomic immutable publication failed during write/fsync: {exc}",
            ) from exc
        try:
            os.link(str(temp_path), str(target_path))
        except FileExistsError:
            try:
                existing_text = target_path.read_text(encoding="utf-8")
            except OSError as exc:
                raise NarrativeTurnError(
                    NarrativeTurnError.INVALID_FIELD,
                    "Failed to read existing immutable record",
                ) from exc
            if existing_text == payload_text:
                return
            raise NarrativeTurnError(
                NarrativeTurnError.IMMUTABLE_RECORD_EXISTS,
                f"Immutable record already exists with different content: {target_path.name}",
            )
        except OSError as exc:
            raise NarrativeTurnError(
                NarrativeTurnError.INVALID_FIELD,
                f"Atomic immutable publication failed: {exc}",
            ) from exc
    finally:
        try:
            temp_path.unlink()
        except OSError:
            pass


def _atomic_write_json(target_path: Path, data: dict[str, Any]) -> None:
    parent = target_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{target_path.name}.",
        suffix=".tmp",
        dir=str(parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, sort_keys=True, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_name, str(target_path))
    except OSError as exc:
        raise NarrativeTurnError(
            NarrativeTurnError.INVALID_FIELD,
            f"Atomic write failed: {exc}",
        ) from exc
    finally:
        try:
            os.unlink(temp_name)
        except OSError:
            pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, "Corrupt JSON") from exc
    except OSError as exc:
        raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, "Failed to read file") from exc


def _compute_event_fingerprint(payload: dict[str, Any]) -> str:
    fp_payload = {k: v for k, v in payload.items() if k != "record_fingerprint"}
    return sha256(
        json.dumps(fp_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


class NarrativeBranchStore:
    def __init__(self, project_context: ProjectContext) -> None:
        self._project_root = project_context.data_dir
        project_id = project_context.root.name
        _validate_path_component(project_id, "project_id")
        self._project_id = project_id

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------
    def _timeline_base_path(self, timeline_context: TimelineContext) -> Path:
        _validate_path_component(timeline_context.timeline_id, "timeline_id")
        path = self._project_root / "branches" / timeline_context.timeline_id
        _validate_path_containment(self._project_root, path)
        return path

    def _branches_path(self, timeline_context: TimelineContext) -> Path:
        return self._timeline_base_path(timeline_context) / "branches"

    def _branch_identity_path(self, timeline_context: TimelineContext, branch_id: str) -> Path:
        return self._branches_path(timeline_context) / f"{branch_id}.json"

    def _lifecycle_events_path(self, timeline_context: TimelineContext, branch_id: str) -> Path:
        _validate_path_component(branch_id, "branch_id")
        path = self._timeline_base_path(timeline_context) / "lifecycle_events" / branch_id
        _validate_path_containment(self._project_root, path)
        return path

    def _registry_path(self, timeline_context: TimelineContext) -> Path:
        return self._timeline_base_path(timeline_context) / "registry.json"

    def _registry_events_path(self, timeline_context: TimelineContext) -> Path:
        return self._timeline_base_path(timeline_context) / "registry_events"

    def _branch_operations_path(self) -> Path:
        # ``self._project_root`` is already ``data_dir`` (= root / "data"),
        # so branch operations live at ``data/branch_operations/`` (project-root scope).
        path = self._project_root / "branch_operations"
        _validate_path_containment(self._project_root, path)
        return path

    def _branch_operation_path(self, operation_id: str) -> Path:
        _validate_path_component(operation_id, "operation_id")
        path = self._branch_operations_path() / f"{operation_id}.json"
        _validate_path_containment(self._project_root, path)
        return path

    def _branch_operation_phase_path(self, operation_id: str) -> Path:
        _validate_path_component(operation_id, "operation_id")
        path = self._branch_operations_path() / f"{operation_id}.phase.json"
        _validate_path_containment(self._project_root, path)
        return path

    def _mutable_operation_path(self, operation_id: str) -> Path:
        """Use the RC1 phase path for immutable-authority operations.

        Older D tests and records keep the historical mutable ``.json`` layout;
        a record carrying the RC1 canonical request fingerprint opts into the
        split authority/phase layout.
        """
        authority = self._branch_operation_path(operation_id)
        if authority.exists():
            try:
                data = _load_json(authority)
            except NarrativeTurnError:
                data = {}
            if data.get("canonical_request_fingerprint"):
                return self._branch_operation_phase_path(operation_id)
        return authority

    # ------------------------------------------------------------------
    # Registry event journal (append-only, sequence-ordered, deterministic)
    # ------------------------------------------------------------------
    def _read_registry_events(
        self,
        timeline_context: TimelineContext,
    ) -> list[RegistryEvent]:
        events_path = self._registry_events_path(timeline_context)
        if not events_path.exists():
            return []
        records: list[dict[str, Any]] = []
        for entry in sorted(events_path.iterdir()):
            if entry.suffix != ".json":
                continue
            if not _SEQUENCE_FILENAME_PATTERN.fullmatch(entry.name):
                raise NarrativeTurnError(
                    NarrativeTurnError.REGISTRY_EVENT_CHAIN_CORRUPT,
                    f"Invalid registry event filename (must be 8-digit sequence): {entry.name}",
                )
            records.append(_load_json(entry))
        records.sort(key=lambda r: r["sequence"])
        previous_event_id: str | None = None
        previous_fp: str | None = None
        expected_seq = 0
        for record in records:
            if record["sequence"] != expected_seq:
                raise NarrativeTurnError(
                    NarrativeTurnError.REGISTRY_EVENT_CHAIN_CORRUPT,
                    f"Registry event sequence gap/duplicate at {expected_seq}",
                )
            if record.get("previous_event_id") != previous_event_id:
                raise NarrativeTurnError(
                    NarrativeTurnError.REGISTRY_EVENT_CHAIN_CORRUPT,
                    "Registry event previous_event_id chain broken",
                )
            if record.get("previous_event_fingerprint") != previous_fp:
                raise NarrativeTurnError(
                    NarrativeTurnError.REGISTRY_EVENT_CHAIN_CORRUPT,
                    "Registry event previous_event_fingerprint chain broken",
                )
            previous_event_id = record["event_id"]
            previous_fp = record["record_fingerprint"]
            expected_seq += 1
        return [
            RegistryEvent(
                schema_version=r["schema_version"],
                event_id=r["event_id"],
                sequence=r["sequence"],
                project_id=r["project_id"],
                timeline_id=r["timeline_id"],
                event_type=r["event_type"],
                from_active_branch_id=r.get("from_active_branch_id"),
                to_active_branch_id=r.get("to_active_branch_id"),
                expected_revision=r["expected_revision"],
                resulting_revision=r["resulting_revision"],
                operation_id=r.get("operation_id"),
                occurred_at=r["occurred_at"],
                previous_event_id=r.get("previous_event_id"),
                previous_event_fingerprint=r.get("previous_event_fingerprint"),
                record_fingerprint=r["record_fingerprint"],
            )
            for r in records
        ]

    def _append_registry_event(
        self,
        timeline_context: TimelineContext,
        event_type: str,
        from_active_branch_id: str | None,
        to_active_branch_id: str | None,
        expected_revision: str,
        resulting_revision: str,
        operation_id: str | None = None,
    ) -> RegistryEvent:
        existing = self._read_registry_events(timeline_context)
        sequence = len(existing)
        if existing:
            last = existing[-1]
            previous_event_id = last.event_id
            previous_event_fingerprint = last.record_fingerprint
        else:
            previous_event_id = None
            previous_event_fingerprint = None

        event_id = new_id("revt")
        occurred_at = now_utc()
        payload = {
            "schema_version": SCHEMA_VERSION,
            "event_id": event_id,
            "sequence": sequence,
            "project_id": self._project_id,
            "timeline_id": timeline_context.timeline_id,
            "event_type": event_type,
            "from_active_branch_id": from_active_branch_id,
            "to_active_branch_id": to_active_branch_id,
            "expected_revision": expected_revision,
            "resulting_revision": resulting_revision,
            "operation_id": operation_id,
            "occurred_at": occurred_at,
            "previous_event_id": previous_event_id,
            "previous_event_fingerprint": previous_event_fingerprint,
        }
        record_fingerprint = _compute_event_fingerprint(payload)
        payload["record_fingerprint"] = record_fingerprint

        event = RegistryEvent(
            schema_version=SCHEMA_VERSION,
            event_id=event_id,
            sequence=sequence,
            project_id=self._project_id,
            timeline_id=timeline_context.timeline_id,
            event_type=event_type,
            from_active_branch_id=from_active_branch_id,
            to_active_branch_id=to_active_branch_id,
            expected_revision=expected_revision,
            resulting_revision=resulting_revision,
            operation_id=operation_id,
            occurred_at=occurred_at,
            previous_event_id=previous_event_id,
            previous_event_fingerprint=previous_event_fingerprint,
            record_fingerprint=record_fingerprint,
        )

        events_path = self._registry_events_path(timeline_context)
        events_path.mkdir(parents=True, exist_ok=True)
        event_path = events_path / f"{sequence:08d}.json"
        _publish_immutable_json(event_path, payload)
        return event

    def _rebuild_registry_from_journal(
        self,
        timeline_context: TimelineContext,
    ) -> dict[str, Any]:
        events = self._read_registry_events(timeline_context)
        current_active: str | None = None
        current_revision = "0"
        created_at = now_utc()
        updated_at: str | None = None
        for evt in events:
            current_active = evt.to_active_branch_id
            current_revision = evt.resulting_revision
            updated_at = evt.occurred_at
        registry = {
            "schema_version": SCHEMA_VERSION,
            "project_id": self._project_id,
            "timeline_id": timeline_context.timeline_id,
            "active_branch_id": current_active,
            "revision": current_revision,
            "created_at": created_at,
        }
        if updated_at is not None:
            registry["updated_at"] = updated_at
        return registry

    def _verify_registry_projection(
        self,
        timeline_context: TimelineContext,
        registry: dict[str, Any],
    ) -> None:
        rebuilt = self._rebuild_registry_from_journal(timeline_context)
        if registry.get("active_branch_id") != rebuilt.get("active_branch_id"):
            raise NarrativeTurnError(
                NarrativeTurnError.REGISTRY_PROJECTION_MISMATCH,
                "Registry projection active_branch_id does not match journal",
            )
        if registry.get("revision") != rebuilt.get("revision"):
            raise NarrativeTurnError(
                NarrativeTurnError.REGISTRY_PROJECTION_MISMATCH,
                "Registry projection revision does not match journal",
            )

    # ------------------------------------------------------------------
    # Registry (mutable snapshot, rebuildable from registry_events)
    # ------------------------------------------------------------------
    def _create_registry_if_missing(self, timeline_context: TimelineContext) -> dict[str, Any]:
        registry_path = self._registry_path(timeline_context)
        events_path = self._registry_events_path(timeline_context)
        if registry_path.exists():
            try:
                registry = _load_json(registry_path)
            except NarrativeTurnError:
                if events_path.exists() and any(events_path.iterdir()):
                    rebuilt = self._rebuild_registry_from_journal(timeline_context)
                    _atomic_write_json(registry_path, rebuilt)
                    return rebuilt
                raise
            if events_path.exists() and any(events_path.iterdir()):
                try:
                    self._verify_registry_projection(timeline_context, registry)
                except NarrativeTurnError as exc:
                    if exc.code == NarrativeTurnError.REGISTRY_PROJECTION_MISMATCH:
                        rebuilt = self._rebuild_registry_from_journal(timeline_context)
                        _atomic_write_json(registry_path, rebuilt)
                        return rebuilt
                    raise
            return registry
        if events_path.exists() and any(events_path.iterdir()):
            rebuilt = self._rebuild_registry_from_journal(timeline_context)
            _atomic_write_json(registry_path, rebuilt)
            return rebuilt
        initial_registry = {
            "schema_version": SCHEMA_VERSION,
            "project_id": self._project_id,
            "timeline_id": timeline_context.timeline_id,
            "active_branch_id": None,
            "revision": "0",
            "created_at": now_utc(),
        }
        _atomic_write_json(registry_path, initial_registry)
        return initial_registry

    def _update_registry(
        self,
        timeline_context: TimelineContext,
        expected_revision: str,
        updates: dict[str, Any],
    ) -> tuple[str, str]:
        registry_path = self._registry_path(timeline_context)
        backup_path = registry_path.with_suffix(".bak")
        registry = _load_json(registry_path)
        if registry["revision"] != expected_revision:
            raise NarrativeTurnError(NarrativeTurnError.BRANCH_OPERATION_STALE_REVISION, "Revision conflict")
        if registry["project_id"] != self._project_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "project_id mismatch")
        if registry["timeline_id"] != timeline_context.timeline_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "timeline_id mismatch")
        old_revision = registry["revision"]
        registry.update(updates)
        new_revision = new_id("rev")
        registry["revision"] = new_revision
        try:
            if registry_path.exists():
                os.replace(str(registry_path), str(backup_path))
            _atomic_write_json(registry_path, registry)
            return old_revision, new_revision
        except NarrativeTurnError:
            if backup_path.exists():
                try:
                    os.replace(str(backup_path), str(registry_path))
                except OSError:
                    pass
            raise

    # ------------------------------------------------------------------
    # Branch identity (immutable creation record)
    # ------------------------------------------------------------------
    def create_branch(
        self,
        timeline_context: TimelineContext,
        branch_id: str,
        display_name: str,
        parent_branch_id: str | None = None,
        created_from_turn_id: str | None = None,
    ) -> NarrativeBranch:
        if timeline_context.project_id != self._project_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "project_id mismatch")
        _validate_path_component(branch_id, "branch_id")
        branch_path = self._branch_identity_path(timeline_context, branch_id)
        if branch_path.exists():
            raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, "Branch already exists")
        if parent_branch_id is not None:
            _validate_path_component(parent_branch_id, "parent_branch_id")
            if parent_branch_id == branch_id:
                raise NarrativeTurnError(NarrativeTurnError.BRANCH_CYCLE, "parent_branch_id cannot equal branch_id")
            parent_identity = self._read_identity(timeline_context, parent_branch_id)
            if parent_identity is None:
                raise NarrativeTurnError(NarrativeTurnError.MISSING_PARENT_BRANCH, f"Parent branch not found: {parent_branch_id}")
            parent_status, _ = self._derive_lifecycle_status(timeline_context, parent_branch_id)
            if parent_status == BranchLifecycleStatus.ARCHIVED:
                raise NarrativeTurnError(NarrativeTurnError.BRANCH_NOT_ACTIVE, "Cannot create child from archived branch")
        if created_from_turn_id is not None:
            _validate_path_component(created_from_turn_id, "created_from_turn_id")

        created_at = now_utc()
        identity = NarrativeBranchIdentity(
            schema_version=SCHEMA_VERSION,
            branch_id=branch_id,
            project_id=self._project_id,
            timeline_id=timeline_context.timeline_id,
            parent_branch_id=parent_branch_id,
            created_from_turn_id=created_from_turn_id,
            display_name=display_name,
            created_at=created_at,
        )
        _publish_immutable_json(branch_path, {
            "schema_version": identity.schema_version,
            "branch_id": identity.branch_id,
            "project_id": identity.project_id,
            "timeline_id": identity.timeline_id,
            "parent_branch_id": identity.parent_branch_id,
            "created_from_turn_id": identity.created_from_turn_id,
            "display_name": identity.display_name,
            "created_at": identity.created_at,
            "fingerprint": identity.fingerprint(),
        })

        registry = self._create_registry_if_missing(timeline_context)
        self._append_registry_event(
            timeline_context,
            event_type="branch_created",
            from_active_branch_id=registry.get("active_branch_id"),
            to_active_branch_id=registry.get("active_branch_id"),
            expected_revision=registry["revision"],
            resulting_revision=registry["revision"],
        )

        return NarrativeBranch(
            schema_version=identity.schema_version,
            branch_id=identity.branch_id,
            project_id=identity.project_id,
            timeline_id=identity.timeline_id,
            parent_branch_id=identity.parent_branch_id,
            created_from_turn_id=identity.created_from_turn_id,
            display_name=identity.display_name,
            lifecycle_status=BranchLifecycleStatus.OPEN,
            created_at=identity.created_at,
            archived_at=None,
        )

    def _read_identity(self, timeline_context: TimelineContext, branch_id: str) -> NarrativeBranchIdentity | None:
        branch_path = self._branch_identity_path(timeline_context, branch_id)
        if not branch_path.exists():
            return None
        data = _load_json(branch_path)
        return NarrativeBranchIdentity(
            schema_version=data["schema_version"],
            branch_id=data["branch_id"],
            project_id=data["project_id"],
            timeline_id=data["timeline_id"],
            parent_branch_id=data.get("parent_branch_id"),
            created_from_turn_id=data.get("created_from_turn_id"),
            display_name=data["display_name"],
            created_at=data["created_at"],
        )

    # ------------------------------------------------------------------
    # Lifecycle event journal (append-only, sequence-ordered)
    # ------------------------------------------------------------------
    def _read_lifecycle_events(
        self,
        timeline_context: TimelineContext,
        branch_id: str,
    ) -> list[BranchLifecycleEvent]:
        events_path = self._lifecycle_events_path(timeline_context, branch_id)
        if not events_path.exists():
            return []
        records: list[dict[str, Any]] = []
        for entry in sorted(events_path.iterdir()):
            if entry.suffix != ".json":
                continue
            if not _SEQUENCE_FILENAME_PATTERN.fullmatch(entry.name):
                raise NarrativeTurnError(
                    NarrativeTurnError.LIFECYCLE_EVENT_CHAIN_CORRUPT,
                    f"Invalid lifecycle event filename (must be 8-digit sequence): {entry.name}",
                )
            records.append(_load_json(entry))
        records.sort(key=lambda r: r["sequence"])
        previous_fp: str | None = None
        expected_seq = 0
        for record in records:
            if record["sequence"] != expected_seq:
                raise NarrativeTurnError(
                    NarrativeTurnError.LIFECYCLE_EVENT_CHAIN_CORRUPT,
                    f"Lifecycle event sequence gap/duplicate at {expected_seq}",
                )
            if record.get("previous_event_fingerprint") != previous_fp:
                raise NarrativeTurnError(
                    NarrativeTurnError.LIFECYCLE_EVENT_CHAIN_CORRUPT,
                    "Lifecycle event previous_event_fingerprint chain broken",
                )
            previous_fp = record["record_fingerprint"]
            expected_seq += 1
        return [
            BranchLifecycleEvent(
                schema_version=r["schema_version"],
                event_id=r["event_id"],
                sequence=r["sequence"],
                branch_id=r["branch_id"],
                project_id=r["project_id"],
                timeline_id=r["timeline_id"],
                from_status=BranchLifecycleStatus(r["from_status"]),
                to_status=BranchLifecycleStatus(r["to_status"]),
                operation_id=r.get("operation_id"),
                occurred_at=r["occurred_at"],
                previous_event_fingerprint=r.get("previous_event_fingerprint"),
                record_fingerprint=r["record_fingerprint"],
            )
            for r in records
        ]

    def _append_lifecycle_event(
        self,
        timeline_context: TimelineContext,
        branch_id: str,
        from_status: BranchLifecycleStatus,
        to_status: BranchLifecycleStatus,
        operation_id: str | None = None,
    ) -> BranchLifecycleEvent:
        existing = self._read_lifecycle_events(timeline_context, branch_id)
        sequence = len(existing)
        if existing:
            last = existing[-1]
            if last.to_status != from_status:
                raise NarrativeTurnError(
                    NarrativeTurnError.BRANCH_LIFECYCLE_CONFLICT,
                    f"Cannot transition from {from_status.value} when current status is {last.to_status.value}",
                )
            previous_event_fingerprint = last.record_fingerprint
        else:
            if from_status != BranchLifecycleStatus.OPEN:
                raise NarrativeTurnError(
                    NarrativeTurnError.BRANCH_LIFECYCLE_CONFLICT,
                    f"First lifecycle event must transition from open, got {from_status.value}",
                )
            previous_event_fingerprint = None

        event_id = new_id("evt")
        occurred_at = now_utc()
        payload = {
            "schema_version": SCHEMA_VERSION,
            "event_id": event_id,
            "sequence": sequence,
            "branch_id": branch_id,
            "project_id": self._project_id,
            "timeline_id": timeline_context.timeline_id,
            "from_status": from_status.value,
            "to_status": to_status.value,
            "operation_id": operation_id,
            "occurred_at": occurred_at,
            "previous_event_fingerprint": previous_event_fingerprint,
        }
        record_fingerprint = _compute_event_fingerprint(payload)
        payload["record_fingerprint"] = record_fingerprint

        event = BranchLifecycleEvent(
            schema_version=SCHEMA_VERSION,
            event_id=event_id,
            sequence=sequence,
            branch_id=branch_id,
            project_id=self._project_id,
            timeline_id=timeline_context.timeline_id,
            from_status=from_status,
            to_status=to_status,
            operation_id=operation_id,
            occurred_at=occurred_at,
            previous_event_fingerprint=previous_event_fingerprint,
            record_fingerprint=record_fingerprint,
        )

        events_path = self._lifecycle_events_path(timeline_context, branch_id)
        events_path.mkdir(parents=True, exist_ok=True)
        event_path = events_path / f"{sequence:08d}.json"
        _publish_immutable_json(event_path, payload)
        return event

    def _derive_lifecycle_status(
        self,
        timeline_context: TimelineContext,
        branch_id: str,
    ) -> tuple[BranchLifecycleStatus, str | None]:
        events = self._read_lifecycle_events(timeline_context, branch_id)
        if not events:
            return BranchLifecycleStatus.OPEN, None
        last = events[-1]
        if last.to_status == BranchLifecycleStatus.ARCHIVED:
            return BranchLifecycleStatus.ARCHIVED, last.occurred_at
        return BranchLifecycleStatus.OPEN, None

    def _build_branch_projection(
        self,
        timeline_context: TimelineContext,
        identity: NarrativeBranchIdentity,
    ) -> NarrativeBranch:
        status, archived_at = self._derive_lifecycle_status(timeline_context, identity.branch_id)
        return NarrativeBranch(
            schema_version=identity.schema_version,
            branch_id=identity.branch_id,
            project_id=identity.project_id,
            timeline_id=identity.timeline_id,
            parent_branch_id=identity.parent_branch_id,
            created_from_turn_id=identity.created_from_turn_id,
            display_name=identity.display_name,
            lifecycle_status=status,
            created_at=identity.created_at,
            archived_at=archived_at,
        )

    # ------------------------------------------------------------------
    # Branch operation record (recoverable multi-phase operations)
    # ------------------------------------------------------------------
    def _read_operation_record(self, operation_id: str) -> BranchOperationRecord | None:
        authority_path = self._branch_operation_path(operation_id)
        phase_path = self._branch_operation_phase_path(operation_id)
        op_path = phase_path if phase_path.exists() else authority_path
        if not op_path.exists():
            return None
        data = _load_json(op_path)
        return BranchOperationRecord(
            schema_version=data["schema_version"],
            operation_id=data["operation_id"],
            project_id=data["project_id"],
            timeline_id=data["timeline_id"],
            operation_type=BranchOperationType(data["operation_type"]),
            target_branch_id=data["target_branch_id"],
            replacement_branch_id=data["replacement_branch_id"],
            expected_registry_revision=data["expected_registry_revision"],
            initial_target_status=BranchLifecycleStatus(data["initial_target_status"]),
            phase=BranchOperationPhase(data["phase"]),
            resulting_registry_revision=data.get("resulting_registry_revision"),
            lifecycle_event_fingerprint=data.get("lifecycle_event_fingerprint"),
            payload_fingerprint=data["payload_fingerprint"],
            created_at=data["created_at"],
            record_fingerprint=data["record_fingerprint"],
            canonical_request_fingerprint=data.get("canonical_request_fingerprint"),
        )

    def _write_operation_phase(
        self,
        operation_id: str,
        record: dict[str, Any],
    ) -> None:
        op_path = self._mutable_operation_path(operation_id)
        _publish_immutable_json(op_path, record)

    def _make_operation_payload(
        self,
        operation_id: str,
        timeline_context: TimelineContext,
        operation_type: BranchOperationType,
        target_branch_id: str,
        replacement_branch_id: str,
        expected_registry_revision: str,
        initial_target_status: BranchLifecycleStatus,
        phase: BranchOperationPhase,
        resulting_registry_revision: str | None,
        lifecycle_event_fingerprint: str | None,
        created_at: str,
        canonical_request_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "operation_id": operation_id,
            "project_id": self._project_id,
            "timeline_id": timeline_context.timeline_id,
            "operation_type": operation_type.value,
            "target_branch_id": target_branch_id,
            "replacement_branch_id": replacement_branch_id,
            "expected_registry_revision": expected_registry_revision,
            "initial_target_status": initial_target_status.value,
            "phase": phase.value,
            "resulting_registry_revision": resulting_registry_revision,
            "lifecycle_event_fingerprint": lifecycle_event_fingerprint,
            "payload_fingerprint": "",
            "created_at": created_at,
            "canonical_request_fingerprint": canonical_request_fingerprint,
        }
        payload_fingerprint = _compute_event_fingerprint(payload)
        payload["payload_fingerprint"] = payload_fingerprint
        record_fingerprint = _compute_event_fingerprint(payload)
        payload["record_fingerprint"] = record_fingerprint
        return payload

    # ------------------------------------------------------------------
    # Public branch API
    # ------------------------------------------------------------------
    def get_branch(self, timeline_context: TimelineContext, branch_id: str) -> NarrativeBranch | None:
        if timeline_context.project_id != self._project_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "project_id mismatch")
        _validate_path_component(branch_id, "branch_id")
        identity = self._read_identity(timeline_context, branch_id)
        if identity is None:
            return None
        return self._build_branch_projection(timeline_context, identity)

    def list_branches(self, timeline_context: TimelineContext) -> list[NarrativeBranch]:
        if timeline_context.project_id != self._project_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "project_id mismatch")
        branches_path = self._branches_path(timeline_context)
        if not branches_path.exists():
            return []
        result: list[NarrativeBranch] = []
        for entry in sorted(branches_path.iterdir()):
            if entry.suffix != ".json":
                continue
            data = _load_json(entry)
            identity = NarrativeBranchIdentity(
                schema_version=data["schema_version"],
                branch_id=data["branch_id"],
                project_id=data["project_id"],
                timeline_id=data["timeline_id"],
                parent_branch_id=data.get("parent_branch_id"),
                created_from_turn_id=data.get("created_from_turn_id"),
                display_name=data["display_name"],
                created_at=data["created_at"],
            )
            result.append(self._build_branch_projection(timeline_context, identity))
        return result

    def get_active_branch_id(self, timeline_context: TimelineContext) -> str | None:
        if timeline_context.project_id != self._project_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "project_id mismatch")
        registry = self._create_registry_if_missing(timeline_context)
        return registry.get("active_branch_id")

    def get_registry(self, timeline_context: TimelineContext) -> dict[str, Any]:
        """Return the rebuildable registry projection for a timeline."""
        if timeline_context.project_id != self._project_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "project_id mismatch")
        return dict(self._create_registry_if_missing(timeline_context))

    def select_branch(self, timeline_context: TimelineContext, branch_id: str, expected_revision: str) -> str:
        if timeline_context.project_id != self._project_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "project_id mismatch")
        _validate_path_component(branch_id, "branch_id")
        branch = self.get_branch(timeline_context, branch_id)
        if branch is None:
            raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, f"Branch not found: {branch_id}")
        if branch.lifecycle_status == BranchLifecycleStatus.ARCHIVED:
            raise NarrativeTurnError(NarrativeTurnError.BRANCH_NOT_ACTIVE, "Cannot select archived branch")
        registry = self._create_registry_if_missing(timeline_context)
        from_active = registry.get("active_branch_id")
        old_revision, new_revision = self._update_registry(timeline_context, expected_revision, {
            "active_branch_id": branch_id,
            "updated_at": now_utc(),
        })
        self._append_registry_event(
            timeline_context,
            event_type="branch_selected",
            from_active_branch_id=from_active,
            to_active_branch_id=branch_id,
            expected_revision=expected_revision,
            resulting_revision=new_revision,
        )
        return old_revision

    def _active_archive_with_replacement(
        self,
        timeline_context: TimelineContext,
        branch_id: str,
        replacement_branch_id: str,
        expected_revision: str,
        operation_id: str,
    ) -> str:
        created_at = now_utc()
        target_branch = self.get_branch(timeline_context, branch_id)
        if target_branch is None:
            raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, f"Branch not found: {branch_id}")
        initial_target_status = target_branch.lifecycle_status

        existing_op = self._read_operation_record(operation_id)
        if existing_op is not None:
            if existing_op.target_branch_id != branch_id:
                raise NarrativeTurnError(
                    NarrativeTurnError.BRANCH_OPERATION_CONFLICT,
                    f"Operation {operation_id} target branch mismatch",
                )
            if existing_op.replacement_branch_id != replacement_branch_id:
                raise NarrativeTurnError(
                    NarrativeTurnError.BRANCH_OPERATION_CONFLICT,
                    f"Operation {operation_id} replacement branch mismatch",
                )

        if initial_target_status == BranchLifecycleStatus.ARCHIVED:
            if existing_op is not None:
                if existing_op.phase == BranchOperationPhase.COMPLETED:
                    return existing_op.resulting_registry_revision or expected_revision
                raise NarrativeTurnError(
                    NarrativeTurnError.BRANCH_OPERATION_INCOMPLETE,
                    f"Operation {operation_id} in phase {existing_op.phase.value} but branch already archived",
                )
            registry = self._create_registry_if_missing(timeline_context)
            return registry["revision"]

        replacement = self.get_branch(timeline_context, replacement_branch_id)
        if replacement is None:
            raise NarrativeTurnError(
                NarrativeTurnError.INVALID_FIELD,
                f"Replacement branch not found: {replacement_branch_id}",
            )
        if replacement.lifecycle_status == BranchLifecycleStatus.ARCHIVED:
            raise NarrativeTurnError(
                NarrativeTurnError.BRANCH_OPERATION_REPLACEMENT_ARCHIVED,
                "Replacement branch cannot be archived",
            )

        if existing_op is not None:
            return self._resume_active_archive_with_replacement(
                timeline_context,
                operation_id,
                existing_op,
            )

        intent_payload = self._make_operation_payload(
            operation_id=operation_id,
            timeline_context=timeline_context,
            operation_type=BranchOperationType.ACTIVE_ARCHIVE_WITH_REPLACEMENT,
            target_branch_id=branch_id,
            replacement_branch_id=replacement_branch_id,
            expected_registry_revision=expected_revision,
            initial_target_status=initial_target_status,
            phase=BranchOperationPhase.INTENT,
            resulting_registry_revision=None,
            lifecycle_event_fingerprint=None,
            created_at=created_at,
            canonical_request_fingerprint=(existing_op.canonical_request_fingerprint if existing_op else None),
        )
        self._write_operation_phase(operation_id, intent_payload)

        return self._resume_active_archive_with_replacement(
            timeline_context,
            operation_id,
            self._read_operation_record(operation_id),
        )

    def _resume_active_archive_with_replacement(
        self,
        timeline_context: TimelineContext,
        operation_id: str,
        op: BranchOperationRecord,
    ) -> str:
        if op.operation_type != BranchOperationType.ACTIVE_ARCHIVE_WITH_REPLACEMENT:
            raise NarrativeTurnError(
                NarrativeTurnError.INVALID_FIELD,
                f"Operation {operation_id} is not active_archive_with_replacement",
            )

        if op.phase == BranchOperationPhase.COMPLETED:
            return op.resulting_registry_revision or op.expected_registry_revision

        if op.phase == BranchOperationPhase.INTENT:
            registry = self._create_registry_if_missing(timeline_context)
            from_active = registry.get("active_branch_id")
            if from_active != op.target_branch_id:
                raise NarrativeTurnError(
                    NarrativeTurnError.BRANCH_LIFECYCLE_CONFLICT,
                    "Active branch does not match operation target",
                )
            replacement = self.get_branch(timeline_context, op.replacement_branch_id)
            if replacement is None or replacement.lifecycle_status == BranchLifecycleStatus.ARCHIVED:
                raise NarrativeTurnError(
                    NarrativeTurnError.BRANCH_OPERATION_REPLACEMENT_ARCHIVED,
                    "Replacement branch not found or archived",
                )

            old_rev, new_rev = self._update_registry(
                timeline_context,
                op.expected_registry_revision,
                {
                    "active_branch_id": op.replacement_branch_id,
                    "updated_at": now_utc(),
                },
            )

            self._append_registry_event(
                timeline_context,
                event_type="branch_archived",
                from_active_branch_id=op.target_branch_id,
                to_active_branch_id=op.replacement_branch_id,
                expected_revision=op.expected_registry_revision,
                resulting_revision=new_rev,
                operation_id=operation_id,
            )

            registry_updated_payload = self._make_operation_payload(
                operation_id=operation_id,
                timeline_context=timeline_context,
                operation_type=BranchOperationType.ACTIVE_ARCHIVE_WITH_REPLACEMENT,
                target_branch_id=op.target_branch_id,
                replacement_branch_id=op.replacement_branch_id,
                expected_registry_revision=op.expected_registry_revision,
                initial_target_status=op.initial_target_status,
                phase=BranchOperationPhase.REGISTRY_UPDATED,
                resulting_registry_revision=new_rev,
                lifecycle_event_fingerprint=None,
                created_at=op.created_at,
                canonical_request_fingerprint=op.canonical_request_fingerprint,
            )
            op_path = self._mutable_operation_path(operation_id)
            _publish_immutable_json(op_path.with_name(f"{operation_id}_registry_updated.json"), registry_updated_payload)
            _atomic_write_json(op_path, registry_updated_payload)

            op = BranchOperationRecord(
                schema_version=registry_updated_payload["schema_version"],
                operation_id=registry_updated_payload["operation_id"],
                project_id=registry_updated_payload["project_id"],
                timeline_id=registry_updated_payload["timeline_id"],
                operation_type=BranchOperationType(registry_updated_payload["operation_type"]),
                target_branch_id=registry_updated_payload["target_branch_id"],
                replacement_branch_id=registry_updated_payload["replacement_branch_id"],
                expected_registry_revision=registry_updated_payload["expected_registry_revision"],
                initial_target_status=BranchLifecycleStatus(registry_updated_payload["initial_target_status"]),
                phase=BranchOperationPhase(registry_updated_payload["phase"]),
                resulting_registry_revision=registry_updated_payload.get("resulting_registry_revision"),
                lifecycle_event_fingerprint=registry_updated_payload.get("lifecycle_event_fingerprint"),
                payload_fingerprint=registry_updated_payload["payload_fingerprint"],
                created_at=registry_updated_payload["created_at"],
                record_fingerprint=registry_updated_payload["record_fingerprint"],
            )

        if op.phase == BranchOperationPhase.REGISTRY_UPDATED:
            target_status, _ = self._derive_lifecycle_status(timeline_context, op.target_branch_id)
            if target_status == BranchLifecycleStatus.ARCHIVED:
                events = self._read_lifecycle_events(timeline_context, op.target_branch_id)
                lifecycle_fp = events[-1].record_fingerprint if events else None
            else:
                lifecycle_event = self._append_lifecycle_event(
                    timeline_context,
                    op.target_branch_id,
                    BranchLifecycleStatus.OPEN,
                    BranchLifecycleStatus.ARCHIVED,
                    operation_id=operation_id,
                )
                lifecycle_fp = lifecycle_event.record_fingerprint

            lifecycle_appended_payload = self._make_operation_payload(
                operation_id=operation_id,
                timeline_context=timeline_context,
                operation_type=BranchOperationType.ACTIVE_ARCHIVE_WITH_REPLACEMENT,
                target_branch_id=op.target_branch_id,
                replacement_branch_id=op.replacement_branch_id,
                expected_registry_revision=op.expected_registry_revision,
                initial_target_status=op.initial_target_status,
                phase=BranchOperationPhase.LIFECYCLE_APPENDED,
                resulting_registry_revision=op.resulting_registry_revision,
                lifecycle_event_fingerprint=lifecycle_fp,
                created_at=op.created_at,
                canonical_request_fingerprint=op.canonical_request_fingerprint,
            )
            op_path = self._mutable_operation_path(operation_id)
            _publish_immutable_json(op_path.with_name(f"{operation_id}_lifecycle_appended.json"), lifecycle_appended_payload)
            _atomic_write_json(op_path, lifecycle_appended_payload)

            op = BranchOperationRecord(
                schema_version=lifecycle_appended_payload["schema_version"],
                operation_id=lifecycle_appended_payload["operation_id"],
                project_id=lifecycle_appended_payload["project_id"],
                timeline_id=lifecycle_appended_payload["timeline_id"],
                operation_type=BranchOperationType(lifecycle_appended_payload["operation_type"]),
                target_branch_id=lifecycle_appended_payload["target_branch_id"],
                replacement_branch_id=lifecycle_appended_payload["replacement_branch_id"],
                expected_registry_revision=lifecycle_appended_payload["expected_registry_revision"],
                initial_target_status=BranchLifecycleStatus(lifecycle_appended_payload["initial_target_status"]),
                phase=BranchOperationPhase(lifecycle_appended_payload["phase"]),
                resulting_registry_revision=lifecycle_appended_payload.get("resulting_registry_revision"),
                lifecycle_event_fingerprint=lifecycle_appended_payload.get("lifecycle_event_fingerprint"),
                payload_fingerprint=lifecycle_appended_payload["payload_fingerprint"],
                created_at=lifecycle_appended_payload["created_at"],
                record_fingerprint=lifecycle_appended_payload["record_fingerprint"],
            )

        if op.phase == BranchOperationPhase.LIFECYCLE_APPENDED:
            completed_payload = self._make_operation_payload(
                operation_id=operation_id,
                timeline_context=timeline_context,
                operation_type=BranchOperationType.ACTIVE_ARCHIVE_WITH_REPLACEMENT,
                target_branch_id=op.target_branch_id,
                replacement_branch_id=op.replacement_branch_id,
                expected_registry_revision=op.expected_registry_revision,
                initial_target_status=op.initial_target_status,
                phase=BranchOperationPhase.COMPLETED,
                resulting_registry_revision=op.resulting_registry_revision,
                lifecycle_event_fingerprint=op.lifecycle_event_fingerprint,
                created_at=op.created_at,
                canonical_request_fingerprint=op.canonical_request_fingerprint,
            )
            op_path = self._mutable_operation_path(operation_id)
            _publish_immutable_json(op_path.with_name(f"{operation_id}_completed.json"), completed_payload)
            _atomic_write_json(op_path, completed_payload)

            op = BranchOperationRecord(
                schema_version=completed_payload["schema_version"],
                operation_id=completed_payload["operation_id"],
                project_id=completed_payload["project_id"],
                timeline_id=completed_payload["timeline_id"],
                operation_type=BranchOperationType(completed_payload["operation_type"]),
                target_branch_id=completed_payload["target_branch_id"],
                replacement_branch_id=completed_payload["replacement_branch_id"],
                expected_registry_revision=completed_payload["expected_registry_revision"],
                initial_target_status=BranchLifecycleStatus(completed_payload["initial_target_status"]),
                phase=BranchOperationPhase(completed_payload["phase"]),
                resulting_registry_revision=completed_payload.get("resulting_registry_revision"),
                lifecycle_event_fingerprint=completed_payload.get("lifecycle_event_fingerprint"),
                payload_fingerprint=completed_payload["payload_fingerprint"],
                created_at=completed_payload["created_at"],
                record_fingerprint=completed_payload["record_fingerprint"],
            )

        return op.resulting_registry_revision or op.expected_registry_revision

    def archive_branch(
        self,
        timeline_context: TimelineContext,
        branch_id: str,
        replacement_branch_id: str | None = None,
        expected_revision: str = "",
        operation_id: str | None = None,
    ) -> str:
        if timeline_context.project_id != self._project_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "project_id mismatch")
        _validate_path_component(branch_id, "branch_id")
        branch = self.get_branch(timeline_context, branch_id)
        if branch is None:
            raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, f"Branch not found: {branch_id}")
        registry = self._create_registry_if_missing(timeline_context)
        active_id = registry.get("active_branch_id")

        if branch.lifecycle_status == BranchLifecycleStatus.ARCHIVED:
            return registry["revision"]

        if active_id == branch_id:
            if replacement_branch_id is None:
                raise NarrativeTurnError(
                    NarrativeTurnError.BRANCH_LIFECYCLE_CONFLICT,
                    "Must specify replacement branch when archiving active branch",
                )
            _validate_path_component(replacement_branch_id, "replacement_branch_id")
            operation_id = operation_id or new_id("op")
            effective_revision = expected_revision if expected_revision else registry["revision"]
            return self._active_archive_with_replacement(
                timeline_context,
                branch_id,
                replacement_branch_id,
                effective_revision,
                operation_id,
            )

        self._append_lifecycle_event(
            timeline_context,
            branch_id,
            BranchLifecycleStatus.OPEN,
            BranchLifecycleStatus.ARCHIVED,
        )

        self._append_registry_event(
            timeline_context,
            event_type="branch_archived",
            from_active_branch_id=active_id,
            to_active_branch_id=active_id,
            expected_revision=registry["revision"],
            resulting_revision=registry["revision"],
        )

        return registry["revision"]

    def restore_branch(self, timeline_context: TimelineContext, branch_id: str) -> NarrativeBranch:
        if timeline_context.project_id != self._project_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "project_id mismatch")
        _validate_path_component(branch_id, "branch_id")
        branch = self.get_branch(timeline_context, branch_id)
        if branch is None:
            raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, f"Branch not found: {branch_id}")
        if branch.lifecycle_status == BranchLifecycleStatus.OPEN:
            return branch
        self._append_lifecycle_event(
            timeline_context,
            branch_id,
            BranchLifecycleStatus.ARCHIVED,
            BranchLifecycleStatus.OPEN,
        )
        registry = self._create_registry_if_missing(timeline_context)
        self._append_registry_event(
            timeline_context,
            event_type="branch_restored",
            from_active_branch_id=registry.get("active_branch_id"),
            to_active_branch_id=registry.get("active_branch_id"),
            expected_revision=registry["revision"],
            resulting_revision=registry["revision"],
        )
        identity = self._read_identity(timeline_context, branch_id)
        assert identity is not None
        return self._build_branch_projection(timeline_context, identity)

    def check_for_cycle(self, timeline_context: TimelineContext, branch_id: str, parent_branch_id: str) -> bool:
        if timeline_context.project_id != self._project_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "project_id mismatch")
        visited = {branch_id}
        current = parent_branch_id
        while current is not None:
            if current in visited:
                return True
            visited.add(current)
            branch = self.get_branch(timeline_context, current)
            if branch is None:
                return False
            current = branch.parent_branch_id
        return False

    def get_registry_revision(self, timeline_context: TimelineContext) -> str:
        if timeline_context.project_id != self._project_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "project_id mismatch")
        registry = self._create_registry_if_missing(timeline_context)
        return registry["revision"]

    # ------------------------------------------------------------------
    # Test/inspection helpers (not part of public lifecycle API)
    # ------------------------------------------------------------------
    def get_lifecycle_events(
        self,
        timeline_context: TimelineContext,
        branch_id: str,
    ) -> list[BranchLifecycleEvent]:
        if timeline_context.project_id != self._project_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "project_id mismatch")
        _validate_path_component(branch_id, "branch_id")
        return self._read_lifecycle_events(timeline_context, branch_id)

    def read_branch_identity(
        self,
        timeline_context: TimelineContext,
        branch_id: str,
    ) -> NarrativeBranchIdentity | None:
        if timeline_context.project_id != self._project_id:
            raise NarrativeTurnError(NarrativeTurnError.SCOPE_MISMATCH, "project_id mismatch")
        _validate_path_component(branch_id, "branch_id")
        return self._read_identity(timeline_context, branch_id)
