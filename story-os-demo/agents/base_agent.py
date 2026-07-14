"""Base contract for deterministic/LLM-backed creative roles."""
from __future__ import annotations

from typing import Any

from agents.models import AgentProfile


class AgentPermissionError(PermissionError):
    """An agent attempted a mutation outside its bounded role."""


class BaseAgent:
    profile: AgentProfile

    def __init__(self, profile: AgentProfile) -> None:
        self.profile = profile

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        """Return advice/artifacts only; agents do not mutate project files."""
        raise NotImplementedError

    def assert_read_only(self, operation: str) -> None:
        if operation in {"write_world", "write_canon", "delete_memory", "commit_chapter"}:
            raise AgentPermissionError(f"{self.profile.id} is not permitted to {operation}.")
