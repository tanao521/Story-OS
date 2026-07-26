"""Protocol objects for author-confirmed version adoption."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .safety import HashGuard, OperationEnvelope, OperationEnvelopeError, SafetyContractError


class AdoptionContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _required(value: object, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > 256:
        raise AdoptionContractError("ADOPTION_FIELD_INVALID", f"{field} is required and bounded.")
    return normalized


def _hash(value: str, field: str) -> str:
    try:
        return HashGuard.normalize_sha256(value)
    except SafetyContractError as exc:
        raise AdoptionContractError("ADOPTION_HASH_INVALID", f"{field} must be a complete SHA-256.") from exc


@dataclass(frozen=True)
class AdoptionPreview:
    preview_id: str
    candidate_id: str
    source_version: str
    source_hash: str
    candidate_hash: str
    expected_result_hash: str
    expires_at: str
    mode: str = "whole"
    selected_patch_ids: tuple[str, ...] = ()
    patch_set_hash: str = ""

    def __post_init__(self) -> None:
        for field in ("preview_id", "candidate_id", "source_version"):
            object.__setattr__(self, field, _required(getattr(self, field), field))
        for field in ("source_hash", "candidate_hash", "expected_result_hash"):
            object.__setattr__(self, field, _hash(getattr(self, field), field))
        stamp = str(self.expires_at or "")
        try:
            datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AdoptionContractError("ADOPTION_PREVIEW_EXPIRY_INVALID", "expires_at must be ISO-8601.") from exc
        object.__setattr__(self, "expires_at", stamp)
        if self.mode not in {"whole", "partial"}:
            raise AdoptionContractError("ADOPTION_MODE_INVALID", "mode must be whole or partial.")
        selected = tuple(_required(item, "selected_patch_ids") for item in self.selected_patch_ids)
        if len(selected) != len(set(selected)):
            raise AdoptionContractError("ADOPTION_PATCH_SELECTION_INVALID", "selected_patch_ids must be unique.")
        if self.mode == "whole" and selected:
            raise AdoptionContractError("ADOPTION_PATCH_SELECTION_INVALID", "whole adoption cannot select patches.")
        if self.mode == "partial" and not selected:
            raise AdoptionContractError("ADOPTION_PATCH_SELECTION_INVALID", "partial adoption requires selected patches.")
        if self.patch_set_hash:
            object.__setattr__(self, "patch_set_hash", _hash(self.patch_set_hash, "patch_set_hash"))
        elif self.mode == "partial":
            raise AdoptionContractError("ADOPTION_PATCH_SET_HASH_REQUIRED", "partial adoption requires patch_set_hash.")
        object.__setattr__(self, "selected_patch_ids", selected)


@dataclass(frozen=True)
class AdoptionRequest:
    operation_id: str
    preview_id: str
    candidate_id: str
    author_confirm: bool
    review_reason: str
    expected_revision: int
    mode: str = "whole"
    selected_patch_ids: tuple[str, ...] = ()
    patch_set_hash: str = ""

    def __post_init__(self) -> None:
        for field in ("operation_id", "preview_id", "candidate_id"):
            object.__setattr__(self, field, _required(getattr(self, field), field))
        if not self.author_confirm:
            raise AdoptionContractError("ADOPTION_CONFIRMATION_REQUIRED", "author_confirm must be true.")
        reason = str(self.review_reason or "").strip()
        if len(reason) > 2000:
            raise AdoptionContractError("ADOPTION_REVIEW_REASON_INVALID", "review_reason exceeds the allowed length.")
        if not isinstance(self.expected_revision, int) or self.expected_revision < 0:
            raise AdoptionContractError("ADOPTION_EXPECTED_REVISION_INVALID", "expected_revision must be a non-negative integer.")
        if self.mode not in {"whole", "partial"}:
            raise AdoptionContractError("ADOPTION_MODE_INVALID", "mode must be whole or partial.")
        selected = tuple(_required(item, "selected_patch_ids") for item in self.selected_patch_ids)
        if len(selected) != len(set(selected)) or (self.mode == "whole" and selected) or (self.mode == "partial" and not selected):
            raise AdoptionContractError("ADOPTION_PATCH_SELECTION_INVALID", "Patch selection does not match adoption mode.")
        if self.patch_set_hash:
            object.__setattr__(self, "patch_set_hash", _hash(self.patch_set_hash, "patch_set_hash"))
        elif self.mode == "partial":
            raise AdoptionContractError("ADOPTION_PATCH_SET_HASH_REQUIRED", "partial adoption requires patch_set_hash.")
        object.__setattr__(self, "selected_patch_ids", selected)
        try:
            OperationEnvelope(self.operation_id, "version_adoption", "contract", "version", self.candidate_id, confirmed=True, reason=reason)
        except OperationEnvelopeError as exc:
            raise AdoptionContractError(exc.code, str(exc)) from exc
        object.__setattr__(self, "review_reason", reason)

    def to_operation_envelope(self, *, project_id: str, target_id: str, expected_hashes: dict[str, str]) -> OperationEnvelope:
        return OperationEnvelope(
            self.operation_id, "version_adoption", project_id, "version", target_id,
            expected_hashes=expected_hashes, confirmed=self.author_confirm, reason=self.review_reason,
        )


@dataclass(frozen=True)
class AdoptionResult:
    operation_id: str
    version_id: str
    new_hash: str
    replayed: bool
    audit_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_id", _required(self.operation_id, "operation_id"))
        object.__setattr__(self, "version_id", _required(self.version_id, "version_id"))
        object.__setattr__(self, "audit_id", _required(self.audit_id, "audit_id"))
        object.__setattr__(self, "new_hash", _hash(self.new_hash, "new_hash"))
