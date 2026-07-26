from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class PersonaArchetype(str, Enum):
    HOOK_DRIVEN = "hook_driven"
    CHARACTER_EMPATHY = "character_empathy"
    PACING_SENSITIVE = "pacing_sensitive"
    CONTINUITY_SENSITIVE = "continuity_sensitive"
    WORLD_LOGIC = "world_logic"


class PersonaSource(str, Enum):
    BUILTIN = "builtin"


class PanelMode(str, Enum):
    DETERMINISTIC = "deterministic"


class AgreementLevel(str, Enum):
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    POLARIZED = "polarized"


class PanelStaleReason(str, Enum):
    SOURCE_CHANGED = "source_changed"
    CONTEXT_CHANGED = "context_changed"
    READER_EVALUATOR_CHANGED = "reader_evaluator_changed"
    PANEL_EVALUATOR_CHANGED = "panel_evaluator_changed"
    PERSONA_CHANGED = "persona_changed"
    PERSONA_SET_CHANGED = "persona_set_changed"


VALID_FOCUS_DIMENSIONS = {
    "hook",
    "pacing",
    "conflict",
    "clarity",
    "continuity",
    "payoff",
    "style_naturalness",
    "emotion",
}


@dataclass(frozen=True)
class FocusWeights:
    hook: float = 0.125
    pacing: float = 0.125
    conflict: float = 0.125
    clarity: float = 0.125
    continuity: float = 0.125
    payoff: float = 0.125
    style_naturalness: float = 0.125
    emotion: float = 0.125

    def to_dict(self) -> dict[str, float]:
        return {
            "hook": self.hook,
            "pacing": self.pacing,
            "conflict": self.conflict,
            "clarity": self.clarity,
            "continuity": self.continuity,
            "payoff": self.payoff,
            "style_naturalness": self.style_naturalness,
            "emotion": self.emotion,
        }

    def normalized(self) -> "FocusWeights":
        total = sum(self.to_dict().values())
        if total == 0:
            return FocusWeights()
        return FocusWeights(**{k: v / total for k, v in self.to_dict().items()})


@dataclass(frozen=True)
class PersonaSensitivity:
    risk_sensitivity: float = 0.5
    repetition_sensitivity: float = 0.5
    slow_opening_sensitivity: float = 0.5
    continuity_sensitivity: float = 0.5
    logic_gap_sensitivity: float = 0.5

    def to_dict(self) -> dict[str, float]:
        return {
            "risk_sensitivity": self.risk_sensitivity,
            "repetition_sensitivity": self.repetition_sensitivity,
            "slow_opening_sensitivity": self.slow_opening_sensitivity,
            "continuity_sensitivity": self.continuity_sensitivity,
            "logic_gap_sensitivity": self.logic_gap_sensitivity,
        }


@dataclass(frozen=True)
class PersonaPreferences:
    preferred_pacing: str = "balanced"
    preferred_dialogue_density: str = "medium"
    preferred_emotion_intensity: str = "moderate"
    preferred_hook_strength: str = "strong"

    def to_dict(self) -> dict[str, str]:
        return {
            "preferred_pacing": self.preferred_pacing,
            "preferred_dialogue_density": self.preferred_dialogue_density,
            "preferred_emotion_intensity": self.preferred_emotion_intensity,
            "preferred_hook_strength": self.preferred_hook_strength,
        }


