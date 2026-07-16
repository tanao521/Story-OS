"""Authoritative orchestration entry point for candidate version adoption.

It deliberately contains no model, Canon, planning, or state mutation logic.
The legacy evaluation services are retained as payload/error adapters while this
service is the single public command boundary for whole, partial, and discard.
"""
from __future__ import annotations

from typing import Any

from core.project_context import ProjectContext
from system.revision_adapters import AdoptionAdapter, LegacyOperationAdapter, RevisionAdapter


class VersionAdoptionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class VersionAdoptionService:
    """One authority for adoption commands; old services only adapt callers."""

    def __init__(self, context: ProjectContext, *, whole_service: Any = None, partial_service: Any = None) -> None:
        self.context = context
        self._whole_service = whole_service
        self._partial_service = partial_service

    def preview_whole(self, request_id: str) -> dict[str, Any]:
        whole = self._whole()
        preview = whole._legacy_preview(request_id)
        AdoptionAdapter.preview(preview)
        return preview

    def preview_partial(self, request_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        partial = self._partial()
        preview = partial._legacy_preview(request_id, payload)
        AdoptionAdapter.preview(preview)
        return preview

    def adopt_whole(self, request_id: str, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        whole = self._whole()
        request = whole.improvements.get(request_id)
        candidate = RevisionAdapter.candidate(request)
        forwarded = dict(payload); forwarded["__operation_fingerprint"] = self._operation(payload, candidate.candidate_hash, request_id)
        return whole._legacy_adopt(request_id, forwarded)

    def adopt_partial(self, request_id: str, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        partial = self._partial()
        request = partial.improvements.get(request_id)
        candidate = RevisionAdapter.candidate(request)
        forwarded = dict(payload); forwarded["__operation_fingerprint"] = self._operation(payload, candidate.candidate_hash, request_id)
        return partial._legacy_adopt(request_id, forwarded)

    def discard(self, request_id: str, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        whole = self._whole()
        request = whole.improvements.get(request_id)
        candidate = RevisionAdapter.candidate(request)
        forwarded = dict(payload); forwarded["__operation_fingerprint"] = self._operation(payload, candidate.candidate_hash, request_id)
        return whole._legacy_discard(request_id, forwarded)

    def _operation(self, payload: dict[str, Any], candidate_hash: str, request_id: str) -> str:
        # Use the shared envelope as the unified command validation seam.  The
        # persisted adoption record in the legacy request remains the replay
        # authority across process restarts.
        # Preserve legacy review-required errors; the legacy policy reports a
        # missing author confirmation before a command becomes executable.
        if "author_confirm" in payload and not bool(payload.get("author_confirm")):
            return ""
        envelope = LegacyOperationAdapter.envelope(
            operation_id=payload.get("operation_id"), project_id=self.context.root.name,
            target_type="version", target_id=request_id,
            expected_hashes={"candidate_hash": candidate_hash}, reason=str(payload.get("review_reason") or payload.get("reason") or ""),
        )
        return envelope.fingerprint()

    def _whole(self):
        if self._whole_service is not None:
            return self._whole_service
        from evaluation_engine.candidate_adoption_service import CandidateAdoptionService
        return CandidateAdoptionService(self.context)

    def _partial(self):
        if self._partial_service is not None:
            return self._partial_service
        from evaluation_engine.candidate_partial_adoption_service import CandidatePartialAdoptionService
        return CandidatePartialAdoptionService(self.context)
