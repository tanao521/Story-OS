"""Read-only compatibility views for pre-Evaluation-Engine report files."""
from __future__ import annotations

from typing import Any

from core.contracts import ProjectRef
from core.project_context import ProjectContext
from system.continuity_checker import load_continuity_report
from system.quality_checker import load_quality_report
from system.data_store import DataStore


class LegacyEvaluationAdapterError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class LegacyEvaluationAdapter:
    """Maps legacy files to safe views without writing reports or indexes."""

    def __init__(self, context: ProjectContext) -> None:
        self.context = context
        self.project = ProjectRef.from_context(context)
        self.store = DataStore(context)

    def quality_view(self, *, chapter_id: int, source_type: str, source_version: int) -> dict[str, Any]:
        self._validate(source_type, source_version)
        report = load_quality_report(chapter_id, source_type, source_version, self.context.data_dir)
        if not report:
            return {"exists": False, "source_format": "legacy", "read_only": True}
        return {
            "exists": True, "source_format": "legacy", "read_only": True,
            "overall_score": report.get("overall_score", 0), "scores": report.get("scores", {}),
            "flags": report.get("flags", []), "suggestions": report.get("suggestions", []),
            "reader_simulation": report.get("reader_simulation", {}), "checks": report.get("checks", {}),
        }

    def continuity_view(self, *, chapter_id: int, source_type: str, source_version: int, content_hash: str, previous_content_hash: str) -> dict[str, Any]:
        self._validate(source_type, source_version)
        report = load_continuity_report(chapter_id, source_type, source_version, self.context.data_dir, content_hash=content_hash, previous_content_hash=previous_content_hash)
        if not report:
            return {"exists": False, "chapter_id": chapter_id, "source_type": source_type, "source_version": source_version, "source_format": "legacy", "read_only": True}
        value = dict(report)
        value.update({"exists": True, "source_format": "legacy", "read_only": True})
        value.pop("source_path", None)
        return value

    @staticmethod
    def _validate(source_type: str, source_version: int) -> None:
        if source_type not in {"draft", "edited", "manual", "committed"} or int(source_version) < 1:
            raise LegacyEvaluationAdapterError("EVALUATION_LEGACY_FORMAT_UNSUPPORTED")
