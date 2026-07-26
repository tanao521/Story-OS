from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.project_context import ProjectContext

from .obsidian_binding import BindingMarker, BindingStatus, MARKER_FILENAME, ObsidianBinding
from .obsidian_binding_store import ObsidianBindingStore
from .obsidian_path_validator import ObsidianPathValidator


class ObsidianBindingError(Exception):
    pass


class ObsidianBindingNotFound(ObsidianBindingError):
    pass


class ObsidianBindingConflict(ObsidianBindingError):
    pass


class ObsidianBindingInvalid(ObsidianBindingError):
    pass


class ObsidianTargetUnsafe(ObsidianBindingError):
    pass


class ObsidianMarkerMismatch(ObsidianBindingError):
    pass


class ObsidianVaultMissing(ObsidianBindingError):
    pass


class ObsidianBindingService:
    def __init__(self, workspace_root: Path | None = None) -> None:
        self.store = ObsidianBindingStore(workspace_root)

    def bind(
        self,
        project_id: str,
        timeline_id: str,
        vault_root: Path,
        target_relative_path: str,
        adopt_existing: bool = False,
    ) -> ObsidianBinding:
        vault_root = vault_root.resolve()

        ok, reason = ObsidianPathValidator.validate(vault_root, target_relative_path)
        if not ok:
            raise ObsidianTargetUnsafe(f"Target path validation failed: {reason}")

        if self.store.is_target_conflict(vault_root, target_relative_path, exclude_project_id=project_id, exclude_timeline_id=timeline_id):
            raise ObsidianBindingConflict("Target path already bound to another project or timeline")

        target_full = vault_root / target_relative_path

        existing_marker = self._read_marker(target_full)
        if existing_marker is not None:
            if existing_marker.project_id != project_id or existing_marker.timeline_id != timeline_id:
                raise ObsidianMarkerMismatch("Target directory has marker for different project/timeline")

        if target_full.exists():
            if target_full.is_dir():
                if not adopt_existing:
                    raise ObsidianBindingConflict("Target directory exists but --adopt-existing not specified")
            else:
                raise ObsidianBindingConflict("Target path exists but is not a directory")

        binding_id = f"obs_{uuid.uuid4().hex[:16]}"
        now = datetime.now(timezone.utc)

        binding = ObsidianBinding(
            binding_id=binding_id,
            project_id=project_id,
            timeline_id=timeline_id,
            vault_root=vault_root,
            target_relative_path=target_relative_path,
            status=BindingStatus.BOUND,
            created_at=now,
            updated_at=now,
        )

        self.store.save(binding)

        target_full.mkdir(parents=True, exist_ok=True)
        self._write_marker(target_full, binding)

        return binding

    def unbind(self, project_id: str, timeline_id: str) -> dict[str, Any]:
        binding = self.store.load(project_id, timeline_id)
        if binding is None:
            return {"deleted": False, "reason": "NOT_FOUND"}

        target_full = binding.target_full_path

        if target_full.exists():
            marker = self._read_marker(target_full)
            if marker is not None:
                if marker.project_id != binding.project_id:
                    return {"deleted": False, "reason": "FOREIGN_MARKER_PROJECT"}
                if marker.timeline_id != binding.timeline_id:
                    return {"deleted": False, "reason": "FOREIGN_MARKER_TIMELINE"}
                if marker.binding_id != binding.binding_id:
                    return {"deleted": False, "reason": "FOREIGN_MARKER_BINDING"}

                # marker 完全匹配，安全删除
                marker_path = target_full / MARKER_FILENAME
                try:
                    marker_path.unlink()
                except OSError:
                    return {"deleted": False, "reason": "MARKER_DELETE_FAILED"}

        # marker 已删除或不存在，删除 binding record
        self.store.delete(project_id, timeline_id)
        return {"deleted": True, "reason": "OK"}

    def get_binding(self, project_id: str, timeline_id: str) -> ObsidianBinding | None:
        return self.store.load(project_id, timeline_id)

    def status(self, project_id: str, timeline_id: str) -> dict[str, Any]:
        binding = self.store.get_binding(project_id, timeline_id)
        if binding is None:
            return {
                "status": BindingStatus.UNBOUND.value,
                "project_id": project_id,
                "timeline_id": timeline_id,
            }

        result: dict[str, Any] = {
            "status": binding.status.value,
            "project_id": binding.project_id,
            "timeline_id": binding.timeline_id,
            "vault_root": binding.vault_root.as_posix(),
            "target_relative_path": binding.target_relative_path,
            "target_full_path": binding.target_full_path.as_posix(),
            "binding_id": binding.binding_id,
            "created_at": binding.created_at.isoformat(),
            "updated_at": binding.updated_at.isoformat(),
            "vault_exists": binding.vault_root.exists(),
            "target_exists": binding.target_full_path.exists(),
        }

        if not binding.vault_root.exists():
            result["status"] = BindingStatus.MISSING_VAULT.value

        elif not binding.target_full_path.exists():
            result["status"] = BindingStatus.MISSING_TARGET.value

        else:
            marker = self._read_marker(binding.target_full_path)
            if marker is None:
                result["status"] = BindingStatus.MARKER_MISMATCH.value
            elif marker.project_id != project_id or marker.timeline_id != timeline_id:
                result["status"] = BindingStatus.MARKER_MISMATCH.value
            else:
                if self.store.is_target_conflict(binding.vault_root, binding.target_relative_path, exclude_project_id=project_id, exclude_timeline_id=timeline_id):
                    result["status"] = BindingStatus.CONFLICT.value

        return result

    def _read_marker(self, target_dir: Path) -> BindingMarker | None:
        marker_path = target_dir / MARKER_FILENAME
        if not marker_path.exists():
            return None
        try:
            data = json.loads(marker_path.read_text(encoding="utf-8"))
            return BindingMarker.from_dict(data)
        except (json.JSONDecodeError, ValueError):
            return None

    def _write_marker(self, target_dir: Path, binding: ObsidianBinding) -> None:
        marker = BindingMarker(
            project_id=binding.project_id,
            timeline_id=binding.timeline_id,
            binding_id=binding.binding_id,
        )
        marker_path = target_dir / MARKER_FILENAME
        tmp_path = marker_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(marker.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(marker_path)

    def _validate_sync_paths(self, binding: ObsidianBinding) -> None:
        """Re-validate all paths before sync. Raises on any violation."""
        vault_root = binding.vault_root.resolve()

        if not vault_root.exists():
            raise ObsidianVaultMissing("Vault root does not exist")
        if not vault_root.is_dir():
            raise ObsidianVaultMissing("Vault root is not a directory")

        from system.project_clone_service import ProjectCloneService
        if ProjectCloneService._is_link_or_reparse_point(vault_root):
            raise ObsidianTargetUnsafe("Vault root is a link or reparse point")

        ok, reason = ObsidianPathValidator.validate_target_relative_path(binding.target_relative_path)
        if not ok:
            raise ObsidianTargetUnsafe(f"Target path invalid: {reason}")

        ok, reason = ObsidianPathValidator.validate_target_under_vault(vault_root, binding.target_relative_path)
        if not ok:
            raise ObsidianTargetUnsafe(f"Target path unsafe: {reason}")

        target_full = vault_root / binding.target_relative_path

        if not target_full.exists():
            raise ObsidianBindingInvalid("Target directory does not exist")
        if not target_full.is_dir():
            raise ObsidianBindingInvalid("Target path is not a directory")

        # Re-validate entire path chain for links
        for part in target_full.parents:
            if part == vault_root:
                break
            if ProjectCloneService._is_link_or_reparse_point(part):
                raise ObsidianTargetUnsafe("Path chain contains link or reparse point")

        # Validate marker
        marker = self._read_marker(target_full)
        if marker is None:
            raise ObsidianMarkerMismatch("Marker missing")
        if marker.project_id != binding.project_id:
            raise ObsidianMarkerMismatch("Marker project_id mismatch")
        if marker.timeline_id != binding.timeline_id:
            raise ObsidianMarkerMismatch("Marker timeline_id mismatch")
        if marker.binding_id != binding.binding_id:
            raise ObsidianMarkerMismatch("Marker binding_id mismatch")

    def sync(
        self,
        project_id: str,
        timeline_id: str,
        data_dir: Path,
        *,
        dry_run: bool = False,
        prune_stale: bool = False,
    ) -> dict[str, Any]:
        binding = self.get_binding(project_id, timeline_id)
        if binding is None:
            raise ObsidianBindingNotFound("Project is not bound to an Obsidian vault")

        # Full path re-validation before every sync
        self._validate_sync_paths(binding)

        from .obsidian_mirror_sync import MirrorSyncService

        sync_service = MirrorSyncService(binding, data_dir)
        result = sync_service.run(dry_run=dry_run, prune_stale=prune_stale)
        return result