"""Cost controls for deterministic creative-loop analysis."""
from __future__ import annotations

from typing import Any

from core.project_context import ProjectContext
from system.data_store import DataStore


class AnalysisProfileService:
    DEFAULT = {"profile": "standard", "enable_reader_simulator": False, "enable_deep_critic": False, "prompt_version": "13.1"}
    PROFILES = {"lite", "standard", "deep"}

    def __init__(self, context: ProjectContext) -> None:
        self.context, self.store = context, DataStore(context)

    def get(self) -> dict[str, Any]:
        stored = self.store.read_json("data/creative_loop/settings.json", default={}, expected_type=dict) or {}
        result = {**self.DEFAULT, **stored}
        if result["profile"] not in self.PROFILES:
            result["profile"] = "standard"
        return result

    def update(self, values: dict[str, Any]) -> dict[str, Any]:
        current = self.get()
        if "profile" in values and values["profile"] not in self.PROFILES:
            raise ValueError("ANALYSIS_PROFILE_INVALID")
        for key in ("profile", "enable_reader_simulator", "enable_deep_critic"):
            if key in values:
                current[key] = values[key] if key == "profile" else bool(values[key])
        self.store.write_json("data/creative_loop/settings.json", current, backup=True)
        return current

    def resolved(self, requested: str | None = None) -> dict[str, Any]:
        result = self.get()
        if requested:
            if requested not in self.PROFILES:
                raise ValueError("ANALYSIS_PROFILE_INVALID")
            result["profile"] = requested
        if result["profile"] == "deep":
            result["enable_deep_critic"] = True
        return result
