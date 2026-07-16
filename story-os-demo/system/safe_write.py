"""Narrow shared write facade built on the existing DataStore atomic primitive."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Any, Callable

from core.contracts import HashExpectation, HashGuard, OperationEnvelope, ProjectRef
from core.contracts.project_ref import ProjectRefError
from core.contracts.safety import OperationEnvelopeError, SafetyContractError
from core.project_context import ProjectContext
from system.data_store import DataStore


class DataStoreWriteError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class WriteResult:
    operation_id: str
    target_type: str
    target_id: str
    before_hash: str | None
    after_hash: str
    replayed: bool
    audit_metadata: dict[str, Any]

    def public_view(self) -> dict[str, Any]:
        return asdict(self)


class DataStoreWriteFacade:
    """Validate a write request, then delegate the actual write to DataStore."""

    def __init__(self, context: ProjectContext) -> None:
        self.context = context
        self.store = DataStore(context)
        self._operations: dict[str, tuple[str, WriteResult]] = {}

    def write_json(self, *, project: ProjectRef, target_path: str, payload: Any, operation: OperationEnvelope, expectation: HashExpectation) -> WriteResult:
        candidate_hash = HashGuard.sha256_json(payload)
        return self._write(project, target_path, candidate_hash, operation, expectation, lambda path: self.store.write_json(path, payload))

    def replace_json(self, **kwargs: Any) -> WriteResult:
        return self.write_json(**kwargs)

    def write_text(self, *, project: ProjectRef, target_path: str, payload: str, operation: OperationEnvelope, expectation: HashExpectation) -> WriteResult:
        text = str(payload)
        candidate_hash = HashGuard.sha256_text(text)
        return self._write(project, target_path, candidate_hash, operation, expectation, lambda path: self.store.write_text(path, text))

    def replace_text(self, **kwargs: Any) -> WriteResult:
        return self.write_text(**kwargs)

    def remove(self, *, project: ProjectRef, target_path: str, operation: OperationEnvelope, expectation: HashExpectation) -> WriteResult:
        """Remove one validated project file for a transaction rollback only."""
        try:
            project.assert_context(self.context)
            project.assert_project_id(operation.project_id)
            relative_target = project.relative_target_path(target_path)
            target = self.store.path(relative_target)
            validation = HashGuard.validate_target(target, expectation)
            signature = HashGuard.sha256_json({"operation": operation.fingerprint(), "target": relative_target, "remove": True})
            existing = self._operations.get(operation.operation_id)
            if existing:
                if existing[0] != signature:
                    raise DataStoreWriteError("OPERATION_ID_CONFLICT", "operation_id was already used for a different request.")
                return replace(existing[1], replayed=True, audit_metadata={**existing[1].audit_metadata, "replayed": True})
            target.unlink()
            audit = {"operation_id": operation.operation_id, "operation_type": operation.operation_type, "project_id": project.public_view().project_id, "target_type": operation.target_type, "target_id": operation.target_id, "before_hash": validation.actual_sha256, "after_hash": "", "status": "removed", "replayed": False, "created_at": datetime.now(timezone.utc).isoformat(), "error_code": ""}
            result = WriteResult(operation.operation_id, operation.target_type, operation.target_id, validation.actual_sha256, "", False, audit)
            self._operations[operation.operation_id] = (signature, result)
            return result
        except (ProjectRefError, OperationEnvelopeError, SafetyContractError, DataStoreWriteError):
            raise
        except OSError as exc:
            raise DataStoreWriteError("DATASTORE_WRITE_FAILED", "Safe project write could not be completed.") from exc

    def _write(self, project: ProjectRef, target_path: str, candidate_hash: str, operation: OperationEnvelope, expectation: HashExpectation, writer: Callable[[str], None]) -> WriteResult:
        try:
            project.assert_context(self.context)
            project.assert_project_id(operation.project_id)
            relative_target = project.relative_target_path(target_path)
            HashGuard.validate_candidate(candidate_hash, expectation.candidate_sha256)
            request_signature = HashGuard.sha256_json({"operation": operation.fingerprint(), "target": relative_target, "candidate_hash": candidate_hash})
            existing = self._operations.get(operation.operation_id)
            if existing:
                if existing[0] != request_signature:
                    raise DataStoreWriteError("OPERATION_ID_CONFLICT", "operation_id was already used for a different request.")
                return replace(existing[1], replayed=True, audit_metadata={**existing[1].audit_metadata, "replayed": True})
            target = self.store.path(relative_target)
            validation = HashGuard.validate_target(target, expectation)
            writer(relative_target)
            after_hash = HashGuard.file_sha256(target)
            audit = {
                "operation_id": operation.operation_id, "operation_type": operation.operation_type,
                "project_id": project.public_view().project_id, "target_type": operation.target_type,
                "target_id": operation.target_id, "before_hash": validation.actual_sha256,
                "after_hash": after_hash, "status": "completed", "replayed": False,
                "created_at": datetime.now(timezone.utc).isoformat(), "error_code": "",
            }
            result = WriteResult(operation.operation_id, operation.target_type, operation.target_id, validation.actual_sha256, after_hash, False, audit)
            self._operations[operation.operation_id] = (request_signature, result)
            return result
        except (ProjectRefError, OperationEnvelopeError, SafetyContractError, DataStoreWriteError):
            raise
        except Exception as exc:
            raise DataStoreWriteError("DATASTORE_WRITE_FAILED", "Safe project write could not be completed.") from exc
