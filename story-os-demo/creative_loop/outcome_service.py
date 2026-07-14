"""Correlational follow-up for author-selected strategies; never claims causation."""
from __future__ import annotations

from typing import Any

from core.project_context import ProjectContext
from creative_loop.models import new_id, now_iso
from creative_loop.lifecycle import LifecycleService
from system.data_store import DataStore


class OutcomeService:
    def __init__(self, context: ProjectContext) -> None: self.context, self.store = context, DataStore(context)

    def list(self) -> list[dict[str, Any]]:
        root=self.store.ensure_directory(self.context.creative_outcomes_dir); rows=[]
        for path in root.glob("*.json"):
            row=self.store.read_json(path,default=None,expected_type=dict)
            if row: rows.append(row)
        return sorted(rows,key=lambda item:item.get("created_at",""),reverse=True)

    def evaluate(self, proposal: dict[str, Any], after_chapter_id: int) -> dict[str, Any]:
        if proposal.get("status") not in {"accepted", "partially_accepted", "applied"}:
            raise ValueError("PROPOSAL_NOT_ACCEPTED")
        history=self.store.read_json("data/creative_loop/health/history.json",default=[],expected_type=list) or []
        before=next((row for row in history if row.get("health_id") in proposal.get("source_health_ids",[])),None)
        after=next((row for row in reversed(history) if int(row.get("chapter_id",0)) >= after_chapter_id),None)
        dimensions={}; known=0
        for key in set((before or {}).get("dimensions",{})) | set((after or {}).get("dimensions",{})):
            left=(before or {}).get("dimensions",{}).get(key); right=(after or {}).get("dimensions",{}).get(key)
            if left is None or right is None: dimensions[key]=None
            else: dimensions[key]=int(right)-int(left); known+=1
        status="evaluated" if before and after and known else "insufficient_data"
        row={"schema_version":"13.0","outcome_id":new_id("outcome"),"project_id":self.context.root.name,"proposal_id":proposal["proposal_id"],"before_health_id":(before or {}).get("health_id"),"after_health_id":(after or {}).get("health_id"),"after_chapter_id":after_chapter_id,"dimension_changes":dimensions,"status":status,"conclusion":"这是前后指标的相关性比较，不能证明策略导致了变化。" if status=="evaluated" else "缺少足够的前后健康记录，暂不作效果判断。","created_at":now_iso()}
        self.store.write_json(f"data/creative_loop/outcomes/{row['outcome_id']}.json",row,backup=True)
        LifecycleService(self.context).audit("strategy_outcome_evaluated", entity_type="outcome", entity_id=row["outcome_id"], operator="system", details={"proposal_id": proposal["proposal_id"], "status": status})
        return row
