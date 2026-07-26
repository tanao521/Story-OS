"""Project Clone Service — Create independent project copies.

Clones a source project into a new independent project directory with:
- New project identity (project_id, slug, timestamps)
- Whitelisted business data copy (chapters, canon, summaries, etc.)
- Excluded runtime/derived data (chroma, pipelines, jobs, etc.)
- State transformation (preserve creative progress, clear runtime state)
- Independent vector index rebuild
- Source project tracking (cloned_from_project_id, cloned_at)
- Symlink/junction/reparse point detection for path boundary safety
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat as stat_module
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.project_context import ProjectContext, get_project_context
from system.data_store import DataStore


class CloneError(RuntimeError):
    """Project clone failed without changing source or leaving visible artifacts."""


class ClonePreflightError(CloneError):
    """Pre-clone validation failed."""


class CloneCopyError(CloneError):
    """Copying whitelisted data failed — symlink or path escape detected."""


class ClonePublishError(CloneError):
    """Publishing the cloned project directory failed."""


_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}

# Whitelisted data subdirectories to copy
_COPY_DATA_SUBDIRS: frozenset[str] = frozenset({
    "chapters",
    "canon_versions",
    "summaries",
    "drafts",
    "edited",
    "manual",
    "versions",
    "reviews",
    "quality_reports",
    "continuity_reports",
    "todos",
    "context",
    "narrative_memory",
    "planning_control",
})

# Whitelisted top-level data files to copy
_COPY_DATA_FILES: frozenset[str] = frozenset({
    "story_spec.json",
    "state.json",
    "story_blueprint.json",
    "characters.json",
    "world_bible.json",
    "next_chapter_plan.json",
    "model_preferences.json",
    "model_cost_limits.json",
})

# Data subdirectories that must NOT be copied
_EXCLUDE_DATA_SUBDIRS: frozenset[str] = frozenset({
    "chroma",
    "pipeline_runs",
    "commit_runs",
    "vector_sync_runs",
    "jobs",
    "logs",
    "model_runs",
    "agents",
    "creative_loop",
    "archive",
})

# State fields that represent creative progress — preserve on clone
_PRESERVE_STATE_KEYS: frozenset[str] = frozenset({
    "current_chapter",
    "current_stage",
    "plot",
    "foreshadows",
    "characters",
    "assets",
    "draft",
    "edited",
    "blueprint",
    "next_chapter_plan",
    "context",
    "obsidian",
    "vector_memory",
})

# State fields that represent runtime state — clear on clone
_CLEAR_STATE_KEYS: frozenset[str] = frozenset({
    "running_pipeline",
    "active_job",
    "pending_operations",
    "lock",
    "pid",
    "temp_files",
})


class CloneProjectResult:
    """Structured result from a project clone operation."""

    def __init__(
        self,
        status: str,
        source_project_id: str,
        project_id: str,
        project_slug: str,
        project_root: str,
        timeline_id: str = "main",
        copied_items: list[str] | None = None,
        skipped_items: list[str] | None = None,
        warnings: list[str] | None = None,
        vector_sync_operation_id: str | None = None,
    ):
        self.status = status
        self.source_project_id = source_project_id
        self.project_id = project_id
        self.project_slug = project_slug
        self.project_root = project_root
        self.timeline_id = timeline_id
        self.copied_items = copied_items or []
        self.skipped_items = skipped_items or []
        self.warnings = warnings or []
        self.vector_sync_operation_id = vector_sync_operation_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source_project_id": self.source_project_id,
            "project_id": self.project_id,
            "project_slug": self.project_slug,
            "project_root": self.project_root,
            "timeline_id": self.timeline_id,
            "copied_items": self.copied_items,
            "skipped_items": self.skipped_items,
            "warnings": self.warnings,
            "vector_sync_operation_id": self.vector_sync_operation_id,
        }


class ProjectCloneService:
    """Clone a source project into an independent new project."""

    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.projects_dir = self.workspace_root / "projects"

    def clone_project(
        self,
        source_context: ProjectContext,
        target_name: str,
        target_slug: str | None = None,
    ) -> CloneProjectResult:
        """Clone source project into a new independent project.

        Steps:
        1. Preflight validation
        2. Reserve target identity
        3. Create staging directory
        4. Copy whitelisted business data
        5. Transform metadata and state
        6. Validate cloned Canon projection
        7. Atomically publish target directory
        8. Rebuild vector index
        9. Post-clone verification
        10. Return structured result
        """
        source_project_id = self._read_project_id(source_context)
        if target_slug is None:
            target_slug = self._slugify(target_name)

        # 1. Preflight
        self._preflight(source_context, target_name, target_slug)

        # 2. Reserve identity
        new_project_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        # 3. Staging
        operation_id = f"clone_{uuid.uuid4().hex[:12]}"
        staging_dir = self.workspace_root / f".clone_{operation_id}"
        target_dir = self.projects_dir / target_slug

        try:
            staging_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise CloneError(f"Staging directory already exists: {staging_dir}") from exc

        copied_items: list[str] = []
        skipped_items: list[str] = []
        warnings: list[str] = []

        try:
            # 4. Copy whitelisted business data
            staging_data = staging_dir / "data"
            staging_data.mkdir(parents=True)
            self._copy_whitelisted_data(
                source_context.data_dir, staging_data,
                copied_items, skipped_items, warnings,
            )

            # 5. Transform metadata and state
            self._transform_project_metadata(
                staging_dir, source_project_id, new_project_id,
                target_name, target_slug, now,
            )
            self._transform_state(staging_data, new_project_id)

            # 6. Validate Canon projection
            self._validate_canon(staging_data, warnings)

            # 7. Publish
            for attempt in range(4):
                try:
                    staging_dir.rename(target_dir)
                    break
                except PermissionError as exc:
                    if attempt == 3:
                        raise ClonePublishError(
                            f"Cannot publish cloned project to {target_dir}: {exc}"
                        ) from exc
                    time.sleep(0.05 * (2**attempt))
                except OSError as exc:
                    raise ClonePublishError(
                        f"Cannot publish cloned project to {target_dir}: {exc}"
                    ) from exc

        except (ClonePreflightError, ClonePublishError, CloneCopyError):
            self._cleanup_staging(staging_dir)
            raise
        except Exception as exc:
            self._cleanup_staging(staging_dir)
            raise CloneError(f"Clone failed: {exc}") from exc

        # 8. Vector index rebuild
        vector_sync_operation_id: str | None = None
        try:
            new_context = get_project_context(target_dir)
            vector_sync_operation_id, rebuild_warnings = self._rebuild_vector_index(
                new_context, new_project_id,
            )
            warnings.extend(rebuild_warnings)
        except Exception as exc:
            warnings.append(f"Vector index rebuild failed: {str(exc)[:200]}")

        # 9. Post-clone verification
        if not (target_dir / "data" / "story_spec.json").exists():
            warnings.append("Cloned project missing story_spec.json")

        # 10. Return result
        has_warnings = bool(warnings)
        return CloneProjectResult(
            status="completed_with_warnings" if has_warnings else "completed",
            source_project_id=source_project_id,
            project_id=new_project_id,
            project_slug=target_slug,
            project_root=self._relative(target_dir),
            timeline_id="main",
            copied_items=copied_items,
            skipped_items=skipped_items,
            warnings=warnings,
            vector_sync_operation_id=vector_sync_operation_id,
        )

    def _preflight(
        self,
        source_context: ProjectContext,
        target_name: str,
        target_slug: str,
    ) -> None:
        if not source_context.root.exists():
            raise ClonePreflightError(f"Source project does not exist: {source_context.root}")
        if not (source_context.data_dir / "story_spec.json").exists():
            raise ClonePreflightError("Source project missing story_spec.json")
        if not (source_context.data_dir / "state.json").exists():
            raise ClonePreflightError("Source project missing state.json")
        if not target_name.strip():
            raise ClonePreflightError("Target name must not be empty")
        slug = target_slug.strip()
        if not slug:
            raise ClonePreflightError("Target slug must not be empty")
        if _INVALID.search(slug):
            raise ClonePreflightError(f"Target slug contains invalid characters: {slug}")
        if slug.casefold() in _RESERVED:
            raise ClonePreflightError(f"Target slug is a reserved name: {slug}")
        target_path = self.projects_dir / slug
        if target_path.exists():
            raise ClonePreflightError(f"Target project directory already exists: {slug}")
        try:
            target_path.resolve().relative_to(self.workspace_root)
        except ValueError:
            raise ClonePreflightError("Target path escapes workspace root")

    @staticmethod
    def _is_junction(path: Path) -> bool:
        """Check if path is a Windows junction (directory link).

        Uses os.path.isjunction if available, otherwise checks reparse point flag.
        Returns False on non-Windows platforms or if detection fails.
        """
        try:
            if hasattr(os.path, "isjunction"):
                return os.path.isjunction(path)
        except (OSError, ValueError):
            pass

        try:
            file_stat = os.lstat(path)
            if hasattr(file_stat, "st_file_attributes"):
                if file_stat.st_file_attributes & stat_module.FILE_ATTRIBUTE_REPARSE_POINT:
                    return True
        except (OSError, ValueError):
            pass

        return False

    @staticmethod
    def _is_reparse_point(path: Path) -> bool:
        """Check if path has FILE_ATTRIBUTE_REPARSE_POINT flag (Windows).

        This catches symlinks, junctions, mount points, and other reparse points.
        """
        try:
            file_stat = os.lstat(path)
            if hasattr(file_stat, "st_file_attributes"):
                return bool(file_stat.st_file_attributes & stat_module.FILE_ATTRIBUTE_REPARSE_POINT)
        except (OSError, ValueError):
            pass
        return False

    @staticmethod
    def _is_link_or_reparse_point(path: Path) -> bool:
        """Check if path is a symlink, junction, or reparse point.

        Cross-platform detection:
        - path.is_symlink() works on all platforms
        - os.path.isjunction() detects Windows junctions
        - FILE_ATTRIBUTE_REPARSE_POINT detects any reparse point
        """
        if path.is_symlink():
            return True
        if ProjectCloneService._is_junction(path):
            return True
        if ProjectCloneService._is_reparse_point(path):
            return True
        return False

    @staticmethod
    def _check_symlink_escape(path: Path, boundary: Path) -> None:
        """Raise CloneCopyError if path is a symlink/junction/reparse point escaping boundary.

        Conservative security approach: rejects ALL links/reparse points regardless
        of whether they currently point inside boundary, because:
        1. Link targets can change after cloning
        2. Cannot audit true destination at copy time
        3. Prevents path traversal attacks
        """
        if not path.exists():
            return

        if ProjectCloneService._is_link_or_reparse_point(path):
            link_type = "symlink" if path.is_symlink() else (
                "junction" if ProjectCloneService._is_junction(path) else "reparse point"
            )
            raise CloneCopyError(
                f"{link_type.capitalize()} detected at {path.name} — clone rejected for safety. "
                f"Links and reparse points are not allowed in source project directories."
            )

    def _check_directory_symlinks(self, directory: Path, boundary: Path) -> None:
        """Recursively check a directory for symlinks/junctions/reparse points."""
        if not directory.is_dir():
            return
        try:
            for entry in directory.iterdir():
                self._check_symlink_escape(entry, boundary)
                if entry.is_dir() and not ProjectCloneService._is_link_or_reparse_point(entry):
                    self._check_directory_symlinks(entry, boundary)
        except PermissionError:
            raise CloneCopyError(
                f"Permission denied reading directory: {directory} — clone rejected for safety"
            )

    def _copy_whitelisted_data(
        self,
        source_data: Path,
        target_data: Path,
        copied_items: list[str],
        skipped_items: list[str],
        warnings: list[str],
    ) -> None:
        # Copy whitelisted files (with symlink safety check)
        for filename in _COPY_DATA_FILES:
            src = source_data / filename
            if src.exists():
                self._check_symlink_escape(src, source_data.parent.parent)
                shutil.copy2(src, target_data / filename)
                copied_items.append(filename)
            else:
                skipped_items.append(filename)

        # Copy whitelisted subdirectories (with symlink safety check)
        for dirname in _COPY_DATA_SUBDIRS:
            src_dir = source_data / dirname
            if src_dir.is_dir():
                # Check for symlinks that escape source project boundary
                self._check_directory_symlinks(src_dir, source_data.parent.parent)
                dst_dir = target_data / dirname
                shutil.copytree(src_dir, dst_dir)
                count = sum(1 for _ in dst_dir.rglob("*") if _.is_file())
                copied_items.append(f"{dirname}/ ({count} files)")
            else:
                skipped_items.append(f"{dirname}/")

        # Copy memory directory selectively (exclude cache/run artifacts)
        src_memory = source_data / "memory"
        if src_memory.is_dir():
            dst_memory = target_data / "memory"
            dst_memory.mkdir(parents=True)
            for item in src_memory.iterdir():
                if item.is_file() and item.suffix == ".json":
                    shutil.copy2(item, dst_memory / item.name)
                    copied_items.append(f"memory/{item.name}")
                elif item.is_dir() and item.name not in {"cache", "runs", "tmp"}:
                    shutil.copytree(item, dst_memory / item.name)
                    copied_items.append(f"memory/{item.name}/")

        # Explicitly skip excluded directories
        for dirname in _EXCLUDE_DATA_SUBDIRS:
            src_dir = source_data / dirname
            if src_dir.exists():
                skipped_items.append(f"{dirname}/ (excluded)")

    def _transform_project_metadata(
        self,
        project_root: Path,
        source_project_id: str,
        new_project_id: str,
        target_name: str,
        target_slug: str,
        now: str,
    ) -> None:
        metadata_path = project_root / "project.json"
        metadata: dict[str, Any] = {}
        if metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        metadata.update({
            "schema_version": "1.0",
            "project_id": new_project_id,
            "slug": target_slug,
            "title": target_name,
            "project_root": self._relative(project_root),
            "created_at": now,
            "updated_at": now,
            "cloned_from_project_id": source_project_id,
            "cloned_at": now,
        })

        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _transform_state(self, data_dir: Path, new_project_id: str) -> None:
        state_path = data_dir / "state.json"
        if not state_path.exists():
            return

        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            return

        if not isinstance(state, dict):
            return

        # Build new state: preserve creative progress, clear runtime, transform nested
        new_state: dict[str, Any] = {}

        for key, value in state.items():
            if key in _CLEAR_STATE_KEYS:
                continue
            # Remove any absolute paths pointing to other projects
            if isinstance(value, str) and self._is_foreign_path(value):
                continue
            new_state[key] = value

        # Ensure project identity is updated
        new_state["project_id"] = new_project_id
        new_state["timeline_id"] = "main"

        # Transform nested vector_memory (DEFECT-VR-1 + VR-3)
        new_state["vector_memory"] = self._transform_vector_memory(
            state.get("vector_memory"), new_project_id,
        )

        # Transform nested obsidian (DEFECT-VR-2)
        new_state["obsidian"] = self._transform_obsidian_binding(
            state.get("obsidian"),
        )

        state_path.write_text(
            json.dumps(new_state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _transform_vector_memory(
        source_vm: Any, new_project_id: str,
    ) -> dict[str, Any]:
        """Transform vector_memory for clone: reset to stale, update identity.

        Clone project has not yet rebuilt its vector index, so it must not
        inherit source project's healthy status or source identity fields.
        """
        # Start from source if it's a dict, otherwise empty
        result: dict[str, Any] = {}
        if isinstance(source_vm, dict):
            # Preserve user preference fields (non-identity, non-runtime)
            _VM_PRESERVE_KEYS: frozenset[str] = frozenset({
                "enabled",
            })
            for key, value in source_vm.items():
                if key in _VM_PRESERVE_KEYS:
                    result[key] = value

        # Set target project identity — index is stale until rebuild completes
        result["project_id"] = new_project_id
        result["timeline_id"] = "main"
        result["healthy"] = False
        result["status"] = "stale"

        return result

    @staticmethod
    def _transform_obsidian_binding(source_obs: Any) -> dict[str, Any]:
        """Transform obsidian config for clone: detach external bindings.

        External vault bindings (vault_path, sync state, etc.) must NOT be
        inherited — the clone must not write to the source project's vault.
        Only user preference fields (format, enabled) are preserved.
        """
        result: dict[str, Any] = {}
        if isinstance(source_obs, dict):
            # Preserve only user preference fields — no paths, no sync state
            _OBS_PRESERVE_KEYS: frozenset[str] = frozenset({
                "enabled",
            })
            for key, value in source_obs.items():
                if key in _OBS_PRESERVE_KEYS:
                    result[key] = value

        return result

    def _update_vector_memory_state(
        self,
        data_dir: Path,
        new_project_id: str,
        *,
        healthy: bool,
        status: str,
        last_error: str | None = None,
    ) -> None:
        """Update vector_memory state in the cloned project's state.json.

        Called after rebuild success/failure to reflect actual index status.
        Writes are not silently swallowed — failures are propagated.
        """
        state_path = data_dir / "state.json"
        if not state_path.exists():
            return

        state = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            return

        vm = state.get("vector_memory")
        if not isinstance(vm, dict):
            vm = {}

        vm["project_id"] = new_project_id
        vm["timeline_id"] = "main"
        vm["healthy"] = healthy
        vm["status"] = status

        if last_error is not None:
            vm["last_error"] = last_error
        elif "last_error" in vm and healthy:
            # Clear stale error on success
            vm.pop("last_error", None)

        state["vector_memory"] = vm
        state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _validate_canon(self, data_dir: Path, warnings: list[str]) -> None:
        chapters_dir = data_dir / "chapters"
        canon_dir = data_dir / "canon_versions"

        if not chapters_dir.exists():
            return

        chapter_files = list(chapters_dir.glob("chapter_*.md"))
        if not chapter_files:
            return

        if not canon_dir.exists() or not any(canon_dir.iterdir()):
            warnings.append("Source has committed chapters but no canon_versions directory")

    def _rebuild_vector_index(
        self,
        context: ProjectContext,
        project_id: str,
    ) -> tuple[str | None, list[str]]:
        from system.vector_sync_run_store import VectorSyncRunStore, VectorSyncOperationType, VectorSyncStatus
        from system.vector_index_lifecycle import rebuild_project_index

        sync_store = VectorSyncRunStore(context)
        sync_run = sync_store.create(
            operation_type=VectorSyncOperationType.CLONE,
            project_id=project_id,
            timeline_id="main",
        )

        sync_store.update_status(sync_run.operation_id, VectorSyncStatus.RUNNING)

        warnings: list[str] = []

        result = rebuild_project_index(context, timeline_id="main")

        if result.get("status") == "success":
            sync_store.update_status(sync_run.operation_id, VectorSyncStatus.COMPLETED)
            try:
                self._update_vector_memory_state(
                    context.data_dir, project_id,
                    healthy=True, status="ready",
                )
            except Exception as exc:
                warnings.append(
                    f"VECTOR_STATE_UPDATE_FAILED: Failed to update cloned project vector state. "
                    f"Index rebuild succeeded but state may be stale. {str(exc)[:100]}"
                )
        else:
            error_msg = result.get("message", "Unknown error")
            sync_store.update_status(
                sync_run.operation_id,
                VectorSyncStatus.FAILED,
                error_msg,
            )
            warnings.append(f"VECTOR_REBUILD_FAILED: {error_msg[:200]}")
            try:
                self._update_vector_memory_state(
                    context.data_dir, project_id,
                    healthy=False, status="failed",
                    last_error=error_msg[:500],
                )
            except Exception as exc:
                warnings.append(
                    f"VECTOR_STATE_UPDATE_FAILED: Failed to update cloned project vector state. "
                    f"{str(exc)[:100]}"
                )

        return sync_run.operation_id, warnings

    def _read_project_id(self, context: ProjectContext) -> str:
        metadata_path = context.root / "project.json"
        if metadata_path.exists():
            try:
                data = json.loads(metadata_path.read_text(encoding="utf-8"))
                return str(data.get("project_id", context.root.name))
            except Exception:
                pass
        return context.root.name

    @staticmethod
    def _is_foreign_path(value: str) -> bool:
        """Check if a string looks like an absolute path to another project."""
        if not value:
            return False
        path = Path(value)
        if not path.is_absolute():
            return False
        # Only flag paths that look like project directories
        return "projects" in path.parts or "story-os-demo" in path.parts

    def _relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.workspace_root).as_posix()
        except ValueError:
            return path.as_posix()

    def _cleanup_staging(self, staging_dir: Path) -> None:
        if not staging_dir.exists():
            return

        try:
            resolved_staging = staging_dir.resolve()
            resolved_workspace = self.workspace_root.resolve()
            resolved_staging.relative_to(resolved_workspace)
        except (OSError, ValueError):
            return

        if not staging_dir.name.startswith(".clone_"):
            return

        if self._is_link_or_reparse_point(staging_dir):
            return

        shutil.rmtree(staging_dir, ignore_errors=True)

    @staticmethod
    def _slugify(title: str) -> str:
        value = _INVALID.sub("-", unicodedata.normalize("NFKC", title).strip())
        value = re.sub(r"\s+", "-", value)
        value = re.sub(r"[-.]+", "-", value).strip("-._")[:72].strip("-._")
        return "cloned-project" if not value or value.casefold() in _RESERVED else value
