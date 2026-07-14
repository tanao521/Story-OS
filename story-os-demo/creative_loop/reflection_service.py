"""Version-bound, deterministic reflections of active canon chapters."""
from __future__ import annotations

from typing import Any

from analytics.service import AnalyticsService
from core.project_context import ProjectContext
from creative_loop.models import as_list, new_id, now_iso, score_100
from creative_loop.lifecycle import LifecycleService
from system.data_store import DataStore
from system.revision_service import CanonVersionNotFoundError, RevisionService


class ReflectionService:
    def __init__(self, context: ProjectContext) -> None:
        self.context, self.store = context, DataStore(context)

    def list(self, chapter_id: int | None = None) -> list[dict[str, Any]]:
        rows = []
        directory = self.store.ensure_directory(self.context.reflections_dir)
        for path in directory.glob("*.json"):
            row = self.store.read_json(path, default=None, expected_type=dict)
            if row and (chapter_id is None or int(row.get("chapter_id", 0)) == chapter_id):
                rows.append(row)
        return sorted(rows, key=lambda item: item.get("created_at", ""), reverse=True)

    def get(self, reflection_id: str) -> dict[str, Any]:
        row = self.store.read_json(f"data/creative_loop/reflections/{reflection_id}.json", default=None, expected_type=dict)
        if not row:
            raise KeyError("REFLECTION_NOT_FOUND")
        return row

    def reflect(self, chapter_id: int, *, force: bool = False, analysis_profile: str = "standard", prompt_version: str = "13.1") -> dict[str, Any]:
        canon = RevisionService(self.context).active_canon(chapter_id)
        cache_key = f"{chapter_id}:{canon['canon_version_id']}:{analysis_profile}:{prompt_version}"
        existing = next((row for row in self.list(chapter_id) if row.get("cache_key") == cache_key and row.get("status") == "completed"), None)
        if existing and not force:
            return existing
        plan = self.store.read_json("data/next_chapter_plan.json", default={}, expected_type=dict) or {}
        analytics = AnalyticsService(self.context).chapter(chapter_id, canon.get("content", ""))
        quality = self._latest_report("quality_reports", chapter_id)
        continuity = self._latest_report("continuity_reports", chapter_id)
        score = analytics.get("score", {}) if isinstance(analytics.get("score"), dict) else {}
        goal = str(plan.get("goal") or plan.get("summary") or "")
        reflection_id = new_id("reflection")
        result = {
            "schema_version": "13.0", "reflection_id": reflection_id, "project_id": self.context.root.name,
            "chapter_id": chapter_id, "chapter_number": chapter_id, "canon_version_id": canon["canon_version_id"],
            "planning_version_id": str(plan.get("planning_version_id") or plan.get("version_id") or ""),
            "context_record_id": str(plan.get("context_record_id") or ""), "status": "pending", "analysis_profile": analysis_profile,
            "prompt_version": prompt_version, "cache_key": cache_key,
            "goal_completion": {"score": score_100(score.get("total")), "completed_goals": [goal] if goal and score_100(score.get("total")) and score_100(score.get("total")) >= 60 else [], "missed_goals": [goal] if goal and (score_100(score.get("total")) or 0) < 60 else [], "unexpected_results": []},
            "plot_progress": self._notes("剧情推进", score_100(score.get("conflict_score")), analytics.get("score", {}).get("weak_points", [])),
            "character_progress": self._notes("人物一致性", score_100(score.get("character_score")), []),
            "relationship_progress": [], "foreshadowing_progress": [],
            "world_progress": self._notes("世界规则稳定性", score_100(score.get("world_score")), []),
            "strengths": [name for name, value in (("开场吸引力", score_100(score.get("hook_score"))), ("结尾钩子", score_100(score.get("ending_hook_score"))), ("节奏推进", score_100(score.get("pacing_score")))) if value is not None and value >= 70],
            "issues": list(as_list(score.get("weak_points"))) + list(as_list(continuity.get("issues")))[:4],
            "next_chapter_implications": list(as_list(score.get("suggestions")))[:5],
            "reader_feedback": quality.get("reader_simulation", {}) if isinstance(quality, dict) else {},
            "data_sources": [item for item in [
                {"type": "active_canon", "id": canon["canon_version_id"]},
                {"type": "chapter_analytics", "id": f"chapter_{chapter_id:03d}"},
                {"type": "quality_report", "id": quality.get("report_id", "") if isinstance(quality, dict) else ""},
                {"type": "continuity_report", "id": continuity.get("report_id", "") if isinstance(continuity, dict) else ""},
            ] if item["id"]],
            "warnings": ["未找到质量报告，已使用本地文本信号。"] if not quality else [],
            "created_at": now_iso(), "updated_at": now_iso(), "status_history": [],
        }
        lifecycle = LifecycleService(self.context)
        lifecycle.transition(result, "reflection", "running", operator="system", reason="开始章节复盘")
        lifecycle.transition(result, "reflection", "completed", operator="system", reason="本地复盘完成")
        self.store.write_json(f"data/creative_loop/reflections/{reflection_id}.json", result, backup=True)
        lifecycle.audit("reflection_completed", entity_type="reflection", entity_id=reflection_id, operator="system", details={"chapter_id": chapter_id, "cache_key": cache_key})
        return result

    def _latest_report(self, directory: str, chapter_id: int) -> dict[str, Any]:
        root = self.store.path(f"data/{directory}")
        if not root.exists():
            return {}
        rows = [self.store.read_json(path, default={}, expected_type=dict) or {} for path in root.glob(f"chapter_{chapter_id:03d}_*.json")]
        rows = [row for row in rows if row]
        return sorted(rows, key=lambda item: str(item.get("generated_at") or item.get("created_at") or ""), reverse=True)[0] if rows else {}

    @staticmethod
    def _notes(label: str, score: int | None, details: list[Any]) -> list[dict[str, Any]]:
        if score is None:
            return []
        return [{"dimension": label, "score": score, "details": [str(item) for item in details[:3]]}]
