"""Narrative Turn Preview contracts — read-only qualitative projection.

Phase 0D4-B: defines the immutable DTO for preview output.

Preview is NEVER persisted, never written to branch state, never
applied to Canon. It's a purely in-memory, qualitative projection
for user review only.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from core.contracts.narrative_turn import (
    NarrativeScope,
    NarrativeTurnError,
    SCHEMA_VERSION,
    ValidationStatus,
    _validate_datetime,
    _validate_fingerprint,
    _validate_id,
    _validate_int,
    _validate_non_empty_string,
    _require_tuple,
    _require_tuple_of_tuples,
)


_SUPPORTED_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION})


@dataclass(frozen=True)
class NarrativeTurnPreview:
    """Read-only qualitative preview of an action's likely consequences.

    This is NEVER persisted. It exists only in memory for the
    current session to help the user decide whether to confirm.

    Fields describe:
    - validation: the feasibility result (blocked/clarification/cost/allowed)
    - expected_costs: qualitative cost projections (not quantitative)
    - expected_risks: qualitative risk projections
    - likely_consequences: qualitative outcome descriptions (NOT facts)
    - evidence_codes: structured evidence codes supporting the preview
    - limitations: explicit statements of what the preview cannot predict
    """

    schema_version: str
    preview_id: str
    turn_id: str
    scope: NarrativeScope
    chapter_id: int
    action_source: str
    selected_action_id: str | None
    custom_action_text_hash: str | None
    validation_status: ValidationStatus
    expected_costs: tuple[tuple[str, str], ...]
    expected_risks: tuple[tuple[str, str], ...]
    likely_consequences: tuple[str, ...]
    evidence_codes: tuple[str, ...]
    limitations: tuple[str, ...]
    context_fingerprint: str
    preview_fingerprint: str
    generated_at: str

    def __post_init__(self) -> None:
        if self.schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
            raise NarrativeTurnError(
                NarrativeTurnError.INVALID_SCHEMA_VERSION,
                f"Unsupported schema version: {self.schema_version}",
            )
        _validate_id(self.preview_id, "preview_id")
        _validate_id(self.turn_id, "turn_id")
        if not isinstance(self.scope, NarrativeScope):
            raise NarrativeTurnError(
                NarrativeTurnError.INVALID_FIELD,
                "scope must be NarrativeScope",
            )
        _validate_int(self.chapter_id, "chapter_id")
        _validate_non_empty_string(self.action_source, "action_source")
        if self.selected_action_id is not None:
            _validate_id(self.selected_action_id, "selected_action_id")
        if self.custom_action_text_hash is not None:
            _validate_fingerprint(
                self.custom_action_text_hash, "custom_action_text_hash"
            )
        if not isinstance(self.validation_status, ValidationStatus):
            raise NarrativeTurnError(
                NarrativeTurnError.INVALID_ENUM,
                f"Invalid validation_status: {self.validation_status}",
            )
        object.__setattr__(
            self,
            "expected_costs",
            _require_tuple_of_tuples(self.expected_costs, "expected_costs"),
        )
        object.__setattr__(
            self,
            "expected_risks",
            _require_tuple_of_tuples(self.expected_risks, "expected_risks"),
        )
        object.__setattr__(
            self, "likely_consequences",
            _require_tuple(self.likely_consequences, "likely_consequences"),
        )
        object.__setattr__(
            self, "evidence_codes",
            _require_tuple(self.evidence_codes, "evidence_codes"),
        )
        object.__setattr__(
            self, "limitations",
            _require_tuple(self.limitations, "limitations"),
        )
        _validate_fingerprint(self.context_fingerprint, "context_fingerprint")
        _validate_fingerprint(self.preview_fingerprint, "preview_fingerprint")
        _validate_datetime(self.generated_at, "generated_at")


def compute_preview_fingerprint(
    *,
    turn_id: str,
    action_source: str,
    selected_action_id: str | None,
    custom_action_text_hash: str | None,
    validation_status: ValidationStatus,
    expected_costs: tuple[tuple[str, str], ...],
    expected_risks: tuple[tuple[str, str], ...],
    likely_consequences: tuple[str, ...],
    evidence_codes: tuple[str, ...],
    limitations: tuple[str, ...],
    context_fingerprint: str,
) -> str:
    """Compute a deterministic SHA-256 fingerprint of preview content.

    Same input → same fingerprint, always.
    """
    payload: dict[str, Any] = {
        "turn_id": turn_id,
        "action_source": action_source,
        "selected_action_id": selected_action_id,
        "custom_action_text_hash": custom_action_text_hash,
        "validation_status": validation_status.value,
        "expected_costs": [list(c) for c in expected_costs],
        "expected_risks": [list(r) for r in expected_risks],
        "likely_consequences": list(likely_consequences),
        "evidence_codes": sorted(evidence_codes),
        "limitations": sorted(limitations),
        "context_fingerprint": context_fingerprint,
    }
    return sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
