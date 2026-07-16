"""One guarded write entrypoint for planning-owned project data.

The service deliberately owns persistence only.  Planning algorithms continue
to live in their existing services; callers pass an already validated payload
and receive one atomic-at-the-domain-boundary mutation or a safe failure.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from core.contracts import HashExpectation, HashGuard, OperationEnvelope, ProjectRef
from core.contracts.safety import OperationEnvelopeError, SafetyContractError
from core.project_context import ProjectContext, get_project_context
from system.data_store import DataStore
from system.safe_write import DataStoreWriteError, DataStoreWriteFacade


class PlanningMutationError(RuntimeError):
    """A code-only error safe for API and compatibility callers."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True)
class PlanningMutationTarget:
    target_type: str
    payload: Any
    expected_before_hash: str | None
    expected_after_hash: str | None = None


@dataclass(frozen=True)
class _TargetSpec:
    path: str
    expected_type: type | tuple[type, ...]
    state_fields: frozenset[str] = frozenset()


class PlanningMutationService:
    """Validate a complete planning mutation before delegating writes to DataStore.

    Target paths are a closed registry: neither HTTP payloads nor legacy
    callers can provide a filesystem path.  The audit record is intentionally
    hash-only and is also the persistent idempotency source across processes.
    """

    TARGETS: dict[str, _TargetSpec] = {
        "next_chapter_plan": _TargetSpec("data/next_chapter_plan.json", dict),
        "next_chapter_plan_markdown": _TargetSpec("data/next_chapter_plan.md", str),
        "planning_state": _TargetSpec("data/state.json", dict, frozenset({"current_stage", "next_chapter_plan"})),
        "story_planning": _TargetSpec("data/story_planning.json", dict),
        "rolling_window": _TargetSpec("data/planning_control/rolling_window.json", dict),
        "dependencies": _TargetSpec("data/planning_control/dependencies.json", dict),
        "schedules": _TargetSpec("data/planning_control/schedules.json", dict),
        "strategy": _TargetSpec("data/planning_control/strategy.json", (dict, type(None))),
        "milestones": _TargetSpec("data/planning_control/milestones.json", list),
        "volume_contracts": _TargetSpec("data/planning_control/volume_contracts.json", list),
        "phase_contracts": _TargetSpec("data/planning_control/phase_contracts.json", list),
        "locks": _TargetSpec("data/planning_control/locks.json", list),
        "conflicts": _TargetSpec("data/planning_control/conflicts.json", list),
        "planning_metadata": _TargetSpec("data/planning_control/metadata.json", dict),
        "planning_version": _TargetSpec("data/planning_versions", dict),
        "planning_control_version": _TargetSpec("data/planning_control/versions", dict),
    }
    AUDIT_PATH = "data/planning_control/mutation_audit.json"
    _STATE_LAST = "planning_state"

    def __init__(self, context: ProjectContext | None = None) -> None:
        self.context = context or get_project_context()
        self.project = ProjectRef.from_context(self.context)
        self.store = DataStore(self.context)
        self.writer = DataStoreWriteFacade(self.context)

    def target_path(self, target_type: str, *, target_id: str = "") -> str:
        spec = self.TARGETS.get(target_type)
        if spec is None:
            raise PlanningMutationError("PLANNING_TARGET_INVALID")
        if target_type in {"planning_version", "planning_control_version"}:
            safe = str(target_id or "").strip()
            if not safe or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in safe):
                raise PlanningMutationError("PLANNING_TARGET_INVALID")
            return f"{spec.path}/{safe}.json"
        if target_id:
            raise PlanningMutationError("PLANNING_TARGET_INVALID")
        return spec.path

    def mutation(
        self,
        *,
        mutation_type: str,
        operation: OperationEnvelope,
        targets: Iterable[PlanningMutationTarget],
        reason: str = "",
    ) -> dict[str, Any]:
        items = list(targets)
        if not items:
            raise PlanningMutationError("PLANNING_TARGET_REQUIRED")
        self._validate_operation(mutation_type, operation)
        prepared = self._prepare(items)
        fingerprint = HashGuard.sha256_json({
            "operation": operation.fingerprint(), "mutation_type": mutation_type,
            "targets": [{"type": item["target_type"], "before": item["before_hash"], "after": item["after_hash"]} for item in prepared],
        })
        persisted = self._find_operation(operation.operation_id)
        if persisted:
            if persisted.get("fingerprint") != fingerprint:
                raise PlanningMutationError("OPERATION_ID_CONFLICT")
            if persisted.get("status") == "completed":
                return {"operation_id": operation.operation_id, "replayed": True, "targets": copy.deepcopy(persisted.get("targets", [])), "audit_id": persisted.get("audit_id", "")}
            raise PlanningMutationError(str(persisted.get("error_code") or "PLANNING_OPERATION_FAILED"))

        # Full preflight happens before any DataStore write.
        for item in prepared:
            self._validate_payload(item)
            HashGuard.validate_target(self.store.path(item["path"]), item["expectation"])
        audit_before, audit_document = self._audit_document()
        audit_id = f"planning_mutation_{uuid4().hex}"
        audit_entry = {
            "audit_id": audit_id, "operation_id": operation.operation_id, "fingerprint": fingerprint,
            "project_id": self.project.public_view().project_id, "mutation_type": mutation_type,
            "target_types": [item["target_type"] for item in prepared],
            "targets": [{"target_type": item["target_type"], "before_hash": item["before_hash"], "after_hash": item["after_hash"]} for item in prepared],
            "before_hashes": {item["target_type"]: item["before_hash"] for item in prepared},
            "after_hashes": {item["target_type"]: item["after_hash"] for item in prepared},
            "status": "completed", "replayed": False,
            "created_at": datetime.now(timezone.utc).isoformat(), "error_code": "",
        }
        audit_document.setdefault("schema_version", "1.0")
        audit_document.setdefault("operations", []).append(audit_entry)
        audit_document["operations"] = audit_document["operations"][-200:]
        audit_document["updated_at"] = datetime.now(timezone.utc).isoformat()
        audit_item = self._prepared_item(
            PlanningMutationTarget("planning_metadata", audit_document, audit_before, None),
            path=self.AUDIT_PATH, target_type="planning_mutation_audit", expected_type=dict,
        )

        written: list[dict[str, Any]] = []
        try:
            # State is last so a partial failure never advances planning state.
            for item in (item for item in prepared if item["target_type"] != self._STATE_LAST):
                self._write_item(item, operation, mutation_type)
                item["written_hash"] = HashGuard.file_sha256(self.store.path(item["path"]))
                written.append(item)
            self._write_item(audit_item, operation, mutation_type)
            audit_item["written_hash"] = HashGuard.file_sha256(self.store.path(audit_item["path"]))
            written.append(audit_item)
            for item in (item for item in prepared if item["target_type"] == self._STATE_LAST):
                self._write_item(item, operation, mutation_type)
                item["written_hash"] = HashGuard.file_sha256(self.store.path(item["path"]))
                written.append(item)
        except Exception as exc:
            rollback_error = self._rollback(written, operation, mutation_type)
            if rollback_error:
                raise PlanningMutationError("PLANNING_ROLLBACK_FAILED") from exc
            if isinstance(exc, PlanningMutationError):
                raise
            if isinstance(exc, (DataStoreWriteError, SafetyContractError, OperationEnvelopeError)):
                raise PlanningMutationError(getattr(exc, "code", "PLANNING_WRITE_FAILED")) from exc
            raise PlanningMutationError("PLANNING_WRITE_FAILED") from exc
        return {"operation_id": operation.operation_id, "replayed": False, "targets": [{"target_type": item["target_type"], "before_hash": item["before_hash"], "after_hash": item["after_hash"]} for item in prepared], "audit_id": audit_id, "reason": str(reason or "")[:2000]}

    def legacy_write(
        self,
        target_type: str,
        payload: Any,
        *,
        mutation_type: str,
        target_id: str = "",
        operation_id: str = "",
        reason: str = "legacy planning compatibility",
    ) -> dict[str, Any]:
        path = self.target_path(target_type, target_id=target_id)
        before = self._existing_hash(path)
        operation = OperationEnvelope(
            operation_id=operation_id or f"planning-{mutation_type}-{uuid4().hex}",
            operation_type="planning_mutation", project_id=self.project.project_id,
            target_type="planning_bundle", target_id=mutation_type[:128] or "planning",
            expected_hashes={"request": HashGuard.sha256_json({"target_type": target_type, "before": before, "payload": payload})},
            confirmed=True, reason=reason, risk_level="low",
        )
        item = PlanningMutationTarget(target_type, payload, before, None)
        if target_id:
            # Dynamic version paths are generated by internal callers only.
            prepared = self._prepared_item(item, path=path, target_type=target_type, expected_type=self.TARGETS[target_type].expected_type)
            return self._mutation_prepared(mutation_type, operation, [prepared], reason)
        return self.mutation(mutation_type=mutation_type, operation=operation, targets=[item], reason=reason)

    def write_bundle_legacy(self, entries: list[tuple[str, Any]], *, mutation_type: str, operation_id: str = "", reason: str = "legacy planning compatibility") -> dict[str, Any]:
        operation = OperationEnvelope(
            operation_id=operation_id or f"planning-{mutation_type}-{uuid4().hex}", operation_type="planning_mutation",
            project_id=self.project.project_id, target_type="planning_bundle", target_id=mutation_type[:128] or "planning",
            expected_hashes={"request": HashGuard.sha256_json({"targets": [name for name, _ in entries]})}, confirmed=True, reason=reason,
        )
        return self.mutation(mutation_type=mutation_type, operation=operation, targets=[PlanningMutationTarget(name, payload, self._existing_hash(self.target_path(name))) for name, payload in entries], reason=reason)

    def _mutation_prepared(self, mutation_type: str, operation: OperationEnvelope, prepared: list[dict[str, Any]], reason: str) -> dict[str, Any]:
        # Version records use the same validation/audit path but have a generated,
        # internal-only target path.  Keep the public contract path-free.
        return self._execute_prepared(mutation_type, operation, prepared, reason)

    def _execute_prepared(self, mutation_type: str, operation: OperationEnvelope, prepared: list[dict[str, Any]], reason: str) -> dict[str, Any]:
        # Reuse the normal transaction by temporarily resolving the supplied internal paths.
        # This small adapter avoids exposing paths through the public target contract.
        original = self._prepare
        try:
            self._prepare = lambda _items: prepared  # type: ignore[method-assign]
            return self.mutation(mutation_type=mutation_type, operation=operation, targets=[PlanningMutationTarget(item["target_type"], item["payload"], item["before_hash"], item["after_hash"]) for item in prepared], reason=reason)
        finally:
            self._prepare = original  # type: ignore[method-assign]

    def _validate_operation(self, mutation_type: str, operation: OperationEnvelope) -> None:
        if not mutation_type or operation.operation_type != "planning_mutation":
            raise PlanningMutationError("PLANNING_OPERATION_INVALID")
        self.project.assert_project_id(operation.project_id)

    def _prepare(self, targets: list[PlanningMutationTarget]) -> list[dict[str, Any]]:
        prepared: list[dict[str, Any]] = []
        seen: set[str] = set()
        for target in targets:
            if target.target_type in seen:
                raise PlanningMutationError("PLANNING_TARGET_DUPLICATE")
            seen.add(target.target_type)
            spec = self.TARGETS.get(target.target_type)
            if spec is None or target.target_type in {"planning_version", "planning_control_version"}:
                raise PlanningMutationError("PLANNING_TARGET_INVALID")
            prepared.append(self._prepared_item(target, path=spec.path, target_type=target.target_type, expected_type=spec.expected_type))
        return prepared

    def _prepared_item(self, target: PlanningMutationTarget, *, path: str, target_type: str, expected_type: type | tuple[type, ...]) -> dict[str, Any]:
        payload = copy.deepcopy(target.payload)
        spec = self.TARGETS.get(target_type)
        if spec and spec.state_fields:
            if not isinstance(payload, dict) or set(payload) - set(spec.state_fields):
                raise PlanningMutationError("PLANNING_STATE_FIELD_FORBIDDEN")
            existing = self.store.read_json(path, default={}, expected_type=dict) or {}
            payload = {**existing, **payload}
        before = target.expected_before_hash
        expectation = HashExpectation(expected_sha256=before) if before else HashExpectation.for_new_target()
        after = HashGuard.sha256_json(payload) if isinstance(payload, (dict, list)) or payload is None else HashGuard.sha256_text(str(payload))
        if target.expected_after_hash:
            HashGuard.validate_candidate(after, target.expected_after_hash)
        original_payload: Any = None
        original_text: str | None = None
        if before:
            # Preserve exact bytes (including CRLF) so a rollback restores the
            # original SHA-256, not merely equivalent JSON content.
            original_text = self.store.path(path).read_bytes().decode("utf-8")
            original_payload = original_text if expected_type is str else self.store.read_json(path, strict=True)
        return {"target_type": target_type, "path": path, "payload": payload, "expected_type": expected_type, "expectation": expectation, "before_hash": before, "after_hash": after, "original_payload": original_payload, "original_text": original_text}

    def _validate_payload(self, item: dict[str, Any]) -> None:
        if not isinstance(item["payload"], item["expected_type"]):
            raise PlanningMutationError("PLANNING_SCHEMA_INVALID")
        if item["target_type"] == "next_chapter_plan" and "chapter_id" in item["payload"] and not isinstance(item["payload"].get("chapter_id"), int):
            raise PlanningMutationError("PLANNING_DOMAIN_INVALID")
        if item["target_type"] == "planning_state" and item["payload"].get("next_chapter_plan", {}).get("chapter_id") is not None and not isinstance(item["payload"]["next_chapter_plan"]["chapter_id"], int):
            raise PlanningMutationError("PLANNING_DOMAIN_INVALID")

    def _write_item(self, item: dict[str, Any], operation: OperationEnvelope, mutation_type: str) -> None:
        child = OperationEnvelope(
            operation_id=f"pm-{HashGuard.sha256_text(operation.operation_id + ':' + mutation_type + ':' + item['target_type'])[:48]}", operation_type="planning_mutation",
            project_id=self.project.project_id, target_type="planning_target", target_id=item["target_type"],
            expected_hashes={"payload": item["after_hash"]}, confirmed=True, reason=mutation_type,
        )
        if isinstance(item["payload"], str):
            self.writer.write_text(project=self.project, target_path=item["path"], payload=item["payload"], operation=child, expectation=item["expectation"])
        else:
            self.writer.write_json(project=self.project, target_path=item["path"], payload=item["payload"], operation=child, expectation=item["expectation"])

    def _rollback(self, written: list[dict[str, Any]], operation: OperationEnvelope, mutation_type: str) -> bool:
        failed = False
        for item in reversed(written):
            if not item["before_hash"]:
                try:
                    self._remove_item(item, operation, f"{mutation_type}_rollback")
                except Exception:
                    failed = True
                continue
            try:
                # The original content is retained by callers in the transaction item.
                original = item.get("original_text")
                if original is None:
                    failed = True
                    continue
                rollback = {**item, "payload": original, "expectation": HashExpectation(expected_sha256=item.get("written_hash") or HashGuard.file_sha256(self.store.path(item["path"]))), "after_hash": item["before_hash"]}
                self._write_item(rollback, operation, f"{mutation_type}_rollback")
            except Exception:
                failed = True
        return failed

    def _remove_item(self, item: dict[str, Any], operation: OperationEnvelope, mutation_type: str) -> None:
        child = OperationEnvelope(
            operation_id=f"pm-{HashGuard.sha256_text(operation.operation_id + ':' + mutation_type + ':' + item['target_type'])[:48]}", operation_type="planning_mutation",
            project_id=self.project.project_id, target_type="planning_target", target_id=item["target_type"],
            expected_hashes={"payload": item.get("written_hash") or item["after_hash"]}, confirmed=True, reason=mutation_type,
        )
        self.writer.remove(project=self.project, target_path=item["path"], operation=child, expectation=HashExpectation(expected_sha256=item.get("written_hash") or item["after_hash"]))

    def _existing_hash(self, path: str) -> str | None:
        target = self.store.path(path)
        return HashGuard.file_sha256(target) if target.exists() else None

    def _audit_document(self) -> tuple[str | None, dict[str, Any]]:
        target = self.store.path(self.AUDIT_PATH)
        before = HashGuard.file_sha256(target) if target.exists() else None
        document = self.store.read_json(self.AUDIT_PATH, default={}, expected_type=dict) or {}
        operations = document.get("operations", [])
        if not isinstance(operations, list):
            raise PlanningMutationError("PLANNING_AUDIT_INVALID")
        document["operations"] = operations
        return before, document

    def _find_operation(self, operation_id: str) -> dict[str, Any] | None:
        _, document = self._audit_document()
        for item in document.get("operations", []):
            if isinstance(item, dict) and item.get("operation_id") == operation_id:
                return item
        return None