@dataclass(frozen=True)
class ReaderPersona:
    persona_id: str
    persona_schema_version: str
    persona_version: str
    display_name: str
    description: str
    archetype: PersonaArchetype
    focus_weights: FocusWeights
    sensitivity: PersonaSensitivity
    preferences: PersonaPreferences
    enabled: bool = True
    source: PersonaSource = PersonaSource.BUILTIN

    @property
    def persona_fingerprint(self) -> str:
        payload = {
            "persona_id": self.persona_id,
            "persona_schema_version": self.persona_schema_version,
            "persona_version": self.persona_version,
            "archetype": self.archetype.value,
            "focus_weights": self.focus_weights.normalized().to_dict(),
            "sensitivity": self.sensitivity.to_dict(),
            "preferences": self.preferences.to_dict(),
            "enabled": self.enabled,
            "source": self.source.value,
        }
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PersonaPriorityFlag:
    flag_code: str
    base_severity: str
    persona_severity: str
    priority: int
    reason: str
    evidence_refs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PersonaObservation:
    category: str
    message: str
    evidence_refs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PersonaOptimizationPriority:
    target: str
    priority: int
    reason: str
    evidence_refs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PersonaResult:
    persona_id: str
    persona_version: str
    persona_fingerprint: str
    engagement_score: float
    retention_risk: float
    priority_flags: list[PersonaPriorityFlag] = field(default_factory=list)
    persona_observations: list[PersonaObservation] = field(default_factory=list)
    optimization_priorities: list[PersonaOptimizationPriority] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)

    def deterministic_payload(self) -> dict[str, Any]:
        return {
            "persona_id": self.persona_id,
            "persona_version": self.persona_version,
            "persona_fingerprint": self.persona_fingerprint,
            "engagement_score": self.engagement_score,
            "retention_risk": self.retention_risk,
            "priority_flags": [
                {
                    "flag_code": f.flag_code,
                    "base_severity": f.base_severity,
                    "persona_severity": f.persona_severity,
                    "priority": f.priority,
                    "reason": f.reason,
                    "evidence_refs": f.evidence_refs,
                }
                for f in sorted(self.priority_flags, key=lambda x: (x.priority, x.flag_code))
            ],
            "persona_observations": [
                {"category": o.category, "message": o.message, "evidence_refs": o.evidence_refs}
                for o in sorted(self.persona_observations, key=lambda x: x.category)
            ],
            "optimization_priorities": [
                {"target": o.target, "priority": o.priority, "reason": o.reason, "evidence_refs": o.evidence_refs}
                for o in sorted(self.optimization_priorities, key=lambda x: x.priority)
            ],
            "evidence_refs": sorted(self.evidence_refs),
        }

    def deterministic_hash(self) -> str:
        payload = json.dumps(self.deterministic_payload(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PanelAgreement:
    score_spread: float
    score_stddev: float
    agreement_level: AgreementLevel
    shared_flag_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PanelDisagreement:
    topic: str
    persona_positions: dict[str, str]
    score_range: tuple[float, float]
    evidence_refs: list[str] = field(default_factory=list)
    explanation: str = ""


@dataclass(frozen=True)
class PanelConsensusFlag:
    flag_code: str
    severity: str
    supporting_personas: list[str]
    evidence_refs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PanelMinorityFlag:
    flag_code: str
    severity: str
    supporting_personas: list[str]
    opposing_or_neutral_personas: list[str]
    evidence_refs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PanelSuggestion:
    target: str
    priority: int
    reason: str
    source_personas: list[str]
    evidence_refs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReaderPanelResult:
    panel_score: float
    panel_retention_risk: float
    persona_results: list[PersonaResult]
    agreement: PanelAgreement
    disagreements: list[PanelDisagreement] = field(default_factory=list)
    consensus_flags: list[PanelConsensusFlag] = field(default_factory=list)
    minority_flags: list[PanelMinorityFlag] = field(default_factory=list)
    panel_suggestions: list[PanelSuggestion] = field(default_factory=list)
    panel_evaluator_version: str = "panel-rule-v1"
    persona_set_fingerprint: str = ""
    evaluated_at: datetime = field(default_factory=datetime.now)

    def deterministic_payload(self) -> dict[str, Any]:
        return {
            "panel_score": self.panel_score,
            "panel_retention_risk": self.panel_retention_risk,
            "persona_results": [
                pr.deterministic_payload()
                for pr in sorted(self.persona_results, key=lambda x: x.persona_id)
            ],
            "agreement": {
                "score_spread": self.agreement.score_spread,
                "score_stddev": self.agreement.score_stddev,
                "agreement_level": self.agreement.agreement_level.value,
                "shared_flag_codes": sorted(self.agreement.shared_flag_codes),
            },
            "disagreements": [
                {
                    "topic": d.topic,
                    "persona_positions": dict(sorted(d.persona_positions.items())),
                    "score_range": list(d.score_range),
                    "evidence_refs": sorted(d.evidence_refs),
                    "explanation": d.explanation,
                }
                for d in sorted(self.disagreements, key=lambda x: x.topic)
            ],
            "consensus_flags": [
                {
                    "flag_code": f.flag_code,
                    "severity": f.severity,
                    "supporting_personas": sorted(f.supporting_personas),
                    "evidence_refs": sorted(f.evidence_refs),
                }
                for f in sorted(self.consensus_flags, key=lambda x: x.flag_code)
            ],
            "minority_flags": [
                {
                    "flag_code": f.flag_code,
                    "severity": f.severity,
                    "supporting_personas": sorted(f.supporting_personas),
                    "opposing_or_neutral_personas": sorted(f.opposing_or_neutral_personas),
                    "evidence_refs": sorted(f.evidence_refs),
                }
                for f in sorted(self.minority_flags, key=lambda x: x.flag_code)
            ],
            "panel_suggestions": [
                {
                    "target": s.target,
                    "priority": s.priority,
                    "reason": s.reason,
                    "source_personas": sorted(s.source_personas),
                    "evidence_refs": sorted(s.evidence_refs),
                }
                for s in sorted(self.panel_suggestions, key=lambda x: (-x.priority, x.target))
            ],
            "panel_evaluator_version": self.panel_evaluator_version,
            "persona_set_fingerprint": self.persona_set_fingerprint,
        }

    def deterministic_hash(self) -> str:
        payload = json.dumps(self.deterministic_payload(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ReaderPanelRequest:
    project_id: str
    timeline_id: str
    chapter_id: int
    source_version_id: Optional[str] = None
    persona_ids: list[str] = field(default_factory=list)
    mode: PanelMode = PanelMode.DETERMINISTIC


@dataclass
class ReaderPanelRun:
    panel_run_id: str
    panel_run_schema_version: str
    status: RunStatus
    request: ReaderPanelRequest
    base_simulation_run_id: str
    snapshot_id: str
    source_hash: str
    context_hash: str
    reader_evaluator_version: str
    panel_evaluator_version: str
    persona_set_fingerprint: str
    persona_versions: dict[str, str]
    result: Optional[ReaderPanelResult] = None
    warnings: list[str] = field(default_factory=list)
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None


class RunStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"


class ResultState(str, Enum):
    CURRENT = "current"
    STALE = "stale"
    SOURCE_MISSING = "source_missing"


class StalenessResult:
    def __init__(
        self,
        state: ResultState,
        stale_reasons: list[PanelStaleReason] | None = None,
    ) -> None:
        self.state = state
        self.stale_reasons = stale_reasons or []