"""Service for model-backed single Reader Persona execution.

Orchestrates: deterministic simulation → deterministic persona → bounded prompt →
single provider call → strict validation → immutable run record.

Default policy: NO retry, NO automatic repair call. At most 1 provider call per request.

Production safety:
- mock mode → _MockProvider only
- live mode → Execution Profile Registry resolves real provider
- live without provider config → blocked (PROVIDER_NOT_CONFIGURED)
- no silent fallback to mock
"""
from __future__ import annotations

import json
import hashlib
import os
import re
import time
import uuid
from datetime import datetime
from typing import Any, Optional, Protocol

from core.contracts.model_persona_execution import (
    MODEL_PERSONA_RUN_SCHEMA_VERSION,
    PROMPT_TEMPLATE_VERSION,
    AuthoritativeScores,
    ConfidenceLevel,
    ExecutionMode,
    ExecutionProfile,
    FeedbackItem,
    GenerationParameters,
    GroundingReport,
    ModelPersonaExecutionRequest,
    ModelPersonaExecutionResult,
    ModelPersonaFeedback,
    ModelRunStatus,
    StructuredOutputMode,
    TokenUsage,
    compute_input_fingerprint,
    compute_provider_config_fingerprint,
)
from core.contracts.reader_persona import PersonaResult, ReaderPanelRequest
from core.contracts.reader_simulation import (
    ReaderSimulationRequest,
    SimulationMode,
)
from core.project_context import ProjectContext
from system.model_persona_prompt_builder import (
    BuiltPrompt,
    MAX_ITEMS_PER_CATEGORY,
    MAX_MESSAGE_CHARS,
    MAX_OVERALL_IMPRESSION_CHARS,
    MAX_REACTION_CHARS,
    ModelPersonaPromptBuilder,
)
from system.model_persona_run_store import ModelPersonaRunStore
from system.conservative_token_budget import (
    CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE,
    ConservativeTextCounter,
    ConservativeTokenBudgetPolicy,
    evaluate_conservative_request,
)
from system.model_persona_provider_openai import (
    OpenAICompatibleModelPersonaProvider,
    OpenAIProviderAuthError,
    OpenAIProviderError,
    OpenAIProviderRateLimitError,
    OpenAIProviderTimeoutError,
    normalized_endpoint_identity,
)
from system.reader_panel_service import ReaderPanelService
from system.reader_persona_registry import ReaderPersonaRegistry, ReaderPersonaRegistryError


FORBIDDEN_SCORE_FIELDS = {
    "new_engagement_score",
    "adjusted_retention_risk",
    "panel_score",
    "engagement_score",
    "retention_risk",
}

MOCK_PROFILE = ExecutionProfile(
    profile_id="mock",
    profile_version="1.0",
    provider_type="mock",
    provider_id="mock",
    model_id="mock-persona-v1",
    generation_parameters=GenerationParameters(
        temperature=0.0,
        max_output_tokens=1024,
        timeout_seconds=60,
    ),
    timeout_seconds=60,
    structured_output_mode=StructuredOutputMode.NONE,
    enabled=True,
    endpoint_identity="",
)


def _build_default_profiles() -> dict[str, ExecutionProfile]:
    profiles: dict[str, ExecutionProfile] = {
        "mock": MOCK_PROFILE,
        "default": MOCK_PROFILE,
    }

    env_provider = os.environ.get("STORYOS_MODEL_PROVIDER", "")
    env_base_url = os.environ.get("STORYOS_MODEL_BASE_URL", "")
    env_model = os.environ.get("STORYOS_MODEL", "")
    env_key_env = os.environ.get("STORYOS_MODEL_KEY_ENV", "STORYOS_MODEL_API_KEY")
    env_api_key = os.environ.get(env_key_env, "")

    if env_provider == "openai_compatible" and env_base_url and env_model:
        enabled = bool(env_api_key)
        endpoint_identity = normalized_endpoint_identity(env_base_url)
        live_profile = ExecutionProfile(
            profile_id="default",
            profile_version="1.0",
            provider_type="openai_compatible",
            provider_id="openai_compatible",
            model_id=env_model,
            generation_parameters=GenerationParameters(
                temperature=0.0,
                max_output_tokens=1024,
                timeout_seconds=60,
            ),
            timeout_seconds=60,
            structured_output_mode=StructuredOutputMode.JSON,
            enabled=enabled,
            endpoint_identity=endpoint_identity,
        )
        profiles["default"] = live_profile
        profiles["live"] = live_profile

    return profiles


EXECUTION_PROFILES: dict[str, ExecutionProfile] = _build_default_profiles()


def _is_profile_enabled(profile: ExecutionProfile) -> bool:
    if not profile.enabled:
        return False
    if profile.provider_type == "mock":
        return True
    if profile.provider_type == "openai_compatible":
        return True
    return False


class ModelPersonaProviderError(Exception):
    code = "PROVIDER_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class ProviderTimeoutError(ModelPersonaProviderError):
    code = "PROVIDER_TIMEOUT"


class ProviderAuthError(ModelPersonaProviderError):
    code = "PROVIDER_AUTH_ERROR"


