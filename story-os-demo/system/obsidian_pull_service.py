from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from core.project_context import ProjectContext
from system.chapter_commit_service import ChapterCommitService, CommitStatus, PostCommitPolicy, SourceType
from system.obsidian_binding import MARKER_FILENAME, ObsidianBinding
from system.obsidian_mirror_manifest import (
    MANIFEST_FILENAME,
    MirrorManifest,
    MirrorManifestEntry,
    MirrorManifestStore,
    build_empty_manifest,
    compute_content_hash,
)
from system.obsidian_mirror_sync import MirrorSyncService


class PullAction(str, Enum):
    UNCHANGED = "unchanged"
    INBOUND_CHANGED = "inbound_changed"
    OUTBOUND_CHANGED = "outbound_changed"
    CONVERGED = "converged"
    DIVERGED = "diverged"
    TARGET_MISSING = "target_missing"
    CONFLICT_TYPE = "conflict_type"
    INVALID_CONTENT = "invalid_content"
    IDENTITY_CONFLICT = "identity_conflict"
    UNSAFE = "unsafe"


class ObsidianPullError(Exception):
    pass


class ObsidianPullNotFound(ObsidianPullError):
    pass


class ObsidianPullStalePreview(ObsidianPullError):
    pass


class ObsidianPullConflict(ObsidianPullError):
    pass


class ObsidianPullUnsafe(ObsidianPullError):
    pass


class ObsidianPullInvalid(ObsidianPullError):
    pass


@dataclass(frozen=True)
class PullPlanEntry:
    relative_path: str
    source_id: str
    action: PullAction
    base_hash: str | None
    source_hash: str | None
    target_hash: str | None
    reason: str | None
    importable: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "source_id": self.source_id,
            "action": self.action.value,
            "base_hash": self.base_hash,
            "source_hash": self.source_hash,
            "target_hash": self.target_hash,
            "reason": self.reason,
            "importable": self.importable,
        }


@dataclass
class ObsidianPullPlan:
    binding_id: str
    project_id: str
    timeline_id: str
    entries: list[PullPlanEntry] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=lambda: {
        "unchanged": 0,
        "inbound_changed": 0,
        "outbound_changed": 0,
        "converged": 0,
        "diverged": 0,
        "target_missing": 0,
        "conflict_type": 0,
        "invalid_content": 0,
        "identity_conflict": 0,
        "unsafe": 0,
    })

    def add(self, entry: PullPlanEntry) -> None:
        self.entries.append(entry)
        self.summary[entry.action.value] += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "project_id": self.project_id,
            "timeline_id": self.timeline_id,
            "summary": self.summary,
            "entries": [e.to_dict() for e in self.entries],
        }


@dataclass(frozen=True)
class ObsidianImportPreview:
    relative_path: str
    source_id: str
    current_storyos_hash: str | None
    manifest_base_hash: str | None
    obsidian_hash: str | None
    current_character_count: int
    imported_character_count: int
    current_title: str | None
    imported_title: str | None
    change_summary: str
    importable: bool
    blocking_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "source_id": self.source_id,
            "current_storyos_hash": self.current_storyos_hash,
            "manifest_base_hash": self.manifest_base_hash,
            "obsidian_hash": self.obsidian_hash,
            "current_character_count": self.current_character_count,
            "imported_character_count": self.imported_character_count,
            "current_title": self.current_title,
            "imported_title": self.imported_title,
            "change_summary": self.change_summary,
            "importable": self.importable,
            "blocking_reason": self.blocking_reason,
        }


@dataclass(frozen=True)
class ObsidianImportResult:
    status: str
    relative_path: str
    chapter_id: int
    commit_result: dict[str, Any] | None
    mirror_updated: bool
    manifest_updated: bool
    warnings: list[str]
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "relative_path": self.relative_path,
            "chapter_id": self.chapter_id,
            "commit_result": self.commit_result,
            "mirror_updated": self.mirror_updated,
            "manifest_updated": self.manifest_updated,
            "warnings": self.warnings,
            "error": self.error,
        }


