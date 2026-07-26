"""One narrow, safe entry point for creating non-canon manual work versions.

The facade deliberately has no caller in the full or partial-adoption services.
It is the migration seam for test-project work-version creation only.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from core.contracts import HashExpectation, HashGuard, OperationEnvelope, ProjectRef
from core.contracts.adoption_contract import AdoptionRequest, AdoptionResult
from core.contracts.revision_contract import RevisionCandidate
from core.project_context import ProjectContext
from system.data_store import DataStore
from system.safe_write import DataStoreWriteFacade, DataStoreWriteError
from system.version_manager import build_versioned_paths, get_next_version_number, list_versions


class VersionWriterError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class VersionWriterFacade:
    """Create a manual work version via DataStoreWriteFacade, never Canon."""

    def __init__(self, context: ProjectContext, *, writer: DataStoreWriteFacade | None = None) -> None:
        self.context = context
        self.store = DataStore(context)
        self.writer = writer or DataStoreWriteFacade(context)
        self._operations: dict[str, tuple[str, AdoptionResult]] = {}

    def create_work_version(
        self,
        *,
        project: ProjectRef,
        chapter_id: int,
        source_type: str,
        source_version: int,
        chapter_title: str,
        candidate_text: str,
        candidate: RevisionCandidate,
        adoption: AdoptionRequest,
        provenance_kind: str = "revision_contract",
        provenance: dict[str, Any] | None = None,
        source_path: str = "",
        expected_result_hash: str | None = None,
    ) -> AdoptionResult:
        if source_type not in {"draft", "edited", "manual"} or chapter_id < 1 or source_version < 1:
            raise VersionWriterError("VERSION_WRITER_INPUT_INVALID", "A valid source version is required.")
        project.assert_context(self.context)
        if candidate.status not in {"qualified", "review_required"}:
            raise VersionWriterError("VERSION_WRITER_CANDIDATE_NOT_READY", "Only qualified or review-required candidates may create a work version.")
        new_hash = HashGuard.sha256_text(candidate_text)
        expected_hash = HashGuard.normalize_sha256(expected_result_hash) if expected_result_hash else candidate.candidate_hash
        if new_hash != expected_hash:
            raise VersionWriterError("HASH_CANDIDATE_MISMATCH", "Candidate text does not match the expected adoption result hash.")
        signature = HashGuard.sha256_json({
            "candidate_id": candidate.candidate_id, "candidate_hash": candidate.candidate_hash, "expected_result_hash": expected_hash,
            "chapter_id": chapter_id, "source_type": source_type, "source_version": source_version,
            "expected_revision": adoption.expected_revision, "operation": adoption.operation_id,
        })
        prior = self._operations.get(adoption.operation_id)
        if prior:
            if prior[0] != signature:
                raise VersionWriterError("OPERATION_ID_CONFLICT", "operation_id was already used for a different request.")
            return replace(prior[1], replayed=True)

        index_path = f"data/versions/chapter_{chapter_id:03d}_versions.json"
        old_index = self.store.read_json(index_path, default={"version_index": "1.5", "chapter_id": chapter_id}, expected_type=dict) or {"version_index": "1.5", "chapter_id": chapter_id}
        current_revision = int(old_index.get("selection_revision", 1) or 1)
        if adoption.expected_revision != current_revision:
            raise VersionWriterError("DRAFT_VERSION_REVISION_CONFLICT", "The selected-version revision changed before work-version creation.")

        version = get_next_version_number(chapter_id, "manual", self.context.data_dir)
        version_id = f"manual_v{version:03d}"
        paths = build_versioned_paths(chapter_id, "manual", version, "data")
        now = datetime.now(timezone.utc).isoformat()
        audit_id = f"version_writer_{adoption.operation_id}"
        manual = {
            "manual_version": "2.3", "chapter_id": chapter_id, "chapter_title": chapter_title,
            "status": "manual", "version": version, "version_label": version_id,
            "source_type": source_type, "source_version": source_version, "source_path": source_path,
            "manual_text": candidate_text, "actual_word_count": len(candidate_text.strip()),
            "created_at": now, "updated_at": now,
            "editing": {"mode": provenance_kind, "model": "none", "fallback_used": False, "warnings": []},
            "checks": {"valid_text": True, "warnings": []},
            "revision_contract": {"revision_id": candidate.revision_id, "candidate_id": candidate.candidate_id, "candidate_hash": candidate.candidate_hash},
        }
        if provenance and provenance_kind:
            manual[provenance_kind] = dict(provenance or {})
        audit = {
            "audit_id": audit_id, "operation_id": adoption.operation_id, "candidate_id": candidate.candidate_id,
            "chapter_id": chapter_id, "version_id": version_id, "action": "work_version_created",
            "created_at": now, "status": "created",
        }
        index = list_versions(chapter_id, self.context.data_dir)
        index["selected"] = {
            "source_type": "manual", "version": version, "version_label": version_id,
            "json_path": paths["json_path"], "markdown_path": paths["markdown_path"], "selected_at": now,
        }
        index["selection_revision"] = current_revision + 1

        written: list[str] = []
        try:
            from system.manual_editor import render_manual_markdown
            self._write_json(project, f"data/audit/version_writer/{audit_id}.json", audit, adoption, "audit", audit_id)
            written.append(f"data/audit/version_writer/{audit_id}.json")
            self._write_json(project, paths["json_path"], manual, adoption, "manual_json", version_id)
            written.append(paths["json_path"])
            self._write_text(project, paths["markdown_path"], render_manual_markdown(manual), adoption, "manual_markdown", version_id)
            written.append(paths["markdown_path"])
            self._write_json(project, index_path, index, adoption, "versions_index", f"chapter_{chapter_id:03d}")
        except Exception:
            for path in reversed(written):
                try:
                    self.store.path(path).unlink(missing_ok=True)
                except OSError:
                    pass
            raise

        result = AdoptionResult(adoption.operation_id, version_id, new_hash, False, audit_id)
        self._operations[adoption.operation_id] = (signature, result)
        return result

    def _child_operation(self, adoption: AdoptionRequest, *, project_id: str, target_type: str, target_id: str, suffix: str) -> OperationEnvelope:
        return OperationEnvelope(
            f"{adoption.operation_id}:{suffix}", "version_adoption", project_id, target_type, target_id,
            confirmed=True, reason=adoption.review_reason,
        )

    def rollback_work_version(self, *, project: ProjectRef, chapter_id: int, version: dict[str, Any], old_index: dict[str, Any], operation_id: str) -> None:
        """Undo a not-yet-authoritative work version using the same write facade."""
        index_path = f"data/versions/chapter_{chapter_id:03d}_versions.json"
        target = self.store.path(index_path)
        if target.exists():
            operation = OperationEnvelope(f"{operation_id}:rollback_index", "version_adoption", project.project_id, "work_version", f"chapter_{chapter_id:03d}", confirmed=True, reason="rollback incomplete adoption")
            self.writer.write_json(
                project=project, target_path=index_path, payload=old_index, operation=operation,
                expectation=HashExpectation(expected_sha256=HashGuard.file_sha256(target), candidate_sha256=HashGuard.sha256_json(old_index)),
            )
        for key in ("json_path", "markdown_path"):
            try:
                self.store.path(str(version.get(key) or "")).unlink(missing_ok=True)
            except OSError:
                pass

    def write_versions_index(self, *, project: ProjectRef, chapter_id: int, index: dict[str, Any], operation_id: str, index_path: str | None = None) -> None:
        """Compatibility writer for a non-Canon selected pointer/index update."""
        path = index_path or f"data/versions/chapter_{chapter_id:03d}_versions.json"
        operation = OperationEnvelope(operation_id, "version_index_write", project.project_id, "work_version", f"chapter_{chapter_id:03d}", confirmed=True, reason="legacy version-manager compatibility")
        self.writer.write_json(project=project, target_path=path, payload=index, operation=operation, expectation=self._expectation(path, HashGuard.sha256_json(index)))

    def write_legacy_work_version(
        self,
        *,
        project: ProjectRef,
        chapter_id: int,
        kind: str,
        version: int,
        payload: dict[str, Any],
        markdown: str,
        operation_id: str,
        select: bool = True,
        aliases: dict[str, str] | None = None,
        version_root: str = "data",
    ) -> dict[str, Any]:
        """Write a legacy-shaped draft/edited/manual version exactly once.

        Naming, schemas, and read behaviour remain in VersionManager; only the
        non-Canon persistence transaction is owned here.
        """
        if kind not in {"draft", "edited", "manual"} or version < 1:
            raise VersionWriterError("VERSION_WRITER_INPUT_INVALID", "Unsupported work-version identity.")
        project.assert_context(self.context)
        paths = build_versioned_paths(chapter_id, kind, version, version_root)
        text = str(payload.get(f"{kind}_text") or "")
        written: list[str] = []
        try:
            self._write_compat_json(project, paths["json_path"], payload, operation_id, "version_json", f"{kind}_v{version:03d}")
            written.append(paths["json_path"])
            self._write_compat_text(project, paths["markdown_path"], markdown, operation_id, "version_markdown", f"{kind}_v{version:03d}")
            written.append(paths["markdown_path"])
            for alias_path, alias_value in (aliases or {}).items():
                if alias_path.endswith(".json"):
                    self._write_compat_json(project, alias_path, payload, operation_id, f"alias_{len(written)}", f"{kind}_alias")
                else:
                    self._write_compat_text(project, alias_path, alias_value, operation_id, f"alias_{len(written)}", f"{kind}_alias")
                written.append(alias_path)
            index_root = self.store.path(version_root)
            index = list_versions(chapter_id, index_root)
            if select:
                now = datetime.now(timezone.utc).isoformat()
                index["selected"] = {"source_type": kind, "version": version, "version_label": f"{kind}_v{version:03d}", "json_path": paths["json_path"], "markdown_path": paths["markdown_path"], "selected_at": now}
                old_index = self.store.read_json(f"{version_root}/versions/chapter_{chapter_id:03d}_versions.json", default={}, expected_type=dict) or {}
                index["selection_revision"] = int(old_index.get("selection_revision", 1) or 1) + 1
            self.write_versions_index(project=project, chapter_id=chapter_id, index=index, operation_id=f"{operation_id}:index", index_path=f"{version_root}/versions/chapter_{chapter_id:03d}_versions.json")
        except Exception:
            for path in reversed(written):
                try:
                    self.store.path(path).unlink(missing_ok=True)
                except OSError:
                    pass
            raise
        return {"version_id": f"{kind}_v{version:03d}", "version": version, "json_path": paths["json_path"], "markdown_path": paths["markdown_path"], "content_hash": HashGuard.sha256_text(text), "selected": select}

    def _write_json(self, project: ProjectRef, path: str, payload: Any, adoption: AdoptionRequest, suffix: str, target_id: str) -> None:
        operation = self._child_operation(adoption, project_id=project.project_id, target_type="work_version", target_id=target_id, suffix=suffix)
        self.writer.write_json(project=project, target_path=path, payload=payload, operation=operation, expectation=self._expectation(path, HashGuard.sha256_json(payload)))

    def _write_text(self, project: ProjectRef, path: str, payload: str, adoption: AdoptionRequest, suffix: str, target_id: str) -> None:
        operation = self._child_operation(adoption, project_id=project.project_id, target_type="work_version", target_id=target_id, suffix=suffix)
        self.writer.write_text(project=project, target_path=path, payload=payload, operation=operation, expectation=self._expectation(path, HashGuard.sha256_text(payload)))

    def _write_compat_json(self, project: ProjectRef, path: str, payload: dict[str, Any], operation_id: str, suffix: str, target_id: str) -> None:
        operation = OperationEnvelope(f"{operation_id}:{suffix}", "version_write", project.project_id, "work_version", target_id, confirmed=True, reason="legacy version compatibility")
        self.writer.write_json(project=project, target_path=path, payload=payload, operation=operation, expectation=self._expectation(path, HashGuard.sha256_json(payload)))

    def _write_compat_text(self, project: ProjectRef, path: str, payload: str, operation_id: str, suffix: str, target_id: str) -> None:
        operation = OperationEnvelope(f"{operation_id}:{suffix}", "version_write", project.project_id, "work_version", target_id, confirmed=True, reason="legacy version compatibility")
        self.writer.write_text(project=project, target_path=path, payload=payload, operation=operation, expectation=self._expectation(path, HashGuard.sha256_text(payload)))

    def _expectation(self, path: str, candidate_hash: str) -> HashExpectation:
        target = self.store.path(path)
        if not target.exists():
            return HashExpectation.for_new_target(candidate_sha256=candidate_hash)
        return HashExpectation(expected_sha256=HashGuard.file_sha256(target), candidate_sha256=candidate_hash)
