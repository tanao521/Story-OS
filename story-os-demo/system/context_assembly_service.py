"""Read-only authority boundary for model-context assembly.

This service does not replace Canon, state, summaries, vector storage, or an
external vault.  It composes safe projections of those sources into one
context package and retains the legacy working-context keys for callers.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from core.contracts import ProjectRef
from core.project_context import ProjectContext, get_project_context
from system.data_store import DataStore


class ContextAssemblyError(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True)
class ContextProfile:
    purpose: str
    recent_chapters: int = 3
    summaries: int = 3
    retrieval_results: int = 5
    vector_results: int = 5
    allow_vector: bool = True
    allow_working_version: bool = False


@dataclass(frozen=True)
class ContextPackage:
    """Stable, read-only projection returned by context assembly."""

    project_id: str
    purpose: str
    chapter_number: int
    payload: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return self.payload


DEFAULT_PROFILES: dict[str, ContextProfile] = {
    "chapter_planning": ContextProfile("chapter_planning", recent_chapters=2, summaries=3, retrieval_results=5),
    "chapter_drafting": ContextProfile("chapter_drafting"),
    "chapter_revision": ContextProfile("chapter_revision", recent_chapters=2, summaries=3),
    "chapter_evaluation": ContextProfile("chapter_evaluation", recent_chapters=2, summaries=3, vector_results=3),
    "continuity_review": ContextProfile("continuity_review", recent_chapters=1, summaries=2, retrieval_results=2, vector_results=0, allow_vector=False),
    "reader_simulation": ContextProfile("reader_simulation", recent_chapters=2, summaries=2),
}


class NarrativeStateAdapter:
    source_type = "narrative_state"

    @staticmethod
    def read(state: dict[str, Any]) -> dict[str, Any]:
        from system.context_builder import build_state_snapshot
        return build_state_snapshot(state)


class CanonMemoryAdapter:
    source_type = "canon_memory"

    def __init__(self, context: ProjectContext) -> None:
        self.context = context

    def read(self) -> list[dict[str, Any]]:
        # NarrativeMemoryService is the existing Canon-adjacent read model.
        try:
            from system.narrative_memory_service import NarrativeMemoryService
            values = NarrativeMemoryService(self.context).events()
        except Exception:
            return []
        return [
            {"source_type": self.source_type, "source_id": str(item.get("event_id", item.get("id", ""))), "chapter_id": item.get("chapter_id"), "summary": str(item.get("summary", item.get("event", "")))[:1000]}
            for item in values if isinstance(item, dict)
        ][:20]


class SummaryMemoryAdapter:
    source_type = "summary_memory"

    @staticmethod
    def read(context: dict[str, Any]) -> list[dict[str, Any]]:
        return [dict(item, source_type="summary_memory", source_id=f"summary:{item.get('chapter_id', '')}") for item in context.get("retrieved_summaries", []) if isinstance(item, dict)]


class VectorRetrievalAdapter:
    source_type = "vector_retrieval"

    @staticmethod
    def read(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [dict(item, source_type="vector_retrieval", source_id=str(item.get("chunk_id", item.get("id", item.get("chapter_id", ""))))) for item in values if isinstance(item, dict)]


class ExternalSyncAdapter:
    source_type = "external_sync"

    @staticmethod
    def read() -> dict[str, Any]:
        # Never resolve the user-level vault configuration during assembly.
        return {"source_type": "external_sync", "available": False, "read_only": True}


class ContextAssemblyService:
    """The sole new composition entrypoint; all adapters are read-only."""

    def __init__(self, context: ProjectContext | None = None, *, vector_retriever: Callable[[str, int], list[dict[str, Any]]] | None = None) -> None:
        self.context = context or get_project_context()
        self.project = ProjectRef.from_context(self.context)
        self.store = DataStore(self.context)
        self.vector_retriever = vector_retriever

    def assemble(
        self,
        *,
        state: dict[str, Any],
        memory_index: dict[str, Any],
        query: str = "",
        story_spec: dict[str, Any] | None = None,
        characters: dict[str, Any] | None = None,
        world_bible: dict[str, Any] | None = None,
        purpose: str = "chapter_drafting",
    ) -> dict[str, Any]:
        profile = DEFAULT_PROFILES.get(purpose)
        if profile is None:
            raise ContextAssemblyError("CONTEXT_PROFILE_INVALID")
        if not isinstance(state, dict) or not isinstance(memory_index, dict):
            raise ContextAssemblyError("CONTEXT_SOURCE_UNAVAILABLE")
        safe_index = self._safe_memory_index(memory_index)
        # Keep the existing context representation stable while giving all new
        # consumers an explicit, project-scoped package and source manifest.
        from system.context_builder import _build_legacy_working_context
        # An injected retriever is a test/integration adapter; do not also
        # initialize the legacy vector client for the same request.
        working = _build_legacy_working_context(
            state, safe_index, query, story_spec or {}, characters or {}, world_bible or {},
            allow_vector=profile.allow_vector and self.vector_retriever is None,
        )
        vector = working.get("vector_retrieved_memories", []) if profile.allow_vector else []
        if self.vector_retriever is not None and profile.allow_vector and query:
            vector = self.vector_retriever(query, profile.vector_results)
        vector_rows = VectorRetrievalAdapter.read(vector if isinstance(vector, list) else [])[:profile.vector_results]
        working["vector_retrieved_memories"] = vector_rows
        if isinstance(working.get("retrieval_memory"), dict):
            working["retrieval_memory"]["vector_results"] = vector_rows

        recent = list(working.get("recent_chapters", []))[-profile.recent_chapters:]
        summaries = list(working.get("retrieved_summaries", []))[:profile.retrieval_results]
        recent_summaries = list((working.get("recent_memory", {}) or {}).get("recent_summaries", []))[:profile.summaries]
        working["recent_chapters"] = recent
        working["retrieved_summaries"] = summaries
        if isinstance(working.get("recent_memory"), dict):
            working["recent_memory"]["recent_summaries"] = recent_summaries

        canon = CanonMemoryAdapter(self.context).read()
        summary_rows = SummaryMemoryAdapter.read(working)
        selected, duplicates, conflicts = self._deduplicate(canon, summary_rows, vector_rows)
        manifest = {
            "selected_sources": selected,
            "excluded_duplicates": duplicates,
            "conflict_sources": conflicts,
            "priority": ["author_constraints", "canon_memory", "narrative_state", "planning_context", "recent_chapters", "working_version", "summary_memory", "vector_retrieval", "external_sync"],
        }
        working.update({
            "context_package_version": "1.0", "project_id": self.project.public_view().project_id,
            "purpose": purpose, "chapter_number": int(state.get("current_chapter", 0) or 0) + 1,
            "working_context": {"recent_chapters": recent, "recent_summaries": recent_summaries},
            "narrative_state": NarrativeStateAdapter.read(state), "canon_facts": canon,
            "chapter_summaries": summary_rows, "retrieved_memories": vector_rows,
            "constraints": working.get("global_memory", {}), "source_manifest": manifest,
            "selected_sources": selected, "excluded_duplicates": duplicates, "conflict_sources": conflicts,
            "budget": {"profile": purpose, "recent_chapters": profile.recent_chapters, "summaries": profile.summaries, "retrieval_results": profile.retrieval_results, "vector_results": profile.vector_results},
            "external_sync": ExternalSyncAdapter.read(), "read_only": True,
        })
        self._scrub_paths(working)
        return ContextPackage(
            project_id=self.project.public_view().project_id,
            purpose=purpose,
            chapter_number=int(state.get("current_chapter", 0) or 0) + 1,
            payload=working,
        ).as_dict()

    def _safe_memory_index(self, value: dict[str, Any]) -> dict[str, Any]:
        safe = copy.deepcopy(value)
        chapters = safe.get("chapters", [])
        if not isinstance(chapters, list):
            safe["chapters"] = []
            return safe
        for entry in chapters:
            if not isinstance(entry, dict):
                continue
            for key in ("chapter_path", "summary_path"):
                raw = str(entry.get(key, "") or "")
                if not raw:
                    continue
                candidate = Path(raw)
                candidate = (self.context.root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
                try:
                    candidate.relative_to(self.context.root)
                except ValueError:
                    entry[key] = (self.context.root / "data" / ".context-unavailable" / f"{key}-{entry.get('chapter_id', 'unknown')}").as_posix()
                else:
                    entry[key] = candidate.as_posix()
        return safe

    @staticmethod
    def _deduplicate(*collections: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        seen: dict[str, dict[str, Any]] = {}
        selected: list[dict[str, Any]] = []; duplicates: list[dict[str, Any]] = []; conflicts: list[dict[str, Any]] = []
        for collection in collections:
            for item in collection:
                source_id = str(item.get("source_id", ""))
                content = str(item.get("summary", item.get("short_summary", item.get("text", ""))))
                key = source_id or hashlib.sha256(content.encode("utf-8")).hexdigest()
                if key in seen:
                    if content and str(seen[key].get("summary", seen[key].get("short_summary", ""))) not in {"", content}:
                        conflicts.append({"source_id": key, "winner": seen[key].get("source_type"), "excluded": item.get("source_type")})
                    else:
                        duplicates.append({"source_id": key, "source_type": item.get("source_type")})
                    continue
                seen[key] = item
                selected.append({"source_type": item.get("source_type"), "source_id": key})
        return selected, duplicates, conflicts

    def _scrub_paths(self, value: Any) -> None:
        if isinstance(value, dict):
            for key, item in list(value.items()):
                if key in {"chapter_path", "summary_path", "source_path", "json_path", "markdown_path"}:
                    value[key] = self._relative(item)
                else:
                    self._scrub_paths(item)
        elif isinstance(value, list):
            for item in value:
                self._scrub_paths(item)

    def _relative(self, value: Any) -> str:
        raw = str(value or "")
        if not raw:
            return ""
        try:
            candidate = Path(raw)
            candidate = (self.context.root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
            return candidate.relative_to(self.context.root).as_posix()
        except (OSError, ValueError):
            return ""
