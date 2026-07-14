"""Pattern candidates require author confirmation before entering author memory."""
from __future__ import annotations

from typing import Any

from author_memory.experience_manager import ExperienceManager
from core.project_context import ProjectContext
from creative_loop.models import new_id, now_iso
from creative_loop.lifecycle import LifecycleService
from system.data_store import DataStore


class PatternService:
    def __init__(self, context: ProjectContext) -> None: self.context, self.store = context, DataStore(context)

    def list(self) -> list[dict[str, Any]]:
        root = self.store.ensure_directory(self.context.creative_patterns_dir); rows=[]
        for path in root.glob("*.json"):
            row=self.store.read_json(path, default=None, expected_type=dict)
            if row: rows.append(row)
        return sorted(rows, key=lambda item: item.get("created_at", ""), reverse=True)

    def propose(self, kind: str, evidence: list[dict[str, Any]], summary: str, conditions: list[str] | None = None) -> dict[str, Any]:
        if kind not in {"success", "failure"}: raise ValueError("PATTERN_KIND_INVALID")
        if len(evidence) < 2: raise ValueError("PATTERN_EVIDENCE_INSUFFICIENT")
        row={"schema_version":"13.1", "pattern_id":new_id("pattern"), "project_id":self.context.root.name, "kind":kind, "summary":summary[:600], "evidence":evidence, "conditions":conditions or [], "status":"pending_confirmation", "confirmed":False, "source":"creative_loop", "created_at":now_iso(), "confirmed_at":None, "author_memory_experience_id":None}
        self.store.write_json(f"data/creative_loop/patterns/{row['pattern_id']}.json",row,backup=True); return row

    def decide(self, pattern_id: str, confirm: bool, note: str = "") -> dict[str, Any]:
        row=self.store.read_json(f"data/creative_loop/patterns/{pattern_id}.json",default=None,expected_type=dict)
        if not row: raise KeyError("PATTERN_NOT_FOUND")
        if row.get("status") != "pending_confirmation": raise RuntimeError("PATTERN_ALREADY_DECIDED")
        row.update({"status":"confirmed" if confirm else "rejected", "confirmed":bool(confirm), "decision_note":note[:600], "confirmed_at":now_iso() if confirm else None})
        if confirm:
            manager=ExperienceManager(self.context)
            if row["kind"] == "success": memory=manager.add_success({"name":row["summary"],"conditions":row.get("conditions",[]),"effect":"来自创作闭环的作者确认模式。","source":"creative_loop","confirmed":True,"confirmed_at":row["confirmed_at"]})
            else: memory=manager.add_failure({"problem":row["summary"],"reason":"来自创作闭环的证据汇总。","lesson":note or "后续创作中避免重复出现该模式。","applies_to":row.get("conditions",[]),"source":"creative_loop","confirmed":True,"confirmed_at":row["confirmed_at"]})
            row["author_memory_experience_id"]=memory.get("id")
        self.store.write_json(f"data/creative_loop/patterns/{pattern_id}.json",row,backup=True)
        LifecycleService(self.context).audit("pattern_confirmed" if confirm else "pattern_rejected", entity_type="pattern", entity_id=pattern_id, operator="user", details={"author_memory_experience_id": row.get("author_memory_experience_id")})
        return row
