from __future__ import annotations

import json
import statistics
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from core.contracts.reader_persona import (
    AgreementLevel,
    FocusWeights,
    PanelAgreement,
    PanelConsensusFlag,
    PanelDisagreement,
    PanelMinorityFlag,
    PanelMode,
    PanelSuggestion,
    PersonaObservation,
    PersonaOptimizationPriority,
    PersonaPriorityFlag,
    PersonaResult,
    ReaderPanelRequest,
    ReaderPanelResult,
    ReaderPanelRun,
    RunStatus,
)
from core.contracts.reader_simulation import (
    FlagCategory,
    FlagSeverity,
    ReaderSimulationRequest,
    ReaderSimulationResult,
    SimulationMode,
    to_public_score,
)
from core.project_context import ProjectContext
from system.reader_persona_registry import ReaderPersonaRegistry, ReaderPersonaRegistryError
from system.reader_simulator import ReaderSimulatorService
from system.reader_panel_store import ReaderPanelStore


CONSENSUS_SUPPORT_THRESHOLD = 0.60


class ReaderPanelServiceError(Exception):
    pass


class ReaderPanelService:
    def __init__(self, context: ProjectContext) -> None:
        self.context = context
        self.persona_registry = ReaderPersonaRegistry()
        self.simulator = ReaderSimulatorService(context)
        self.store = ReaderPanelStore(context)

    def _get_project_state(self) -> dict[str, Any]:
        state_path = self.context.data_dir / "state.json"
        if state_path.exists():
            return json.loads(state_path.read_text(encoding="utf-8"))
        return {"project_id": "unknown", "timeline_id": "main"}

    def run_panel(self, request: ReaderPanelRequest) -> ReaderPanelRun:
        panel_run_id = str(uuid.uuid4()).replace("-", "")[:16]
        run = ReaderPanelRun(
            panel_run_id=panel_run_id,
            panel_run_schema_version="1.0",
            status=RunStatus.FAILED,
            request=request,
            base_simulation_run_id="",
            snapshot_id="",
            source_hash="",
            context_hash="",
            reader_evaluator_version="",
            panel_evaluator_version="panel-rule-v1",
            persona_set_fingerprint="",
            persona_versions={},
            created_at=datetime.now(),
        )

        try:
            self._validate_request(request)

            simulation_run = self._get_or_create_simulation(request)
            run.base_simulation_run_id = simulation_run.run_id
            run.snapshot_id = simulation_run.snapshot.snapshot_id
            run.source_hash = simulation_run.snapshot.source.source_hash
            run.context_hash = simulation_run.snapshot.context_hash
            run.reader_evaluator_version = simulation_run.result.evaluator_version

            persona_versions = self.persona_registry.get_persona_versions(request.persona_ids)
            persona_set_fingerprint = self.persona_registry.calculate_persona_set_fingerprint(request.persona_ids)
            run.persona_versions = persona_versions
            run.persona_set_fingerprint = persona_set_fingerprint

            persona_results = []
            for persona_id in sorted(request.persona_ids):
                persona = self.persona_registry.get_persona(persona_id)
                result = self._evaluate_persona(persona, simulation_run.result)
                persona_results.append(result)

            panel_result = self._aggregate_panel(persona_results, persona_set_fingerprint)

            run.result = panel_result
            run.status = RunStatus.COMPLETED
            run.completed_at = datetime.now()

        except Exception as exc:
            run.error = str(exc)
            run.status = RunStatus.FAILED

        self.store.save_run(run)
        return run

    def _validate_request(self, request: ReaderPanelRequest) -> None:
        if request.mode != PanelMode.DETERMINISTIC:
            raise ReaderPanelServiceError(f"Unsupported mode: {request.mode.value}")

        if len(request.persona_ids) < 2:
            raise ReaderPanelServiceError("At least 2 personas required")

        if len(request.persona_ids) > 5:
            raise ReaderPanelServiceError("Maximum 5 personas allowed")

        try:
            self.persona_registry.validate_persona_ids(request.persona_ids)
        except ReaderPersonaRegistryError as exc:
            raise ReaderPanelServiceError(str(exc)) from exc

    def _get_or_create_simulation(self, request: ReaderPanelRequest) -> Any:
        sim_request = ReaderSimulationRequest(
            project_id=request.project_id,
            timeline_id=request.timeline_id,
            chapter_id=request.chapter_id,
            source_version_id=request.source_version_id,
            mode=SimulationMode.RULE,
        )
        return self.simulator.run_simulation(sim_request)

    def _evaluate_persona(self, persona, base_result: ReaderSimulationResult) -> PersonaResult:
        normalized_weights = persona.focus_weights.normalized()
        weights_dict = normalized_weights.to_dict()

        base_health = base_result.novel_health
        raw_score = (
            base_health.pacing * weights_dict["pacing"]
            + base_health.clarity * weights_dict["clarity"]
            + base_health.conflict * weights_dict["conflict"]
            + base_health.continuity * weights_dict["continuity"]
            + base_health.payoff * weights_dict["payoff"]
            + base_health.style_stability * weights_dict["style_naturalness"]
            + (base_result.engagement_score.score * 0.1) * weights_dict["emotion"]
        )

        hook_bonus = self._calculate_hook_bonus(persona, base_result)
        raw_score = raw_score + hook_bonus

        engagement_score = max(0.0, min(100.0, raw_score))

        retention_risk = self._calculate_retention_risk(persona, base_result, engagement_score)

        priority_flags = self._build_priority_flags(persona, base_result)
        observations = self._build_observations(persona, base_result)
        optimization_priorities = self._build_optimization_priorities(persona, base_result)
        evidence_refs = self._collect_evidence_refs(base_result)

        return PersonaResult(
            persona_id=persona.persona_id,
            persona_version=persona.persona_version,
            persona_fingerprint=persona.persona_fingerprint,
            engagement_score=round(engagement_score, 2),
            retention_risk=round(retention_risk, 2),
            priority_flags=priority_flags,
            persona_observations=observations,
            optimization_priorities=optimization_priorities,
            evidence_refs=evidence_refs,
        )

    def _calculate_hook_bonus(self, persona, base_result: ReaderSimulationResult) -> float:
        weights = persona.focus_weights.normalized().to_dict()
        hook_weight = weights["hook"]

        hook_strength = 0.0
        for evidence in base_result.engagement_score.evidence:
            if "hook" in evidence.lower():
                try:
                    hook_strength = float(evidence.split("=")[1]) / 100.0
                except (IndexError, ValueError):
                    hook_strength = 0.5
                break

        return hook_strength * hook_weight * 15.0

    def _calculate_retention_risk(self, persona, base_result: ReaderSimulationResult, engagement_score: float) -> float:
        base_risk = base_result.retention_risk.score
        sensitivity = persona.sensitivity

        risk_multiplier = 1.0
        if base_risk > 50:
            risk_multiplier += (base_risk - 50) / 100 * sensitivity.risk_sensitivity

        if base_result.novel_health.pacing < 40:
            risk_multiplier += (40 - base_result.novel_health.pacing) / 100 * sensitivity.slow_opening_sensitivity

        if base_result.novel_health.continuity < 50:
            risk_multiplier += (50 - base_result.novel_health.continuity) / 100 * sensitivity.continuity_sensitivity

        adjusted_risk = base_risk * risk_multiplier

        if engagement_score < 40:
            adjusted_risk = adjusted_risk + 20

        clamped_risk = min(100.0, max(0.0, adjusted_risk))
        return clamped_risk

    def _build_priority_flags(self, persona, base_result: ReaderSimulationResult) -> List[PersonaPriorityFlag]:
        flags = []
        sensitivity = persona.sensitivity
        weights = persona.focus_weights.normalized().to_dict()

        for flag in base_result.problem_flags:
            base_severity = flag.severity.value

            weight_multiplier = 1.0
            if flag.category == FlagCategory.PACING:
                weight_multiplier = weights["pacing"] * 2
            elif flag.category == FlagCategory.CONTINUITY:
                weight_multiplier = weights["continuity"] * 2 * sensitivity.continuity_sensitivity
            elif flag.category == FlagCategory.CONTENT:
                weight_multiplier = weights["conflict"] * 2
            elif flag.category == FlagCategory.STYLE:
                weight_multiplier = weights["style_naturalness"] * 2
            elif flag.category == FlagCategory.CHARACTER:
                weight_multiplier = weights["emotion"] * 2

            severity_score = {"low": 1, "medium": 2, "high": 3}[base_severity]
            adjusted_severity_score = min(3, int(severity_score * weight_multiplier))
            persona_severity = ["low", "medium", "high"][adjusted_severity_score - 1]

            priority = adjusted_severity_score * 10
            if flag.category == FlagCategory.CONTINUITY and sensitivity.logic_gap_sensitivity > 0.7:
                priority += 5

            reason = self._generate_flag_reason(persona, flag)

            flags.append(PersonaPriorityFlag(
                flag_code=flag.code,
                base_severity=base_severity,
                persona_severity=persona_severity,
                priority=priority,
                reason=reason,
                evidence_refs=flag.evidence,
            ))

        return sorted(flags, key=lambda x: -x.priority)

    def _generate_flag_reason(self, persona, flag) -> str:
        archetype = persona.archetype.value

        if archetype == "hook_driven":
            return f"钩子驱动型读者对{flag.message}较为敏感"
        elif archetype == "character_empathy":
            return f"角色共情型读者关注{flag.message}"
        elif archetype == "pacing_sensitive":
            return f"节奏敏感型读者认为{flag.message}影响阅读体验"
        elif archetype == "continuity_sensitive":
            return f"连续性核心读者认为{flag.message}破坏一致性"
        elif archetype == "world_logic":
            return f"世界逻辑型读者发现{flag.message}存在逻辑问题"
        return f"{persona.display_name}关注{flag.message}"

    def _build_observations(self, persona, base_result: ReaderSimulationResult) -> List[PersonaObservation]:
        observations = []
        archetype = persona.archetype.value

        if base_result.novel_health.payoff < 50:
            observations.append(PersonaObservation(
                category="payoff",
                message=f"{persona.display_name}认为当前回报不足",
                evidence_refs=[f"payoff={base_result.novel_health.payoff}"],
            ))

        if base_result.novel_health.pacing < 40:
            observations.append(PersonaObservation(
                category="pacing",
                message=f"{persona.display_name}认为节奏偏慢",
                evidence_refs=[f"pacing={base_result.novel_health.pacing}"],
            ))

        if base_result.novel_health.continuity < 50:
            observations.append(PersonaObservation(
                category="continuity",
                message=f"{persona.display_name}发现连续性问题",
                evidence_refs=[f"continuity={base_result.novel_health.continuity}"],
            ))

        if "钩子" in str(base_result.engagement_score.reasons):
            observations.append(PersonaObservation(
                category="hook",
                message=f"{persona.display_name}关注章末钩子强度",
                evidence_refs=base_result.engagement_score.evidence,
            ))

        return observations

    def _build_optimization_priorities(self, persona, base_result: ReaderSimulationResult) -> List[PersonaOptimizationPriority]:
        priorities = []
        health = base_result.novel_health

        if health.payoff < 50:
            priorities.append(PersonaOptimizationPriority(
                target="increase_payoff",
                priority=10,
                reason=f"{persona.display_name}建议增强回报感",
                evidence_refs=[f"payoff={health.payoff}"],
            ))

        if health.pacing < 40:
            priorities.append(PersonaOptimizationPriority(
                target="adjust_pacing",
                priority=8,
                reason=f"{persona.display_name}建议调整节奏",
                evidence_refs=[f"pacing={health.pacing}"],
            ))

        if health.continuity < 50:
            priorities.append(PersonaOptimizationPriority(
                target="resolve_continuity_gap",
                priority=8,
                reason=f"{persona.display_name}建议解决连续性问题",
                evidence_refs=[f"continuity={health.continuity}"],
            ))

        if health.clarity < 50:
            priorities.append(PersonaOptimizationPriority(
                target="increase_clarity",
                priority=6,
                reason=f"{persona.display_name}建议提高清晰度",
                evidence_refs=[f"clarity={health.clarity}"],
            ))

        return sorted(priorities, key=lambda x: -x.priority)

    def _collect_evidence_refs(self, base_result: ReaderSimulationResult) -> List[str]:
        refs = []
        refs.extend(base_result.engagement_score.evidence)
        for flag in base_result.problem_flags:
            refs.extend(flag.evidence)
        return sorted(list(set(refs)))

    def _aggregate_panel(self, persona_results: List[PersonaResult], persona_set_fingerprint: str) -> ReaderPanelResult:
        scores = [pr.engagement_score for pr in persona_results]
        retention_risks = [pr.retention_risk for pr in persona_results]

        panel_score = round(sum(scores) / len(scores), 2)
        panel_retention_risk = round(sum(retention_risks) / len(retention_risks), 2)

        score_spread = round(max(scores) - min(scores), 2) if len(scores) > 1 else 0.0
        score_stddev = round(statistics.stdev(scores) if len(scores) > 1 else 0.0, 2)
        agreement_level = self._calculate_agreement_level(score_spread, score_stddev)

        shared_flags = self._find_shared_flags(persona_results)

        agreement = PanelAgreement(
            score_spread=score_spread,
            score_stddev=score_stddev,
            agreement_level=agreement_level,
            shared_flag_codes=shared_flags,
        )

        disagreements = self._find_disagreements(persona_results)
        consensus_flags = self._find_consensus_flags(persona_results)
        minority_flags = self._find_minority_flags(persona_results)
        panel_suggestions = self._aggregate_suggestions(persona_results)

        return ReaderPanelResult(
            panel_score=panel_score,
            panel_retention_risk=panel_retention_risk,
            persona_results=persona_results,
            agreement=agreement,
            disagreements=disagreements,
            consensus_flags=consensus_flags,
            minority_flags=minority_flags,
            panel_suggestions=panel_suggestions,
            panel_evaluator_version="panel-rule-v1",
            persona_set_fingerprint=persona_set_fingerprint,
            evaluated_at=datetime.now(),
        )

    def _calculate_agreement_level(self, spread: float, stddev: float) -> AgreementLevel:
        if spread <= 10 and stddev <= 5:
            return AgreementLevel.STRONG
        elif spread <= 25 and stddev <= 12:
            return AgreementLevel.MODERATE
        elif spread <= 40 and stddev <= 20:
            return AgreementLevel.WEAK
        else:
            return AgreementLevel.POLARIZED

    def _find_shared_flags(self, persona_results: List[PersonaResult]) -> List[str]:
        flag_sets = [set(f.flag_code for f in pr.priority_flags) for pr in persona_results]
        if not flag_sets:
            return []
        common = set.intersection(*flag_sets)
        return sorted(list(common))

    def _find_disagreements(self, persona_results: List[PersonaResult]) -> List[PanelDisagreement]:
        disagreements = []

        all_flag_codes = set()
        for pr in persona_results:
            all_flag_codes.update(f.flag_code for f in pr.priority_flags)

        for flag_code in all_flag_codes:
            positions = {}
            severity_counts = {}
            for pr in persona_results:
                flag = next((f for f in pr.priority_flags if f.flag_code == flag_code), None)
                if flag:
                    positions[pr.persona_id] = flag.persona_severity
                    severity_counts[pr.persona_id] = {"low": 1, "medium": 2, "high": 3}[flag.persona_severity]
                else:
                    positions[pr.persona_id] = "neutral"
                    severity_counts[pr.persona_id] = 0

            if len(set(positions.values())) > 1:
                score_range = (min(severity_counts.values()), max(severity_counts.values()))
                if score_range[1] - score_range[0] >= 2:
                    explanation = self._generate_disagreement_explanation(persona_results, flag_code)
                    disagreements.append(PanelDisagreement(
                        topic=flag_code,
                        persona_positions=positions,
                        score_range=score_range,
                        explanation=explanation,
                    ))

        return disagreements

    def _generate_disagreement_explanation(self, persona_results: List[PersonaResult], flag_code: str) -> str:
        high_personas = []
        low_personas = []

        for pr in persona_results:
            flag = next((f for f in pr.priority_flags if f.flag_code == flag_code), None)
            if flag:
                if flag.persona_severity == "high":
                    high_personas.append(pr.persona_id)
                elif flag.persona_severity in ("low", "medium"):
                    low_personas.append(pr.persona_id)

        if high_personas and low_personas:
            return f"{', '.join(high_personas)}认为问题严重，{', '.join(low_personas)}认为影响较小"
        return ""

    def _find_consensus_flags(self, persona_results: List[PersonaResult]) -> List[PanelConsensusFlag]:
        all_flag_codes = set()
        for pr in persona_results:
            all_flag_codes.update(f.flag_code for f in pr.priority_flags)

        consensus_flags = []
        total_personas = len(persona_results)

        for flag_code in all_flag_codes:
            supporting = []
            max_severity = "low"

            for pr in persona_results:
                flag = next((f for f in pr.priority_flags if f.flag_code == flag_code), None)
                if flag and flag.persona_severity in ("high", "medium"):
                    supporting.append(pr.persona_id)
                    if {"low": 1, "medium": 2, "high": 3}[flag.persona_severity] > {"low": 1, "medium": 2, "high": 3}[max_severity]:
                        max_severity = flag.persona_severity

            if len(supporting) / total_personas >= CONSENSUS_SUPPORT_THRESHOLD:
                first_flag = next(
                    (f for pr in persona_results for f in pr.priority_flags if f.flag_code == flag_code),
                    None
                )
                evidence_refs = first_flag.evidence_refs if first_flag else []
                consensus_flags.append(PanelConsensusFlag(
                    flag_code=flag_code,
                    severity=max_severity,
                    supporting_personas=supporting,
                    evidence_refs=evidence_refs,
                ))

        return sorted(consensus_flags, key=lambda x: {"low": 1, "medium": 2, "high": 3}[x.severity], reverse=True)

    def _find_minority_flags(self, persona_results: List[PersonaResult]) -> List[PanelMinorityFlag]:
        all_flag_codes = set()
        for pr in persona_results:
            all_flag_codes.update(f.flag_code for f in pr.priority_flags)

        minority_flags = []
        total_personas = len(persona_results)

        consensus_codes = set(f.flag_code for f in self._find_consensus_flags(persona_results))

        for flag_code in all_flag_codes:
            if flag_code in consensus_codes:
                continue

            supporting = []
            opposing_or_neutral = []
            max_severity = "low"

            for pr in persona_results:
                flag = next((f for f in pr.priority_flags if f.flag_code == flag_code), None)
                if flag and flag.persona_severity in ("high", "medium"):
                    supporting.append(pr.persona_id)
                    if {"low": 1, "medium": 2, "high": 3}[flag.persona_severity] > {"low": 1, "medium": 2, "high": 3}[max_severity]:
                        max_severity = flag.persona_severity
                else:
                    opposing_or_neutral.append(pr.persona_id)

            support_ratio = len(supporting) / total_personas
            if 0 < support_ratio < CONSENSUS_SUPPORT_THRESHOLD:
                first_flag = next(
                    (f for pr in persona_results for f in pr.priority_flags if f.flag_code == flag_code),
                    None
                )
                evidence_refs = first_flag.evidence_refs if first_flag else []
                minority_flags.append(PanelMinorityFlag(
                    flag_code=flag_code,
                    severity=max_severity,
                    supporting_personas=supporting,
                    opposing_or_neutral_personas=opposing_or_neutral,
                    evidence_refs=evidence_refs,
                ))

        return sorted(minority_flags, key=lambda x: -len(x.supporting_personas))

    def _aggregate_suggestions(self, persona_results: List[PersonaResult]) -> List[PanelSuggestion]:
        suggestion_map: Dict[str, Dict[str, Any]] = {}

        for pr in persona_results:
            for opt in pr.optimization_priorities:
                if opt.target not in suggestion_map:
                    suggestion_map[opt.target] = {
                        "priority": 0,
                        "reason": "",
                        "source_personas": [],
                        "evidence_refs": [],
                        "count": 0,
                    }
                suggestion_map[opt.target]["priority"] += opt.priority
                suggestion_map[opt.target]["source_personas"].append(pr.persona_id)
                suggestion_map[opt.target]["evidence_refs"].extend(opt.evidence_refs)
                suggestion_map[opt.target]["count"] += 1

        suggestions = []
        for target, data in suggestion_map.items():
            priority = data["priority"]
            if data["count"] >= 2:
                priority += 5

            reasons = {pr.persona_id: "" for pr in persona_results}
            for pr in persona_results:
                for opt in pr.optimization_priorities:
                    if opt.target == target:
                        reasons[pr.persona_id] = opt.reason
                        break

            reasons_str = "; ".join(r for r in reasons.values() if r)

            suggestions.append(PanelSuggestion(
                target=target,
                priority=priority,
                reason=reasons_str,
                source_personas=data["source_personas"],
                evidence_refs=sorted(list(set(data["evidence_refs"]))),
            ))

        return sorted(suggestions, key=lambda x: -x.priority)