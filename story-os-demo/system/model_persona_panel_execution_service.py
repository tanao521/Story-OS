"""Bounded sequential orchestration for existing single-persona executions."""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from typing import Optional

from core.contracts.model_persona_execution import (
    ExecutionMode, ModelPersonaExecutionRequest, ModelRunStatus,
    compute_input_fingerprint,
)
from core.contracts.model_persona_panel_execution import (
    DEFAULT_MAX_PROVIDER_CALLS, MAX_PANEL_PERSONAS,
    ModelPersonaPanelExecutionPlan, ModelPersonaPanelExecutionRequest,
    ModelPersonaPanelExecutionResult, ModelPersonaPanelState,
    ModelPersonaPanelStatus, ModelPersonaPanelUsage,
    compute_panel_execution_fingerprint,
)
from core.contracts.reader_simulation import ReaderSimulationRequest, SimulationMode
from core.project_context import ProjectContext
from system.model_persona_execution_service import ModelPersonaExecutionService
from system.model_persona_panel_run_store import ModelPersonaPanelRunStore
from system.reader_persona_registry import ReaderPersonaRegistry, ReaderPersonaRegistryError
from system.reader_simulator import ReaderSimulatorService


class ModelPersonaPanelExecutionService:
    """Plans before executing; never performs parallel, retry, or synthesis calls."""

    def __init__(
        self, context: ProjectContext, *, provider=None, profiles=None,
        conservative_counter=None, conservative_policy=None,
    ) -> None:
        self.context = context
        self.registry = ReaderPersonaRegistry()
        self.child_service = ModelPersonaExecutionService(
            context, provider=provider, profiles=profiles,
            conservative_counter=conservative_counter,
            conservative_policy=conservative_policy,
        )
        self.simulator = ReaderSimulatorService(context)
        self.store = ModelPersonaPanelRunStore(context)

    def plan(self, request: ModelPersonaPanelExecutionRequest) -> ModelPersonaPanelExecutionPlan:
        requested = list(request.persona_ids) if isinstance(request.persona_ids, list) else []
        validation = self._validate_request(request)
        if validation is not None:
            return self._blocked_plan(request, requested, validation[0], validation[1])

        ordered = sorted(requested)
        profile = self.child_service._profiles.get(request.execution_profile)
        if profile is None:
            return self._blocked_plan(request, requested, "INVALID_PROFILE", "Unknown execution profile")
        if request.execution_mode == ExecutionMode.LIVE and not request.allow_model_call:
            return self._blocked_plan(request, ordered, "MODEL_CALL_BLOCKED", "Live model call requires explicit authorization")
        if request.execution_mode == ExecutionMode.LIVE and profile.provider_type == "mock" and self.child_service._provider is None:
            return self._blocked_plan(request, ordered, "PROVIDER_NOT_CONFIGURED", "Live provider is not configured")

        try:
            snapshot = self.simulator._build_snapshot(self._simulation_request(request))
            simulation_result = self.simulator._evaluate(snapshot)
        except Exception:
            return self._blocked_plan(request, ordered, "SOURCE_MISSING", "Source version is unavailable")
        if (
            request.expected_source_hash is not None
            and snapshot.source.source_hash != request.expected_source_hash
        ) or (
            request.expected_context_hash is not None
            and snapshot.context_hash != request.expected_context_hash
        ):
            return self._blocked_plan(request, ordered, "SOURCE_CHANGED_AFTER_CONSENT", "Source changed after Live consent was issued")

        provider = self.child_service._resolve_provider(request.execution_mode, profile)
        if provider is None:
            return self._blocked_plan(request, ordered, "PROVIDER_NOT_CONFIGURED", "Provider is not configured")
        profile_fingerprint = self.child_service._compute_profile_fingerprint(profile, provider)
        fingerprints: dict[str, str] = {}
        cache_hits: list[str] = []
        cache_misses: list[str] = []
        for persona_id in ordered:
            persona = self.registry.get_persona(persona_id)
            fingerprint = compute_input_fingerprint(
                source_hash=snapshot.source.source_hash,
                context_hash=snapshot.context_hash,
                reader_evaluator_version=simulation_result.evaluator_version,
                persona_fingerprint=persona.persona_fingerprint,
                prompt_template_version="model-persona-v1",
                provider_id=provider.provider_id,
                model_id=provider.model_id,
                generation_parameters=profile.generation_parameters,
                provider_config_fingerprint=profile_fingerprint,
            )
            fingerprints[persona_id] = fingerprint
            cached = None if request.force else self.child_service.store.find_by_fingerprint(fingerprint)
            if cached is not None and cached.status == ModelRunStatus.COMPLETED:
                cache_hits.append(persona_id)
            else:
                cache_misses.append(persona_id)

        expected = len(cache_misses) if request.execution_mode == ExecutionMode.LIVE else 0
        fingerprint = self.registry.calculate_persona_set_fingerprint(ordered)
        if expected > request.max_provider_calls:
            return ModelPersonaPanelExecutionPlan(
                requested_persona_ids=requested, ordered_persona_ids=ordered,
                cache_hit_persona_ids=cache_hits, cache_miss_persona_ids=cache_misses,
                blocked_persona_ids=[], expected_provider_calls=expected,
                max_provider_calls=request.max_provider_calls, execution_mode=request.execution_mode,
                execution_profile=request.execution_profile, can_execute=False,
                blocked_reason="Provider call budget exceeded", error_code="PANEL_CALL_BUDGET_EXCEEDED",
                source_hash=snapshot.source.source_hash, context_hash=snapshot.context_hash,
                reader_evaluator_version=simulation_result.evaluator_version,
                authoritative_panel_fingerprint=fingerprint, child_input_fingerprints=fingerprints,
            )
        return ModelPersonaPanelExecutionPlan(
            requested_persona_ids=requested, ordered_persona_ids=ordered,
            cache_hit_persona_ids=cache_hits, cache_miss_persona_ids=cache_misses,
            blocked_persona_ids=[], expected_provider_calls=expected,
            max_provider_calls=request.max_provider_calls, execution_mode=request.execution_mode,
            execution_profile=request.execution_profile, can_execute=True,
            source_hash=snapshot.source.source_hash, context_hash=snapshot.context_hash,
            reader_evaluator_version=simulation_result.evaluator_version,
            authoritative_panel_fingerprint=fingerprint, child_input_fingerprints=fingerprints,
        )

    def execute(self, request: ModelPersonaPanelExecutionRequest) -> ModelPersonaPanelExecutionResult:
        plan = self.plan(request)  # recompute immediately before any provider call
        created_at = datetime.now()
        panel_id = uuid.uuid4().hex[:16]
        profile = self.child_service._profiles.get(request.execution_profile)
        profile_version = profile.profile_version if profile else ""
        panel_fingerprint = compute_panel_execution_fingerprint(
            project_id=request.project_id, timeline_id=request.timeline_id, chapter_id=request.chapter_id,
            source_version_id=request.source_version_id,
            authoritative_panel_fingerprint=plan.authoritative_panel_fingerprint,
            ordered_persona_ids=plan.ordered_persona_ids,
            child_input_fingerprints=plan.child_input_fingerprints,
            execution_mode=request.execution_mode, execution_profile=request.execution_profile,
            max_provider_calls=request.max_provider_calls,
        )
        if not plan.can_execute:
            result = ModelPersonaPanelExecutionResult(
                panel_execution_id=panel_id, created_at=created_at, project_id=request.project_id,
                timeline_id=request.timeline_id, chapter_id=request.chapter_id, source_version_id=request.source_version_id,
                status=ModelPersonaPanelStatus.BLOCKED, execution_mode=request.execution_mode,
                execution_profile=request.execution_profile, execution_profile_version=profile_version,
                ordered_persona_ids=plan.ordered_persona_ids, child_execution_ids={}, child_statuses={},
                authoritative_panel_fingerprint=plan.authoritative_panel_fingerprint,
                panel_execution_fingerprint=panel_fingerprint, source_hash=plan.source_hash,
                context_hash=plan.context_hash, reader_evaluator_version=plan.reader_evaluator_version,
                child_input_fingerprints=plan.child_input_fingerprints,
                expected_provider_call_count=plan.expected_provider_calls, actual_provider_call_count=0,
                cache_hit_count=len(plan.cache_hit_persona_ids), cache_miss_count=len(plan.cache_miss_persona_ids),
                usage=None, usage_completeness="not_applicable", error_code=plan.error_code,
                completed_at=datetime.now(), live_ticket_id=request.live_ticket_id,
                profile_registry_revision=request.profile_registry_revision, budget_policy_id=request.budget_policy_id,
                budget_policy_revision=request.budget_policy_revision,
                counter_id=request.counter_id, counter_revision=request.counter_revision,
                counter_scope=request.counter_scope, canonical_payload_hash=request.canonical_payload_hash,
                thinking_mode=request.thinking_mode, structured_output_mode=request.structured_output_mode,
            )
            self.store.save_run(result)
            return result

        children = {}
        statuses = {}
        actual_calls = 0
        new_usages = []
        for persona_id in plan.ordered_persona_ids:  # intentionally sequential
            child_request = ModelPersonaExecutionRequest(
                project_id=request.project_id, timeline_id=request.timeline_id, chapter_id=request.chapter_id,
                persona_id=persona_id, source_version_id=request.source_version_id,
                execution_mode=request.execution_mode, execution_profile=request.execution_profile,
                allow_model_call=request.allow_model_call, force=request.force,
                expected_source_hash=request.expected_source_hash, expected_context_hash=request.expected_context_hash,
                max_input_tokens_per_call=request.max_input_tokens_per_call,
            )
            before = time.monotonic()
            child = self.child_service.execute(child_request)
            elapsed_ms = int((time.monotonic() - before) * 1000)
            children[persona_id] = child.execution_id
            statuses[persona_id] = child.status.value
            if (
                request.execution_mode == ExecutionMode.LIVE
                and child.cache_status == "miss"
                and child.status != ModelRunStatus.BLOCKED
            ):
                actual_calls += 1
                new_usages.append((child.usage, elapsed_ms))

        status = self._aggregate_status(statuses)
        usage, completeness = self._aggregate_usage(new_usages)
        child_results = [self.child_service.get_run(execution_id) for execution_id in children.values()]
        child_error_codes = [child.error_code for child in child_results if child is not None and child.error_code]
        source_changed = "SOURCE_CHANGED_AFTER_CONSENT" in child_error_codes
        result = ModelPersonaPanelExecutionResult(
            panel_execution_id=panel_id, created_at=created_at, project_id=request.project_id,
            timeline_id=request.timeline_id, chapter_id=request.chapter_id, source_version_id=request.source_version_id,
            status=status, execution_mode=request.execution_mode, execution_profile=request.execution_profile,
            execution_profile_version=profile_version, ordered_persona_ids=plan.ordered_persona_ids,
            child_execution_ids=children, child_statuses=statuses,
            authoritative_panel_fingerprint=plan.authoritative_panel_fingerprint,
            panel_execution_fingerprint=panel_fingerprint, source_hash=plan.source_hash,
            context_hash=plan.context_hash, reader_evaluator_version=plan.reader_evaluator_version,
            child_input_fingerprints=plan.child_input_fingerprints,
            expected_provider_call_count=plan.expected_provider_calls, actual_provider_call_count=actual_calls,
            cache_hit_count=sum(1 for value in children if value in plan.cache_hit_persona_ids),
            cache_miss_count=sum(1 for value in children if value not in plan.cache_hit_persona_ids),
            usage=usage, usage_completeness=completeness,
            error_code=("SOURCE_CHANGED_AFTER_CONSENT" if source_changed else self._panel_error_code(statuses, child_error_codes)),
            completed_at=datetime.now(), live_ticket_id=request.live_ticket_id,
            profile_registry_revision=request.profile_registry_revision, budget_policy_id=request.budget_policy_id,
            budget_policy_revision=request.budget_policy_revision,
            counter_id=request.counter_id, counter_revision=request.counter_revision,
            counter_scope=request.counter_scope, canonical_payload_hash=request.canonical_payload_hash,
            thinking_mode=request.thinking_mode, structured_output_mode=request.structured_output_mode,
        )
        self.store.save_run(result)
        return result

    def list_runs(self, chapter_id: Optional[int] = None) -> list[ModelPersonaPanelExecutionResult]:
        return self.store.list_runs(chapter_id)

    def get_run(self, panel_execution_id: str) -> Optional[ModelPersonaPanelExecutionResult]:
        return self.store.load_run(panel_execution_id)

    def check_staleness(self, panel_execution_id: str) -> ModelPersonaPanelState:
        run = self.store.load_run(panel_execution_id)
        if run is None:
            raise KeyError("PANEL_RUN_NOT_FOUND")
        try:
            request = ModelPersonaPanelExecutionRequest(
                project_id=run.project_id, timeline_id=run.timeline_id, chapter_id=run.chapter_id,
                persona_ids=run.ordered_persona_ids, source_version_id=run.source_version_id,
                execution_mode=run.execution_mode, execution_profile=run.execution_profile,
                allow_model_call=True, max_provider_calls=run.expected_provider_call_count,
            )
            snapshot = self.simulator._build_snapshot(self._simulation_request(request))
        except Exception:
            return ModelPersonaPanelState.SOURCE_MISSING
        if snapshot.source.source_hash != run.source_hash or snapshot.context_hash != run.context_hash:
            return ModelPersonaPanelState.STALE
        if self.registry.calculate_persona_set_fingerprint(run.ordered_persona_ids) != run.authoritative_panel_fingerprint:
            return ModelPersonaPanelState.STALE
        states = []
        for persona_id, execution_id in run.child_execution_ids.items():
            child = self.child_service.get_run(execution_id)
            if child is None:
                states.append("stale")
                continue
            if child.input_fingerprint != run.child_input_fingerprints.get(persona_id):
                states.append("stale")
            else:
                states.append("current")
        if states and all(state == "stale" for state in states):
            return ModelPersonaPanelState.STALE
        if any(state == "stale" for state in states):
            return ModelPersonaPanelState.PARTIALLY_STALE
        return ModelPersonaPanelState.CURRENT

    def _validate_request(self, request: ModelPersonaPanelExecutionRequest):
        if not isinstance(request.persona_ids, list) or not request.persona_ids:
            return "INVALID_PERSONA_SELECTION", "persona_ids must be a non-empty list"
        if len(request.persona_ids) > MAX_PANEL_PERSONAS:
            return "PERSONA_LIMIT_EXCEEDED", f"At most {MAX_PANEL_PERSONAS} personas are allowed"
        if any(not isinstance(persona_id, str) or not persona_id for persona_id in request.persona_ids):
            return "INVALID_PERSONA_SELECTION", "persona_ids must contain non-empty strings"
        if len(set(request.persona_ids)) != len(request.persona_ids):
            return "INVALID_PERSONA_SELECTION", "Duplicate persona_ids are not allowed"
        if request.execution_mode not in (ExecutionMode.MOCK, ExecutionMode.LIVE):
            return "INVALID_MODE", "Unknown execution mode"
        if not isinstance(request.max_provider_calls, int) or not 0 <= request.max_provider_calls <= MAX_PANEL_PERSONAS:
            return "PANEL_CALL_BUDGET_EXCEEDED", "max_provider_calls must be between 0 and 5"
        try:
            self.registry.validate_persona_ids(request.persona_ids)
        except ReaderPersonaRegistryError as exc:
            return "INVALID_PERSONA_SELECTION", str(exc)
        state_path = self.context.data_dir / "state.json"
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if request.project_id != state.get("project_id", "default-project"):
                return "PROJECT_MISMATCH", "Project does not match the current context"
            if request.timeline_id != state.get("timeline_id", "main"):
                return "TIMELINE_MISMATCH", "Timeline does not match the current context"
        return None

    @staticmethod
    def _simulation_request(request: ModelPersonaPanelExecutionRequest) -> ReaderSimulationRequest:
        return ReaderSimulationRequest(project_id=request.project_id, timeline_id=request.timeline_id,
            chapter_id=request.chapter_id, source_version_id=request.source_version_id, mode=SimulationMode.RULE)

    @staticmethod
    def _blocked_plan(request, ordered, error_code, reason):
        return ModelPersonaPanelExecutionPlan(
            requested_persona_ids=list(request.persona_ids) if isinstance(request.persona_ids, list) else [],
            ordered_persona_ids=ordered, cache_hit_persona_ids=[], cache_miss_persona_ids=[],
            blocked_persona_ids=ordered, expected_provider_calls=0,
            max_provider_calls=getattr(request, "max_provider_calls", DEFAULT_MAX_PROVIDER_CALLS),
            execution_mode=request.execution_mode, execution_profile=request.execution_profile,
            can_execute=False, blocked_reason=reason, error_code=error_code,
        )

    @staticmethod
    def _aggregate_status(statuses: dict[str, str]) -> ModelPersonaPanelStatus:
        values = list(statuses.values())
        successes = sum(value == ModelRunStatus.COMPLETED.value for value in values)
        invalids = sum(value == ModelRunStatus.INVALID_OUTPUT.value for value in values)
        blocked = sum(value == ModelRunStatus.BLOCKED.value for value in values)
        if values and blocked == len(values):
            return ModelPersonaPanelStatus.BLOCKED
        if successes == len(values):
            return ModelPersonaPanelStatus.COMPLETED
        if successes:
            return ModelPersonaPanelStatus.PARTIALLY_COMPLETED
        if values and invalids == len(values):
            return ModelPersonaPanelStatus.INVALID_OUTPUT
        return ModelPersonaPanelStatus.FAILED

    @staticmethod
    def _aggregate_usage(entries):
        if not entries:
            return None, "not_applicable"
        usages = [usage for usage, _ in entries]
        complete = all(usage is not None and usage.input_tokens is not None and usage.output_tokens is not None and usage.total_tokens is not None for usage in usages)
        def total(field):
            values = [getattr(usage, field) for usage in usages if usage is not None and getattr(usage, field) is not None]
            return sum(values) if values else None
        return ModelPersonaPanelUsage(input_tokens=total("input_tokens"), output_tokens=total("output_tokens"), total_tokens=total("total_tokens"), duration_ms=sum(duration for _, duration in entries)), ("complete" if complete else "partial")

    @staticmethod
    def _panel_error_code(statuses: dict[str, str], child_error_codes: Optional[list[str]] = None) -> Optional[str]:
        if all(status == ModelRunStatus.COMPLETED.value for status in statuses.values()):
            return None
        if statuses and all(status == ModelRunStatus.INVALID_OUTPUT.value for status in statuses.values()):
            return "MODEL_OUTPUT_INVALID"
        distinct = set(child_error_codes or [])
        if len(distinct) == 1:
            return next(iter(distinct))
        return "PROVIDER_ERROR"
