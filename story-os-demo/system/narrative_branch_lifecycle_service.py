"""Phase 0D4-E1 branch lifecycle HTTP operation service.

This module owns only Branch registry operations. It never touches
NarrativeMemory, Chroma, Canon, providers, or Turn state.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Iterator

from core.contracts.narrative_turn import (
    BranchLifecycleStatus,
    BranchOperationPhase,
    BranchOperationType,
    NarrativeTurnError,
    TimelineContext,
)
from core.project_context import ProjectContext
from system.narrative_branch_store import (
    NarrativeBranchStore,
    _load_json,
    _validate_path_component,
    _validate_path_containment,
)


_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_SCHEMA_VERSION = "1.0"


def _validate_local_containment(base: Path, target: Path) -> None:
    base_abs = os.path.abspath(str(base))
    target_abs = os.path.abspath(str(target))
    try:
        if os.path.commonpath([base_abs, target_abs]) != base_abs:
            raise ValueError
    except ValueError as exc:
        raise NarrativeTurnError(NarrativeTurnError.INVALID_FIELD, "Path traversal detected") from exc


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _fingerprint(value: dict[str, Any]) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, str(path))
    finally:
        try:
            os.unlink(temp_name)
        except OSError:
            pass


def _publish_if_absent(path: Path, payload: dict[str, Any]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent), text=True)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(str(temp_path), str(path))
            return True
        except FileExistsError:
            return False
    finally:
        try:
            temp_path.unlink()
        except OSError:
            pass


class BranchLifecycleService:
    """Idempotent, scope-checked facade over ``NarrativeBranchStore``."""

    _local_lock_guard = threading.Lock()
    _local_locks: dict[str, threading.Lock] = {}

    def __init__(
        self,
        context: ProjectContext,
        *,
        canonical_project_id: str | None = None,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self.context = context
        self.storage_project_id = context.root.name or "default"
        self.project_id = canonical_project_id or self.storage_project_id
        self.store = NarrativeBranchStore(context)
        self._operations_dir = context.data_dir / "branch_operations"
        self._locks_dir = self._operations_dir / ".locks"
        self._fault_injector = fault_injector
        _validate_path_component(self.project_id, "project_id")
        _validate_path_component(self.storage_project_id, "storage_project_id")

    def _fault(self, point: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(point)

    def _validate_id(self, value: str, name: str) -> None:
        if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
            raise NarrativeTurnError(NarrativeTurnError.INVALID_ID, f"Invalid {name}")

    def _timeline(self, timeline_id: str) -> TimelineContext:
        self._validate_id(timeline_id, "timeline_id")
        return TimelineContext(project_id=self.storage_project_id, timeline_id=timeline_id)

    def _assert_scope(self, project_id: str, timeline_id: str) -> TimelineContext:
        if project_id != self.project_id:
            raise NarrativeTurnError(NarrativeTurnError.PROJECT_NOT_FOUND, "Project not found")
        timeline = self._timeline(timeline_id)
        if timeline_id != "main" and not (self.context.data_dir / "branches" / timeline_id).exists():
            raise NarrativeTurnError(NarrativeTurnError.TIMELINE_NOT_FOUND, "Timeline not found")
        return timeline

    def _operation_path(self, operation_id: str) -> Path:
        self._validate_id(operation_id, "operation_id")
        path = self._operations_dir / f"{operation_id}.json"
        _validate_local_containment(self.context.data_dir, path)
        return path

    def _peek_registry_revision(self, timeline: TimelineContext) -> str:
        """Read registry revision without creating a registry on an API claim."""
        path = self.context.data_dir / "branches" / timeline.timeline_id / "registry.json"
        if not path.exists():
            return "0"
        data = _load_json(path)
        revision = data.get("revision")
        return revision if isinstance(revision, str) and revision else "0"

    def _registry_advanced_only_by_selection(
        self,
        timeline: TimelineContext,
        expected_revision: str,
        current_revision: str,
    ) -> bool:
        """Prove that an old active-pointer revision drifted only via selects."""
        cursor = "0"
        expected_seen = expected_revision == cursor
        for event in self.store._read_registry_events(timeline):
            if event.expected_revision != cursor:
                return False
            if event.resulting_revision != cursor:
                if expected_seen and event.event_type != "branch_selected":
                    return False
                cursor = event.resulting_revision
            if cursor == expected_revision:
                expected_seen = True
        return expected_seen and cursor == current_revision

    def _read_registry_projection(self, timeline: TimelineContext) -> dict[str, Any]:
        """Read registry for GET endpoints without creating missing state."""
        path = self.context.data_dir / "branches" / timeline.timeline_id / "registry.json"
        if not path.exists():
            return {"project_id": self.project_id, "timeline_id": timeline.timeline_id, "active_branch_id": None, "revision": "0"}
        return _load_json(path)

    def _phase_path(self, operation_id: str) -> Path:
        path = self._operations_dir / f"{operation_id}.phase.json"
        _validate_local_containment(self.context.data_dir, path)
        return path

    def _lock_path(self, timeline_id: str) -> Path:
        digest = sha256(f"{self.project_id}:{timeline_id}".encode("utf-8")).hexdigest()
        path = self._locks_dir / f"registry-{digest}.lock"
        _validate_local_containment(self.context.data_dir, path)
        return path

    @staticmethod
    def _process_start_identity(pid: int) -> str | None:
        """Return a PID-reuse-resistant process start identity."""
        if pid <= 0:
            return None
        if os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes

                kernel32 = ctypes.windll.kernel32
                kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
                kernel32.OpenProcess.restype = wintypes.HANDLE
                kernel32.GetProcessTimes.argtypes = [
                    wintypes.HANDLE,
                    ctypes.POINTER(wintypes.FILETIME),
                    ctypes.POINTER(wintypes.FILETIME),
                    ctypes.POINTER(wintypes.FILETIME),
                    ctypes.POINTER(wintypes.FILETIME),
                ]
                kernel32.GetProcessTimes.restype = wintypes.BOOL
                kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
                kernel32.CloseHandle.restype = wintypes.BOOL
                handle = kernel32.OpenProcess(0x1000, False, pid)
                if not handle:
                    return None
                creation = wintypes.FILETIME()
                exit_time = wintypes.FILETIME()
                kernel_time = wintypes.FILETIME()
                user_time = wintypes.FILETIME()
                ok = kernel32.GetProcessTimes(
                    handle,
                    ctypes.byref(creation),
                    ctypes.byref(exit_time),
                    ctypes.byref(kernel_time),
                    ctypes.byref(user_time),
                )
                kernel32.CloseHandle(handle)
                if not ok:
                    return None
                return str((creation.dwHighDateTime << 32) | creation.dwLowDateTime)
            except Exception:
                return None
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
            return stat.rsplit(")", 1)[1].split()[19]
        except (OSError, IndexError):
            return None

    @classmethod
    def _lock_owner_alive(cls, owner: dict[str, Any]) -> bool:
        pid = owner.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            return False
        if os.name == "nt":
            try:
                import ctypes

                kernel32 = ctypes.windll.kernel32
                kernel32.SetLastError(0)
                handle = kernel32.OpenProcess(0x1000, False, pid)
                if not handle:
                    # ERROR_INVALID_PARAMETER proves that the PID does not
                    # exist. Access denial and unknown query failures are not
                    # evidence of death and therefore fail closed.
                    return kernel32.GetLastError() != 87
                exit_code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    kernel32.CloseHandle(handle)
                    return True
                kernel32.CloseHandle(handle)
                if exit_code.value != 259:
                    return False
            except Exception:
                return True
        else:
            try:
                os.kill(pid, 0)
            except (OSError, ValueError):
                return False
        expected = owner.get("process_start_identity")
        current = cls._process_start_identity(pid)
        return not (isinstance(expected, str) and expected and current and current != expected)

    def _read_lock_owner(self, owner_path: Path) -> dict[str, Any] | None:
        try:
            owner = _load_json(owner_path)
        except NarrativeTurnError:
            return None
        return owner if isinstance(owner, dict) else None

    def _cleanup_retired_lock(self, path: Path) -> None:
        """Best-effort cleanup of a non-authoritative retired lock directory."""
        for attempt in range(8):
            try:
                for child in path.iterdir():
                    if child.is_file():
                        self._fault("registry_lock_owner_unlink")
                        child.unlink(missing_ok=True)
                self._fault("registry_lock_directory_rmdir")
                path.rmdir()
                return
            except OSError:
                if attempt < 7:
                    time.sleep(0.002 * (attempt + 1))

    @staticmethod
    def _lock_identity(path: Path) -> str:
        normalized = os.path.normcase(os.path.abspath(str(path)))
        return sha256(normalized.encode("utf-8")).hexdigest()

    @contextmanager
    def _reclaim_guard(self, path: Path, timeout: float = 0.05) -> Iterator[bool]:
        """Serialize reclaimers with a kernel lock that is released on process death."""
        guard_root = Path(tempfile.gettempdir()) / "storyos-registry-reclaim-guards"
        guard_path = guard_root / f"{self._lock_identity(path)}.guard"
        guard_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(guard_path, "a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + timeout
        acquired = False
        try:
            while not acquired:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except (OSError, BlockingIOError):
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(0.005)
            yield acquired
        finally:
            if acquired:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            handle.close()

    def _valid_reclaim_claim(
        self,
        claim: dict[str, Any] | None,
        *,
        lock_identity: str,
        owner_fingerprint: str,
        owner_nonce: str,
    ) -> bool:
        return bool(
            claim
            and claim.get("schema_version") == "1.0"
            and claim.get("lock_identity") == lock_identity
            and claim.get("owner_fingerprint") == owner_fingerprint
            and claim.get("owner_nonce") == owner_nonce
            and isinstance(claim.get("claim_nonce"), str)
            and claim.get("claim_nonce")
            and isinstance(claim.get("pid"), int)
            and claim.get("pid") > 0
        )

    def _retire_lock_directory(self, path: Path, expected_owner: dict[str, Any]) -> bool:
        """Conditionally move one exact released/dead authority out of the namespace."""
        with self._reclaim_guard(path) as guarded:
            if not guarded:
                return False
            current = self._read_lock_owner(path / "owner.json")
            if current != expected_owner:
                return False

            claim_path = path / "reclaim.claim"
            lock_identity = self._lock_identity(path)
            owner_fingerprint = _fingerprint(expected_owner)
            owner_nonce = expected_owner.get("nonce")
            if not isinstance(owner_nonce, str) or not owner_nonce:
                return False
            existing = self._read_lock_owner(claim_path) if claim_path.exists() else None
            if claim_path.exists():
                if not self._valid_reclaim_claim(
                    existing,
                    lock_identity=lock_identity,
                    owner_fingerprint=owner_fingerprint,
                    owner_nonce=owner_nonce,
                ):
                    return False
                if self._lock_owner_alive(
                    {
                        "pid": existing["pid"],
                        "process_start_identity": existing.get("process_start_identity"),
                    }
                ):
                    return False

            claim_nonce = secrets.token_hex(16)
            claimant_start_identity = self._process_start_identity(os.getpid())
            claim = {
                "schema_version": "1.0",
                "lock_identity": lock_identity,
                "owner_fingerprint": owner_fingerprint,
                "owner_nonce": owner_nonce,
                "claim_nonce": claim_nonce,
                "pid": os.getpid(),
                "process_start_identity": claimant_start_identity,
            }
            try:
                if existing is None:
                    if not _publish_if_absent(claim_path, claim):
                        return False
                else:
                    _atomic_json(claim_path, claim)
                self._fault("after_registry_reclaim_claim_publish")
                if self._read_lock_owner(path / "owner.json") != expected_owner:
                    return False
                if self._read_lock_owner(claim_path) != claim:
                    return False
                tombstone = path.parent / f".{path.name}.{claim_nonce}.released"
                self._fault("registry_lock_handoff")
                os.replace(str(path), str(tombstone))
                self._fault("after_registry_reclaim_handoff")
                self._cleanup_retired_lock(tombstone)
                return True
            except OSError:
                try:
                    current_claim = self._read_lock_owner(claim_path)
                    if current_claim == claim:
                        claim_path.unlink(missing_ok=True)
                except OSError:
                    pass
                return False

    @classmethod
    def _local_registry_lock(cls, path: Path) -> threading.Lock:
        key = os.path.normcase(os.path.abspath(str(path)))
        with cls._local_lock_guard:
            return cls._local_locks.setdefault(key, threading.Lock())

    @contextmanager
    def _registry_lock(self, timeline_id: str, timeout: float = 15.0) -> Iterator[None]:
        deadline = time.monotonic() + timeout
        local_lock = self._local_registry_lock(self._lock_path(timeline_id))
        if not local_lock.acquire(timeout=max(0.0, timeout)):
            raise NarrativeTurnError(NarrativeTurnError.CONFIRM_RECOVERY_REQUIRED, "Registry lock timed out")
        try:
            remaining = max(0.0, deadline - time.monotonic())
            with self._registry_filesystem_lock(timeline_id, timeout=remaining):
                yield
        finally:
            local_lock.release()

    @contextmanager
    def _registry_filesystem_lock(self, timeline_id: str, timeout: float = 15.0) -> Iterator[None]:
        path = self._lock_path(timeline_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        nonce = secrets.token_hex(16)
        owner_path = path / "owner.json"

        owner_start_identity = self._process_start_identity(os.getpid())
        held_owner = {
            "pid": os.getpid(),
            "nonce": nonce,
            "process_start_identity": owner_start_identity,
            "state": "held",
        }

        deadline = time.monotonic() + timeout
        while True:
            try:
                path.mkdir()
                try:
                    self._fault("before_registry_lock_owner_publish")
                    _atomic_json(owner_path, held_owner)
                except Exception:
                    try:
                        path.rmdir()
                    except OSError:
                        pass
                    raise
                break
            except FileExistsError:
                owner = self._read_lock_owner(owner_path)
                if owner is not None:
                    state = owner.get("state", "held")
                    reclaimable = state == "released" or (state == "held" and not self._lock_owner_alive(owner))
                    if reclaimable and self._retire_lock_directory(path, owner):
                        continue
                if time.monotonic() >= deadline:
                    raise NarrativeTurnError(NarrativeTurnError.CONFIRM_RECOVERY_REQUIRED, "Registry lock timed out")
                time.sleep(0.01)
        try:
            yield
        finally:
            owner = self._read_lock_owner(owner_path)
            if owner == held_owner:
                released_owner = {**held_owner, "state": "released"}
                published = False
                for attempt in range(8):
                    try:
                        _atomic_json(owner_path, released_owner)
                        published = True
                        break
                    except OSError:
                        if attempt < 7:
                            time.sleep(0.002 * (attempt + 1))
                if published:
                    self._retire_lock_directory(path, released_owner)

    def _request_payload(self, operation_type: str, values: dict[str, Any]) -> dict[str, Any]:
        return {
            "operation_type": operation_type,
            "project_id": self.project_id,
            "timeline_id": values["timeline_id"],
            "branch_id": values.get("branch_id"),
            "parent_branch_id": values.get("parent_branch_id"),
            "created_from_turn_id": values.get("created_from_turn_id"),
            "replacement_branch_id": values.get("replacement_branch_id"),
            "expected_registry_revision": values.get("expected_registry_revision"),
            "display_name": values.get("display_name") or values.get("branch_id"),
        }

    def _claim(self, operation_id: str, request: dict[str, Any], timeline: TimelineContext) -> tuple[dict[str, Any], bool]:
        path = self._operation_path(operation_id)
        request_fp = _fingerprint(request)
        existing = _load_json(path) if path.exists() else None
        if existing is not None:
            if existing.get("canonical_request_fingerprint") != request_fp:
                raise NarrativeTurnError(NarrativeTurnError.OPERATION_COLLISION, "Operation ID conflicts with another request")
            phase_path = self._phase_path(operation_id)
            phase = _load_json(phase_path) if phase_path.exists() else {}
            for key, expected in (("project_id", self.project_id), ("timeline_id", timeline.timeline_id), ("target_branch_id", request["branch_id"])):
                if phase.get(key) is not None and phase.get(key) != expected:
                    raise NarrativeTurnError(NarrativeTurnError.OPERATION_COLLISION, "Operation phase scope conflicts with authority")
            if phase.get("canonical_request_fingerprint") not in (None, request_fp):
                raise NarrativeTurnError(NarrativeTurnError.OPERATION_COLLISION, "Operation phase conflicts with authority")
            return existing, phase.get("phase") == "completed"

        branch = self.store.get_branch(timeline, request["branch_id"])
        initial_status = branch.lifecycle_status.value if branch else BranchLifecycleStatus.OPEN.value
        operation_kind = request["operation_type"]
        internal_type = (
            BranchOperationType.ACTIVE_ARCHIVE_WITH_REPLACEMENT.value
            if operation_kind == "archive" and request.get("replacement_branch_id")
            else operation_kind
        )
        payload: dict[str, Any] = {
            "schema_version": _SCHEMA_VERSION,
            "operation_id": operation_id,
            "operation_type": internal_type,
            "project_id": self.project_id,
            "timeline_id": timeline.timeline_id,
            "target_branch_id": request["branch_id"],
            "replacement_branch_id": request.get("replacement_branch_id") or "placeholder",
            "parent_branch_id": request.get("parent_branch_id"),
            "created_from_turn_id": request.get("created_from_turn_id"),
            "expected_registry_revision": request.get("expected_registry_revision") or self._peek_registry_revision(timeline),
            "canonical_request_fingerprint": request_fp,
            "created_at": _now(),
            "record_fingerprint": _fingerprint({"operation_id": operation_id, "request": request}),
        }
        if _publish_if_absent(path, payload):
            phase_payload: dict[str, Any] = {
                "schema_version": _SCHEMA_VERSION,
                "operation_id": operation_id,
                "operation_type": internal_type,
                "project_id": self.project_id,
                "timeline_id": timeline.timeline_id,
                "target_branch_id": request["branch_id"],
                "replacement_branch_id": request.get("replacement_branch_id") or "placeholder",
                "expected_registry_revision": payload["expected_registry_revision"],
                "canonical_request_fingerprint": request_fp,
                "phase": BranchOperationPhase.INTENT.value,
                "updated_at": _now(),
            }
            if internal_type == BranchOperationType.ACTIVE_ARCHIVE_WITH_REPLACEMENT.value:
                phase_payload.update({
                    "initial_target_status": initial_status,
                    "resulting_registry_revision": None,
                    "lifecycle_event_fingerprint": None,
                    "payload_fingerprint": request_fp,
                    "created_at": payload["created_at"],
                    "record_fingerprint": payload["record_fingerprint"],
                })
            _atomic_json(self._phase_path(operation_id), phase_payload)
            self._fault("after_operation_claim")
            return payload, False
        winner = _load_json(path)
        if winner.get("canonical_request_fingerprint") != request_fp:
            raise NarrativeTurnError(NarrativeTurnError.OPERATION_COLLISION, "Operation ID conflicts with another request")
        phase_path = self._phase_path(operation_id)
        phase = _load_json(phase_path) if phase_path.exists() else {}
        return winner, phase.get("phase") == "completed"

    def _phase(self, operation_id: str, phase: str, **extra: Any) -> None:
        path = self._phase_path(operation_id)
        payload = _load_json(path) if path.exists() else {"schema_version": _SCHEMA_VERSION, "operation_id": operation_id}
        payload.update({"phase": phase, "updated_at": _now(), **extra})
        _atomic_json(path, payload)

    def _complete(self, operation_id: str, authority: dict[str, Any], timeline: TimelineContext, branch_id: str, *, recovery_performed: bool = False) -> dict[str, Any]:
        registry = self._read_registry_projection(timeline)
        branch = self.store.get_branch(timeline, branch_id)
        if branch is None:
            raise NarrativeTurnError(NarrativeTurnError.BRANCH_NOT_FOUND, "Branch not found")
        self._fault("before_completed_marker")
        self._phase(operation_id, "completed", registry_revision=registry["revision"], recovery_performed=recovery_performed)
        return {"operation_id": operation_id, "registry_revision": registry["revision"], "active_branch_id": registry.get("active_branch_id"), "branch": self._branch_payload(branch, registry), "idempotent_replay": False, "recovery_performed": recovery_performed}

    def _replay(self, operation_id: str, authority: dict[str, Any], timeline: TimelineContext) -> dict[str, Any]:
        branch = self.store.get_branch(timeline, authority["target_branch_id"])
        registry = self._read_registry_projection(timeline)
        phase_path = self._phase_path(operation_id)
        phase = _load_json(phase_path) if phase_path.exists() else {}
        return {"operation_id": operation_id, "registry_revision": registry["revision"], "active_branch_id": registry.get("active_branch_id"), "branch": self._branch_payload(branch, registry) if branch else None, "idempotent_replay": True, "recovery_performed": bool(phase.get("recovery_performed"))}

    def list_branches(self, project_id: str, timeline_id: str) -> dict[str, Any]:
        timeline = self._assert_scope(project_id, timeline_id)
        registry = self._read_registry_projection(timeline)
        branches = [self._branch_payload(item, registry) for item in self.store.list_branches(timeline)]
        return {"registry_revision": registry["revision"], "active_branch_id": registry.get("active_branch_id"), "branches": branches}

    def get_branch(self, project_id: str, timeline_id: str, branch_id: str) -> dict[str, Any]:
        timeline = self._assert_scope(project_id, timeline_id)
        self._validate_id(branch_id, "branch_id")
        registry = self._read_registry_projection(timeline)
        branch = self.store.get_branch(timeline, branch_id)
        if branch is None:
            raise NarrativeTurnError(NarrativeTurnError.BRANCH_NOT_FOUND, "Branch not found")
        return {"registry_revision": registry["revision"], "active_branch_id": registry.get("active_branch_id"), "branch": self._branch_payload(branch, registry)}

    def create(self, operation_id: str, values: dict[str, Any]) -> dict[str, Any]:
        timeline = self._assert_scope(values["project_id"], values["timeline_id"])
        self._validate_id(values["branch_id"], "branch_id")
        if values.get("parent_branch_id"):
            self._validate_id(values["parent_branch_id"], "parent_branch_id")
        request = self._request_payload("create", values)
        with self._registry_lock(timeline.timeline_id):
            authority, replay = self._claim(operation_id, request, timeline)
            if replay:
                return self._replay(operation_id, authority, timeline)
            expected = values.get("expected_registry_revision")
            if expected and expected != self.store.get_registry_revision(timeline):
                raise NarrativeTurnError(NarrativeTurnError.BRANCH_OPERATION_STALE_REVISION, "Revision conflict")
            existing = self.store.get_branch(timeline, values["branch_id"])
            if existing is not None:
                phase_path = self._phase_path(operation_id)
                phase = _load_json(phase_path) if phase_path.exists() else {}
                if phase.get("phase") in (None, "identity_published", "completed") and existing.parent_branch_id == values.get("parent_branch_id") and existing.created_from_turn_id == values.get("created_from_turn_id"):
                    return self._complete(operation_id, authority, timeline, values["branch_id"], recovery_performed=True)
                raise NarrativeTurnError(NarrativeTurnError.BRANCH_ALREADY_EXISTS, "Branch already exists")
            if values.get("parent_branch_id"):
                parent = self.store.get_branch(timeline, values["parent_branch_id"])
                if parent is None:
                    raise NarrativeTurnError(NarrativeTurnError.PARENT_BRANCH_NOT_FOUND, "Parent branch not found")
                if parent.lifecycle_status == BranchLifecycleStatus.ARCHIVED:
                    raise NarrativeTurnError(NarrativeTurnError.PARENT_BRANCH_ARCHIVED, "Parent branch is archived")
            try:
                self.store.create_branch(timeline, values["branch_id"], request["display_name"], values.get("parent_branch_id"), values.get("created_from_turn_id"))
            except NarrativeTurnError:
                raise
            self._phase(operation_id, "identity_published")
            self._fault("after_identity_publish")
            return self._complete(operation_id, authority, timeline, values["branch_id"])

    def select(self, operation_id: str, values: dict[str, Any]) -> dict[str, Any]:
        timeline = self._assert_scope(values["project_id"], values["timeline_id"])
        self._validate_id(values["branch_id"], "branch_id")
        request = self._request_payload("select", values)
        with self._registry_lock(timeline.timeline_id):
            authority, replay = self._claim(operation_id, request, timeline)
            if replay:
                return self._replay(operation_id, authority, timeline)
            current = self.store.get_registry(timeline)
            expected = values.get("expected_registry_revision")
            if current.get("active_branch_id") == values["branch_id"]:
                return self._complete(operation_id, authority, timeline, values["branch_id"], recovery_performed=True)
            if expected and expected != current["revision"]:
                raise NarrativeTurnError(NarrativeTurnError.BRANCH_OPERATION_STALE_REVISION, "Revision conflict")
            if current.get("active_branch_id") != values["branch_id"]:
                self.store.select_branch(timeline, values["branch_id"], expected or current["revision"])
            else:
                return self._complete(operation_id, authority, timeline, values["branch_id"], recovery_performed=True)
            self._phase(operation_id, "registry_event_published")
            self._fault("after_registry_publish")
            return self._complete(operation_id, authority, timeline, values["branch_id"])

    def archive(self, operation_id: str, values: dict[str, Any]) -> dict[str, Any]:
        timeline = self._assert_scope(values["project_id"], values["timeline_id"])
        self._validate_id(values["branch_id"], "branch_id")
        if values.get("replacement_branch_id"):
            self._validate_id(values["replacement_branch_id"], "replacement_branch_id")
        request = self._request_payload("archive", values)
        from system.chapter_lifecycle_service import (
            ChapterLifecycleRecoveryRequiredError,
            ChapterLifecycleService,
        )
        chapter_lifecycle = ChapterLifecycleService(self.context)
        with chapter_lifecycle.timeline_authority_lock(timeline.timeline_id), self._registry_lock(timeline.timeline_id):
            try:
                chapter_lifecycle.assert_branch_archive_safe(
                    timeline.timeline_id, values["branch_id"]
                )
                from system.cross_chapter_turn_start_service import CrossChapterTurnStartService
                CrossChapterTurnStartService(
                    self.context, canonical_project_id=self.project_id
                ).assert_branch_archive_safe(
                    timeline.timeline_id, values["branch_id"]
                )
            except ChapterLifecycleRecoveryRequiredError as exc:
                raise NarrativeTurnError(
                    NarrativeTurnError.CONFIRM_RECOVERY_REQUIRED,
                    "Chapter lifecycle recovery is required before branch archive",
                ) from exc
            except Exception as exc:
                if getattr(exc, "code", "") == "TURN_START_RECOVERY_REQUIRED":
                    raise NarrativeTurnError(
                        NarrativeTurnError.CONFIRM_RECOVERY_REQUIRED,
                        "Turn start recovery is required before branch archive",
                    ) from exc
                raise
            authority, replay = self._claim(operation_id, request, timeline)
            if replay:
                return self._replay(operation_id, authority, timeline)
            current = self.store.get_registry(timeline)
            branch = self.store.get_branch(timeline, values["branch_id"])
            if branch is None:
                raise NarrativeTurnError(NarrativeTurnError.BRANCH_NOT_FOUND, "Branch not found")
            # A crash after the durable archive may leave the registry revision
            # newer than the request's original expectation. The branch state
            # is the durable fact, so recover it before stale-revision checks.
            if branch.lifecycle_status == BranchLifecycleStatus.ARCHIVED:
                phase_path = self._phase_path(operation_id)
                phase = _load_json(phase_path) if phase_path.exists() else {}
                if phase.get("phase") == BranchOperationPhase.INTENT.value:
                    raise NarrativeTurnError(NarrativeTurnError.BRANCH_OPERATION_STALE_REVISION, "Archive lost registry race")
                return self._complete(operation_id, authority, timeline, values["branch_id"], recovery_performed=True)
            expected = values.get("expected_registry_revision")
            if expected and expected != current["revision"]:
                raise NarrativeTurnError(NarrativeTurnError.BRANCH_OPERATION_STALE_REVISION, "Revision conflict")
            if values.get("replacement_branch_id"):
                replacement = self.store.get_branch(timeline, values["replacement_branch_id"])
                if replacement is None:
                    raise NarrativeTurnError(NarrativeTurnError.REPLACEMENT_BRANCH_NOT_FOUND, "Replacement branch not found")
                if replacement.branch_id == branch.branch_id or replacement.lifecycle_status == BranchLifecycleStatus.ARCHIVED:
                    raise NarrativeTurnError(NarrativeTurnError.INVALID_REPLACEMENT_BRANCH, "Replacement branch is invalid")
            self.store.archive_branch(timeline, values["branch_id"], values.get("replacement_branch_id"), expected or current["revision"], operation_id=operation_id)
            self._phase(operation_id, "lifecycle_event_published")
            self._fault("after_archive")
            return self._complete(operation_id, authority, timeline, values["branch_id"])

    def restore(self, operation_id: str, values: dict[str, Any]) -> dict[str, Any]:
        timeline = self._assert_scope(values["project_id"], values["timeline_id"])
        self._validate_id(values["branch_id"], "branch_id")
        request = self._request_payload("restore", values)
        with self._registry_lock(timeline.timeline_id):
            authority, replay = self._claim(operation_id, request, timeline)
            if replay:
                return self._replay(operation_id, authority, timeline)
            current = self.store.get_registry(timeline)
            branch = self.store.get_branch(timeline, values["branch_id"])
            if branch is None:
                raise NarrativeTurnError(NarrativeTurnError.BRANCH_NOT_FOUND, "Branch not found")
            if branch.lifecycle_status != BranchLifecycleStatus.ARCHIVED:
                phase_path = self._phase_path(operation_id)
                phase = _load_json(phase_path) if phase_path.exists() else {}
                if phase.get("phase") == BranchOperationPhase.INTENT.value:
                    raise NarrativeTurnError(
                        NarrativeTurnError.BRANCH_OPERATION_STALE_REVISION,
                        "Restore lost lifecycle race",
                    )
                return self._complete(operation_id, authority, timeline, values["branch_id"], recovery_performed=True)
            expected = values.get("expected_registry_revision")
            if (
                expected
                and expected != current["revision"]
                and not self._registry_advanced_only_by_selection(timeline, expected, current["revision"])
            ):
                raise NarrativeTurnError(NarrativeTurnError.BRANCH_OPERATION_STALE_REVISION, "Revision conflict")
            self.store.restore_branch(timeline, values["branch_id"])
            self._phase(operation_id, "lifecycle_event_published")
            self._fault("after_restore")
            return self._complete(operation_id, authority, timeline, values["branch_id"])

    @staticmethod
    def _branch_payload(branch: Any, registry: dict[str, Any]) -> dict[str, Any]:
        return {
            "branch_id": branch.branch_id,
            "parent_branch_id": branch.parent_branch_id,
            "created_from_turn_id": branch.created_from_turn_id,
            "lifecycle_status": branch.lifecycle_status.value,
            "activity": "active" if registry.get("active_branch_id") == branch.branch_id else "inactive",
            "is_active": registry.get("active_branch_id") == branch.branch_id,
            "created_at": branch.created_at,
            "archived_at": branch.archived_at,
        }
