"""Project-aware model registry with environment-only credential references."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import config
from core.project_context import ProjectContext, get_project_context
from system.data_store import DataStore
from llm.model_models import MODEL_TASK_TYPES, ModelDefinition, ModelGatewayError, ModelRoute


DEFAULT_TASK_ROUTE = {
    "generate_story_blueprint": "deepseek", "generate_story_assets": "deepseek",
    "generate_volume_plan": "deepseek", "generate_chapter_plan": "deepseek",
    "generate_next_chapter_plan": "deepseek", "write_draft": "write_model",
    "edit_draft": "write_model", "rewrite_revision": "write_model",
    "quality_review": "deepseek", "continuity_review": "deepseek",
    "revision_impact_analysis": "deepseek", "chapter_summary": "deepseek",
    "narrative_event_extraction": "deepseek", "story_qa": "deepseek",
    "memory_qa": "deepseek", "planning_analysis": "deepseek", "context_compression": "deepseek",
    "creative_team_advice": "qwen",
}


class ModelRegistry:
    def __init__(self, context: ProjectContext | None = None, *, workspace_root: str | Path | None = None) -> None:
        self.context = context or get_project_context()
        self.workspace_root = Path(workspace_root or Path.cwd()).resolve()
        self.project_store = DataStore(self.context)
        self.global_store = DataStore(get_project_context(self.workspace_root))

    @property
    def models_path(self) -> str:
        return ".story_os/models.json"

    @property
    def pricing_path(self) -> str:
        return ".story_os/model_pricing.json"

    def models(self) -> list[ModelDefinition]:
        stored = self.global_store.read_json(self.models_path, default={}, expected_type=dict) or {}
        raw = stored.get("models") if isinstance(stored.get("models"), list) else []
        definitions = [self._definition(item) for item in raw if isinstance(item, dict) and item.get("model_key")]
        if not definitions:
            definitions = self._defaults()
        return definitions

    def model(self, key: str) -> ModelDefinition:
        for definition in self.models():
            if definition.model_key == key:
                return definition
        raise ModelGatewayError("Model route references an unknown model.", code="MODEL_NOT_FOUND")

    def routes(self) -> dict[str, ModelRoute]:
        global_data = self.global_store.read_json(self.models_path, default={}, expected_type=dict) or {}
        preferences = self.project_store.read_json(self.context.model_preferences_path, default={}, expected_type=dict) or {}
        raw = dict(global_data.get("routes") or {})
        raw.update(dict(preferences.get("routes") or {}))
        return {task: self._route(task, raw.get(task)) for task in sorted(MODEL_TASK_TYPES)}

    def route(self, task_type: str) -> ModelRoute:
        if task_type not in MODEL_TASK_TYPES:
            raise ModelGatewayError("Unsupported model task type.", code="TASK_TYPE_UNSUPPORTED")
        return self.routes()[task_type]

    def update_routes(self, values: dict[str, Any]) -> dict[str, ModelRoute]:
        if not isinstance(values, dict):
            raise ModelGatewayError("Routes must be an object.", code="INVALID_ROUTE_CONFIG")
        current = self.project_store.read_json(self.context.model_preferences_path, default={}, expected_type=dict) or {}
        routes = dict(current.get("routes") or {})
        known = {model.model_key for model in self.models()}
        for task, payload in values.items():
            if task not in MODEL_TASK_TYPES or not isinstance(payload, dict):
                raise ModelGatewayError("Invalid routing task configuration.", code="INVALID_ROUTE_CONFIG")
            primary = str(payload.get("primary", ""))
            fallbacks = [str(item) for item in payload.get("fallbacks", []) if str(item)]
            if primary not in known or any(item not in known for item in fallbacks):
                raise ModelGatewayError("Route contains an unknown model key.", code="MODEL_NOT_FOUND")
            if bool(payload.get("local_only")) and any(not self.model(key).local for key in [primary, *fallbacks]):
                raise ModelGatewayError("A local-only route cannot use a cloud fallback.", code="LOCAL_ONLY_ROUTE_INVALID")
            routes[task] = {"primary": primary, "fallbacks": fallbacks, "local_only": bool(payload.get("local_only", False)), "policy_version": str(payload.get("policy_version", "1.0")), "parameters": dict(payload.get("parameters") or {})}
        current.update({"schema_version": "1.0", "routes": routes})
        self.project_store.write_json(self.context.model_preferences_path, current, backup=True)
        return self.routes()

    def pricing(self) -> dict[str, Any]:
        return self.global_store.read_json(self.pricing_path, default={"schema_version": "1.0", "models": {}}, expected_type=dict) or {"schema_version": "1.0", "models": {}}

    def update_pricing(self, pricing: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(pricing, dict) or not isinstance(pricing.get("models", {}), dict):
            raise ModelGatewayError("Pricing must contain a models object.", code="INVALID_PRICING")
        clean = {"schema_version": "1.0", "models": {}}
        for key, value in pricing["models"].items():
            if not isinstance(value, dict):
                continue
            clean["models"][str(key)] = {name: value.get(name) for name in ("currency", "input_per_million", "output_per_million")}
        self.global_store.write_json(self.pricing_path, clean, backup=True)
        return clean

    def pricing_for(self, model_key: str) -> dict[str, Any] | None:
        result = self.pricing().get("models", {}).get(model_key)
        return result if isinstance(result, dict) else None

    def limits(self) -> dict[str, Any]:
        value = self.project_store.read_json(self.context.model_cost_limits_path, default={}, expected_type=dict) or {}
        return {"schema_version": "1.0", "max_total_tokens": value.get("max_total_tokens"), "max_cost": value.get("max_cost"), "currency": str(value.get("currency", "USD"))}

    def update_limits(self, limits: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(limits, dict):
            raise ModelGatewayError("Limits must be an object.", code="INVALID_COST_LIMIT")
        clean = {"schema_version": "1.0", "max_total_tokens": self._positive_or_none(limits.get("max_total_tokens")), "max_cost": self._positive_or_none(limits.get("max_cost")), "currency": str(limits.get("currency", "USD"))}
        self.project_store.write_json(self.context.model_cost_limits_path, clean, backup=True)
        return clean

    def frozen_route(self, task_type: str) -> dict[str, Any]:
        route = self.route(task_type)
        primary = self.model(route.primary)
        candidates = [route.primary, *route.fallbacks]
        return {"task_type": task_type, "resolved_provider": primary.provider, "resolved_model": primary.model, "model_key": primary.model_key, "fallback_chain": candidates[1:], "routing_policy_version": route.policy_version, "local_only": route.local_only, "generation_parameters": dict(route.parameters), "frozen_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(timespec="seconds")}

    @staticmethod
    def _definition(raw: dict[str, Any]) -> ModelDefinition:
        return ModelDefinition(model_key=str(raw["model_key"]), provider=str(raw.get("provider", "openai_compatible")), model=str(raw.get("model", "")), enabled=bool(raw.get("enabled", True)), local=bool(raw.get("local", False)), capabilities=[str(item) for item in raw.get("capabilities", ["text"])], context_window=raw.get("context_window"), max_output_tokens=raw.get("max_output_tokens"), timeout_seconds=int(raw.get("timeout_seconds", 180) or 180), api_key_env=str(raw.get("api_key_env", "")), base_url=str(raw.get("base_url", "")), display_name=str(raw.get("display_name", "")))

    @staticmethod
    def _positive_or_none(value: Any) -> float | int | None:
        if value in (None, ""):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ModelGatewayError("Limits must be positive numbers.", code="INVALID_COST_LIMIT") from exc
        if number <= 0:
            raise ModelGatewayError("Limits must be positive numbers.", code="INVALID_COST_LIMIT")
        return int(number) if number.is_integer() else number

    def _route(self, task: str, raw: Any) -> ModelRoute:
        source = raw if isinstance(raw, dict) else {}
        return ModelRoute(task_type=task, primary=str(source.get("primary") or DEFAULT_TASK_ROUTE[task]), fallbacks=[str(item) for item in source.get("fallbacks", []) if str(item)], local_only=bool(source.get("local_only", False)), policy_version=str(source.get("policy_version", "1.0")), parameters=dict(source.get("parameters") or {}))

    @staticmethod
    def _defaults() -> list[ModelDefinition]:
        return [
            ModelDefinition("deepseek", "openai_compatible", str(config.DEEPSEEK_MODEL), api_key_env="DEEPSEEK_API_KEY", base_url=str(config.DEEPSEEK_BASE_URL), display_name="DeepSeek"),
            ModelDefinition("write_model", "openai_compatible", str(config.WRITE_MODEL_NAME), api_key_env="WRITE_MODEL_API_KEY", base_url=str(config.WRITE_MODEL_BASE_URL), timeout_seconds=int(config.WRITE_MODEL_TIMEOUT_SECONDS), display_name="Writing model"),
            ModelDefinition("qwen", "openai_compatible", str(config.QWEN_MODEL), api_key_env="QWEN_API_KEY", base_url=str(config.QWEN_BASE_URL), timeout_seconds=int(config.QWEN_TIMEOUT_SECONDS), display_name="Qwen"),
            ModelDefinition("local_model", "ollama", str(config.LOCAL_MODEL_NAME), api_key_env="LOCAL_MODEL_API_KEY", base_url=str(config.LOCAL_MODEL_BASE_URL), local=True, timeout_seconds=int(config.OLLAMA_TIMEOUT_SECONDS), display_name="Local model"),
        ]
