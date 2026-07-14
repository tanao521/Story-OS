"""Evidence-backed creative issues; never speculative market predictions."""
from __future__ import annotations

from typing import Any

from core.project_context import ProjectContext
from creative_loop.models import ISSUE_STATUSES, ISSUE_SEVERITIES, new_id, now_iso
from system.data_store import DataStore


class IssueDetector:
    def __init__(self, context: ProjectContext) -> None: self.context, self.store = context, DataStore(context)

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        rows = self.store.read_json("data/creative_loop/issues/index.json", default=[], expected_type=list) or []
        rows = [row for row in rows if not status or row.get("status") == status]
        return sorted(rows, key=lambda item: (item.get("status") != "open", item.get("created_at", "")), reverse=True)

    def detect(self, reflection: dict[str, Any], health: dict[str, Any]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for dimension, value in (health.get("dimensions") or {}).items():
            if value is not None and int(value) < 55:
                candidates.append(self._candidate(reflection, f"low_{dimension}", "plot" if "plot" in dimension or "pacing" in dimension else "consistency", "high" if int(value) < 40 else "medium", f"{dimension} 偏低", f"本章该维度为 {value} 分。", [f"health:{health['health_id']}"], [dimension], [f"下一章优先针对 {dimension} 设计一个可观察的改进动作。"] ))
        history = self.store.read_json("data/creative_loop/health/history.json", default=[], expected_type=list) or []
        recent = [row for row in history if row.get("chapter_id", 0) <= reflection["chapter_id"]][-3:]
        momentum = [row.get("dimensions", {}).get("plot_momentum") for row in recent]
        if len(momentum) == 3 and all(value is not None and int(value) < 55 for value in momentum):
            candidates.append(self._candidate(reflection, "main_plot_stagnation", "plot", "high", "主线推进连续不足", "最近三章的剧情推进指标均低于 55 分。", [f"health:{row.get('health_id')}" for row in recent], [], ["在下一章安排一个会改变局势的主线选择或信息揭示。"] ))
        index = self.list(); created = []
        for candidate in candidates:
            same = next((row for row in index if row.get("fingerprint") == candidate["fingerprint"] and row.get("status") == "open"), None)
            if same:
                same["evidence"] = candidate["evidence"]; same["updated_at"] = now_iso()
            else:
                index.append(candidate); created.append(candidate)
        self.store.write_json("data/creative_loop/issues/index.json", index, backup=True)
        return created

    def update_status(self, issue_id: str, status: str, reason: str = "") -> dict[str, Any]:
        if status not in ISSUE_STATUSES:
            raise ValueError("ISSUE_STATUS_INVALID")
        rows = self.list(); item = next((row for row in rows if row.get("issue_id") == issue_id), None)
        if not item:
            raise KeyError("ISSUE_NOT_FOUND")
        item.update({"status": status, "resolution_reason": reason[:500], "resolved_at": now_iso() if status == "resolved" else None, "updated_at": now_iso()})
        self.store.write_json("data/creative_loop/issues/index.json", rows, backup=True)
        return item

    def _candidate(self, reflection: dict[str, Any], issue_type: str, category: str, severity: str, title: str, description: str, source_ids: list[str], entities: list[str], suggestions: list[str]) -> dict[str, Any]:
        if severity not in ISSUE_SEVERITIES:
            severity = "medium"
        fingerprint = f"{issue_type}:{reflection['chapter_id']}"
        return {"schema_version": "13.0", "issue_id": new_id("issue"), "project_id": self.context.root.name, "chapter_id": reflection["chapter_id"], "issue_type": issue_type, "category": category, "severity": severity, "title": title, "description": description, "evidence": [{"chapter_id": reflection["chapter_id"], "reason": description, "source": source} for source in source_ids], "affected_entities": entities, "source_report_ids": source_ids, "status": "open", "suggestions": suggestions, "fingerprint": fingerprint, "created_at": now_iso(), "updated_at": now_iso(), "resolved_at": None}
