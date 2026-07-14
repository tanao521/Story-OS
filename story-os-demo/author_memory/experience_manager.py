"""Success and failure memories remain author-entered, reusable lessons."""
from __future__ import annotations

from typing import Any
from author_memory.asset_store import AuthorAssetStore
from core.project_context import ProjectContext

class ExperienceManager:
    def __init__(self, context: ProjectContext) -> None: self.store = AuthorAssetStore(context)
    def list(self) -> list[dict[str, Any]]: return self.store.list_experiences()
    def add_failure(self, value: dict[str, Any]) -> dict[str, Any]: return self.store.add_experience({"problem": str(value.get("problem") or ""), "reason": str(value.get("reason") or ""), "lesson": str(value.get("lesson") or ""), "applies_to": value.get("applies_to") if isinstance(value.get("applies_to"), list) else [], "source": str(value.get("source") or "author"), "confirmed": bool(value.get("confirmed", True)), "confirmed_at": value.get("confirmed_at")}, "failure")
    def add_success(self, value: dict[str, Any]) -> dict[str, Any]: return self.store.add_experience({"name": str(value.get("name") or ""), "conditions": value.get("conditions") if isinstance(value.get("conditions"), list) else [], "effect": str(value.get("effect") or ""), "source": str(value.get("source") or "author"), "confirmed": bool(value.get("confirmed", True)), "confirmed_at": value.get("confirmed_at")}, "success")
