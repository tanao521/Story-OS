"""Provider boundary.  Adapters return normalized text and usage only."""
from __future__ import annotations

from typing import Protocol

from llm.model_models import ModelDefinition, ModelRequest, ModelResponse


class ModelProvider(Protocol):
    def generate(self, definition: ModelDefinition, request: ModelRequest) -> ModelResponse: ...
    def health_check(self, definition: ModelDefinition) -> dict: ...
