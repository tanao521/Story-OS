"""Read-only deterministic aggregation for model-persona panel reviews."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any, Optional

from core.contracts.model_persona_execution import (
    ModelRunState,
    ModelRunStatus,
    PROMPT_TEMPLATE_VERSION,
    compute_input_fingerprint,
)
from core.contracts.model_persona_panel_review import (
    ModelPersonaPanelReview,
    PanelReviewStaleness,
    PanelReviewStatus,
    PersonaReviewCard,
    PersonaReviewDisplayStatus,
)
from core.contracts.reader_persona import PersonaResult, RunStatus
from core.contracts.reader_simulation import ReaderSimulationRequest, SimulationMode
from core.project_context import ProjectContext
from system.model_persona_execution_service import ModelPersonaExecutionService
from system.model_persona_panel_run_store import ModelPersonaPanelRunStore
from system.reader_panel_store import ReaderPanelStore
from system.reader_persona_registry import ReaderPersonaRegistry
from system.reader_simulator import ReaderSimulatorService


class ModelPersonaPanelReviewServiceError(Exception):
    def __init__(self, message: str, *, code: str = "PANEL_REVIEW_ERROR") -> None:
        super().__init__(message)
        self.code = code


_WARNING_ORDER = (
    "PARTIAL_PANEL_RESULT",
    "STALE_MODEL_RESULT",
    "INVALID_MODEL_OUTPUT",
    "INVALID_EVIDENCE",
    "MISSING_PERSONA_RESULT",
    "PROVIDER_FAILURE",
    "USAGE_INCOMPLETE",
    "SOURCE_VERSION_MISMATCH",
)


class ModelPersonaPanelReviewService:
    """Build a review response without invoking providers or writing records."""

    def __init__(self, context: ProjectContext, *, provider: Any = None) -> None:
        self.context = context
        self.registry = ReaderPersonaRegistry()
        self.panel_store = ModelPersonaPanelRunStore(context)
        self.reader_panel_store = ReaderPanelStore(context)
        self.child_service = ModelPersonaExecutionService(context, provider=provider)
        self.simulator = ReaderSimulatorService(context)

    def review(
        self,
        *,
        chapter_id: int,
        source_version_id: Optional[str] = None,
        panel_execution_id: Optional[str] = None,
    ) -> ModelPersonaPanelReview:
        project_id, timeline_id = self._project_identity()
        candidates = [
            run
            for run in self.panel_store.list_runs(chapter_id)
            if run.project_id == project_id
            and run.timeline_id == timeline_id
            and (source_version_id is None or run.source_version_id == source_version_id)
        ]

        source = self._current_source(chapter_id, source_version_id)
        if panel_execution_id:
            selected = next((run for run in candidates if run.panel_execution_id == panel_execution_id), None)
            if selected is None:
                raise ModelPersonaPanelReviewServiceError("Panel run not found", code="PANEL_RUN_NOT_FOUND")
            selection_reason = "explicit_panel_execution_id"
        else:
            selected, selection_reason = self._select_run(candidates, source)
        authority_run = self._select_authority_run(
            chapter_id=chapter_id,
            project_id=project_id,
            timeline_id=timeline_id,
            source_version_id=source_version_id,
            persona_ids=selected.ordered_persona_ids if selected else None,
            panel_fingerprint=selected.authoritative_panel_fingerprint if selected else None,
        )

        panel_state = PanelReviewStaleness.SOURCE_MISSING if source is None else PanelReviewStaleness.NOT_RUN
        panel_state_reason = "not_run"
        child_runs: dict[str, Any] = {}
        child_states: dict[str, str] = {}
        if selected is not None:
            panel_state = self._panel_staleness(selected, source, authority_run)
            panel_state_reason = panel_state.value
            for persona_id, execution_id in selected.child_execution_ids.items():
                child = self.child_service.get_run(execution_id)
                child_runs[persona_id] = child
                child_states[persona_id] = self._child_staleness(selected, child, source)

        authority_results = self._authority_results(authority_run)
        ordered_ids = (
            list(selected.ordered_persona_ids)
            if selected is not None
            else self._authority_order(authority_run)
        )
        cards = self._build_cards(
            ordered_ids=ordered_ids,
            authority_results=authority_results,
            authority_run=authority_run,
            selected=selected,
            child_runs=child_runs,
            child_states=child_states,
        )
        warnings = self._warnings(
            selected=selected,
            authority_run=authority_run,
            source=source,
            panel_state=panel_state,
            child_runs=child_runs,
            child_states=child_states,
            cards=cards,
        )
        review_status = self._review_status(
            selected=selected,
            source=source,
            panel_state=panel_state,
            authority_run=authority_run,
            child_states=child_states,
        )
        summary = {
            "review_status": review_status.value,
            "selection_reason": selection_reason,
            "selected_panel_execution_id": selected.panel_execution_id if selected else None,
            "selected_run_status": selected.status.value if selected else None,
            "selected_run_staleness": panel_state.value,
            "persona_count": len(cards),
            "warning_count": len(warnings),
        }

        selected_run_payload = self._selected_run_payload(selected, panel_state)
        effective_source_version_id = source_version_id
        if effective_source_version_id is None:
            if selected is not None:
                effective_source_version_id = selected.source_version_id
            elif authority_run is not None:
                effective_source_version_id = authority_run.request.source_version_id
        return ModelPersonaPanelReview(
            project_id=project_id,
            timeline_id=timeline_id,
            chapter_id=chapter_id,
            source_version_id=effective_source_version_id,
            review_status=review_status,
            summary=summary,
            selection_reason=selection_reason,
            selected_panel_execution_id=selected.panel_execution_id if selected else None,
            selected_run_status=selected.status.value if selected else None,
            selected_run_staleness=panel_state,
            authoritative_panel=self._authority_payload(authority_run, ordered_ids),
            selected_panel_run=selected_run_payload,
            persona_reviews=cards,
            agreement_groups=self._agreement_groups(cards),
            conflict_groups=self._conflict_groups(cards),
            evidence_summary=self._evidence_summary(cards),
            execution_summary=self._execution_summary(selected, child_runs),
            usage_summary=self._usage_summary(selected),
            staleness_summary=self._staleness_summary(panel_state, child_states),
            warnings=warnings,
        )

    def _project_identity(self) -> tuple[str, str]:
        state_path = self.context.data_dir / "state.json"
        if not state_path.exists():
            return "default-project", "main"
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return "default-project", "main"
        return str(state.get("project_id", "default-project")), str(state.get("timeline_id", "main"))

    def _current_source(self, chapter_id: int, source_version_id: Optional[str]) -> Optional[dict[str, Any]]:
        try:
            request = ReaderSimulationRequest(
                project_id=self._project_identity()[0], timeline_id=self._project_identity()[1],
                chapter_id=chapter_id, source_version_id=source_version_id, mode=SimulationMode.RULE,
            )
            snapshot = self.simulator._build_snapshot(request)
            result = self.simulator._evaluate(snapshot)
            return {
                "source_hash": snapshot.source.source_hash,
                "context_hash": snapshot.context_hash,
                "reader_evaluator_version": result.evaluator_version,
                "snapshot": snapshot,
            }
        except Exception:
            return None

    def _select_run(self, candidates: list[Any], source: Optional[dict[str, Any]]) -> tuple[Any | None, str]:
        if not candidates:
            return None, "not_run"
        ranked: list[tuple[tuple[int, int, float], Any, PanelReviewStaleness]] = []
        for run in candidates:
            state = self._panel_staleness(run, source, None)
            state_rank = 0 if state == PanelReviewStaleness.CURRENT else 1 if state != PanelReviewStaleness.SOURCE_MISSING else 2
            status_rank = {"completed": 0, "partially_completed": 1, "failed": 2, "blocked": 3}.get(run.status.value, 4)
            if run.status.value in {"failed", "blocked"}:
                state_rank += 2
            ranked.append(((state_rank, status_rank, -run.created_at.timestamp()), run, state))
        ranked.sort(key=lambda item: item[0])
        _, selected, state = ranked[0]
        if state == PanelReviewStaleness.CURRENT:
            if selected.status.value == "completed":
                return selected, "current_completed_run"
            if selected.status.value == "partially_completed":
                return selected, "current_partially_completed_run"
            return selected, "current_fallback_run"
        if state == PanelReviewStaleness.STALE:
            return selected, "latest_stale_run"
        return selected, "latest_available_run"

    def _select_authority_run(
        self, *, chapter_id: int, project_id: str, timeline_id: str,
        source_version_id: Optional[str], persona_ids: Optional[list[str]],
        panel_fingerprint: Optional[str],
    ) -> Any:
        runs = [
            run for run in self.reader_panel_store.list_runs(chapter_id)
            if run.status == RunStatus.COMPLETED
            and run.request.project_id == project_id
            and run.request.timeline_id == timeline_id
            and (source_version_id is None or run.request.source_version_id == source_version_id)
        ]
        if panel_fingerprint:
            exact = [run for run in runs if run.persona_set_fingerprint == panel_fingerprint]
            if exact:
                runs = exact
        elif persona_ids:
            fingerprint = self.registry.calculate_persona_set_fingerprint(persona_ids)
            exact = [run for run in runs if run.persona_set_fingerprint == fingerprint]
            if exact:
                runs = exact
        return max(runs, key=lambda run: run.created_at) if runs else None

    @staticmethod
    def _authority_order(authority_run: Any) -> list[str]:
        if authority_run is None:
            return []
        return [result.persona_id for result in (authority_run.result.persona_results if authority_run.result else [])]

    @staticmethod
    def _authority_results(authority_run: Any) -> dict[str, PersonaResult]:
        if authority_run is None or authority_run.result is None:
            return {}
        return {result.persona_id: result for result in authority_run.result.persona_results}

    def _panel_staleness(self, run: Any, source: Optional[dict[str, Any]], authority_run: Any) -> PanelReviewStaleness:
        if source is None:
            # Selection ranking cannot read the current source; defer the public
            # source_missing result to the main review path.
            return PanelReviewStaleness.CURRENT
        if run.source_hash != source["source_hash"] or run.context_hash != source["context_hash"]:
            return PanelReviewStaleness.STALE
        try:
            if self.registry.calculate_persona_set_fingerprint(run.ordered_persona_ids) != run.authoritative_panel_fingerprint:
                return PanelReviewStaleness.STALE
        except Exception:
            return PanelReviewStaleness.STALE
        if authority_run is not None and authority_run.persona_set_fingerprint != run.authoritative_panel_fingerprint:
            return PanelReviewStaleness.STALE
        states = [self._child_staleness(run, self.child_service.get_run(execution_id), source) for execution_id in run.child_execution_ids.values()]
        if states and all(state == "stale" for state in states):
            return PanelReviewStaleness.STALE
        if any(state == "stale" for state in states):
            return PanelReviewStaleness.PARTIALLY_STALE
        return PanelReviewStaleness.CURRENT

    def _child_staleness(self, panel_run: Any, child: Any, source: Optional[dict[str, Any]]) -> str:
        if child is None or source is None:
            return "stale"
        try:
            persona = self.registry.get_persona(child.persona_id)
            profile = self.child_service._profiles.get(child.execution_profile or panel_run.execution_profile)
            if profile is None:
                return "stale"
            mode = child.execution_mode or panel_run.execution_mode
            provider = self.child_service._resolve_provider(mode, profile)
            provider_id = getattr(provider, "provider_id", profile.provider_id)
            model_id = getattr(provider, "model_id", profile.model_id)
            provider_config_fingerprint = self.child_service._compute_profile_fingerprint(profile, provider)
            current_input = compute_input_fingerprint(
                source_hash=source["source_hash"], context_hash=source["context_hash"],
                reader_evaluator_version=source["reader_evaluator_version"],
                persona_fingerprint=persona.persona_fingerprint,
                prompt_template_version=PROMPT_TEMPLATE_VERSION,
                provider_id=provider_id, model_id=model_id,
                generation_parameters=profile.generation_parameters,
                provider_config_fingerprint=provider_config_fingerprint,
            )
            if current_input != child.input_fingerprint:
                return "stale"
            result = self.child_service.check_staleness(
                child.execution_id,
                current_source_hash=source["source_hash"],
                current_context_hash=source["context_hash"],
                current_reader_evaluator_version=source["reader_evaluator_version"],
                current_persona_fingerprint=persona.persona_fingerprint,
                current_prompt_template_version=PROMPT_TEMPLATE_VERSION,
                current_provider_id=provider_id,
                current_model_id=model_id,
                current_generation_parameters=profile.generation_parameters,
                current_provider_config_fingerprint=provider_config_fingerprint,
            )
            return "current" if result.state == ModelRunState.CURRENT else "stale"
        except Exception:
            return "stale"

    def _build_cards(
        self, *, ordered_ids: list[str], authority_results: dict[str, PersonaResult],
        authority_run: Any, selected: Any, child_runs: dict[str, Any], child_states: dict[str, str],
    ) -> list[PersonaReviewCard]:
        authority_order = self._authority_order(authority_run)
        order_lookup = {persona_id: index for index, persona_id in enumerate(authority_order)}
        cards: list[PersonaReviewCard] = []
        for index, persona_id in enumerate(ordered_ids):
            persona = self.registry.get_persona(persona_id)
            result = authority_results.get(persona_id)
            child = child_runs.get(persona_id)
            child_state = child_states.get(persona_id, "current")
            authoritative = self._authoritative_card(result, persona, order_lookup.get(persona_id, index))
            supplement = self._model_supplement(child, child_state)
            status, warnings = self._display_status(selected, child, child_state, supplement)
            cards.append(PersonaReviewCard(
                persona_id=persona_id, persona_name=persona.display_name,
                persona_order=order_lookup.get(persona_id, index),
                authoritative=authoritative, model_supplement=supplement,
                display_status=status, warnings=warnings,
            ))
        return cards

    @staticmethod
    def _authoritative_card(result: Optional[PersonaResult], persona: Any, order: int) -> dict[str, Any]:
        if result is None:
            return {
                "persona_id": persona.persona_id, "persona_name": persona.display_name,
                "persona_order": order, "engagement_score": None, "retention_risk": None,
                "priority_flags": [], "persona_weight": persona.focus_weights.normalized().to_dict(),
                "panel_rank": order, "authoritative_status": "not_available",
            }
        return {
            "persona_id": result.persona_id, "persona_name": persona.display_name,
            "persona_order": order, "engagement_score": result.engagement_score,
            "retention_risk": result.retention_risk,
            "priority_flags": [
                {
                    "flag_code": flag.flag_code, "base_severity": flag.base_severity,
                    "persona_severity": flag.persona_severity, "priority": flag.priority,
                    "evidence_refs": sorted(set(flag.evidence_refs)),
                }
                for flag in sorted(result.priority_flags, key=lambda item: (item.flag_code, item.priority))
            ],
            "persona_weight": persona.focus_weights.normalized().to_dict(),
            "panel_rank": order, "authoritative_status": "completed",
        }

    def _model_supplement(self, child: Any, child_state: str) -> dict[str, Any]:
        if child is None:
            return {
                "model_run_status": "not_run", "model_feedback": None, "evidence_references": [],
                "grounding_status": "not_available", "cache_status": "not_run", "execution_id": None,
                "execution_profile": None, "provider_identity": None, "usage": None,
                "staleness": "not_run",
            }
        feedback = None
        evidence: set[str] = set()
        if child.model_feedback:
            feedback = {
                "reader_reaction": child.model_feedback.reader_reaction,
                "strengths": [self._feedback_item(item) for item in child.model_feedback.strengths],
                "concerns": [self._feedback_item(item) for item in child.model_feedback.concerns],
                "reader_questions": [self._feedback_item(item) for item in child.model_feedback.reader_questions],
                "optimization_directions": [self._feedback_item(item) for item in child.model_feedback.optimization_directions],
                "overall_impression": child.model_feedback.overall_impression,
            }
            for items in (child.model_feedback.strengths, child.model_feedback.concerns, child.model_feedback.reader_questions, child.model_feedback.optimization_directions):
                for item in items:
                    evidence.update(item.evidence_refs)
        grounding = child.grounding_report
        if grounding is not None:
            if grounding.invalid_reference_count:
                grounding_status = "invalid"
            elif grounding.valid_reference_count and grounding.unsupported_item_count == 0:
                grounding_status = "complete"
            elif grounding.valid_reference_count:
                grounding_status = "partial"
            else:
                grounding_status = "none"
        else:
            grounding_status = "not_available"
        usage = child.usage.to_dict() if child.usage else None
        return {
            "model_run_status": child.status.value,
            "model_feedback": feedback,
            "evidence_references": sorted(evidence),
            "grounding_status": grounding_status,
            "grounding_report": {
                "valid_reference_count": grounding.valid_reference_count,
                "invalid_reference_count": grounding.invalid_reference_count,
                "unsupported_item_count": grounding.unsupported_item_count,
                "grounding_coverage": grounding.grounding_coverage,
            } if grounding else None,
            "cache_status": child.cache_status,
            "execution_id": child.execution_id,
            "execution_profile": child.execution_profile,
            "provider_identity": {"provider_id": child.provider_id, "model_id": child.model_id},
            "usage": usage,
            "staleness": child_state,
        }

    @staticmethod
    def _feedback_item(item: Any) -> dict[str, Any]:
        return {"message": item.message, "evidence_refs": sorted(set(item.evidence_refs)), "confidence": item.confidence.value}

    @staticmethod
    def _display_status(selected: Any, child: Any, child_state: str, supplement: dict[str, Any]) -> tuple[PersonaReviewDisplayStatus, list[str]]:
        warnings: list[str] = []
        if child_state == "stale":
            warnings.append("STALE_MODEL_RESULT")
            return PersonaReviewDisplayStatus.STALE, warnings
        if child is None:
            return (PersonaReviewDisplayStatus.BLOCKED if selected and selected.status.value == "blocked" else PersonaReviewDisplayStatus.NOT_RUN), warnings
        status = child.status.value
        if status == ModelRunStatus.COMPLETED.value:
            return (PersonaReviewDisplayStatus.CACHED if child.cache_status == "hit" else PersonaReviewDisplayStatus.COMPLETE), warnings
        if status == ModelRunStatus.INVALID_OUTPUT.value:
            warnings.append("INVALID_MODEL_OUTPUT")
            return PersonaReviewDisplayStatus.INVALID_OUTPUT, warnings
        if status == ModelRunStatus.BLOCKED.value:
            return PersonaReviewDisplayStatus.BLOCKED, warnings
        warnings.append("PROVIDER_FAILURE")
        return PersonaReviewDisplayStatus.PROVIDER_FAILED, warnings

    @staticmethod
    def _selected_run_payload(run: Any, state: PanelReviewStaleness) -> Optional[dict[str, Any]]:
        if run is None:
            return None
        return {
            "panel_execution_id": run.panel_execution_id,
            "status": run.status.value,
            "staleness": state.value,
            "created_at": run.created_at.isoformat(),
            "project_id": run.project_id,
            "timeline_id": run.timeline_id,
            "chapter_id": run.chapter_id,
            "source_version_id": run.source_version_id,
            "ordered_persona_ids": list(run.ordered_persona_ids),
            "execution_mode": run.execution_mode.value,
            "execution_profile": run.execution_profile,
        }

    @staticmethod
    def _authority_payload(authority_run: Any, ordered_ids: list[str]) -> dict[str, Any]:
        if authority_run is None:
            return {"ordered_persona_ids": list(ordered_ids), "status": "not_available", "panel_run_id": None}
        return {
            "ordered_persona_ids": list(ordered_ids), "status": authority_run.status.value,
            "panel_run_id": authority_run.panel_run_id,
            "source_hash": authority_run.source_hash,
            "context_hash": authority_run.context_hash,
            "reader_evaluator_version": authority_run.reader_evaluator_version,
            "panel_evaluator_version": authority_run.panel_evaluator_version,
            "fingerprint": authority_run.persona_set_fingerprint,
        }

    @staticmethod
    def _execution_summary(selected: Any, child_runs: dict[str, Any]) -> dict[str, Any]:
        if selected is None:
            return {
                "requested_persona_count": 0, "completed_persona_count": 0, "cached_persona_count": 0,
                "failed_persona_count": 0, "invalid_output_count": 0, "blocked_persona_count": 0,
                "expected_provider_call_count": 0, "actual_provider_call_count": 0,
            }
        values = list(child_runs.values())
        return {
            "requested_persona_count": len(selected.ordered_persona_ids),
            "completed_persona_count": sum(1 for child in values if child and child.status == ModelRunStatus.COMPLETED),
            "cached_persona_count": sum(1 for child in values if child and child.cache_status == "hit"),
            "failed_persona_count": sum(1 for child in values if child and child.status == ModelRunStatus.FAILED),
            "invalid_output_count": sum(1 for child in values if child and child.status == ModelRunStatus.INVALID_OUTPUT),
            "blocked_persona_count": sum(1 for child in values if child and child.status == ModelRunStatus.BLOCKED),
            "expected_provider_call_count": selected.expected_provider_call_count,
            "actual_provider_call_count": selected.actual_provider_call_count,
        }

    @staticmethod
    def _usage_summary(selected: Any) -> dict[str, Any]:
        if selected is None or selected.usage is None:
            return {"input_tokens": None, "output_tokens": None, "total_tokens": None, "duration_ms": None, "usage_completeness": "not_applicable"}
        return {
            **selected.usage.to_dict(), "usage_completeness": selected.usage_completeness,
        }

    @staticmethod
    def _staleness_summary(panel_state: PanelReviewStaleness, child_states: dict[str, str]) -> dict[str, Any]:
        current = sum(value == "current" for value in child_states.values())
        stale = sum(value == "stale" for value in child_states.values())
        return {
            "status": panel_state.value, "current_persona_count": current,
            "stale_persona_count": stale,
            "stale_persona_ids": [key for key, value in child_states.items() if value == "stale"],
        }

    @staticmethod
    def _evidence_summary(cards: list[PersonaReviewCard]) -> dict[str, Any]:
        refs: set[str] = set()
        covered: set[str] = set()
        grounding_status_counts: dict[str, int] = defaultdict(int)
        valid = invalid = unknown = 0
        for card in cards:
            supplement = card.model_supplement
            grounding_status_counts[str(supplement.get("grounding_status", "not_available"))] += 1
            card_refs = set(supplement.get("evidence_references", []))
            if card_refs:
                covered.add(card.persona_id)
                refs.update(card_refs)
            grounding = supplement.get("grounding_report") or {}
            valid += int(grounding.get("valid_reference_count", 0) or 0)
            invalid += int(grounding.get("invalid_reference_count", 0) or 0)
            unknown += int(grounding.get("unsupported_item_count", 0) or 0)
        total = max(len(refs), valid + invalid + unknown)
        uncovered = [card.persona_id for card in cards if card.persona_id not in covered]
        if total == 0:
            coverage = "not_applicable"
        elif invalid and not valid:
            coverage = "invalid"
        elif valid == total:
            coverage = "complete"
        elif valid:
            coverage = "partial"
        else:
            coverage = "none"
        return {
            "total_references": total, "valid_references": valid,
            "invalid_references": invalid, "unknown_references": unknown,
            "unique_evidence_count": len(refs), "covered_persona_count": len(covered),
            "uncovered_persona_ids": uncovered, "coverage_status": coverage,
            "grounding_status_counts": dict(sorted(grounding_status_counts.items())),
        }

    @staticmethod
    def _stable_id(prefix: str, payload: Any) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return f"{prefix}-{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:12]}"

    def _agreement_groups(self, cards: list[PersonaReviewCard]) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str], list[tuple[PersonaReviewCard, Any]]] = defaultdict(list)
        for card in cards:
            for flag in card.authoritative.get("priority_flags", []):
                grouped[("issue_code", str(flag.get("flag_code", "")))].append((card, flag))
            for evidence_id in card.model_supplement.get("evidence_references", []):
                grouped[("evidence_id", str(evidence_id))].append((card, evidence_id))
        groups: list[dict[str, Any]] = []
        for (category, key), entries in sorted(grouped.items()):
            persona_ids = sorted({entry[0].persona_id for entry in entries}, key=lambda pid: next(card.persona_order for card in cards if card.persona_id == pid))
            if len(persona_ids) < 2:
                continue
            evidence_ids = sorted({ref for _, value in entries for ref in (value.get("evidence_refs", []) if isinstance(value, dict) else [value])})
            severity = None
            if category == "issue_code":
                severity_values = {value.get("persona_severity") for _, value in entries}
                severity = next(iter(severity_values)) if len(severity_values) == 1 else None
            groups.append({
                "agreement_id": self._stable_id("agreement", [category, key]),
                "category": category, "persona_ids": persona_ids,
                "evidence_ids": evidence_ids, "target_location": None,
                "severity": severity,
                "source_fields": ["authoritative.priority_flags.flag_code"] if category == "issue_code" else ["model_supplement.evidence_references"],
            })
        return groups

    def _conflict_groups(self, cards: list[PersonaReviewCard]) -> list[dict[str, Any]]:
        by_code: dict[str, list[tuple[PersonaReviewCard, dict[str, Any]]]] = defaultdict(list)
        for card in cards:
            for flag in card.authoritative.get("priority_flags", []):
                by_code[str(flag.get("flag_code", ""))].append((card, flag))
        groups: list[dict[str, Any]] = []
        for code, entries in sorted(by_code.items()):
            if len({item[0].persona_id for item in entries}) < 2:
                continue
            severities = {str(flag.get("persona_severity", "")) for _, flag in entries}
            evidence_sets = {tuple(sorted(flag.get("evidence_refs", []))) for _, flag in entries}
            risks = {self._risk_band(card.authoritative.get("retention_risk")) for card, _ in entries}
            conflict_types: list[tuple[str, Any]] = []
            if len(severities) > 1:
                conflict_types.append(("severity_conflict", sorted(severities)))
            if len(evidence_sets) > 1:
                conflict_types.append(("evidence_conflict", [list(value) for value in sorted(evidence_sets)]))
            if len(risks) > 1:
                conflict_types.append(("risk_conflict", sorted(risks)))
            for conflict_type, compared_values in conflict_types:
                persona_ids = [card.persona_id for card, _ in sorted(entries, key=lambda item: item[0].persona_order)]
                evidence_ids = sorted({ref for _, flag in entries for ref in flag.get("evidence_refs", [])})
                groups.append({
                    "conflict_id": self._stable_id("conflict", [code, conflict_type, persona_ids, compared_values]),
                    "conflict_type": conflict_type, "persona_ids": persona_ids,
                    "compared_values": compared_values, "evidence_ids": evidence_ids,
                    "target_location": None, "resolution_status": "unresolved",
                })
        return groups

    @staticmethod
    def _risk_band(value: Any) -> str:
        if value is None:
            return "unknown"
        number = float(value)
        return "low" if number < 33 else "medium" if number < 66 else "high"

    def _warnings(self, *, selected: Any, authority_run: Any, source: Optional[dict[str, Any]], panel_state: PanelReviewStaleness, child_runs: dict[str, Any], child_states: dict[str, str], cards: list[PersonaReviewCard]) -> list[str]:
        warnings: set[str] = set()
        if selected and selected.status.value == "partially_completed":
            warnings.add("PARTIAL_PANEL_RESULT")
        if panel_state in (PanelReviewStaleness.STALE, PanelReviewStaleness.PARTIALLY_STALE):
            warnings.add("STALE_MODEL_RESULT")
        if source is None:
            return ["SOURCE_VERSION_MISMATCH"]
        if selected and any(child is None for child in child_runs.values()):
            warnings.add("MISSING_PERSONA_RESULT")
        for card in cards:
            warnings.update(card.warnings)
            if card.model_supplement.get("grounding_status") == "invalid":
                warnings.add("INVALID_EVIDENCE")
        if selected and selected.usage_completeness == "partial":
            warnings.add("USAGE_INCOMPLETE")
        if authority_run is None and selected is not None:
            warnings.add("MISSING_PERSONA_RESULT")
        return [code for code in _WARNING_ORDER if code in warnings]

    @staticmethod
    def _review_status(*, selected: Any, source: Optional[dict[str, Any]], panel_state: PanelReviewStaleness, authority_run: Any, child_states: dict[str, str]) -> PanelReviewStatus:
        if source is None:
            return PanelReviewStatus.SOURCE_MISSING
        if selected is None:
            return PanelReviewStatus.NOT_RUN
        if panel_state == PanelReviewStaleness.STALE:
            return PanelReviewStatus.STALE
        if selected.status.value in {"failed", "blocked"}:
            return PanelReviewStatus.FAILED
        if selected.status.value == "partially_completed" or panel_state == PanelReviewStaleness.PARTIALLY_STALE or authority_run is None or any(value == "stale" for value in child_states.values()):
            return PanelReviewStatus.PARTIAL
        return PanelReviewStatus.READY
