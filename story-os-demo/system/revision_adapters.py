"""Narrow conversion adapters from legacy evaluation payloads to shared contracts."""
from __future__ import annotations

from typing import Any, Mapping

from core.contracts import HashGuard, OperationEnvelope
from core.contracts.adoption_contract import AdoptionPreview, AdoptionRequest, AdoptionResult
from core.contracts.revision_contract import RevisionCandidate, RevisionPatch, RevisionRequest


class LegacyHashAdapter:
    @staticmethod
    def sha256(value: Any, *, field: str) -> str:
        return HashGuard.normalize_sha256(str(value or ""))


class LegacyOperationAdapter:
    @staticmethod
    def envelope(*, operation_id: Any, project_id: str, target_type: str, target_id: str, expected_hashes: Mapping[str, str], reason: str = "") -> OperationEnvelope:
        return OperationEnvelope(str(operation_id or ""), "version_adoption", project_id, target_type, target_id, expected_hashes=dict(expected_hashes), confirmed=True, reason=reason)


class RevisionAdapter:
    @staticmethod
    def request(legacy: Mapping[str, Any]) -> RevisionRequest:
        return RevisionRequest(
            revision_id=str(legacy.get("improvement_id") or legacy.get("revision_id") or ""),
            project_id=str(legacy.get("project_id") or ""), target_type="chapter_draft",
            target_id=str(legacy.get("chapter_id") or ""),
            source_version=f"{(legacy.get('source_ref') or {}).get('source_type', '')}_v{int((legacy.get('source_ref') or {}).get('source_version') or 0):03d}",
            issue_refs=tuple(str(item) for item in legacy.get("issue_ids", []) or []),
            strategy=str(legacy.get("mode") or "restricted_candidate"), risk_level="low",
        )

    @staticmethod
    def candidate(legacy_request: Mapping[str, Any]) -> RevisionCandidate:
        candidate = legacy_request.get("candidate") if isinstance(legacy_request.get("candidate"), Mapping) else {}
        status = str((legacy_request.get("comparison") or {}).get("recommendation") or legacy_request.get("state") or "draft")
        return RevisionCandidate(
            candidate_id=str(candidate.get("candidate_id") or ""), revision_id=str(legacy_request.get("improvement_id") or ""),
            source_hash=LegacyHashAdapter.sha256(legacy_request.get("source_hash"), field="source_hash"),
            candidate_hash=LegacyHashAdapter.sha256(candidate.get("content_hash"), field="candidate_hash"),
            change_type="bounded_local_revision", status=status,
        )

    @staticmethod
    def patch(legacy: Mapping[str, Any], *, candidate_id: str, source_hash: str, candidate_hash: str) -> RevisionPatch:
        return RevisionPatch(
            patch_id=str(legacy.get("patch_id") or ""), candidate_id=candidate_id,
            location={"anchor": str(legacy.get("original_anchor") or legacy.get("anchor") or "")},
            before_text_hash=LegacyHashAdapter.sha256(source_hash, field="source_hash"),
            after_text_hash=LegacyHashAdapter.sha256(candidate_hash, field="candidate_hash"),
            risk=str(legacy.get("risk") or "low"),
            dependencies=tuple(str(item) for item in legacy.get("depends_on_patch_ids", []) or []),
            conflicts=tuple(str(item) for item in legacy.get("conflicts_with_patch_ids", []) or []),
        )


class AdoptionAdapter:
    @staticmethod
    def preview(legacy: Mapping[str, Any]) -> AdoptionPreview:
        selected = tuple(str(item) for item in legacy.get("selected_patch_ids", []) or [])
        patch_set_hash = HashGuard.sha256_json(selected) if selected else ""
        return AdoptionPreview(
            preview_id=str(legacy.get("preview_id") or ""), candidate_id=str(legacy.get("candidate_id") or ""),
            source_version=str(legacy.get("expected_source_version_id") or legacy.get("current_version_id") or ""),
            source_hash=LegacyHashAdapter.sha256(legacy.get("expected_source_hash") or legacy.get("current_content_hash"), field="source_hash"),
            candidate_hash=LegacyHashAdapter.sha256(legacy.get("candidate_content_hash"), field="candidate_hash"),
            expected_result_hash=LegacyHashAdapter.sha256(legacy.get("candidate_content_hash"), field="expected_result_hash"),
            expires_at=str(legacy.get("expires_at") or ""), mode="partial" if selected else "whole",
            selected_patch_ids=selected, patch_set_hash=patch_set_hash,
        )

    @staticmethod
    def request(legacy: Mapping[str, Any]) -> AdoptionRequest:
        selected = tuple(str(item) for item in legacy.get("selected_patch_ids", []) or [])
        return AdoptionRequest(
            operation_id=str(legacy.get("operation_id") or ""), preview_id=str(legacy.get("preview_id") or ""),
            candidate_id=str(legacy.get("candidate_id") or ""), author_confirm=bool(legacy.get("author_confirm")),
            review_reason=str(legacy.get("review_reason") or ""), expected_revision=int(legacy.get("expected_current_version_revision") or 0),
            mode="partial" if selected else "whole", selected_patch_ids=selected,
            patch_set_hash=HashGuard.sha256_json(selected) if selected else "",
        )


class VersionAdapter:
    @staticmethod
    def result(legacy: Mapping[str, Any], *, operation_id: str, audit_id: str, replayed: bool = False) -> AdoptionResult:
        version = legacy.get("new_version") if isinstance(legacy.get("new_version"), Mapping) else legacy
        return AdoptionResult(operation_id, str(version.get("version_id") or ""), LegacyHashAdapter.sha256(version.get("content_hash"), field="new_hash"), replayed, audit_id)
