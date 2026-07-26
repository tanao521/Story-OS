"""Deterministic, read-only review model for a model-persona panel."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


PANEL_REVIEW_SCHEMA_VERSION = "1.0"
PANEL_REVIEW_EVALUATOR_VERSION = "panel-review-v1"


class PanelReviewStatus(str, Enum):
    READY = "ready"
    PARTIAL = "partial"
    NOT_RUN = "not_run"
    FAILED = "failed"
    STALE = "stale"
    SOURCE_MISSING = "source_missing"


class PanelReviewStaleness(str, Enum):
    CURRENT = "current"
    PARTIALLY_STALE = "partially_stale"
    STALE = "stale"
    SOURCE_MISSING = "source_missing"
    NOT_RUN = "not_run"


class PersonaReviewDisplayStatus(str, Enum):
    COMPLETE = "complete"
    CACHED = "cached"
    PARTIAL = "partial"
    INVALID_OUTPUT = "invalid_output"
    PROVIDER_FAILED = "provider_failed"
    BLOCKED = "blocked"
    NOT_RUN = "not_run"
    STALE = "stale"


@dataclass(frozen=True)
class PersonaReviewCard:
    persona_id: str
    persona_name: str
    persona_order: int
    authoritative: dict[str, Any]
    model_supplement: dict[str, Any]
    display_status: PersonaReviewDisplayStatus
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "persona_id": self.persona_id,
            "persona_name": self.persona_name,
            "persona_order": self.persona_order,
            "authoritative": self.authoritative,
            "model_supplement": self.model_supplement,
            "display_status": self.display_status.value,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ModelPersonaPanelReview:
    project_id: str
    timeline_id: str
    chapter_id: int
    source_version_id: Optional[str]
    review_status: PanelReviewStatus
    summary: dict[str, Any]
    selection_reason: str
    selected_panel_execution_id: Optional[str]
    selected_run_status: Optional[str]
    selected_run_staleness: PanelReviewStaleness
    authoritative_panel: dict[str, Any]
    selected_panel_run: Optional[dict[str, Any]]
    persona_reviews: list[PersonaReviewCard]
    agreement_groups: list[dict[str, Any]]
    conflict_groups: list[dict[str, Any]]
    evidence_summary: dict[str, Any]
    execution_summary: dict[str, Any]
    usage_summary: dict[str, Any]
    staleness_summary: dict[str, Any]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PANEL_REVIEW_SCHEMA_VERSION,
            "evaluator_version": PANEL_REVIEW_EVALUATOR_VERSION,
            "project_id": self.project_id,
            "timeline_id": self.timeline_id,
            "chapter_id": self.chapter_id,
            "source_version_id": self.source_version_id,
            "review_status": self.review_status.value,
            "summary": self.summary,
            "selection_reason": self.selection_reason,
            "selected_panel_execution_id": self.selected_panel_execution_id,
            "selected_run_status": self.selected_run_status,
            "selected_run_staleness": self.selected_run_staleness.value,
            "authoritative_panel": self.authoritative_panel,
            "selected_panel_run": self.selected_panel_run,
            "persona_reviews": [card.to_dict() for card in self.persona_reviews],
            "agreement_groups": self.agreement_groups,
            "conflict_groups": self.conflict_groups,
            "evidence_summary": self.evidence_summary,
            "execution_summary": self.execution_summary,
            "usage_summary": self.usage_summary,
            "staleness_summary": self.staleness_summary,
            "warnings": list(self.warnings),
        }
