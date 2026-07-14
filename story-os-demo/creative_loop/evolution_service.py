"""Chronological, project-local creative-loop history."""
from __future__ import annotations

from typing import Any

from core.project_context import ProjectContext
from system.data_store import DataStore


class EvolutionService:
    def __init__(self, context: ProjectContext) -> None: self.context, self.store = context, DataStore(context)

    def timeline(self, chapter_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
        events=[]
        for folder, kind, key in (("reflections", "chapter_reflection", "reflection_id"), ("proposals", "strategy_proposal", "proposal_id"), ("experiments", "creative_experiment", "experiment_id"), ("patterns", "creative_pattern", "pattern_id"), ("outcomes", "strategy_outcome", "outcome_id")):
            root=self.store.path(f"data/creative_loop/{folder}")
            if not root.exists(): continue
            for path in root.glob("*.json"):
                row=self.store.read_json(path,default=None,expected_type=dict)
                if not row or (chapter_id is not None and int(row.get("chapter_id") or row.get("source_chapter_id") or 0) != chapter_id): continue
                events.append({"event_type":kind,"event_id":row.get(key),"chapter_id":row.get("chapter_id") or row.get("source_chapter_id"),"status":row.get("status"),"title":row.get("title") or row.get("summary") or kind,"at":row.get("updated_at") or row.get("resolved_at") or row.get("created_at"),"data":row})
        return sorted(events,key=lambda item:str(item.get("at") or ""),reverse=True)[:max(1,min(limit,200))]
