"""Stable data shapes for the local model-routing layer."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import os
from typing import Any


MODEL_TASK_TYPES = {
    "generate_story_blueprint", "generate_story_assets", "generate_volume_plan",
    "generate_chapter_plan", "generate_next_chapter_plan", "write_draft", "edit_draft",
    "rewrite_revision", "quality_review", "continuity_review", "revision_impact_analysis",
    "chapter_summary", "narrative_event_extraction", "story_qa", "memory_qa",
    "planning_analysis", "context_compression", "chapter_quality_plan", "chapter_quality_revision",
    "creative_team_advice",
}


class ModelGatewayError(RuntimeError):
    code = "MODEL_GATEWAY_ERROR"
    recoverable = False

    def __init__(self, message: str, *, code: str | None = None, recoverable: bool | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code
        if recoverable is not None:
            self.recoverable = recoverable


@dataclass
class ModelDefinition:
    model_key: str
    provider: str
    model: str
    enabled: bool = True
    local: bool = False
    capabilities: list[str] = field(default_factory=lambda: ["text"])
    context_window: int | None = None
    max_output_tokens: int | None = None
    timeout_seconds: int = 180
    api_key_env: str = ""
    base_url: str = ""
    display_name: str = ""

    def public(self) -> dict[str, Any]:
        data = asdict(self)
        data["api_key_configured"] = bool(os.getenv(self.api_key_env, "")) if self.api_key_env else True
        data.pop("api_key_env", None)
        return data


@dataclass
class ModelRoute:
    task_type: str
    primary: str
    fallbacks: list[str] = field(default_factory=list)
    local_only: bool = False
    policy_version: str = "1.0"
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ModelResponse:
    text: str
    provider: str
    model: str
    usage: dict[str, Any] = field(default_factory=dict)
    raw_status: int | None = None
    estimated_usage: bool = False


@dataclass
class ModelRequest:
    task_type: str
    prompt: str
    temperature: float = 0.4
    max_tokens: int | None = None
    prompt_id: str = ""
    prompt_version: str = ""
    job_id: str | None = None
    chapter_id: int | None = None
    generation_parameters: dict[str, Any] = field(default_factory=dict)
    route_snapshot: dict[str, Any] | None = None
    cancellation_requested: Any = None