class ProviderRateLimitError(ModelPersonaProviderError):
    code = "PROVIDER_RATE_LIMITED"


class ProviderNotConfiguredError(ModelPersonaProviderError):
    code = "PROVIDER_NOT_CONFIGURED"


class ProviderRequest:
    """Minimal request to a model provider. No project context, no file paths."""

    def __init__(
        self,
        model_id: str,
        system_prompt: str,
        user_prompt: str,
        generation_parameters: GenerationParameters,
        *,
        provider_id: str = "",
        profile_revision: str = "",
        structured_output_schema: Any = None,
        thinking: Any = None,
        counter_id: str = "",
        counter_revision: str = "",
    ) -> None:
        self.model_id = model_id
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        self.generation_parameters = generation_parameters
        self.provider_id = provider_id
        self.profile_revision = profile_revision
        self.structured_output_schema = structured_output_schema
        self.thinking = thinking
        self.counter_id = counter_id
        self.counter_revision = counter_revision
        payload: dict[str, Any] = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": self.user_prompt},
            ],
            "stream": False,
            "temperature": self.generation_parameters.temperature,
        }
        if self.generation_parameters.max_output_tokens is not None:
            payload["max_tokens"] = self.generation_parameters.max_output_tokens
        if self.thinking is not None:
            payload["thinking"] = self.thinking
        if self.structured_output_schema is not None:
            payload["response_format"] = self.structured_output_schema
        self._canonical_payload_json = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    def canonical_payload(self) -> dict[str, Any]:
        # Return a fresh copy of the exact object frozen at construction.  A
        # caller cannot mutate the later Provider send after it was counted.
        return json.loads(self._canonical_payload_json)

    def canonical_payload_hash(self) -> str:
        return hashlib.sha256(self._canonical_payload_json.encode("utf-8")).hexdigest()


class ProviderResponse:
    def __init__(
        self,
        text: str,
        usage: Optional[dict[str, Any]] = None,
        duration_ms: Optional[int] = None,
        provider_request_id: Optional[str] = None,
    ) -> None:
        self.text = text
        self.usage = usage
        self.duration_ms = duration_ms
        self.provider_request_id = provider_request_id


class ModelPersonaProvider(Protocol):
    """Minimal provider contract. Does NOT receive ProjectContext or read files."""

    provider_id: str
    model_id: str

    def generate(self, request: ProviderRequest) -> ProviderResponse: ...


class ModelPersonaExecutionServiceError(Exception):
    def __init__(self, message: str, *, error_code: str = "SERVICE_ERROR") -> None:
        super().__init__(message)
        self.error_code = error_code


def _build_injected_provider_profile(
    profile_id: str, provider: ModelPersonaProvider
) -> ExecutionProfile:
    gen_params = getattr(provider, "generation_parameters", None)
    if gen_params is None:
        gen_params = GenerationParameters()
    return ExecutionProfile(
        profile_id=profile_id,
        profile_version="injected-1.0",
        provider_type=getattr(provider, "provider_type", "injected"),
        provider_id=provider.provider_id,
        model_id=provider.model_id,
        generation_parameters=gen_params,
        timeout_seconds=getattr(gen_params, "timeout_seconds", 60),
        structured_output_mode=StructuredOutputMode.NONE,
        enabled=True,
        endpoint_identity="injected",
    )


