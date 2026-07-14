"""Single model-call boundary for routing, fallback, traces, and cost accounting."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from core.project_context import ProjectContext, get_project_context
from llm.cost_calculator import calculate_cost, estimate_tokens
from llm.json_utils import extract_json_from_text
from llm.model_models import ModelGatewayError, ModelRequest, ModelResponse
from llm.model_registry import ModelRegistry
from llm.prompt_registry import PromptRegistry
from llm.providers.ollama import OllamaProvider
from llm.providers.openai_compatible import OpenAICompatibleProvider
from llm.retry_policy import is_recoverable, retry_call
from llm.run_recorder import RunRecorder


class ModelGateway:
    def __init__(self, context: ProjectContext | None = None, *, registry: ModelRegistry | None = None,
                 recorder: RunRecorder | None = None, providers: dict[str, Any] | None = None) -> None:
        self.context = context or get_project_context()
        self.registry = registry or ModelRegistry(self.context)
        self.recorder = recorder or RunRecorder(self.context)
        self.prompts = PromptRegistry()
        self.providers = providers or {"openai_compatible": OpenAICompatibleProvider(), "ollama": OllamaProvider(), "deepseek": OpenAICompatibleProvider(), "openai": OpenAICompatibleProvider()}

    def freeze_route(self, task_type: str, *, prompt_id: str = "generic", parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        frozen = self.registry.frozen_route(task_type)
        metadata = self.prompts.get(prompt_id) or self.prompts.get("generic") or {}
        frozen.update({"prompt_id": prompt_id if self.prompts.get(prompt_id) else "generic", "prompt_version": metadata.get("version", "1.0")})
        if parameters:
            frozen["generation_parameters"] = {**frozen.get("generation_parameters", {}), **parameters}
        return frozen

    def generate(self, request: ModelRequest) -> ModelResponse:
        if request.cancellation_requested and request.cancellation_requested():
            raise ModelGatewayError("Model call was cancelled before it started.", code="CANCELLED")
        bound = _bound_route.get()
        snapshot = dict(request.route_snapshot or (bound if bound and bound.get("task_type") == request.task_type else {}) or self.freeze_route(request.task_type, prompt_id=request.prompt_id or "generic", parameters=request.generation_parameters))
        selected = str(snapshot.get("model_key") or "")
        chain = [selected, *[str(item) for item in snapshot.get("fallback_chain", []) if str(item)]]
        if not selected:
            raise ModelGatewayError("No model is configured for this task.", code="MODEL_NOT_CONFIGURED")
        metadata = self.prompts.metadata(str(snapshot.get("prompt_id") or request.prompt_id or "generic"), request.prompt)
        first = self.registry.model(selected)
        self._preflight(first, request, selected)
        run = self.recorder.start(task_type=request.task_type, model_key=selected, provider=first.provider, model=first.model, prompt_id=metadata["prompt_id"], prompt_version=str(snapshot.get("prompt_version") or metadata["prompt_version"]), prompt_hash=metadata["prompt_hash"], job_id=request.job_id, chapter_id=request.chapter_id, route_snapshot=self._public_snapshot(snapshot))
        errors: list[str] = []
        for index, model_key in enumerate(chain):
            if request.cancellation_requested and request.cancellation_requested():
                self.recorder.finish(run, status="cancelled", usage={}, cost={}, warnings=errors, error="Cancelled at a safe model-call boundary.")
                raise ModelGatewayError("Model call cancelled.", code="CANCELLED")
            definition = self.registry.model(model_key)
            if not definition.enabled:
                errors.append(f"{model_key}: disabled")
                continue
            if bool(snapshot.get("local_only")) and not definition.local:
                errors.append(f"{model_key}: blocked by local-only route")
                continue
            provider = self.providers.get(definition.provider)
            if provider is None:
                errors.append(f"{model_key}: provider unavailable")
                continue
            try:
                self.recorder.attempt(run, model_key=model_key, status="running")
                response = retry_call(lambda: provider.generate(definition, request), attempts=2, on_retry=lambda attempt, error: self.recorder.attempt(run, model_key=model_key, status="retry", message=f"retry {attempt}: {error}"))
                usage = self._usage(request.prompt, response)
                cost = calculate_cost(usage, self.registry.pricing_for(model_key))
                warnings = errors + (["Token usage was estimated locally."] if usage.get("estimated") else [])
                self.recorder.attempt(run, model_key=model_key, status="completed")
                self.recorder.finish(run, status="completed_with_fallback" if index else "completed", usage=usage, cost=cost, warnings=warnings)
                return response
            except Exception as exc:
                self.recorder.attempt(run, model_key=model_key, status="failed", message=str(exc))
                errors.append(f"{model_key}: {getattr(exc, 'code', 'MODEL_ERROR')}")
                if not is_recoverable(exc):
                    self.recorder.finish(run, status="failed", usage={}, cost={}, warnings=errors, error=str(exc))
                    raise
                if index + 1 >= len(chain):
                    self.recorder.finish(run, status="failed", usage={}, cost={}, warnings=errors, error=str(exc))
                    raise
        error = ModelGatewayError("All configured model routes failed.", code="MODEL_ROUTE_EXHAUSTED", recoverable=True)
        self.recorder.finish(run, status="failed", usage={}, cost={}, warnings=errors, error=str(error))
        raise error

    def generate_text(self, task_type: str, prompt: str, *, temperature: float = 0.4, max_tokens: int | None = None,
                      prompt_id: str = "generic", job_id: str | None = None, chapter_id: int | None = None,
                      route_snapshot: dict[str, Any] | None = None, cancellation_requested: Any = None) -> str:
        return self.generate(ModelRequest(task_type=task_type, prompt=prompt, temperature=temperature, max_tokens=max_tokens, prompt_id=prompt_id, job_id=job_id, chapter_id=chapter_id, route_snapshot=route_snapshot, cancellation_requested=cancellation_requested)).text

    def generate_json(self, task_type: str, prompt: str, **kwargs: Any) -> dict[str, Any]:
        """Parse structured output once, then make one explicit repair request if needed."""
        text = self.generate_text(task_type, prompt, **kwargs)
        parsed = extract_json_from_text(text)
        if parsed:
            return parsed
        repair = "Return only a valid JSON object for the same request. Do not add explanation.\n\n" + prompt
        parsed = extract_json_from_text(self.generate_text(task_type, repair, **kwargs))
        if not parsed:
            raise ModelGatewayError("Model did not return valid JSON after one repair attempt.", code="STRUCTURED_OUTPUT_INVALID")
        return parsed

    def health(self) -> list[dict[str, Any]]:
        results = []
        for definition in self.registry.models():
            provider = self.providers.get(definition.provider)
            item = provider.health_check(definition) if provider else {"status": "provider_unavailable"}
            results.append({"model_key": definition.model_key, **item})
        return results

    def health_check(self, model_key: str) -> dict[str, Any]:
        definition = self.registry.model(model_key); provider = self.providers.get(definition.provider)
        if not provider:
            raise ModelGatewayError("Provider is unavailable.", code="PROVIDER_UNAVAILABLE")
        return {"model_key": model_key, **provider.health_check(definition)}

    @staticmethod
    def _usage(prompt: str, response: ModelResponse) -> dict[str, Any]:
        raw = dict(response.usage or {})
        prompt_tokens = raw.get("prompt_tokens")
        completion_tokens = raw.get("completion_tokens")
        estimated = not isinstance(prompt_tokens, int) or not isinstance(completion_tokens, int)
        if estimated:
            prompt_tokens = estimate_tokens(prompt); completion_tokens = estimate_tokens(response.text)
        return {"prompt_tokens": int(prompt_tokens), "completion_tokens": int(completion_tokens), "total_tokens": int(raw.get("total_tokens", int(prompt_tokens) + int(completion_tokens)) or int(prompt_tokens) + int(completion_tokens)), "estimated": estimated}

    @staticmethod
    def _public_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
        allowed = {"task_type", "resolved_provider", "resolved_model", "model_key", "fallback_chain", "routing_policy_version", "local_only", "generation_parameters", "prompt_id", "prompt_version", "frozen_at"}
        return {key: value for key, value in snapshot.items() if key in allowed}

    def _preflight(self, definition: Any, request: ModelRequest, model_key: str) -> None:
        estimated_input = estimate_tokens(request.prompt)
        if definition.context_window and estimated_input + int(request.max_tokens or 0) > int(definition.context_window):
            raise ModelGatewayError("Prompt exceeds the configured model context window.", code="CONTEXT_TOO_LONG")
        limits = self.registry.limits(); usage = self.recorder.usage_summary().get("totals", {})
        if limits.get("max_total_tokens") and int(usage.get("total_tokens", 0) or 0) + estimated_input > int(limits["max_total_tokens"]):
            raise ModelGatewayError("Project token limit would be exceeded.", code="TOKEN_LIMIT_EXCEEDED")
        price = self.registry.pricing_for(model_key)
        estimate = calculate_cost({"prompt_tokens": estimated_input, "completion_tokens": int(request.max_tokens or 0)}, price)
        if limits.get("max_cost") and estimate.get("amount") is not None and float(usage.get("cost", 0) or 0) + float(estimate["amount"]) > float(limits["max_cost"]):
            raise ModelGatewayError("Project cost limit would be exceeded.", code="COST_LIMIT_EXCEEDED")


def get_model_gateway(context: ProjectContext | None = None) -> ModelGateway:
    return ModelGateway(context)


_bound_route: ContextVar[dict[str, Any] | None] = ContextVar("storyos_model_route", default=None)


def current_model_route_snapshot() -> dict[str, Any] | None:
    """Return the task-owned frozen route, if this is a managed background run."""
    return _bound_route.get()


@contextmanager
def bind_model_route_snapshot(snapshot: dict[str, Any] | None):
    """Bind a queued job's frozen routing decision for its execution thread."""
    token = _bound_route.set(dict(snapshot or {}) or None)
    try:
        yield
    finally:
        _bound_route.reset(token)
