from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class SimulationMode(str, Enum):
    RULE = "rule"


class RetentionLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FlagSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FlagCategory(str, Enum):
    CONTENT = "content"
    STRUCTURE = "structure"
    STYLE = "style"
    CONTINUITY = "continuity"
    PACING = "pacing"
    CHARACTER = "character"
    READABILITY = "readability"


class RunStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"


class ResultState(str, Enum):
    CURRENT = "current"
    STALE = "stale"
    SOURCE_MISSING = "source_missing"


class StaleReason(str, Enum):
    SOURCE_CHANGED = "source_changed"
    CONTEXT_CHANGED = "context_changed"
    EVALUATOR_CHANGED = "evaluator_changed"


def to_public_score(normalized: float) -> float:
    return round(max(0.0, min(1.0, normalized)) * 100, 2)


def score_level(public_score: float) -> str:
    if public_score >= 85:
        return "excellent"
    if public_score >= 70:
        return "good"
    if public_score >= 55:
        return "fair"
    if public_score >= 40:
        return "poor"
    return "critical"


def retention_level(public_score: float) -> RetentionLevel:
    if public_score < 30:
        return RetentionLevel.LOW
    if public_score < 50:
        return RetentionLevel.MEDIUM
    if public_score < 75:
        return RetentionLevel.HIGH
    return RetentionLevel.CRITICAL


@dataclass(frozen=True)
class ReaderSimulationSource:
    chapter_id: int
    source_version_id: str
    source_type: str
    source_path: str
    source_hash: str
    title: str
    character_count: int
    resolved_at: datetime


@dataclass(frozen=True)
class ReaderSimulationSnapshot:
    snapshot_id: str
    snapshot_schema_version: str
    project_id: str
    timeline_id: str
    chapter_id: int
    source: ReaderSimulationSource
    story_spec: dict[str, Any] = field(default_factory=dict)
    chapter_plan: dict[str, Any] = field(default_factory=dict)
    chapter_summary: dict[str, Any] = field(default_factory=dict)
    pacing_data: dict[str, Any] = field(default_factory=dict)
    climax_data: dict[str, Any] = field(default_factory=dict)
    conflict_data: dict[str, Any] = field(default_factory=dict)
    continuity_state: dict[str, Any] = field(default_factory=dict)
    quality_evidence: dict[str, Any] = field(default_factory=dict)
    context_refs: dict[str, Any] = field(default_factory=dict)
    context_hash: str = ""
    missing_inputs: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True)
class EngagementScore:
    score: float
    level: str
    reasons: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RetentionRisk:
    score: float
    level: RetentionLevel
    risk_points: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EmotionCurveNode:
    position: float
    segment_label: str
    tension: float
    curiosity: float
    emotional_intensity: float
    payoff: float
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProblemFlag:
    code: str
    severity: FlagSeverity
    category: FlagCategory
    message: str
    evidence: list[str] = field(default_factory=list)
    source_span: Optional[tuple[int, int]] = None


@dataclass(frozen=True)
class OptimizationSuggestion:
    priority: int
    target: str
    reason: str
    expected_effect: str
    related_flag_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class NovelHealth:
    overall_score: float
    pacing: float
    clarity: float
    continuity: float
    conflict: float
    payoff: float
    style_stability: float
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReaderSimulationResult:
    engagement_score: EngagementScore
    retention_risk: RetentionRisk
    novel_health: NovelHealth
    reader_emotion_curve: list[EmotionCurveNode] = field(default_factory=list)
    problem_flags: list[ProblemFlag] = field(default_factory=list)
    optimization_suggestions: list[OptimizationSuggestion] = field(default_factory=list)
    evaluator_version: str = "reader-rule-v1"
    evaluated_at: datetime = field(default_factory=datetime.now)

    def deterministic_payload(self) -> dict[str, Any]:
        return {
            "engagement_score": {
                "score": self.engagement_score.score,
                "level": self.engagement_score.level,
                "reasons": self.engagement_score.reasons,
                "evidence": self.engagement_score.evidence,
            },
            "retention_risk": {
                "score": self.retention_risk.score,
                "level": self.retention_risk.level.value,
                "risk_points": self.retention_risk.risk_points,
            },
            "novel_health": {
                "overall_score": self.novel_health.overall_score,
                "pacing": self.novel_health.pacing,
                "clarity": self.novel_health.clarity,
                "continuity": self.novel_health.continuity,
                "conflict": self.novel_health.conflict,
                "payoff": self.novel_health.payoff,
                "style_stability": self.novel_health.style_stability,
                "warnings": self.novel_health.warnings,
            },
            "reader_emotion_curve": [
                {
                    "position": node.position,
                    "segment_label": node.segment_label,
                    "tension": node.tension,
                    "curiosity": node.curiosity,
                    "emotional_intensity": node.emotional_intensity,
                    "payoff": node.payoff,
                    "evidence": node.evidence,
                }
                for node in self.reader_emotion_curve
            ],
            "problem_flags": [
                {
                    "code": flag.code,
                    "severity": flag.severity.value,
                    "category": flag.category.value,
                    "message": flag.message,
                    "evidence": flag.evidence,
                    "source_span": flag.source_span,
                }
                for flag in self.problem_flags
            ],
            "optimization_suggestions": [
                {
                    "priority": s.priority,
                    "target": s.target,
                    "reason": s.reason,
                    "expected_effect": s.expected_effect,
                    "related_flag_codes": s.related_flag_codes,
                }
                for s in self.optimization_suggestions
            ],
            "evaluator_version": self.evaluator_version,
        }

    def deterministic_hash(self) -> str:
        payload = json.dumps(self.deterministic_payload(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ReaderSimulationRequest:
    project_id: str
    timeline_id: str
    chapter_id: int
    source_version_id: Optional[str] = None
    source_type: Optional[str] = None
    mode: SimulationMode = SimulationMode.RULE


@dataclass(frozen=True)
class ReaderSimulationRun:
    run_id: str
    run_schema_version: str
    status: RunStatus
    request: ReaderSimulationRequest
    snapshot: ReaderSimulationSnapshot
    result: Optional[ReaderSimulationResult] = None
    warnings: list[str] = field(default_factory=list)
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None