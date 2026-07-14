"""Author-controlled strategy proposal lifecycle with source-version checks."""
from __future__ import annotations

from typing import Any

from core.project_context import ProjectContext
from creative_loop.models import PROPOSAL_STATUSES, as_list, new_id, now_iso
from creative_loop.lifecycle import LifecycleService
from system.data_store import DataStore
from system.revision_service import RevisionService


class ProposalService:
    def __init__(self, context: ProjectContext) -> None: self.context, self.store = context, DataStore(context)

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        root = self.store.ensure_directory(self.context.creative_proposals_dir); rows=[]
        for path in root.glob("*.json"):
            row = self.store.read_json(path, default=None, expected_type=dict)
            if row and (not status or row.get("status") == status): rows.append(row)
        return sorted(rows, key=lambda item: item.get("created_at", ""), reverse=True)

    def get(self, proposal_id: str) -> dict[str, Any]:
        row = self.store.read_json(f"data/creative_loop/proposals/{proposal_id}.json", default=None, expected_type=dict)
        if not row: raise KeyError("PROPOSAL_NOT_FOUND")
        return row

    def create(self, *, issue_ids: list[str], reflection_ids: list[str], health_ids: list[str], scope: dict[str, Any] | None = None, title: str = "") -> dict[str, Any]:
        issues = {row.get("issue_id"): row for row in self.store.read_json("data/creative_loop/issues/index.json", default=[], expected_type=list) or []}
        selected = [issues[item] for item in issue_ids if item in issues]
        chapter = max([int(item.get("chapter_id", 0)) for item in selected] or [0])
        canon_id = ""
        if chapter:
            try: canon_id = RevisionService(self.context).active_canon(chapter)["canon_version_id"]
            except Exception: pass
        changes = [suggestion for item in selected for suggestion in as_list(item.get("suggestions"))][:6]
        proposal = {"schema_version": "13.1", "proposal_id": new_id("proposal"), "project_id": self.context.root.name, "proposal_type": "future_strategy", "scope": scope or {"chapter_start": chapter + 1 if chapter else None, "chapter_end": chapter + 3 if chapter else None}, "title": title or (selected[0]["title"] if selected else "后续创作策略"), "reason": "；".join(item.get("description", "") for item in selected) or "基于作者手动创建的策略提案。", "source_issue_ids": issue_ids, "source_reflection_ids": reflection_ids, "source_health_ids": health_ids, "source_canon_version_id": canon_id, "recommended_changes": changes, "preserved_elements": [], "expected_effects": ["改善相关创作维度；实际效果将在后续章节中以相关性方式复盘。"], "risks": ["提案不会自动改写计划或正文，仍需作者在后续创作中选择采用。"], "affected_entities": [entity for item in selected for entity in as_list(item.get("affected_entities"))], "status": "pending", "status_history": [], "author_decision": {}, "created_at": now_iso(), "resolved_at": None}
        self.store.write_json(f"data/creative_loop/proposals/{proposal['proposal_id']}.json", proposal, backup=True)
        LifecycleService(self.context).audit("proposal_created", entity_type="proposal", entity_id=proposal["proposal_id"], operator="system", details={"issue_ids": issue_ids})
        return proposal

    def decide(self, proposal_id: str, status: str, *, accepted_changes: list[str] | None = None, note: str = "") -> dict[str, Any]:
        if status not in PROPOSAL_STATUSES or status in {"pending", "expired", "applied"}: raise ValueError("PROPOSAL_STATUS_INVALID")
        proposal = self.get(proposal_id)
        self._assert_fresh(proposal)
        LifecycleService(self.context).transition(proposal, "proposal", status, operator="user", reason=note or "作者作出提案决定")
        proposal.update({"author_decision": {"accepted_changes": [str(item) for item in (accepted_changes or [])], "note": note[:1000], "decided_at": now_iso()}, "resolved_at": now_iso()})
        self.store.write_json(f"data/creative_loop/proposals/{proposal_id}.json", proposal, backup=True)
        LifecycleService(self.context).audit(f"proposal_{status}", entity_type="proposal", entity_id=proposal_id, operator="user", details={"accepted_changes": proposal["author_decision"]["accepted_changes"]})
        return proposal

    def _assert_fresh(self, proposal: dict[str, Any]) -> None:
        chapter = int((proposal.get("scope") or {}).get("chapter_start") or 1) - 1
        source = str(proposal.get("source_canon_version_id") or "")
        if source and chapter > 0:
            try: current = RevisionService(self.context).active_canon(chapter)["canon_version_id"]
            except Exception: return
            if current != source:
                LifecycleService(self.context).transition(proposal, "proposal", "expired", operator="system", reason="来源正史版本已变化")
                proposal.update({"resolved_at": now_iso()})
                self.store.write_json(f"data/creative_loop/proposals/{proposal['proposal_id']}.json", proposal, backup=True)
                raise RuntimeError("PROPOSAL_SOURCE_STALE")
