"""Shared Chapter Lifecycle Authority for Traditional and Simulator modes.

This module owns only Chapter lifecycle operations:
- Pure next-chapter resolution (read-only)
- Explicit next-chapter creation (mutation with operation authority)

It never owns:
- Content generation
- Turn management
- Candidate/review/commit
- Provider calls
- Vector embeddings
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from core.project_context import ProjectContext
from system.data_store import DataStore
from system.branch_memory_continuity_service import (
    BranchMemoryContinuityError,
    BranchMemoryContinuityService,
)
from system.revision_service import RevisionService
from system.version_manager import (
    format_chapter_id,
    initialize_chapter_versions,
    list_versions,
)


_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_SCHEMA_VERSION = "1.0"
_LOCAL_OPERATION_LOCKS = threading.local()


class ChapterLifecycleError(RuntimeError):
    code = "CHAPTER_LIFECYCLE_ERROR"


class CurrentChapterNotCompleteError(ChapterLifecycleError):
    code = "CURRENT_CHAPTER_NOT_COMPLETE"


class CommitRecoveryRequiredError(ChapterLifecycleError):
    code = "COMMIT_RECOVERY_REQUIRED"


class CommitResultInvalidError(ChapterLifecycleError):
    code = "COMMIT_RESULT_INVALID"


class NextChapterAlreadyExistsError(ChapterLifecycleError):
    code = "NEXT_CHAPTER_ALREADY_EXISTS"


class ChapterCreationConflictError(ChapterLifecycleError):
    code = "CHAPTER_CREATION_CONFLICT"


class OperationConflictError(ChapterLifecycleError):
    code = "OPERATION_CONFLICT"


class BranchStaleError(ChapterLifecycleError):
    code = "BRANCH_STALE"


class BranchArchivedError(ChapterLifecycleError):
    code = "BRANCH_ARCHIVED"


class PlanningStaleError(ChapterLifecycleError):
    code = "PLANNING_STALE"


class VersionInitializationError(ChapterLifecycleError):
    code = "VERSION_INITIALIZATION_FAILED"


class CanonInitializationError(ChapterLifecycleError):
    code = "CANON_INITIALIZATION_FAILED"


class ChapterLifecycleRecoveryRequiredError(ChapterLifecycleError):
    code = "CHAPTER_LIFECYCLE_RECOVERY_REQUIRED"


class MemoryContinuityError(ChapterLifecycleError):
    code = "MEMORY_CONTINUITY_RECOVERY_REQUIRED"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _fingerprint(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _chapter_path(chapter_id: int) -> str:
    return f"data/chapters/chapter_{chapter_id:03d}.md"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent), text=True
    )
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


def _publish_if_absent(path: Path, content: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent), text=True
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
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


def _load_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


class ChapterLifecycleService:
    """Shared Chapter lifecycle authority for Traditional and Simulator.

    Operation authority follows the BranchLifecycleService pattern:
    immutable request claim → phase marker → publish → durable result.
    """

    def __init__(
        self,
        context: ProjectContext,
        *,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self.context = context
        self.project_id = context.root.name or "default"
        self.store = DataStore(context)
        self.revision_service = RevisionService(context)
        self.memory_continuity = BranchMemoryContinuityService(context)
        self._operations_dir = context.data_dir / "chapter_lifecycle" / "operations"
        self._locks_dir = self._operations_dir / ".locks"
        self._fault_injector = fault_injector

    def _fault(self, point: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(point)

    def _validate_id(self, value: str, name: str) -> None:
        if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
            raise ChapterLifecycleError(f"Invalid {name}")

    def _operation_path(self, operation_id: str) -> Path:
        self._validate_id(operation_id, "operation_id")
        path = self._operations_dir / f"{operation_id}.json"
        self._validate_containment(path)
        return path

    def _phase_path(self, operation_id: str) -> Path:
        path = self._operations_dir / f"{operation_id}.phase.json"
        self._validate_containment(path)
        return path

    def _result_path(self, operation_id: str) -> Path:
        path = self._operations_dir / f"{operation_id}.result.json"
        self._validate_containment(path)
        return path

    def _staging_path(self, operation_id: str) -> Path:
        path = self._operations_dir / f"{operation_id}.staging.json"
        self._validate_containment(path)
        return path

    def _lock_path(self, lock_key: str) -> Path:
        digest = hashlib.sha256(
            f"{self.project_id}:{lock_key}".encode("utf-8")
        ).hexdigest()
        path = self._locks_dir / f"chapter-{digest}.lock"
        self._validate_containment(path)
        return path

    def _validate_containment(self, path: Path) -> None:
        base_abs = os.path.abspath(str(self.context.data_dir))
        target_abs = os.path.abspath(str(path))
        if os.path.commonpath([base_abs, target_abs]) != base_abs:
            raise ChapterLifecycleError("Path traversal detected")

    def _request_payload(
        self, operation_type: str, values: dict[str, Any]
    ) -> dict[str, Any]:
        caller_values = {
            key: value for key, value in values.items()
            if not key.endswith("_authority")
        }
        return {
            "schema_version": _SCHEMA_VERSION,
            "operation_type": operation_type,
            "project_id": self.project_id,
            "request": values,
            "request_fingerprint": _fingerprint(values),
            "caller_fingerprint": _fingerprint(caller_values),
            "created_at": _now(),
        }

    def _claim(
        self,
        operation_id: str,
        request: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        op_path = self._operation_path(operation_id)
        if op_path.exists():
            existing = _load_json(op_path)
            if existing.get("caller_fingerprint") == request.get("caller_fingerprint"):
                return existing, True
            raise OperationConflictError(
                "Operation ID already claimed with a different request"
            )
        op_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_json(op_path, request)
        return request, False

    def _planning_authority(self) -> dict[str, Any]:
        path = self.context.data_dir / "next_chapter_plan.json"
        if not path.exists():
            raise PlanningStaleError("Planning authority is missing")
        try:
            raw = path.read_bytes()
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PlanningStaleError("Planning authority is invalid") from exc
        if not isinstance(payload, dict):
            raise PlanningStaleError("Planning authority must be an object")
        return {
            "path": "data/next_chapter_plan.json",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "chapter_id": int(payload.get("chapter_id", 0) or 0),
            "revision": str(payload.get("revision", "") or ""),
        }

    def _completion_authority(self, chapter_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
        path = (
            self.context.data_dir / "chapter_commits" /
            f"commit_{chapter_id:03d}.json"
        )
        if not path.exists():
            raise CurrentChapterNotCompleteError(
                f"Chapter {chapter_id} has not been committed"
            )
        try:
            raw = path.read_bytes()
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CommitResultInvalidError(
                f"Chapter {chapter_id} completion authority is invalid"
            ) from exc
        if not isinstance(payload, dict) or int(payload.get("chapter_id", 0) or 0) != chapter_id:
            raise CommitResultInvalidError(
                f"Chapter {chapter_id} completion authority scope is invalid"
            )
        status = str(payload.get("status", "") or "")
        if status == "recovery_required":
            raise CommitRecoveryRequiredError(
                f"Chapter {chapter_id} requires commit recovery"
            )
        if status not in ("committed", "committed_with_warnings"):
            raise CommitResultInvalidError(
                f"Chapter {chapter_id} commit status: {status}"
            )
        authority = {
            "path": f"data/chapter_commits/commit_{chapter_id:03d}.json",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "status": status,
            "commit_id": str(payload.get("commit_id", "") or ""),
            "source_version_id": str(payload.get("source_version_id", "") or ""),
            "canon_revision_id": str(payload.get("canon_revision_id", "") or ""),
        }
        return payload, authority

    def _branch_authority(self, timeline_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        registry = self._read_branch_registry_projection(timeline_id)
        if registry.get("project_id") not in (None, self.project_id):
            raise ChapterLifecycleError("Project ID mismatch")
        if registry.get("timeline_id") not in (None, timeline_id):
            raise ChapterLifecycleError("Timeline ID mismatch")
        active_branch = registry.get("active_branch_id")
        if not isinstance(active_branch, str) or not active_branch:
            raise BranchStaleError("No active branch is available")
        lifecycle_status = "unknown"
        try:
            from core.contracts.narrative_turn import BranchLifecycleStatus, TimelineContext
            from system.narrative_branch_store import NarrativeBranchStore

            branch = NarrativeBranchStore(self.context).get_branch(
                TimelineContext(self.project_id, timeline_id), active_branch
            )
            if branch is not None:
                lifecycle_status = branch.lifecycle_status.value
                if branch.lifecycle_status == BranchLifecycleStatus.ARCHIVED:
                    raise BranchArchivedError("Bound branch is archived")
        except BranchArchivedError:
            raise
        except Exception:
            lifecycle_status = "unknown"
        canonical = _canonical(registry).encode("utf-8")
        return registry, {
            "timeline_id": timeline_id,
            "active_branch_id": active_branch,
            "revision": str(registry.get("revision", "0") or "0"),
            "sha256": hashlib.sha256(canonical).hexdigest(),
            "lifecycle_status": lifecycle_status,
        }

    def _validate_bound_authorities(self, authority: dict[str, Any]) -> None:
        request = authority.get("request", {})
        chapter_id = int(request.get("current_chapter_id", 0) or 0)
        timeline_id = str(request.get("timeline_id", "main") or "main")
        _commit, completion = self._completion_authority(chapter_id)
        planning = self._planning_authority()
        _registry, branch = self._branch_authority(timeline_id)
        if completion != request.get("completion_authority"):
            raise CommitResultInvalidError("Completion authority changed during lifecycle operation")
        if planning != request.get("planning_authority"):
            raise PlanningStaleError("Planning authority changed during lifecycle operation")
        if branch != request.get("branch_authority"):
            if branch.get("active_branch_id") != request.get("branch_authority", {}).get("active_branch_id"):
                raise BranchArchivedError("Bound branch is no longer active")
            raise BranchStaleError("Branch authority changed during lifecycle operation")

    def _cleanup_incomplete_successor(
        self, operation_id: str, authority: dict[str, Any]
    ) -> None:
        """Remove only successor assets owned by an incomplete operation."""
        if self._result_path(operation_id).exists():
            return
        phase_path = self._phase_path(operation_id)
        phase = _load_json(phase_path).get("phase", "") if phase_path.exists() else ""
        request = authority.get("request", {})
        chapter_id = int(request.get("next_chapter_id", 0) or 0)
        if chapter_id <= 0:
            return
        if phase in ("initializing_versions", "initializing_canon", "publishing_chapter"):
            (
                self.context.data_dir / "versions" /
                f"chapter_{chapter_id:03d}_versions.json"
            ).unlink(missing_ok=True)
        if phase in ("initializing_canon", "publishing_chapter"):
            shutil.rmtree(
                self.context.data_dir / "canon_versions" / f"chapter_{chapter_id:03d}",
                ignore_errors=True,
            )
        if phase == "publishing_chapter":
            chapter_path = self.context.chapters_dir / f"chapter_{chapter_id:03d}.md"
            staging_path = self._staging_path(operation_id)
            try:
                staging = _load_json(staging_path)
                if (
                    chapter_path.exists()
                    and chapter_path.read_text(encoding="utf-8")
                    == str(staging.get("content") or "")
                ):
                    chapter_path.unlink()
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                pass
        self._staging_path(operation_id).unlink(missing_ok=True)
        self._phase(operation_id, "authority_stale")

    def _rewind_unpublished_assets(
        self, operation_id: str, authority: dict[str, Any]
    ) -> None:
        phase_path = self._phase_path(operation_id)
        if not phase_path.exists():
            return
        phase = str(_load_json(phase_path).get("phase", "") or "")
        if phase not in ("initializing_versions", "initializing_canon"):
            return
        chapter_id = int(
            authority.get("request", {}).get("next_chapter_id", 0) or 0
        )
        if chapter_id <= 0 or self._is_chapter_file(chapter_id):
            return
        (
            self.context.data_dir / "versions" /
            f"chapter_{chapter_id:03d}_versions.json"
        ).unlink(missing_ok=True)
        shutil.rmtree(
            self.context.data_dir / "canon_versions" / f"chapter_{chapter_id:03d}",
            ignore_errors=True,
        )
        self._phase(operation_id, "staging_created")

    def _replay(
        self, operation_id: str, authority: dict[str, Any]
    ) -> dict[str, Any]:
        result_path = self._result_path(operation_id)
        if result_path.exists():
            result = _load_json(result_path)
            phase_path = self._phase_path(operation_id)
            phase = _load_json(phase_path) if phase_path.exists() else {}
            if phase.get("phase") != "completed":
                self._phase(operation_id, "completed")
            return result
        phase_path = self._phase_path(operation_id)
        if not phase_path.exists():
            raise ChapterLifecycleRecoveryRequiredError(
                "Operation authority exists but phase/result missing"
            )
        phase_data = _load_json(phase_path)
        last_phase = str(phase_data.get("phase") or "")
        return self._resume_from(operation_id, authority, last_phase)

    def _phase(self, operation_id: str, phase: str) -> None:
        path = self._phase_path(operation_id)
        _atomic_json(path, {"phase": phase, "updated_at": _now()})

    def _complete(
        self,
        operation_id: str,
        authority: dict[str, Any],
        result: dict[str, Any],
        *,
        recovery_performed: bool = False,
    ) -> dict[str, Any]:
        result["operation_id"] = operation_id
        result["operation_type"] = authority.get("operation_type", "")
        result["project_id"] = self.project_id
        result["completed_at"] = _now()
        result["outcome_fingerprint"] = _fingerprint(result)
        if recovery_performed:
            result["recovery_performed"] = True
        result_path = self._result_path(operation_id)
        try:
            _atomic_json(result_path, result)
        except OSError as exc:
            raise ChapterLifecycleRecoveryRequiredError(
                "Durable lifecycle result publication failed"
            ) from exc
        try:
            self._staging_path(operation_id).unlink(missing_ok=True)
        except OSError:
            pass
        return result

    @contextmanager
    def timeline_authority_lock(self, timeline_id: str, timeout: float = 15.0):
        """Serialize chapter publication with branch archive for one timeline."""
        self._validate_id(timeline_id, "timeline_id")
        with self._operation_lock(f"{timeline_id}:authority", timeout=timeout):
            yield

    def assert_branch_archive_safe(self, timeline_id: str, branch_id: str) -> None:
        """Fail closed while a bound chapter lifecycle operation is incomplete."""
        self._validate_id(timeline_id, "timeline_id")
        self._validate_id(branch_id, "branch_id")
        if not self._operations_dir.exists():
            return
        for path in self._operations_dir.glob("*.json"):
            if path.name.endswith((".phase.json", ".result.json", ".staging.json")):
                continue
            try:
                authority = _load_json(path)
            except (OSError, json.JSONDecodeError):
                continue
            request = authority.get("request", {})
            bound = request.get("branch_authority", {})
            if (
                request.get("timeline_id") == timeline_id
                and bound.get("active_branch_id") == branch_id
                and not self._result_path(path.stem).exists()
            ):
                raise ChapterLifecycleRecoveryRequiredError(
                    "A chapter lifecycle operation must be recovered before branch archive"
                )

    @contextmanager
    def _operation_lock(
        self, lock_key: str, timeout: float = 15.0
    ):
        path = self._lock_path(lock_key)
        held = getattr(_LOCAL_OPERATION_LOCKS, "paths", set())
        lock_name = str(path)
        if lock_name in held:
            yield
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        nonce = secrets.token_hex(16)
        owner_path = path / "owner.json"

        deadline = time.monotonic() + timeout
        while True:
            try:
                path.mkdir()
                try:
                    _atomic_json(
                        owner_path,
                        {
                            "pid": os.getpid(),
                            "thread_id": threading.get_ident(),
                            "nonce": nonce,
                            "acquired_at": _now(),
                        },
                    )
                except BaseException:
                    owner_path.unlink(missing_ok=True)
                    try:
                        path.rmdir()
                    except OSError:
                        pass
                    raise
                break
            except FileExistsError:
                owner: dict[str, Any] = {}
                try:
                    owner = _load_json(owner_path)
                except (FileNotFoundError, json.JSONDecodeError):
                    pass
                owner_pid = int(owner.get("pid", 0) or 0)
                owner_thread = int(owner.get("thread_id", 0) or 0)
                stale = False
                if owner_pid == os.getpid() and owner_thread:
                    stale = owner_thread not in {
                        item.ident for item in threading.enumerate()
                    }
                elif owner_pid:
                    if os.name == "nt":
                        import ctypes

                        synchronize = 0x00100000
                        handle = ctypes.windll.kernel32.OpenProcess(
                            synchronize, False, owner_pid
                        )
                        if handle:
                            ctypes.windll.kernel32.CloseHandle(handle)
                        else:
                            # Access denied means the process exists but cannot
                            # be queried; other errors mean the owner is gone.
                            stale = ctypes.get_last_error() != 5
                    else:
                        try:
                            os.kill(owner_pid, 0)
                        except OSError:
                            stale = True
                else:
                    try:
                        stale = time.time() - path.stat().st_mtime > 1.0
                    except OSError:
                        stale = False
                if stale:
                    try:
                        owner_path.unlink(missing_ok=True)
                        path.rmdir()
                        continue
                    except OSError:
                        pass
                if time.monotonic() > deadline:
                    raise ChapterLifecycleError(
                        f"Could not acquire lock for {lock_key}"
                    )
                time.sleep(0.1)

        held.add(lock_name)
        _LOCAL_OPERATION_LOCKS.paths = held
        try:
            yield
        finally:
            held.remove(lock_name)
            try:
                owner_path.unlink(missing_ok=True)
                path.rmdir()
            except OSError:
                pass

    def _read_state_projection(self) -> dict[str, Any]:
        return (
            self.store.read_json("data/state.json", default={}, expected_type=dict)
            or {}
        )

    def _read_next_plan_projection(self) -> dict[str, Any]:
        return (
            self.store.read_json(
                "data/next_chapter_plan.json", default={}, expected_type=dict
            )
            or {}
        )

    def _read_branch_registry_projection(
        self, timeline_id: str
    ) -> dict[str, Any]:
        self._validate_id(timeline_id, "timeline_id")
        if timeline_id != "main":
            raise ChapterLifecycleError("Only the authoritative main timeline may create chapters")
        path = (
            self.context.data_dir / "branches" / timeline_id / "registry.json"
        )
        if not path.exists():
            return {
                "project_id": self.project_id,
                "timeline_id": timeline_id,
                "active_branch_id": None,
                "revision": "0",
            }
        return _load_json(path)

    def _is_chapter_file(self, chapter_id: int) -> bool:
        return (self.context.chapters_dir / f"chapter_{chapter_id:03d}.md").exists()

    def _has_versions_index(self, chapter_id: int) -> bool:
        return (
            self.context.data_dir
            / "versions"
            / f"chapter_{chapter_id:03d}_versions.json"
        ).exists()

    def _has_canon_index(self, chapter_id: int) -> bool:
        return (
            self.context.data_dir
            / "canon_versions"
            / f"chapter_{chapter_id:03d}"
            / "index.json"
        ).exists()

    def initialize_chapter_versions(
        self,
        chapter_id: int,
    ) -> dict[str, Any]:
        from system.version_manager import initialize_chapter_versions as _init_versions
        return _init_versions(chapter_id, self.context.data_dir)

    def initialize_chapter_canon(
        self,
        chapter_id: int,
        content: str,
    ) -> dict[str, Any]:
        return self.revision_service.initialize_chapter_canon(
            chapter_id, content, publish_chapter=False
        )

    def _read_committed_chapters(self) -> list[dict[str, Any]]:
        root = self.context.data_dir / "chapter_commits"
        if not root.exists():
            return []
        results: list[dict[str, Any]] = []
        for path in root.glob("commit_*.json"):
            try:
                data = _load_json(path)
                if isinstance(data, dict):
                    results.append(data)
            except (json.JSONDecodeError, OSError):
                pass
        return sorted(
            results,
            key=lambda x: int(x.get("chapter_id", 0) or 0),
        )

    # ── Pure read: resolve next chapter ──────────────────────────

    def resolve_next_chapter(
        self,
        *,
        project_id: str | None = None,
        timeline_id: str = "main",
        current_chapter_id: int | None = None,
    ) -> dict[str, Any]:
        """Pure read resolution of the next chapter status.

        Never creates files, never modifies state.
        Returns structured status for the caller to decide on mutation.
        """
        if project_id is not None and project_id != self.project_id:
            raise ChapterLifecycleError("Project ID mismatch")
        state = self._read_state_projection()
        plan = self._read_next_plan_projection()

        if current_chapter_id is None:
            current_chapter_id = int(state.get("current_chapter", 0) or 0)

        if current_chapter_id <= 0:
            return {
                "status": "NEXT_CHAPTER_BLOCKED",
                "reason": "NO_CURRENT_CHAPTER",
                "current_chapter_id": None,
                "next_chapter_id": None,
                "existence": "absent",
                "message": "No current chapter set. Complete a chapter first.",
                "warnings": [],
            }

        next_id = current_chapter_id + 1
        next_exists = self._is_chapter_file(next_id)

        has_versions = self._has_versions_index(next_id)
        has_canon = self._has_canon_index(next_id)

        branch_registry = self._read_branch_registry_projection(timeline_id)
        active_branch_id = branch_registry.get("active_branch_id")
        branch_revision = str(branch_registry.get("revision", "0") or "0")

        committed = self._read_committed_chapters()
        current_commit = next(
            (
                c
                for c in committed
                if int(c.get("chapter_id", 0) or 0) == current_chapter_id
            ),
            None,
        )
        current_complete = (
            current_commit is not None
            and current_commit.get("status") in ("committed", "committed_with_warnings")
        )

        if not current_complete:
            return {
                "status": "NEXT_CHAPTER_BLOCKED",
                "reason": "CURRENT_CHAPTER_NOT_COMPLETE",
                "current_chapter_id": current_chapter_id,
                "next_chapter_id": next_id,
                "existence": "absent" if not next_exists else "exists",
                "current_commit_status": (
                    current_commit.get("status") if current_commit else None
                ),
                "message": f"Chapter {current_chapter_id} is not committed.",
                "warnings": [],
            }

        if next_exists and has_versions and has_canon:
            return {
                "status": "NEXT_CHAPTER_AVAILABLE",
                "reason": None,
                "current_chapter_id": current_chapter_id,
                "next_chapter_id": next_id,
                "existence": "exists",
                "version_readiness": "ready",
                "canon_readiness": "ready",
                "branch_id": active_branch_id,
                "branch_revision": branch_revision,
                "commit_ready": True,
                "message": f"Chapter {next_id} is ready.",
                "warnings": [],
            }

        if next_exists and not (has_versions and has_canon):
            missing: list[str] = []
            if not has_versions:
                missing.append("versions")
            if not has_canon:
                missing.append("canon")
            return {
                "status": "NEXT_CHAPTER_RECOVERY_REQUIRED",
                "reason": "INCOMPLETE_CHAPTER",
                "current_chapter_id": current_chapter_id,
                "next_chapter_id": next_id,
                "existence": "exists",
                "missing_assets": missing,
                "message": f"Chapter {next_id} exists but missing: {', '.join(missing)}.",
                "warnings": [],
            }

        return {
            "status": "NEXT_CHAPTER_MISSING",
            "reason": None,
            "current_chapter_id": current_chapter_id,
            "next_chapter_id": next_id,
            "existence": "absent",
            "version_readiness": "not_ready",
            "canon_readiness": "not_ready",
            "branch_id": active_branch_id,
            "branch_revision": branch_revision,
            "commit_ready": True,
            "message": f"Chapter {next_id} has not been created yet.",
            "warnings": [],
        }

    # ── Explicit create: next chapter ─────────────────────────────

    def create_next_chapter(
        self,
        *,
        operation_id: str,
        project_id: str | None = None,
        timeline_id: str = "main",
        current_chapter_id: int | None = None,
        expected_completion_status: str | None = None,
        expected_active_branch_id: str | None = None,
        expected_branch_revision: str | None = None,
        planning_chapter_id: int | None = None,
    ) -> dict[str, Any]:
        """Explicit creation of the next chapter with operation authority.

        Follows: claim → fence → publish → init_versions → init_canon → complete.
        Recovery replays resume from the last committed phase.
        """
        if project_id is not None and project_id != self.project_id:
            raise ChapterLifecycleError("Project ID mismatch")

        state = self._read_state_projection()
        if current_chapter_id is None:
            current_chapter_id = int(state.get("current_chapter", 0) or 0)

        if current_chapter_id <= 0:
            raise CurrentChapterNotCompleteError("No current chapter set")

        next_chapter_id = current_chapter_id + 1
        caller_values = {
            "project_id": self.project_id,
            "timeline_id": timeline_id,
            "current_chapter_id": current_chapter_id,
            "next_chapter_id": next_chapter_id,
            "expected_completion_status": expected_completion_status,
            "expected_active_branch_id": expected_active_branch_id,
            "expected_branch_revision": expected_branch_revision,
            "planning_chapter_id": planning_chapter_id,
        }
        op_path = self._operation_path(operation_id)
        if op_path.exists() and self._result_path(operation_id).exists():
            existing = _load_json(op_path)
            if existing.get("caller_fingerprint") != _fingerprint(caller_values):
                raise OperationConflictError(
                    "Operation ID already claimed with a different request"
                )
            return self._replay(operation_id, existing)

        lock_key = f"{timeline_id}:chapter:{next_chapter_id}"
        with self._operation_lock(f"{timeline_id}:authority"), self._operation_lock(lock_key):
            current_commit, completion_authority = self._completion_authority(
                current_chapter_id
            )
            commit_status = str(current_commit.get("status", "") or "")
            branch_registry, branch_authority = self._branch_authority(timeline_id)
            planning_authority = self._planning_authority()
            active_branch = branch_authority["active_branch_id"]
            branch_revision = branch_authority["revision"]
            if expected_active_branch_id is not None and active_branch != expected_active_branch_id:
                raise BranchStaleError(
                    f"Active branch changed: expected {expected_active_branch_id}, got {active_branch}"
                )
            if (
                expected_branch_revision is not None
                and str(expected_branch_revision) != branch_revision
            ):
                raise BranchStaleError(
                    f"Branch revision changed: expected {expected_branch_revision}, got {branch_revision}"
                )
            if expected_completion_status is not None and expected_completion_status != commit_status:
                raise ChapterLifecycleError(
                    f"Completion status mismatch: expected {expected_completion_status}, got {commit_status}"
                )
            if planning_chapter_id is not None and planning_authority["chapter_id"] not in (
                0, planning_chapter_id
            ):
                raise PlanningStaleError("Planning chapter identity is stale")

            request = self._request_payload(
                "create_next_chapter",
                {
                    **caller_values,
                    "branch_authority": branch_authority,
                    "planning_authority": planning_authority,
                    "completion_authority": completion_authority,
                },
            )
            authority, replay = self._claim(operation_id, request)
            if replay:
                return self._replay(operation_id, authority)

            state_check = self._read_state_projection()
            current_after = int(state_check.get("current_chapter", 0) or 0)
            if current_after != current_chapter_id:
                raise ChapterCreationConflictError(
                    f"Current chapter changed during operation: was {current_chapter_id}, now {current_after}"
                )

            self._validate_bound_authorities(authority)

            if self._is_chapter_file(next_chapter_id):
                has_versions = self._has_versions_index(next_chapter_id)
                has_canon = self._has_canon_index(next_chapter_id)
                if has_versions and has_canon:
                    continuity = self._capture_memory_continuity(
                        operation_id=operation_id,
                        authority=authority,
                        timeline_id=timeline_id,
                        active_branch=active_branch,
                        branch_revision=branch_revision,
                        current_chapter_id=current_chapter_id,
                        next_chapter_id=next_chapter_id,
                    )
                    result = {
                        "status": "NEXT_CHAPTER_ALREADY_EXISTS",
                        "chapter_id": next_chapter_id,
                        "message": f"Chapter {next_chapter_id} already exists with complete assets.",
                        "chapter_created": False,
                        "creation_source": "existing",
                        "memory_readiness": "ready",
                        "vector_readiness": "not_ready",
                        "memory_continuity": self._continuity_result(continuity),
                    }
                    return self._complete(operation_id, authority, result, recovery_performed=True)
                raise NextChapterAlreadyExistsError(
                    f"Chapter {next_chapter_id} already exists but is incomplete. Manual recovery required."
                )

            self._step_claimed(
                operation_id=operation_id,
                authority=authority,
                current_chapter_id=current_chapter_id,
                next_chapter_id=next_chapter_id,
                timeline_id=timeline_id,
                commit_status=commit_status,
                active_branch=active_branch,
                branch_revision=branch_revision,
            )

            return self._resume_from(operation_id, authority, "claimed")

    # ── Recovery: replay / resume incomplete operation ───────────

    def resume_operation(self, operation_id: str) -> dict[str, Any]:
        """Resume a previously interrupted operation by replaying it."""
        op_path = self._operation_path(operation_id)
        if not op_path.exists():
            raise ChapterLifecycleError(
                f"Operation {operation_id} not found"
            )
        authority = _load_json(op_path)
        return self._replay(operation_id, authority)

    def _resume_from(
        self,
        operation_id: str,
        authority: dict[str, Any],
        last_phase: str,
    ) -> dict[str, Any]:
        request = authority.get("request", {})
        current_chapter_id = int(request.get("current_chapter_id", 0) or 0)
        next_chapter_id = int(request.get("next_chapter_id", 0) or 0)
        timeline_id = str(request.get("timeline_id", "main") or "main")
        expected_completion_status = request.get("expected_completion_status")
        expected_active_branch_id = request.get("expected_active_branch_id")
        expected_branch_revision = request.get("expected_branch_revision")

        current_commit, _completion = self._completion_authority(current_chapter_id)
        commit_status = str(current_commit.get("status", "") or "")

        if expected_completion_status is not None:
            if expected_completion_status != commit_status:
                raise ChapterLifecycleError(
                    f"Completion status mismatch: expected {expected_completion_status}, got {commit_status}"
                )

        branch_registry = self._read_branch_registry_projection(timeline_id)
        active_branch = branch_registry.get("active_branch_id")
        if expected_active_branch_id is not None:
            if active_branch != expected_active_branch_id:
                raise BranchStaleError(
                    f"Active branch changed: expected {expected_active_branch_id}, got {active_branch}"
                )

        branch_revision = str(branch_registry.get("revision", "0") or "0")
        if expected_branch_revision is not None:
            if str(expected_branch_revision) != branch_revision:
                raise BranchStaleError(
                    f"Branch revision changed: expected {expected_branch_revision}, got {branch_revision}"
                )

        try:
            self._validate_bound_authorities(authority)
        except ChapterLifecycleError:
            self._cleanup_incomplete_successor(operation_id, authority)
            raise

        STEPS = [
            ("claimed", self._step_claimed),
            ("fence_check", self._step_fence_check),
            ("staging_created", self._step_staging),
            ("initializing_versions", self._step_init_versions),
            ("initializing_canon", self._step_init_canon),
            ("publishing_chapter", self._step_publishing),
            ("capturing_memory_continuity", self._step_memory_continuity),
            ("completed", self._step_completed),
        ]
        start_index = 0
        for i, (phase_name, _) in enumerate(STEPS):
            if phase_name == last_phase:
                start_index = i + 1
                break

        lock_key = f"{timeline_id}:chapter:{next_chapter_id}"
        with self._operation_lock(f"{timeline_id}:authority"), self._operation_lock(lock_key):
            try:
                self._validate_bound_authorities(authority)
                for i in range(start_index, len(STEPS)):
                    phase_name, step_fn = STEPS[i]
                    step_fn(
                        operation_id=operation_id,
                        authority=authority,
                        current_chapter_id=current_chapter_id,
                        next_chapter_id=next_chapter_id,
                        timeline_id=timeline_id,
                        commit_status=commit_status,
                        active_branch=active_branch,
                        branch_revision=branch_revision,
                    )
            except ChapterLifecycleError:
                self._rewind_unpublished_assets(operation_id, authority)
                raise

            result_path = self._result_path(operation_id)
            if result_path.exists():
                return _load_json(result_path)

            if last_phase == "completed" or start_index >= len(STEPS):
                if self._is_chapter_file(next_chapter_id):
                    has_versions = self._has_versions_index(next_chapter_id)
                    has_canon = self._has_canon_index(next_chapter_id)
                    if has_versions and has_canon:
                        result = {
                            "status": "CHAPTER_CREATED",
                            "chapter_id": next_chapter_id,
                            "chapter_created": True,
                            "chapter_navigation_ready": True,
                            "turn_start_ready": False,
                            "memory_readiness": "not_ready",
                            "vector_readiness": "not_ready",
                            "blocking_reason": None,
                            "warnings": [],
                            "version_initialized": True,
                            "canon_initialized": True,
                            "branch_carry_forward": {
                                "branch_id": active_branch,
                                "branch_revision": branch_revision,
                            },
                            "commit_snapshot": {
                                "source_chapter_id": current_chapter_id,
                                "source_status": commit_status,
                                "source_commit_id": "",
                            },
                        }
                        return result
            raise ChapterLifecycleRecoveryRequiredError(
                f"Operation {operation_id} did not complete; no durable result"
            )

    def _step_claimed(self, **kwargs: Any) -> None:
        op_id = kwargs["operation_id"]
        self._phase(op_id, "claimed")
        self._fault("after_claim")

    def _step_fence_check(self, **kwargs: Any) -> None:
        op_id = kwargs["operation_id"]
        current_chapter_id = kwargs["current_chapter_id"]
        timeline_id = kwargs["timeline_id"]
        branch_revision = kwargs["branch_revision"]
        active_branch = kwargs["active_branch"]

        state_check = self._read_state_projection()
        current_after = int(state_check.get("current_chapter", 0) or 0)
        if current_after != current_chapter_id:
            raise ChapterCreationConflictError(
                f"Current chapter changed during operation: was {current_chapter_id}, now {current_after}"
            )

        registry_check = self._read_branch_registry_projection(timeline_id)
        if str(registry_check.get("revision", "0") or "0") != branch_revision:
            raise BranchStaleError("Branch revision changed during operation")
        if registry_check.get("active_branch_id") != active_branch:
            raise BranchStaleError("Active branch changed during operation")

        next_chapter_id = kwargs["next_chapter_id"]
        if self._is_chapter_file(next_chapter_id):
            has_versions = self._has_versions_index(next_chapter_id)
            has_canon = self._has_canon_index(next_chapter_id)
            if has_versions and has_canon:
                op_id = kwargs["operation_id"]
                authority = kwargs["authority"]
                result = {
                    "status": "NEXT_CHAPTER_ALREADY_EXISTS",
                    "chapter_id": next_chapter_id,
                    "message": f"Chapter {next_chapter_id} already exists with complete assets.",
                    "chapter_created": False,
                    "creation_source": "existing",
                }
                self._complete(op_id, authority, result, recovery_performed=True)
                return
            raise NextChapterAlreadyExistsError(
                f"Chapter {next_chapter_id} already exists but is incomplete. Manual recovery required."
            )

        self._phase(op_id, "fence_check")
        self._fault("after_fence")
        self._fault("after_successor_resolution")

    def _step_staging(self, **kwargs: Any) -> None:
        op_id = kwargs["operation_id"]
        next_chapter_id = kwargs["next_chapter_id"]
        chapter_content = f"# Chapter {format_chapter_id(next_chapter_id)}\n"
        _atomic_json(
            self._staging_path(op_id),
            {"chapter_id": next_chapter_id, "content": chapter_content},
        )
        self._phase(op_id, "staging_created")
        self._fault("after_staging_creation")

    def _step_publishing(self, **kwargs: Any) -> None:
        op_id = kwargs["operation_id"]
        next_chapter_id = kwargs["next_chapter_id"]
        self._validate_bound_authorities(kwargs["authority"])

        chapter_path = self.context.chapters_dir / f"chapter_{next_chapter_id:03d}.md"
        staging = _load_json(self._staging_path(op_id))
        chapter_content = str(staging.get("content") or "")
        if not chapter_content:
            raise ChapterLifecycleRecoveryRequiredError("Chapter staging content is missing")
        published = _publish_if_absent(
            chapter_path,
            chapter_content,
        )
        if not published:
            raise ChapterCreationConflictError(
                f"Chapter {next_chapter_id} was published by another operation"
            )
        self._phase(op_id, "publishing_chapter")
        self._fault("after_publish")

    def _step_init_versions(self, **kwargs: Any) -> None:
        op_id = kwargs["operation_id"]
        next_chapter_id = kwargs["next_chapter_id"]

        try:
            initialize_chapter_versions(next_chapter_id, self.context.data_dir)
        except Exception as exc:
            (
                self.context.data_dir / "versions" /
                f"chapter_{next_chapter_id:03d}_versions.json"
            ).unlink(missing_ok=True)
            raise VersionInitializationError(str(exc)) from exc
        self._phase(op_id, "initializing_versions")
        self._fault("after_version_init")

    def _step_init_canon(self, **kwargs: Any) -> None:
        op_id = kwargs["operation_id"]
        next_chapter_id = kwargs["next_chapter_id"]

        chapter_content = f"# Chapter {format_chapter_id(next_chapter_id)}\n"
        try:
            self.initialize_chapter_canon(next_chapter_id, chapter_content)
        except Exception as exc:
            shutil.rmtree(
                self.context.data_dir / "canon_versions" /
                f"chapter_{next_chapter_id:03d}",
                ignore_errors=True,
            )
            raise CanonInitializationError(str(exc)) from exc
        self._phase(op_id, "initializing_canon")
        self._fault("after_canon_init")

    @staticmethod
    def _continuity_result(continuity: dict[str, Any]) -> dict[str, Any]:
        return {
            "snapshot_id": continuity["snapshot_id"],
            "source_fingerprint": continuity["source_fingerprint"],
            "record_fingerprint": continuity["record_fingerprint"],
            "completion_state": continuity["completion_state"],
            "vector_role": continuity["vector_role"],
        }

    def _capture_memory_continuity(
        self,
        *,
        operation_id: str,
        authority: dict[str, Any],
        timeline_id: str,
        active_branch: str,
        branch_revision: str,
        current_chapter_id: int,
        next_chapter_id: int,
    ) -> dict[str, Any]:
        request = authority.get("request", {})
        try:
            return self.memory_continuity.create(
                operation_id=operation_id,
                project_id=self.project_id,
                timeline_id=timeline_id,
                branch_id=active_branch,
                branch_revision=branch_revision,
                previous_chapter_id=current_chapter_id,
                successor_chapter_id=next_chapter_id,
                completion_authority=request.get("completion_authority", {}),
            )
        except BranchMemoryContinuityError as exc:
            raise MemoryContinuityError(str(exc)) from exc

    def _step_memory_continuity(self, **kwargs: Any) -> None:
        op_id = kwargs["operation_id"]
        self._capture_memory_continuity(
            operation_id=op_id,
            authority=kwargs["authority"],
            timeline_id=kwargs["timeline_id"],
            active_branch=kwargs["active_branch"],
            branch_revision=kwargs["branch_revision"],
            current_chapter_id=kwargs["current_chapter_id"],
            next_chapter_id=kwargs["next_chapter_id"],
        )
        self._fault("after_memory_continuity_snapshot")
        self._phase(op_id, "capturing_memory_continuity")

    def _step_completed(self, **kwargs: Any) -> None:
        op_id = kwargs["operation_id"]
        authority = kwargs["authority"]
        next_chapter_id = kwargs["next_chapter_id"]
        current_chapter_id = kwargs["current_chapter_id"]
        commit_status = kwargs["commit_status"]
        active_branch = kwargs["active_branch"]
        branch_revision = kwargs["branch_revision"]
        self._validate_bound_authorities(authority)
        try:
            continuity = self.memory_continuity.read(
                project_id=self.project_id,
                timeline_id=kwargs["timeline_id"],
                branch_id=active_branch,
                previous_chapter_id=current_chapter_id,
                successor_chapter_id=next_chapter_id,
            )
        except BranchMemoryContinuityError as exc:
            raise MemoryContinuityError(str(exc)) from exc

        result = {
            "status": "CHAPTER_CREATED",
            "chapter_id": next_chapter_id,
            "chapter_created": True,
            "chapter_navigation_ready": True,
            "turn_start_ready": False,
            "memory_readiness": "ready",
            "vector_readiness": "not_ready",
            "blocking_reason": None,
            "warnings": [],
            "version_initialized": True,
            "canon_initialized": True,
            "branch_carry_forward": {
                "branch_id": active_branch,
                "branch_revision": branch_revision,
            },
            "memory_continuity": self._continuity_result(continuity),
            "commit_snapshot": {
                "source_chapter_id": current_chapter_id,
                "source_status": commit_status,
                "source_commit_id": "",
            },
        }
        self._complete(op_id, authority, result)
        self._fault("after_result_publication")
        self._fault("before_completed_phase")
        self._fault("before_complete")
        self._phase(op_id, "completed")
