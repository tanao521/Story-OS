"""Version-bound, advisory chapter assembly evidence.

This service observes existing version, Canon, commit, and compilation records.
It never changes their authority and never invokes a Provider.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.contracts import HashGuard
from core.project_context import ProjectContext
from system.revision_service import RevisionService
from system.version_manager import list_versions, read_version_payload


_ID = re.compile(r"^[A-Za-z0-9_-]+$")


class ChapterAssemblyEvidenceError(RuntimeError):
    """Safe domain errors for advisory evidence operations."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ChapterAssemblyEvidenceScope:
    """The minimum authority tuple for one version-bound evidence record."""

    project_id: str
    timeline_id: str
    branch_id: str
    chapter_id: int
    source_version_id: str
    expected_canon_revision_id: str | None = None
    expected_commit_id: str | None = None


def _sha(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ChapterAssemblyEvidenceError("EVIDENCE_INVALID", "Evidence record is invalid.") from exc
    if not isinstance(value, dict):
        raise ChapterAssemblyEvidenceError("EVIDENCE_INVALID", "Evidence record is invalid.")
    return value


class ChapterAssemblyEvidenceService:
    """Persist and audit immutable, advisory evidence for one source version."""

    schema_version = "1.0"

    def __init__(self, context: ProjectContext, *, canonical_project_id: str | None = None) -> None:
        self.context = context
        self.canonical_project_id = canonical_project_id or context.root.name
        self.storage_project_id = context.root.name

    @property
    def _root(self) -> Path:
        return self.context.data_dir / "chapter_assembly_evidence"

    def generate(self, scope: ChapterAssemblyEvidenceScope) -> dict[str, Any]:
        """Publish once for current source authority; identical replay reuses it."""
        resolved = self._resolve(scope)
        identity = self._identity(scope, resolved)
        path = self._path(scope, identity["evidence_id"])
        if path.exists():
            record = self._validated_record(path)
            if record.get("identity") != identity:
                raise ChapterAssemblyEvidenceError("EVIDENCE_CONFLICT", "Evidence identity conflicts with current authority.")
            return {**record, "replayed": True, "status": "CURRENT"}

        record = {
            "schema_version": self.schema_version,
            "classification": "DURABLE_ADVISORY_EVIDENCE",
            "evidence_type": "chapter_assembly",
            "identity": identity,
            "source": resolved["source"],
            "assembly": resolved["assembly"],
            "canon": resolved["canon"],
            "commit": resolved["commit"],
            "generated_at": _now(),
        }
        record["record_fingerprint"] = _sha({key: value for key, value in record.items() if key != "record_fingerprint"})
        self._publish_immutable(path, record)
        return {**record, "replayed": False, "status": "CURRENT"}

    def read_status(self, scope: ChapterAssemblyEvidenceScope) -> dict[str, Any]:
        """Return CURRENT, MISSING, STALE, or INVALID without mutating authority."""
        try:
            resolved = self._resolve(scope)
        except ChapterAssemblyEvidenceError as exc:
            return {"status": "INVALID", "code": exc.code}
        identity = self._identity(scope, resolved)
        path = self._path(scope, identity["evidence_id"])
        if path.exists():
            try:
                record = self._validated_record(path)
            except ChapterAssemblyEvidenceError as exc:
                return {"status": "INVALID", "code": exc.code}
            return {"status": "CURRENT", "record": record}
        try:
            historical = list(self._version_dir(scope).glob("*.json"))
            for candidate in historical:
                record = self._validated_record(candidate)
                candidate_identity = record.get("identity", {})
                if candidate_identity.get("source_version_id") == scope.source_version_id:
                    return {"status": "STALE", "record": record}
        except ChapterAssemblyEvidenceError as exc:
            return {"status": "INVALID", "code": exc.code}
        return {"status": "MISSING"}

    def _resolve(self, scope: ChapterAssemblyEvidenceScope) -> dict[str, Any]:
        self._validate_scope(scope)
        branch_revision = self._branch_revision(scope)
        source_info = self._source_info(scope)
        payload = read_version_payload(source_info)
        source_text = str(payload.get("manual_text") or payload.get("edited_text") or payload.get("draft_text") or "")
        source_fingerprint = HashGuard.sha256_text(source_text)
        provenance = payload.get("narrative_compilation") if isinstance(payload.get("narrative_compilation"), dict) else {}
        candidate_scope = payload.get("candidate_scope") or provenance.get("scope")
        if candidate_scope is not None:
            if not isinstance(candidate_scope, dict) or any(
                candidate_scope.get(key) != value for key, value in (
                    ("project_id", scope.project_id),
                    ("timeline_id", scope.timeline_id),
                    ("branch_id", scope.branch_id),
                    ("chapter_id", scope.chapter_id),
                    ("source_version_id", scope.source_version_id),
                )
            ):
                raise ChapterAssemblyEvidenceError("ASSEMBLY_SCOPE_MISMATCH", "Assembly provenance does not match evidence scope.")

        active = RevisionService(self.context).read_active_canon(scope.chapter_id)
        active_id = str((active or {}).get("canon_version_id") or (active or {}).get("revision_id") or "") or None
        if scope.expected_canon_revision_id is not None and active_id != scope.expected_canon_revision_id:
            raise ChapterAssemblyEvidenceError("CANON_REVISION_STALE", "Expected Canon revision is no longer active.")
        commit = self._matching_commit(scope, source_fingerprint)
        if scope.expected_commit_id is not None and (commit or {}).get("commit_id") != scope.expected_commit_id:
            raise ChapterAssemblyEvidenceError("COMMIT_STALE", "Expected chapter commit is unavailable.")

        return {
            "source": {
                "source_version_id": scope.source_version_id,
                "source_type": str(source_info.get("source_type") or ""),
                "source_fingerprint": source_fingerprint,
                "content_length": len(source_text),
            },
            "assembly": {
                "candidate_id": str(payload.get("candidate_id") or provenance.get("candidate_id") or "") or None,
                "candidate_fingerprint": str(payload.get("candidate_fingerprint") or provenance.get("candidate_fingerprint") or "") or None,
                "compilation_scope": candidate_scope,
                "included_turn_ids": list(provenance.get("included_turn_ids") or []),
            },
            "branch_registry_revision": branch_revision,
            "canon": {"canon_revision_id": active_id},
            "commit": {"commit_id": (commit or {}).get("commit_id"), "source_hash": (commit or {}).get("source_hash")},
        }

    def _validate_scope(self, scope: ChapterAssemblyEvidenceScope) -> None:
        if not isinstance(scope, ChapterAssemblyEvidenceScope):
            raise ChapterAssemblyEvidenceError("EVIDENCE_SCOPE_REQUIRED", "Complete evidence scope is required.")
        values = (scope.project_id, scope.timeline_id, scope.branch_id, scope.source_version_id)
        if any(not isinstance(value, str) or not _ID.fullmatch(value) for value in values) or scope.chapter_id < 1:
            raise ChapterAssemblyEvidenceError("EVIDENCE_SCOPE_REQUIRED", "Complete evidence scope is required.")
        if scope.project_id != self.canonical_project_id:
            raise ChapterAssemblyEvidenceError("PROJECT_SCOPE_MISMATCH", "Project does not match the captured context.")
        if scope.timeline_id != "main":
            raise ChapterAssemblyEvidenceError("TIMELINE_SCOPE_UNSUPPORTED", "Only the main timeline is supported.")

    def _source_info(self, scope: ChapterAssemblyEvidenceScope) -> dict[str, Any]:
        versions = list_versions(scope.chapter_id, self.context.data_dir)
        matches = [
            entry for kind in ("drafts", "edited", "manual")
            for entry in versions.get(kind, [])
            if entry.get("version_label") == scope.source_version_id
        ]
        if len(matches) != 1:
            raise ChapterAssemblyEvidenceError("SOURCE_VERSION_STALE", "Source version is unavailable or ambiguous.")
        return matches[0]

    def _branch_revision(self, scope: ChapterAssemblyEvidenceScope) -> str:
        path = self.context.data_dir / "branches" / scope.timeline_id / "registry.json"
        try:
            registry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ChapterAssemblyEvidenceError("BRANCH_SCOPE_MISMATCH", "Branch registry is unavailable.") from exc
        if (not isinstance(registry, dict)
                or registry.get("project_id") != self.storage_project_id
                or registry.get("timeline_id") != scope.timeline_id
                or registry.get("active_branch_id") != scope.branch_id
                or not isinstance(registry.get("revision"), str)
                or not registry["revision"]):
            raise ChapterAssemblyEvidenceError("BRANCH_SCOPE_MISMATCH", "Branch scope is not current.")
        return registry["revision"]

    def _matching_commit(self, scope: ChapterAssemblyEvidenceScope, source_fingerprint: str) -> dict[str, Any] | None:
        directory = self.context.data_dir / "chapter_commits"
        if not directory.exists():
            return None
        matches: list[dict[str, Any]] = []
        for path in directory.glob("*.json"):
            try:
                candidate = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(candidate, dict):
                continue
            if (candidate.get("chapter_id") == scope.chapter_id
                    and candidate.get("source_hash") == source_fingerprint):
                matches.append(candidate)
        if len(matches) > 1:
            raise ChapterAssemblyEvidenceError("COMMIT_AMBIGUOUS", "Chapter commit evidence is ambiguous.")
        return matches[0] if matches else None

    def _identity(self, scope: ChapterAssemblyEvidenceScope, resolved: dict[str, Any]) -> dict[str, Any]:
        binding = {
            "project_id": scope.project_id,
            "storage_project_id": self.storage_project_id,
            "timeline_id": scope.timeline_id,
            "branch_id": scope.branch_id,
            "chapter_id": scope.chapter_id,
            "source_version_id": scope.source_version_id,
            "source_fingerprint": resolved["source"]["source_fingerprint"],
            "canon_revision_id": resolved["canon"]["canon_revision_id"],
            "commit_id": resolved["commit"]["commit_id"],
            "branch_registry_revision": resolved["branch_registry_revision"],
            "candidate_id": resolved["assembly"]["candidate_id"],
            "candidate_fingerprint": resolved["assembly"]["candidate_fingerprint"],
            "compilation_scope": resolved["assembly"]["compilation_scope"],
        }
        return {**binding, "evidence_id": f"assembly_{_sha(binding)[:24]}"}

    def _version_dir(self, scope: ChapterAssemblyEvidenceScope) -> Path:
        return self._root / scope.timeline_id / scope.branch_id / f"chapter_{scope.chapter_id:03d}" / scope.source_version_id

    def _path(self, scope: ChapterAssemblyEvidenceScope, evidence_id: str) -> Path:
        if not _ID.fullmatch(evidence_id):
            raise ChapterAssemblyEvidenceError("EVIDENCE_INVALID", "Evidence identity is invalid.")
        target = self._version_dir(scope) / f"{evidence_id}.json"
        try:
            target.resolve(strict=False).relative_to(self._root.resolve(strict=False))
        except (OSError, ValueError) as exc:
            raise ChapterAssemblyEvidenceError("EVIDENCE_PATH_INVALID", "Evidence path is invalid.") from exc
        return target

    def _validated_record(self, path: Path) -> dict[str, Any]:
        record = _read_json(path)
        expected = _sha({key: value for key, value in record.items() if key != "record_fingerprint"})
        if (record.get("schema_version") != self.schema_version
                or record.get("classification") != "DURABLE_ADVISORY_EVIDENCE"
                or record.get("record_fingerprint") != expected
                or not isinstance(record.get("identity"), dict)):
            raise ChapterAssemblyEvidenceError("EVIDENCE_INVALID", "Evidence record is invalid.")
        return record

    def _publish_immutable(self, path: Path, record: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.parent.is_symlink():
            raise ChapterAssemblyEvidenceError("EVIDENCE_PATH_INVALID", "Evidence path is invalid.")
        payload = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent), text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary_name, path)
            except FileExistsError:
                existing = self._validated_record(path)
                if existing.get("identity") != record.get("identity"):
                    raise ChapterAssemblyEvidenceError("EVIDENCE_CONFLICT", "Evidence identity conflicts with existing record.")
        finally:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
