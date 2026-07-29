"""Thin production adapters for the shared Chapter lifecycle authority."""
from __future__ import annotations

from typing import Any, Literal

from core.project_context import ProjectContext
from system.chapter_lifecycle_service import ChapterLifecycleService


class ChapterLifecycleAdapter:
    """Delegate entry-specific calls without duplicating lifecycle semantics."""

    def __init__(
        self,
        context: ProjectContext,
        *,
        source: Literal["traditional", "simulator"],
    ) -> None:
        self.source = source
        self.service = ChapterLifecycleService(context)

    def resolve(self, **values: Any) -> dict[str, Any]:
        return self.service.resolve_next_chapter(**values)

    def create(self, **values: Any) -> dict[str, Any]:
        return self.service.create_next_chapter(**values)


class TraditionalChapterLifecycleAdapter(ChapterLifecycleAdapter):
    def __init__(self, context: ProjectContext) -> None:
        super().__init__(context, source="traditional")


class SimulatorChapterLifecycleAdapter(ChapterLifecycleAdapter):
    def __init__(self, context: ProjectContext) -> None:
        super().__init__(context, source="simulator")
