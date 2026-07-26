"""Protocol objects for bounded candidate revision work."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .safety import HashGuard, SafetyContractError


class RevisionContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


_CANDIDATE_STATES = {"draft", "ready", "review_required", "qualified", "rejected"}
_RISK_LEVELS = {"low", "medium", "high"}


def _required(value: object, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > 256:
        raise RevisionContractError("REVISION_FIELD_INVALID", f"{field} is required and bounded.")
    return normalized


def _hash(value: str, field: str) -> str:
    try:
        return HashGuard.normalize_sha256(value)
    except SafetyContractError as exc:
        raise RevisionContractError("REVISION_HASH_INVALID", f"{field} must be a complete SHA-256.") from exc


@dataclass(frozen=True)
class RevisionRequest:
    revision_id: str
    project_id: str
    target_type: str
    target_id: str
    source_version: str
    issue_refs: tuple[str, ...]
    strategy: str
    risk_level: str

    def __post_init__(self) -> None:
        for field in ("revision_id", "project_id", "target_type", "target_id", "source_version", "strategy"):
            object.__setattr__(self, field, _required(getattr(self, field), field))
        refs = tuple(_required(item, "issue_refs") for item in self.issue_refs)
        if not refs or len(refs) > 25 or len(set(refs)) != len(refs):
            raise RevisionContractError("REVISION_ISSUE_REFS_INVALID", "issue_refs must be a unique, non-empty list of at most 25 items.")
        if self.risk_level not in _RISK_LEVELS:
            raise RevisionContractError("REVISION_RISK_INVALID", "risk_level is invalid.")
        object.__setattr__(self, "issue_refs", refs)


@dataclass(frozen=True)
class RevisionCandidate:
    candidate_id: str
    revision_id: str
    source_hash: str
    candidate_hash: str
    change_type: str
    status: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _required(self.candidate_id, "candidate_id"))
        object.__setattr__(self, "revision_id", _required(self.revision_id, "revision_id"))
        object.__setattr__(self, "change_type", _required(self.change_type, "change_type"))
        object.__setattr__(self, "source_hash", _hash(self.source_hash, "source_hash"))
        object.__setattr__(self, "candidate_hash", _hash(self.candidate_hash, "candidate_hash"))
        if self.status not in _CANDIDATE_STATES:
            raise RevisionContractError("REVISION_CANDIDATE_STATUS_INVALID", "candidate status belongs to Revision, not Adoption.")


@dataclass(frozen=True)
class RevisionPatch:
    patch_id: str
    candidate_id: str
    location: Mapping[str, Any]
    before_text_hash: str
    after_text_hash: str
    risk: str
    dependencies: tuple[str, ...]
    conflicts: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "patch_id", _required(self.patch_id, "patch_id"))
        object.__setattr__(self, "candidate_id", _required(self.candidate_id, "candidate_id"))
        if not isinstance(self.location, Mapping) or not self.location:
            raise RevisionContractError("REVISION_PATCH_LOCATION_INVALID", "location is required.")
        object.__setattr__(self, "before_text_hash", _hash(self.before_text_hash, "before_text_hash"))
        object.__setattr__(self, "after_text_hash", _hash(self.after_text_hash, "after_text_hash"))
        if self.risk not in _RISK_LEVELS:
            raise RevisionContractError("REVISION_PATCH_RISK_INVALID", "patch risk is invalid.")
        object.__setattr__(self, "dependencies", tuple(_required(item, "dependencies") for item in self.dependencies))
        object.__setattr__(self, "conflicts", tuple(_required(item, "conflicts") for item in self.conflicts))