class ObsidianPullService:
    # Process-level lock map keyed by (binding_id, relative_path).
    # NOTE: This is an in-process threading lock. Cross-process isolation
    # (e.g. CLI + Web server simultaneously) requires a file-based or
    # OS-level lock in addition to this map.
    _lock_map: dict[tuple[str, str], threading.Lock] = {}
    _lock_map_lock = threading.Lock()

    def __init__(self, binding: ObsidianBinding, context: ProjectContext) -> None:
        self.binding = binding
        self.context = context
        self.target_dir = binding.target_full_path
        self.manifest_store = MirrorManifestStore(self.target_dir)
        self.data_dir = context.data_dir

    def scan(self) -> ObsidianPullPlan:
        old_manifest = self._load_and_validate_manifest()
        source_snapshot = self._build_source_snapshot()
        plan = self._compute_pull_plan(old_manifest, source_snapshot)
        return plan

    def preview_file(self, relative_path: str) -> ObsidianImportPreview:
        old_manifest = self._load_and_validate_manifest()
        source_snapshot = self._build_source_snapshot()

        if not self._is_safe_path(relative_path):
            return self._preview_unsafe(relative_path)

        source_content = source_snapshot.get(relative_path)
        source_hash = compute_content_hash(source_content) if source_content else None

        target_path = self.target_dir / relative_path
        if not target_path.exists():
            return self._preview_missing(relative_path, source_hash, old_manifest)

        if not target_path.is_file():
            return self._preview_conflict_type(relative_path, source_hash, old_manifest)

        target_content = target_path.read_bytes()
        target_hash = compute_content_hash(target_content)

        old_entry = old_manifest.files.get(relative_path) if old_manifest else None
        base_hash = old_entry.content_hash if old_entry else None

        action = self._classify_action(base_hash, source_hash, target_hash)

        if action == PullAction.INVALID_CONTENT:
            return self._preview_invalid(relative_path, source_hash, base_hash, target_hash)

        current_title = None
        imported_title = None
        current_chars = 0
        imported_chars = 0

        if source_content:
            current_title = self._parse_markdown_title(source_content.decode("utf-8", errors="replace"))
            current_chars = len(source_content.decode("utf-8", errors="replace"))

        parsed = self._parse_chapter_markdown(target_content, relative_path)
        if parsed:
            imported_title = parsed.get("title")
            imported_chars = len(parsed.get("content", ""))

        change_summary = self._build_change_summary(action, current_chars, imported_chars)

        return ObsidianImportPreview(
            relative_path=relative_path,
            source_id=relative_path,
            current_storyos_hash=source_hash,
            manifest_base_hash=base_hash,
            obsidian_hash=target_hash,
            current_character_count=current_chars,
            imported_character_count=imported_chars,
            current_title=current_title,
            imported_title=imported_title,
            change_summary=change_summary,
            importable=(action == PullAction.INBOUND_CHANGED),
            blocking_reason=None if action == PullAction.INBOUND_CHANGED else action.value,
        )

    def _acquire_file_lock(self, relative_path: str) -> threading.Lock:
        key = (self.binding.binding_id, relative_path)
        with self._lock_map_lock:
            if key not in self._lock_map:
                self._lock_map[key] = threading.Lock()
            return self._lock_map[key]

    def import_file(self, relative_path: str, expected_target_hash: str) -> ObsidianImportResult:
        file_lock = self._acquire_file_lock(relative_path)
        with file_lock:
            return self._import_file_locked(relative_path, expected_target_hash)

    def _import_file_locked(self, relative_path: str, expected_target_hash: str) -> ObsidianImportResult:
        warnings: list[str] = []

        # Re-validate binding and manifest under lock
        try:
            old_manifest = self._load_and_validate_manifest()
        except ObsidianPullError as exc:
            return ObsidianImportResult(
                status="failed",
                relative_path=relative_path,
                chapter_id=0,
                commit_result=None,
                mirror_updated=False,
                manifest_updated=False,
                warnings=[],
                error=str(exc),
            )

        # Re-validate path safety
        if not self._is_safe_path(relative_path):
            return ObsidianImportResult(
                status="failed",
                relative_path=relative_path,
                chapter_id=0,
                commit_result=None,
                mirror_updated=False,
                manifest_updated=False,
                warnings=[],
                error="Path unsafe",
            )

        target_path = self.target_dir / relative_path
        if not target_path.exists() or not target_path.is_file():
            return ObsidianImportResult(
                status="failed",
                relative_path=relative_path,
                chapter_id=0,
                commit_result=None,
                mirror_updated=False,
                manifest_updated=False,
                warnings=[],
                error="Target file no longer exists",
            )

        # Re-read target and compute hashes
        target_content = target_path.read_bytes()
        current_target_hash = compute_content_hash(target_content)
        if current_target_hash != expected_target_hash:
            return ObsidianImportResult(
                status="stale_preview",
                relative_path=relative_path,
                chapter_id=0,
                commit_result=None,
                mirror_updated=False,
                manifest_updated=False,
                warnings=[],
                error="OBSIDIAN_IMPORT_STALE_PREVIEW",
            )

        # Re-compute source hash
        source_snapshot = self._build_source_snapshot()
        source_content = source_snapshot.get(relative_path)
        source_hash = compute_content_hash(source_content) if source_content else None

        old_entry = old_manifest.files.get(relative_path) if old_manifest else None
        base_hash = old_entry.content_hash if old_entry else None

        action = self._classify_action(base_hash, source_hash, current_target_hash)
        if action != PullAction.INBOUND_CHANGED:
            return ObsidianImportResult(
                status="rejected",
                relative_path=relative_path,
                chapter_id=0,
                commit_result=None,
                mirror_updated=False,
                manifest_updated=False,
                warnings=[],
                error=f"State changed to {action.value} after lock acquisition",
            )

        parsed = self._parse_chapter_markdown(target_content, relative_path)
        if not parsed:
            return ObsidianImportResult(
                status="failed",
                relative_path=relative_path,
                chapter_id=0,
                commit_result=None,
                mirror_updated=False,
                manifest_updated=False,
                warnings=[],
                error="Failed to parse chapter markdown",
            )

        chapter_id = parsed["chapter_id"]
        content = parsed["content"]
        title = parsed["title"]

        commit_result = self._commit_via_service(chapter_id, content, title)

        if commit_result.get("status") not in ("committed", "already_committed", "committed_with_warnings"):
            return ObsidianImportResult(
                status="commit_failed",
                relative_path=relative_path,
                chapter_id=chapter_id,
                commit_result=commit_result,
                mirror_updated=False,
                manifest_updated=False,
                warnings=commit_result.get("warnings", []),
                error="Chapter commit failed",
            )

        if commit_result.get("status") == "already_committed":
            warnings.append("Chapter already committed with same content")

        # Update mirror first; only update manifest if mirror succeeds.
        mirror_ok = False
        manifest_ok = False
        chapter_path = self.context.root / "data" / "chapters" / f"chapter_{chapter_id:03d}.md"

        try:
            if chapter_path.exists():
                committed_content = chapter_path.read_bytes()
            else:
                committed_content = content.encode("utf-8")
            mirror_ok = self._update_mirror_file(relative_path, committed_content)
        except Exception as exc:
            warnings.append(f"Mirror update failed: {exc}")

        if mirror_ok:
            try:
                if chapter_path.exists():
                    committed_content = chapter_path.read_bytes()
                else:
                    committed_content = content.encode("utf-8")
                manifest_ok = self._update_manifest_entry(relative_path, committed_content)
            except Exception as exc:
                warnings.append(f"Manifest update failed: {exc}")
        else:
            warnings.append("Story OS chapter committed but Obsidian mirror not updated. "
                            "Run safe sync to converge mirror.")

        final_status = "completed" if (mirror_ok and manifest_ok) else "completed_with_warnings"

        return ObsidianImportResult(
            status=final_status,
            relative_path=relative_path,
            chapter_id=chapter_id,
            commit_result=commit_result,
            mirror_updated=mirror_ok,
            manifest_updated=manifest_ok,
            warnings=warnings,
            error=None,
        )

    def repair_converged(self) -> ObsidianPullPlan:
        old_manifest = self._load_and_validate_manifest()
        source_snapshot = self._build_source_snapshot()
        plan = ObsidianPullPlan(
            binding_id=self.binding.binding_id,
            project_id=self.binding.project_id,
            timeline_id=self.binding.timeline_id,
        )

        for rel_path in old_manifest.files if old_manifest else []:
            if not rel_path.startswith("03_Chapters/"):
                continue
            if not self._is_safe_path(rel_path):
                continue

            source_content = source_snapshot.get(rel_path)
            source_hash = compute_content_hash(source_content) if source_content else None

            target_path = self.target_dir / rel_path
            if not target_path.exists() or not target_path.is_file():
                continue

            target_content = target_path.read_bytes()
            target_hash = compute_content_hash(target_content)

            old_entry = old_manifest.files.get(rel_path)
            base_hash = old_entry.content_hash if old_entry else None

            if source_hash == target_hash and source_hash != base_hash:
                self._update_manifest_entry(rel_path, target_content)
                plan.add(PullPlanEntry(
                    relative_path=rel_path,
                    source_id=rel_path,
                    action=PullAction.CONVERGED,
                    base_hash=base_hash,
                    source_hash=source_hash,
                    target_hash=target_hash,
                    reason="Manifest repaired",
                    importable=False,
                ))

        return plan

    def _load_and_validate_manifest(self) -> MirrorManifest | None:
        manifest = self.manifest_store.load()
        if manifest is None:
            return None
        if manifest.schema_version != "1.0":
            raise ObsidianPullInvalid(f"Unsupported manifest schema version: {manifest.schema_version}")
        if not manifest.validate_identity(
            self.binding.binding_id,
            self.binding.project_id,
            self.binding.timeline_id,
        ):
            raise ObsidianPullInvalid("Manifest identity does not match current binding")
        return manifest

    def _build_source_snapshot(self) -> dict[str, bytes]:
        snapshot: dict[str, bytes] = {}
        chapters_dir = self.data_dir / "chapters"
        if chapters_dir.exists():
            for source in sorted(chapters_dir.glob("*.md")):
                snapshot[f"03_Chapters/{source.name}"] = source.read_bytes()
        return snapshot

    def _compute_pull_plan(
        self, old_manifest: MirrorManifest | None, source_snapshot: dict[str, bytes]
    ) -> ObsidianPullPlan:
        plan = ObsidianPullPlan(
            binding_id=self.binding.binding_id,
            project_id=self.binding.project_id,
            timeline_id=self.binding.timeline_id,
        )
        old_files: dict[str, MirrorManifestEntry] = old_manifest.files if old_manifest else {}

        for rel_path, source_content in source_snapshot.items():
            if not self._is_safe_path(rel_path):
                plan.add(PullPlanEntry(
                    relative_path=rel_path, source_id=rel_path,
                    action=PullAction.UNSAFE, base_hash=None, source_hash=None,
                    target_hash=None, reason="Path validation failed", importable=False,
                ))
                continue

            source_hash = compute_content_hash(source_content)
            target_path = self.target_dir / rel_path
            old_entry = old_files.get(rel_path)
            base_hash = old_entry.content_hash if old_entry else None

            if not target_path.exists():
                action = PullAction.TARGET_MISSING
                reason = "Obsidian file missing"
            elif not target_path.is_file():
                action = PullAction.CONFLICT_TYPE
                reason = "Not a regular file"
            else:
                target_content = target_path.read_bytes()
                target_hash = compute_content_hash(target_content)
                action = self._classify_action(base_hash, source_hash, target_hash)
                reason = action.value if action != PullAction.UNCHANGED else ""

            plan.add(PullPlanEntry(
                relative_path=rel_path,
                source_id=rel_path,
                action=action,
                base_hash=base_hash,
                source_hash=source_hash,
                target_hash=target_hash if target_path.exists() and target_path.is_file() else None,
                reason=reason or None,
                importable=(action == PullAction.INBOUND_CHANGED),
            ))

        return plan

    def _classify_action(
        self, base_hash: str | None, source_hash: str | None, target_hash: str | None
    ) -> PullAction:
        if source_hash is None or target_hash is None:
            return PullAction.INVALID_CONTENT

        if base_hash is None:
            if source_hash == target_hash:
                return PullAction.CONVERGED
            return PullAction.DIVERGED

        if source_hash == target_hash:
            if source_hash == base_hash:
                return PullAction.UNCHANGED
            return PullAction.CONVERGED

        if source_hash == base_hash and target_hash != base_hash:
            return PullAction.INBOUND_CHANGED

        if target_hash == base_hash and source_hash != base_hash:
            return PullAction.OUTBOUND_CHANGED

        return PullAction.DIVERGED

    def _is_safe_path(self, rel_path: str) -> bool:
        from system.obsidian_path_validator import ObsidianPathValidator
        ok, _ = ObsidianPathValidator.validate_target_relative_path(rel_path)
        if not ok:
            return False
        target = self.target_dir / rel_path
        try:
            target.relative_to(self.target_dir.resolve())
        except ValueError:
            return False
        return True

    def _parse_chapter_markdown(self, content: bytes, rel_path: str) -> dict[str, Any] | None:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            return None

        chapter_id = self._extract_chapter_id_from_path(rel_path)
        if chapter_id is None:
            return None

        title = self._parse_markdown_title(text)
        body = self._extract_markdown_body(text)

        return {
            "chapter_id": chapter_id,
            "title": title,
            "content": body,
        }

    def _extract_chapter_id_from_path(self, rel_path: str) -> int | None:
        name = Path(rel_path).stem
        m = re.match(r"chapter_(\d+)", name)
        if m:
            return int(m.group(1))
        return None

    def _parse_markdown_title(self, text: str) -> str | None:
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()
        return None

    def _extract_markdown_body(self, text: str) -> str:
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("# "):
            return "\n".join(lines[1:]).strip()
        return text.strip()

    def _build_change_summary(self, action: PullAction, current_chars: int, imported_chars: int) -> str:
        delta = imported_chars - current_chars
        if action == PullAction.INBOUND_CHANGED:
            if delta > 0:
                return f"增加 {delta} 字符"
            if delta < 0:
                return f"减少 {abs(delta)} 字符"
            return "字符数相同，内容有变化"
        return action.value

    def _commit_via_service(self, chapter_id: int, content: str, title: str) -> dict[str, Any]:
        commit_service = ChapterCommitService(self.context)
        temp_version_id = self._write_temp_manual_version(chapter_id, content, title)
        try:
            result = commit_service.commit_chapter(
                chapter_id=chapter_id,
                source_version_id=temp_version_id,
                post_commit_policy=PostCommitPolicy.LOCAL_ONLY,
            )
            return {
                "status": result.status.value,
                "project_id": result.project_id,
                "chapter_id": result.chapter_id,
                "commit_id": result.commit_id,
                "source_type": result.source_type.value,
                "source_version_id": result.source_version_id,
                "source_hash": result.source_hash,
                "canon_revision_id": result.canon_revision_id,
                "chapter_path": result.chapter_path,
                "summary_path": result.summary_path,
                "warnings": result.warnings,
                "post_commit": result.post_commit,
            }
        except Exception as exc:
            return {"status": "commit_failed", "error": str(exc), "warnings": []}
        finally:
            self._cleanup_temp_manual_version(temp_version_id)

    def _write_temp_manual_version(self, chapter_id: int, content: str, title: str) -> str:
        version_label = f"chapter_{chapter_id:03d}_obsidian_pull_v001.json"
        version_path = self.context.root / "data" / "manual" / version_label
        version_path.parent.mkdir(parents=True, exist_ok=True)
        version_data = {
            "content": content,
            "manual_text": content,
            "chapter_title": title,
            "chapter_id": chapter_id,
            "source_origin_type": "obsidian_pull",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        version_path.write_text(json.dumps(version_data, ensure_ascii=False, indent=2), encoding="utf-8")
        return version_label

    def _cleanup_temp_manual_version(self, version_id: str) -> None:
        try:
            path = self.context.root / "data" / "manual" / version_id
            if path.exists():
                path.unlink()
        except OSError:
            pass

    def _update_mirror_file(self, rel_path: str, content: bytes | str) -> bool:
        target_path = self.target_dir / rel_path
        if not target_path.exists():
            return False
        current = target_path.read_bytes()
        expected = content if isinstance(content, bytes) else content.encode("utf-8")
        if current == expected:
            return True
        target_path.write_bytes(expected)
        return True

    def _update_manifest_entry(self, rel_path: str, content: bytes | str) -> bool:
        manifest = self.manifest_store.load()
        if manifest is None:
            return False
        if isinstance(content, str):
            content = content.encode("utf-8")
        manifest.files[rel_path] = MirrorManifestEntry(
            source_id=rel_path,
            content_hash=compute_content_hash(content),
            size_bytes=len(content),
            last_synced_at=datetime.now(timezone.utc).isoformat(),
        )
        self.manifest_store.save(manifest)
        return True

    def _preview_unsafe(self, relative_path: str) -> ObsidianImportPreview:
        return ObsidianImportPreview(
            relative_path=relative_path, source_id=relative_path,
            current_storyos_hash=None, manifest_base_hash=None, obsidian_hash=None,
            current_character_count=0, imported_character_count=0,
            current_title=None, imported_title=None,
            change_summary="Path unsafe", importable=False, blocking_reason="unsafe",
        )

    def _preview_missing(self, relative_path: str, source_hash: str | None, old_manifest: MirrorManifest | None) -> ObsidianImportPreview:
        old_entry = old_manifest.files.get(relative_path) if old_manifest else None
        return ObsidianImportPreview(
            relative_path=relative_path, source_id=relative_path,
            current_storyos_hash=source_hash, manifest_base_hash=old_entry.content_hash if old_entry else None,
            obsidian_hash=None, current_character_count=0, imported_character_count=0,
            current_title=None, imported_title=None,
            change_summary="Target missing", importable=False, blocking_reason="target_missing",
        )

    def _preview_conflict_type(self, relative_path: str, source_hash: str | None, old_manifest: MirrorManifest | None) -> ObsidianImportPreview:
        old_entry = old_manifest.files.get(relative_path) if old_manifest else None
        return ObsidianImportPreview(
            relative_path=relative_path, source_id=relative_path,
            current_storyos_hash=source_hash, manifest_base_hash=old_entry.content_hash if old_entry else None,
            obsidian_hash=None, current_character_count=0, imported_character_count=0,
            current_title=None, imported_title=None,
            change_summary="Not a regular file", importable=False, blocking_reason="conflict_type",
        )

    def _preview_invalid(self, relative_path: str, source_hash: str | None, base_hash: str | None, target_hash: str | None) -> ObsidianImportPreview:
        return ObsidianImportPreview(
            relative_path=relative_path, source_id=relative_path,
            current_storyos_hash=source_hash, manifest_base_hash=base_hash,
            obsidian_hash=target_hash, current_character_count=0, imported_character_count=0,
            current_title=None, imported_title=None,
            change_summary="Invalid content", importable=False, blocking_reason="invalid_content",
        )
