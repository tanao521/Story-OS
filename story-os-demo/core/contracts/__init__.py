"""Shared, dependency-light contracts for safe Story OS operations."""

from .project_ref import ProjectIdentityView, ProjectRef, ProjectRefError, normalize_project_id
from .adoption_contract import AdoptionContractError, AdoptionPreview, AdoptionRequest, AdoptionResult
from .revision_contract import RevisionCandidate, RevisionContractError, RevisionPatch, RevisionRequest
from .safety import (
    ErrorEnvelope,
    HashExpectation,
    HashGuard,
    HashValidationResult,
    OperationEnvelope,
    OperationEnvelopeError,
    SafeResult,
    SafetyContractError,
)

__all__ = [
    "ErrorEnvelope",
    "AdoptionContractError",
    "AdoptionPreview",
    "AdoptionRequest",
    "AdoptionResult",
    "HashExpectation",
    "HashGuard",
    "HashValidationResult",
    "OperationEnvelope",
    "OperationEnvelopeError",
    "ProjectIdentityView",
    "ProjectRef",
    "ProjectRefError",
    "RevisionCandidate",
    "RevisionContractError",
    "RevisionPatch",
    "RevisionRequest",
    "SafeResult",
    "SafetyContractError",
    "normalize_project_id",
]
