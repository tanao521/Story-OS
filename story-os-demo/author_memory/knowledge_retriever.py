"""Local hashed-ngram retrieval across explicitly saved author assets only."""
from __future__ import annotations

from typing import Any
from author_memory.asset_store import AuthorAssetStore
from core.project_context import ProjectContext

def _terms(text: str) -> set[str]:
    text = str(text).casefold(); return {text[i:i + 2] for i in range(max(0, len(text) - 1)) if text[i:i + 2].strip()}
def _score(query: str, text: str) -> float:
    a, b = _terms(query), _terms(text); return round(len(a & b) / max(1, len(a | b)), 3)

class AuthorKnowledgeRetriever:
    def __init__(self, context: ProjectContext) -> None: self.store = AuthorAssetStore(context)
    def retrieve(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        rows = self.store.list_assets() + self.store.list_experiences() + self.store.list_preferences(); ranked=[]
        for row in rows:
            text = " ".join(str(row.get(key, "")) for key in ("name", "content", "problem", "reason", "lesson", "effect"))
            score = _score(query, text)
            if score > 0: ranked.append({"id": row.get("id", ""), "type": row.get("type", "asset"), "name": row.get("name") or row.get("problem") or row.get("content", ""), "score": score, "source": "author_asset", "reason": "local_hashed_embedding match"})
        return sorted(ranked, key=lambda item: item["score"], reverse=True)[:limit]
    def context_for_task(self, query: str, project_rules: list[str] | None = None) -> dict[str, Any]:
        from author_memory.preference_engine import resolve_preferences
        preferences = self.store.list_preferences(); return {"preferences": [row.get("content", "") for row in preferences if row.get("type") in {"preference", "avoid"}], "retrieved_knowledge": self.retrieve(query), "preference_resolution": resolve_preferences(preferences, project_rules or []), "source": "author_global"}