class ModelPersonaExecutionService:
    def __init__(
        self,
        context: ProjectContext,
        *,
        provider: Optional[ModelPersonaProvider] = None,
        profiles: Optional[dict[str, ExecutionProfile]] = None,
        conservative_counter: Optional[ConservativeTextCounter] = None,
        conservative_policy: Optional[ConservativeTokenBudgetPolicy] = None,
    ) -> None:
        self.context = context
        self.persona_registry = ReaderPersonaRegistry()
        self.panel_service = ReaderPanelService(context)
        self.prompt_builder = ModelPersonaPromptBuilder()
        self.store = ModelPersonaRunStore(context)
        self._provider = provider
        self._profiles = profiles or EXECUTION_PROFILES
        self._conservative_counter = conservative_counter
        self._conservative_policy = conservative_policy

    def execute(
        self,
        request: ModelPersonaExecutionRequest,
    ) -> ModelPersonaExecutionResult:
        execution_id = str(uuid.uuid4()).replace("-", "")[:16]
        created_at = datetime.now()

        try:
            self._validate_request(request)
        except ModelPersonaExecutionServiceError as exc:
            return self._build_blocked_result(
                execution_id, request, str(exc), created_at,
                error_code=exc.error_code,
            )

        if request.execution_mode == ExecutionMode.LIVE and not request.allow_model_call:
            return self._build_blocked_result(
                execution_id,
                request,
                "Live model call requires explicit allow_model_call=true",
                created_at,
                error_code="MODEL_CALL_BLOCKED",
            )

        profile = self._profiles.get(request.execution_profile)
        if profile is None:
            return self._build_blocked_result(
                execution_id,
                request,
                f"Unknown execution profile: {request.execution_profile}",
                created_at,
                error_code="INVALID_PROFILE",
            )

        if request.execution_mode == ExecutionMode.MOCK:
            if profile.provider_type != "mock" and self._provider is None:
                return self._build_blocked_result(
                    execution_id,
                    request,
                    "Mock mode requires a mock provider profile",
                    created_at,
                    error_code="INVALID_PROFILE",
                )
        elif request.execution_mode == ExecutionMode.LIVE:
            if self._provider is None:
                if profile.provider_type == "mock":
                    missing_default = request.execution_profile == "default"
                    return self._build_blocked_result(
                        execution_id,
                        request,
                        (
                            "Live provider is not configured"
                            if missing_default
                            else "Live mode cannot use mock provider profile"
                        ),
                        created_at,
                        error_code=(
                            "PROVIDER_NOT_CONFIGURED"
                            if missing_default
                            else "INVALID_PROFILE"
                        ),
                    )
                if not _is_profile_enabled(profile):
                    return self._build_blocked_result(
                        execution_id,
                        request,
                        "Execution profile is disabled or missing required configuration",
                        created_at,
                        error_code="PROVIDER_NOT_CONFIGURED",
                    )

        try:
            sim_run, persona_result = self._build_deterministic_inputs(request)
        except Exception as exc:
            return self._build_failed_result(
                execution_id, request, str(exc), created_at,
                error_code="SIMULATION_FAILED",
            )

        if (
            request.expected_source_hash is not None
            and sim_run.snapshot.source.source_hash != request.expected_source_hash
        ) or (
            request.expected_context_hash is not None
            and sim_run.snapshot.context_hash != request.expected_context_hash
        ):
            return self._build_blocked_result(
                execution_id,
                request,
                "Source changed after Live consent was issued",
                created_at,
                error_code="SOURCE_CHANGED_AFTER_CONSENT",
            )

        persona = self.persona_registry.get_persona(request.persona_id)

        provider = self._resolve_provider(request.execution_mode, profile)
        if provider is None:
            return self._build_blocked_result(
                execution_id,
                request,
                "Provider could not be resolved for this profile",
                created_at,
                error_code="PROVIDER_NOT_CONFIGURED",
            )

        provider_config_fingerprint = self._compute_profile_fingerprint(
            profile, provider
        )

        gen_params = profile.generation_parameters
        if provider.provider_id == "deepseek" and provider.model_id == "deepseek-v4-flash":
            gen_params = GenerationParameters(
                temperature=gen_params.temperature,
                max_output_tokens=512,
                timeout_seconds=60,
            )

        input_fingerprint = compute_input_fingerprint(
            source_hash=sim_run.snapshot.source.source_hash,
            context_hash=sim_run.snapshot.context_hash,
            reader_evaluator_version=sim_run.result.evaluator_version,
            persona_fingerprint=persona.persona_fingerprint,
            prompt_template_version=PROMPT_TEMPLATE_VERSION,
            provider_id=provider.provider_id,
            model_id=provider.model_id,
            generation_parameters=gen_params,
            provider_config_fingerprint=provider_config_fingerprint,
        )

        if not request.force:
            cached = self.store.find_by_fingerprint(input_fingerprint)
            if cached is not None and cached.status == ModelRunStatus.COMPLETED:
                cached_result = ModelPersonaExecutionResult(
                    execution_id=cached.execution_id,
                    run_schema_version=cached.run_schema_version,
                    status=cached.status,
                    persona_id=cached.persona_id,
                    persona_version=cached.persona_version,
                    persona_fingerprint=cached.persona_fingerprint,
                    base_simulation_run_id=cached.base_simulation_run_id,
                    source_hash=cached.source_hash,
                    context_hash=cached.context_hash,
                    reader_evaluator_version=cached.reader_evaluator_version,
                    prompt_template_version=cached.prompt_template_version,
                    provider_id=cached.provider_id,
                    model_id=cached.model_id,
                    generation_parameters=cached.generation_parameters,
                    input_fingerprint=cached.input_fingerprint,
                    authoritative_scores=cached.authoritative_scores,
                    execution_mode=cached.execution_mode,
                    execution_profile=cached.execution_profile,
                    execution_profile_version=cached.execution_profile_version,
                    provider_config_fingerprint=cached.provider_config_fingerprint,
                    provider_request_id=cached.provider_request_id,
                    error_code=cached.error_code,
                    model_feedback=cached.model_feedback,
                    grounding_report=cached.grounding_report,
                    usage=cached.usage,
                    cache_status="hit",
                    warnings=cached.warnings,
                    error=cached.error,
                    created_at=cached.created_at,
                    completed_at=cached.completed_at,
                )
                object.__setattr__(cached_result, "chapter_id", request.chapter_id)
                return cached_result

        chapter_text = self._read_chapter_text(sim_run.snapshot)
        built_prompt = self.prompt_builder.build(
            persona=persona,
            snapshot=sim_run.snapshot,
            chapter_text=chapter_text,
            simulation_result=sim_run.result,
            persona_result=persona_result,
        )

        strict_conservative = (
            provider.provider_id == "deepseek"
            and provider.model_id == "deepseek-v4-flash"
        )
        provider_request = ProviderRequest(
            model_id=provider.model_id,
            system_prompt=built_prompt.system_prompt,
            user_prompt=built_prompt.user_prompt,
            generation_parameters=gen_params,
            provider_id=provider.provider_id,
            profile_revision=profile.profile_version,
            structured_output_schema=(
                {"type": "json_object"} if strict_conservative else None
            ),
            thinking=({"type": "disabled"} if strict_conservative else None),
            counter_id=str(getattr(provider, "counter_id", "")),
            counter_revision=str(getattr(provider, "counter_revision", "")),
        )

        if request.execution_mode == ExecutionMode.LIVE and strict_conservative:
            if self._conservative_policy is None or self._conservative_counter is None:
                return self._build_blocked_result(
                    execution_id, request, "Conservative token budget is unavailable",
                    created_at, error_code=CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE,
                )
            evaluation = evaluate_conservative_request(
                canonical_payload=provider_request.canonical_payload(),
                provider_id=provider.provider_id,
                policy=self._conservative_policy,
                counter=self._conservative_counter,
                client_input_limit=request.max_input_tokens_per_call,
                client_call_limit=1,
            )
            if not evaluation.allowed:
                return self._build_blocked_result(
                    execution_id, request, "Conservative token budget blocked the request",
                    created_at, error_code=evaluation.safe_code,
                )
        elif request.execution_mode == ExecutionMode.LIVE and request.max_input_tokens_per_call is not None:
            request_counter = getattr(provider, "count_request_tokens", None)
            legacy_counter = getattr(provider, "count_input_tokens", None)
            if not callable(request_counter) and not callable(legacy_counter):
                return self._build_blocked_result(
                    execution_id, request, "Provider cannot verify the input token budget", created_at,
                    error_code="INPUT_TOKEN_BUDGET_UNAVAILABLE",
                )
            try:
                input_tokens = (
                    request_counter(provider_request)
                    if callable(request_counter)
                    else legacy_counter(provider_request.system_prompt, provider_request.user_prompt)
                )
            except Exception:
                input_tokens = None
            if not isinstance(input_tokens, int) or input_tokens < 0:
                return self._build_blocked_result(
                    execution_id, request, "Provider cannot verify the input token budget", created_at,
                    error_code="INPUT_TOKEN_BUDGET_UNAVAILABLE",
                )
            if input_tokens > request.max_input_tokens_per_call:
                return self._build_blocked_result(
                    execution_id, request, "Input token budget exceeded", created_at,
                    error_code="INPUT_TOKEN_BUDGET_EXCEEDED",
                )

        try:
            provider_response = provider.generate(provider_request)
        except Exception as exc:
            error_code = self._map_provider_error_code(exc)
            return self._build_provider_failed_result(
                execution_id,
                request,
                profile,
                persona,
                sim_run,
                persona_result,
                input_fingerprint,
                provider_config_fingerprint,
                provider,
                gen_params,
                self._public_provider_error_message(error_code),
                created_at,
                error_code=error_code,
            )

        try:
            feedback, grounding = self._validate_output(
                provider_response.text,
                built_prompt.evidence_catalog,
            )
        except ModelPersonaExecutionServiceError as exc:
            usage = self._extract_usage(provider_response)
            error_code = exc.error_code
            result = ModelPersonaExecutionResult(
                execution_id=execution_id,
                run_schema_version=MODEL_PERSONA_RUN_SCHEMA_VERSION,
                status=ModelRunStatus.INVALID_OUTPUT,
                persona_id=persona.persona_id,
                persona_version=persona.persona_version,
                persona_fingerprint=persona.persona_fingerprint,
                base_simulation_run_id=sim_run.run_id,
                source_hash=sim_run.snapshot.source.source_hash,
                context_hash=sim_run.snapshot.context_hash,
                reader_evaluator_version=sim_run.result.evaluator_version,
                prompt_template_version=PROMPT_TEMPLATE_VERSION,
                provider_id=provider.provider_id,
                model_id=provider.model_id,
                generation_parameters=gen_params,
                input_fingerprint=input_fingerprint,
                authoritative_scores=AuthoritativeScores(
                    engagement_score=persona_result.engagement_score,
                    retention_risk=persona_result.retention_risk,
                ),
                execution_mode=request.execution_mode,
                execution_profile=profile.profile_id,
                execution_profile_version=profile.profile_version,
                provider_config_fingerprint=provider_config_fingerprint,
                provider_request_id=getattr(provider_response, "provider_request_id", None),
                error_code=error_code,
                model_feedback=None,
                grounding_report=None,
                usage=usage,
                cache_status="miss",
                warnings=[],
                error=str(exc),
                created_at=created_at,
                completed_at=datetime.now(),
            )
            object.__setattr__(result, "chapter_id", request.chapter_id)
            self.store.save_run(result)
            return result

        usage = self._extract_usage(provider_response)
        result = ModelPersonaExecutionResult(
            execution_id=execution_id,
            run_schema_version=MODEL_PERSONA_RUN_SCHEMA_VERSION,
            status=ModelRunStatus.COMPLETED,
            persona_id=persona.persona_id,
            persona_version=persona.persona_version,
            persona_fingerprint=persona.persona_fingerprint,
            base_simulation_run_id=sim_run.run_id,
            source_hash=sim_run.snapshot.source.source_hash,
            context_hash=sim_run.snapshot.context_hash,
            reader_evaluator_version=sim_run.result.evaluator_version,
            prompt_template_version=PROMPT_TEMPLATE_VERSION,
            provider_id=provider.provider_id,
            model_id=provider.model_id,
            generation_parameters=gen_params,
            input_fingerprint=input_fingerprint,
            authoritative_scores=AuthoritativeScores(
                engagement_score=persona_result.engagement_score,
                retention_risk=persona_result.retention_risk,
            ),
            execution_mode=request.execution_mode,
            execution_profile=profile.profile_id,
            execution_profile_version=profile.profile_version,
            provider_config_fingerprint=provider_config_fingerprint,
            provider_request_id=getattr(provider_response, "provider_request_id", None),
            error_code=None,
            model_feedback=feedback,
            grounding_report=grounding,
            usage=usage,
            cache_status="miss",
            warnings=[],
            created_at=created_at,
            completed_at=datetime.now(),
        )
        object.__setattr__(result, "chapter_id", request.chapter_id)
        self.store.save_run(result)
        return result

    def list_runs(
        self,
        chapter_id: Optional[int] = None,
        persona_id: Optional[str] = None,
    ) -> list[ModelPersonaExecutionResult]:
        return self.store.list_runs(chapter_id=chapter_id, persona_id=persona_id)

    def get_run(self, execution_id: str) -> Optional[ModelPersonaExecutionResult]:
        return self.store.load_run(execution_id)

    def check_staleness(
        self,
        execution_id: str,
        current_source_hash: str = "",
        current_context_hash: str = "",
        current_reader_evaluator_version: str = "",
        current_persona_fingerprint: str = "",
        current_prompt_template_version: str = "",
        current_provider_id: str = "",
        current_model_id: str = "",
        current_generation_parameters: Optional[GenerationParameters] = None,
        current_provider_config_fingerprint: str = "",
    ):
        return self.store.check_staleness(
            execution_id,
            current_source_hash=current_source_hash,
            current_context_hash=current_context_hash,
            current_reader_evaluator_version=current_reader_evaluator_version,
            current_persona_fingerprint=current_persona_fingerprint,
            current_prompt_template_version=current_prompt_template_version,
            current_provider_id=current_provider_id,
            current_model_id=current_model_id,
            current_generation_parameters=current_generation_parameters,
            current_provider_config_fingerprint=current_provider_config_fingerprint,
        )

    def _validate_request(self, request: ModelPersonaExecutionRequest) -> None:
        if request.execution_mode not in (ExecutionMode.MOCK, ExecutionMode.LIVE):
            raise ModelPersonaExecutionServiceError(
                f"Unknown execution mode: {request.execution_mode}",
                error_code="INVALID_MODE",
            )

        try:
            persona = self.persona_registry.get_persona(request.persona_id)
        except ReaderPersonaRegistryError as exc:
            raise ModelPersonaExecutionServiceError(
                str(exc), error_code="UNKNOWN_PERSONA"
            ) from exc

        if hasattr(persona, "enabled") and not persona.enabled:
            raise ModelPersonaExecutionServiceError(
                f"Persona is disabled: {request.persona_id}",
                error_code="DISABLED_PERSONA",
            )

    def _build_deterministic_inputs(
        self, request: ModelPersonaExecutionRequest
    ):
        panel_request = ReaderPanelRequest(
            project_id=request.project_id,
            timeline_id=request.timeline_id,
            chapter_id=request.chapter_id,
            source_version_id=request.source_version_id,
            persona_ids=[request.persona_id],
            mode=SimulationMode.RULE,
        )
        # Use simulator directly for single persona deterministic result
        from system.reader_simulator import ReaderSimulatorService

        sim_service = ReaderSimulatorService(self.context)
        sim_request = ReaderSimulationRequest(
            project_id=request.project_id,
            timeline_id=request.timeline_id,
            chapter_id=request.chapter_id,
            source_version_id=request.source_version_id,
            mode=SimulationMode.RULE,
        )
        sim_run = sim_service.run_simulation(sim_request)

        if sim_run.status.value != "completed" or sim_run.result is None:
            raise ModelPersonaExecutionServiceError(
                f"Simulation failed: {sim_run.error or 'unknown'}"
            )

        persona = self.persona_registry.get_persona(request.persona_id)
        persona_result = self.panel_service._evaluate_persona(persona, sim_run.result)

        return sim_run, persona_result

    def _read_chapter_text(self, snapshot) -> str:
        from system.reader_simulator import ReaderSimulatorService

        sim_service = ReaderSimulatorService(self.context)
        return sim_service._read_chapter_text(snapshot)

    def _resolve_provider(
        self, mode: ExecutionMode, profile: ExecutionProfile
    ) -> Optional[ModelPersonaProvider]:
        if self._provider is not None:
            return self._provider

        if mode == ExecutionMode.MOCK:
            return _MockProvider()

        if profile.provider_type == "openai_compatible":
            api_key = self._resolve_api_key(profile)
            base_url = os.environ.get(
                f"STORYOS_{profile.profile_id.upper()}_BASE_URL",
                os.environ.get("STORYOS_MODEL_BASE_URL", ""),
            )
            if not api_key or not base_url:
                return None
            return OpenAICompatibleModelPersonaProvider(
                provider_id=profile.provider_id,
                model_id=profile.model_id,
                api_key=api_key,
                base_url=base_url,
            )

        return None

    def _resolve_api_key(self, profile: ExecutionProfile) -> str:
        env_name = f"STORYOS_{profile.profile_id.upper()}_API_KEY"
        key = os.environ.get(env_name, "")
        if key:
            return key
        key_env = os.environ.get("STORYOS_MODEL_KEY_ENV", "STORYOS_MODEL_API_KEY")
        return os.environ.get(key_env, "")

    def _compute_profile_fingerprint(
        self,
        profile: ExecutionProfile,
        provider: Optional[ModelPersonaProvider] = None,
    ) -> str:
        provider_type = profile.provider_type
        protocol_version = (
            OpenAICompatibleModelPersonaProvider.protocol_version
            if provider_type == "openai_compatible"
            else "mock-v1"
        )
        endpoint_identity = (
            getattr(provider, "endpoint_identity", "") or profile.endpoint_identity
        )
        return compute_provider_config_fingerprint(
            provider_type=provider_type,
            profile_id=profile.profile_id,
            profile_version=profile.profile_version,
            provider_id=profile.provider_id,
            model_id=profile.model_id,
            protocol_version=protocol_version,
            structured_output_mode=profile.structured_output_mode.value,
            normalized_endpoint_identity=endpoint_identity,
            generation_parameters=profile.generation_parameters,
            timeout_policy_version="1.0",
        )

    @staticmethod
    def _map_provider_error_code(exc: Exception) -> str:
        if isinstance(exc, (OpenAIProviderAuthError,)):
            return "PROVIDER_AUTH_ERROR"
        if isinstance(exc, (OpenAIProviderRateLimitError,)):
            return "PROVIDER_RATE_LIMITED"
        if isinstance(exc, (OpenAIProviderTimeoutError, ProviderTimeoutError)):
            return "PROVIDER_TIMEOUT"
        if isinstance(exc, (OpenAIProviderError, ModelPersonaProviderError)):
            code = getattr(exc, "code", None)
            if code:
                return code
            return "PROVIDER_ERROR"
        text = str(exc).lower()
        if "401" in text or "403" in text or "auth" in text or "unauthorized" in text:
            return "PROVIDER_AUTH_ERROR"
        if "429" in text or "rate limit" in text:
            return "PROVIDER_RATE_LIMITED"
        if "timeout" in text or "timed out" in text:
            return "PROVIDER_TIMEOUT"
        return "PROVIDER_ERROR"

    @staticmethod
    def _public_provider_error_message(error_code: str) -> str:
        return {
            "PROVIDER_AUTH_ERROR": "Provider authentication failed",
            "PROVIDER_RATE_LIMITED": "Provider rate limit exceeded",
            "PROVIDER_TIMEOUT": "Provider request timed out",
            "PROVIDER_NOT_CONFIGURED": "Provider is not configured",
        }.get(error_code, "Provider request failed")

    def _validate_output(
        self,
        raw_text: str,
        evidence_catalog: list,
    ) -> tuple[ModelPersonaFeedback, GroundingReport]:
        # Step 1: JSON extraction (local repair only, no second model call)
        parsed = self._extract_json(raw_text)
        if parsed is None:
            raise ModelPersonaExecutionServiceError(
                "Model output is not valid JSON",
                error_code="MODEL_OUTPUT_INVALID",
            )

        # Step 2: Forbidden fields check
        for field_name in FORBIDDEN_SCORE_FIELDS:
            if field_name in parsed:
                raise ModelPersonaExecutionServiceError(
                    f"Forbidden field in model output: {field_name}",
                    error_code="MODEL_OUTPUT_INVALID",
                )

        # Step 3: Required fields
        reader_reaction = str(parsed.get("reader_reaction", ""))
        if not reader_reaction:
            raise ModelPersonaExecutionServiceError(
                "Missing required field: reader_reaction",
                error_code="MODEL_OUTPUT_INVALID",
            )
        if len(reader_reaction) > MAX_REACTION_CHARS:
            raise ModelPersonaExecutionServiceError(
                f"reader_reaction exceeds {MAX_REACTION_CHARS} chars",
                error_code="MODEL_OUTPUT_INVALID",
            )

        overall_impression = str(parsed.get("overall_impression", ""))
        if len(overall_impression) > MAX_OVERALL_IMPRESSION_CHARS:
            raise ModelPersonaExecutionServiceError(
                f"overall_impression exceeds {MAX_OVERALL_IMPRESSION_CHARS} chars",
                error_code="MODEL_OUTPUT_INVALID",
            )

        # Step 4: Validate list items
        valid_refs = {e.ref for e in evidence_catalog}
        invalid_refs: set[str] = set()
        total_refs = 0
        valid_ref_count = 0
        unsupported_items = 0

        def validate_items(
            items: list,
            category_name: str,
        ) -> list[FeedbackItem]:
            nonlocal total_refs, valid_ref_count, unsupported_items

            if len(items) > MAX_ITEMS_PER_CATEGORY:
                raise ModelPersonaExecutionServiceError(
                    f"{category_name} exceeds max {MAX_ITEMS_PER_CATEGORY} items",
                    error_code="MODEL_OUTPUT_INVALID",
                )

            result = []
            for item in items:
                if not isinstance(item, dict):
                    unsupported_items += 1
                    continue

                message = str(item.get("message", ""))
                if not message:
                    unsupported_items += 1
                    continue
                if len(message) > MAX_MESSAGE_CHARS:
                    raise ModelPersonaExecutionServiceError(
                        f"{category_name} message exceeds {MAX_MESSAGE_CHARS} chars",
                        error_code="MODEL_OUTPUT_INVALID",
                    )

                refs = item.get("evidence_refs", [])
                if not isinstance(refs, list):
                    refs = []

                clean_refs = []
                for ref in refs:
                    ref_str = str(ref)
                    total_refs += 1
                    if ref_str in valid_refs:
                        valid_ref_count += 1
                        clean_refs.append(ref_str)
                    else:
                        invalid_refs.add(ref_str)

                confidence_str = str(item.get("confidence", "medium"))
                try:
                    confidence = ConfidenceLevel(confidence_str)
                except ValueError:
                    confidence = ConfidenceLevel.MEDIUM

                result.append(FeedbackItem(
                    message=message,
                    evidence_refs=clean_refs,
                    confidence=confidence,
                ))
            return result

        strengths = validate_items(parsed.get("strengths", []), "strengths")
        concerns = validate_items(parsed.get("concerns", []), "concerns")
        reader_questions = validate_items(parsed.get("reader_questions", []), "reader_questions")
        optimization_directions = validate_items(
            parsed.get("optimization_directions", []), "optimization_directions"
        )

        # Step 5: Strict evidence policy — any unknown ref → invalid_output
        if invalid_refs:
            raise ModelPersonaExecutionServiceError(
                "Model output contains unknown evidence references",
                error_code="MODEL_EVIDENCE_INVALID",
            )

        feedback = ModelPersonaFeedback(
            reader_reaction=reader_reaction,
            strengths=strengths,
            concerns=concerns,
            reader_questions=reader_questions,
            optimization_directions=optimization_directions,
            overall_impression=overall_impression,
        )

        invalid_count = len(invalid_refs)
        coverage = 1.0 if total_refs == 0 else valid_ref_count / total_refs

        grounding = GroundingReport(
            valid_reference_count=valid_ref_count,
            invalid_reference_count=invalid_count,
            unsupported_item_count=unsupported_items,
            grounding_coverage=round(coverage, 4),
            invalid_refs=sorted(invalid_refs),
        )

        return feedback, grounding

    def _extract_json(self, text: str) -> Optional[dict[str, Any]]:
        """Extract JSON from model output. Local repair only — no second model call."""
        text = text.strip()

        # Remove Markdown JSON fence
        fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if fence_match:
            text = fence_match.group(1).strip()

        # Try direct parse
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # Extract first JSON object
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                result = json.loads(text[start : end + 1])
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        return None

    def _extract_usage(self, response: ProviderResponse) -> Optional[TokenUsage]:
        if not response.usage:
            return None
        usage = response.usage
        input_tokens = usage.get("input_tokens") or usage.get("prompt_tokens")
        output_tokens = usage.get("output_tokens") or usage.get("completion_tokens")
        total = usage.get("total_tokens")
        if total is None and input_tokens is not None and output_tokens is not None:
            total = input_tokens + output_tokens
        return TokenUsage(
            input_tokens=input_tokens if isinstance(input_tokens, int) else None,
            output_tokens=output_tokens if isinstance(output_tokens, int) else None,
            total_tokens=total if isinstance(total, int) else None,
        )

    def _build_blocked_result(
        self,
        execution_id: str,
        request: ModelPersonaExecutionRequest,
        error: str,
        created_at: datetime,
        *,
        error_code: Optional[str] = None,
    ) -> ModelPersonaExecutionResult:
        gen_params = (
            self._profiles.get(request.execution_profile, EXECUTION_PROFILES.get("default")).generation_parameters
            if request.execution_profile in self._profiles
            else GenerationParameters()
        )
        result = ModelPersonaExecutionResult(
            execution_id=execution_id,
            run_schema_version=MODEL_PERSONA_RUN_SCHEMA_VERSION,
            status=ModelRunStatus.BLOCKED,
            persona_id=request.persona_id,
            persona_version="",
            persona_fingerprint="",
            base_simulation_run_id="",
            source_hash="",
            context_hash="",
            reader_evaluator_version="",
            prompt_template_version=PROMPT_TEMPLATE_VERSION,
            provider_id="",
            model_id="",
            generation_parameters=gen_params,
            input_fingerprint="",
            authoritative_scores=AuthoritativeScores(
                engagement_score=0.0,
                retention_risk=0.0,
            ),
            execution_mode=request.execution_mode,
            execution_profile=request.execution_profile,
            execution_profile_version="",
            provider_config_fingerprint="",
            provider_request_id=None,
            error_code=error_code,
            cache_status="miss",
            warnings=[],
            error=error,
            created_at=created_at,
            completed_at=datetime.now(),
        )
        object.__setattr__(result, "chapter_id", request.chapter_id)
        try:
            self.store.save_run(result)
        except Exception:
            pass
        return result

    def _build_failed_result(
        self,
        execution_id: str,
        request: ModelPersonaExecutionRequest,
        error: str,
        created_at: datetime,
        *,
        error_code: Optional[str] = None,
    ) -> ModelPersonaExecutionResult:
        gen_params = (
            self._profiles.get(request.execution_profile, EXECUTION_PROFILES.get("default")).generation_parameters
            if request.execution_profile in self._profiles
            else GenerationParameters()
        )
        result = ModelPersonaExecutionResult(
            execution_id=execution_id,
            run_schema_version=MODEL_PERSONA_RUN_SCHEMA_VERSION,
            status=ModelRunStatus.FAILED,
            persona_id=request.persona_id,
            persona_version="",
            persona_fingerprint="",
            base_simulation_run_id="",
            source_hash="",
            context_hash="",
            reader_evaluator_version="",
            prompt_template_version=PROMPT_TEMPLATE_VERSION,
            provider_id="",
            model_id="",
            generation_parameters=gen_params,
            input_fingerprint="",
            authoritative_scores=AuthoritativeScores(
                engagement_score=0.0,
                retention_risk=0.0,
            ),
            execution_mode=request.execution_mode,
            execution_profile=request.execution_profile,
            execution_profile_version="",
            provider_config_fingerprint="",
            provider_request_id=None,
            error_code=error_code,
            cache_status="miss",
            warnings=[],
            error=error,
            created_at=created_at,
            completed_at=datetime.now(),
        )
        object.__setattr__(result, "chapter_id", request.chapter_id)
        try:
            self.store.save_run(result)
        except Exception:
            pass
        return result

    def _build_provider_failed_result(
        self,
        execution_id: str,
        request: ModelPersonaExecutionRequest,
        profile: ExecutionProfile,
        persona,
        sim_run,
        persona_result: PersonaResult,
        input_fingerprint: str,
        provider_config_fingerprint: str,
        provider: ModelPersonaProvider,
        gen_params: GenerationParameters,
        error: str,
        created_at: datetime,
        *,
        error_code: Optional[str] = None,
    ) -> ModelPersonaExecutionResult:
        result = ModelPersonaExecutionResult(
            execution_id=execution_id,
            run_schema_version=MODEL_PERSONA_RUN_SCHEMA_VERSION,
            status=ModelRunStatus.FAILED,
            persona_id=persona.persona_id,
            persona_version=persona.persona_version,
            persona_fingerprint=persona.persona_fingerprint,
            base_simulation_run_id=sim_run.run_id,
            source_hash=sim_run.snapshot.source.source_hash,
            context_hash=sim_run.snapshot.context_hash,
            reader_evaluator_version=sim_run.result.evaluator_version,
            prompt_template_version=PROMPT_TEMPLATE_VERSION,
            provider_id=provider.provider_id,
            model_id=provider.model_id,
            generation_parameters=gen_params,
            input_fingerprint=input_fingerprint,
            authoritative_scores=AuthoritativeScores(
                engagement_score=persona_result.engagement_score,
                retention_risk=persona_result.retention_risk,
            ),
            execution_mode=request.execution_mode,
            execution_profile=profile.profile_id,
            execution_profile_version=profile.profile_version,
            provider_config_fingerprint=provider_config_fingerprint,
            provider_request_id=None,
            error_code=error_code,
            cache_status="miss",
            warnings=[],
            error=error,
            created_at=created_at,
            completed_at=datetime.now(),
        )
        object.__setattr__(result, "chapter_id", request.chapter_id)
        self.store.save_run(result)
        return result


class _MockProvider:
    """Deterministic mock provider for testing and development. Zero network access."""

    provider_id = "mock"
    model_id = "mock-persona-v1"

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        response_text = json.dumps({
            "reader_reaction": "This chapter shows clear narrative momentum with engaging hooks.",
            "strengths": [
                {
                    "message": "The opening creates immediate tension.",
                    "evidence_refs": [],
                    "confidence": "high",
                }
            ],
            "concerns": [
                {
                    "message": "Pacing slows in the middle section.",
                    "evidence_refs": [],
                    "confidence": "medium",
                }
            ],
            "reader_questions": [
                {
                    "message": "What motivates the protagonist's sudden decision?",
                    "evidence_refs": [],
                    "confidence": "low",
                }
            ],
            "optimization_directions": [
                {
                    "message": "Consider tightening the middle section pacing.",
                    "evidence_refs": [],
                    "confidence": "medium",
                }
            ],
            "overall_impression": "A solid chapter with room for pacing improvement.",
        }, ensure_ascii=False)

        return ProviderResponse(
            text=response_text,
            usage={
                "input_tokens": 500,
                "output_tokens": 200,
                "total_tokens": 700,
            },
            duration_ms=10,
        )
