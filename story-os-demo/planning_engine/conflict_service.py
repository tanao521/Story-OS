"""Deterministic, low-risk planning conflict checks."""
from __future__ import annotations

from typing import Any

from .models import content_hash, new_id, now


class ConflictService:
    def scan(self, project_id: str, strategy: dict[str, Any] | None, milestones: list[dict[str, Any]], volume_contracts: list[dict[str, Any]], phase_contracts: list[dict[str, Any]], locks: list[dict[str, Any]], source_service: Any) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        blueprint = source_service.blueprint_projection()
        if strategy:
            for field in ("central_conflict", "ending_direction"):
                saved, current = strategy.get(field), blueprint["fields"].get("core_conflict" if field == "central_conflict" else field)
                if saved not in (None, "") and current not in (None, "") and saved != current:
                    findings.append(self._finding(project_id, "story_strategy", strategy.get("strategy_id", strategy.get("id", "")), field, "source_value_conflict", saved, current, strategy.get("source_refs", [])))
        for contract in phase_contracts:
            if not source_service.phase_exists(contract.get("phase_ref", {})):
                findings.append(self._finding(project_id, "phase_contract", contract.get("contract_id", contract.get("id", "")), "phase_ref", "reference_missing", contract.get("phase_ref"), None, contract.get("source_refs", [])))
        for contract in volume_contracts:
            if not source_service.volume_exists(contract.get("volume_ref", {})):
                findings.append(self._finding(project_id, "volume_contract", contract.get("contract_id", contract.get("id", "")), "volume_ref", "reference_missing", contract.get("volume_ref"), None, contract.get("source_refs", [])))
        for milestone in milestones:
            scope = milestone.get("target_scope", {})
            phase_ref = scope.get("phase_ref") if isinstance(scope, dict) else None
            if isinstance(phase_ref, dict) and phase_ref and not source_service.phase_exists(phase_ref):
                findings.append(self._finding(project_id, "narrative_milestone", milestone.get("milestone_id", milestone.get("id", "")), "target_scope.phase_ref", "reference_missing", phase_ref, None, milestone.get("source_refs", [])))
        return findings

    def _finding(self, project_id: str, entity_type: str, entity_id: str, field: str, kind: str, saved: Any, current: Any, refs: list[dict[str, Any]]) -> dict[str, Any]:
        return {"schema_version": "1.0", "project_id": project_id, "conflict_id": new_id("conflict"), "conflict_type": kind, "entity_type": entity_type, "entity_id": entity_id, "field": field, "severity": "warning", "sources": [{"authority": "planning_control", "value": saved, "source_ref": refs}, {"authority": "story_blueprint", "value": current, "source_ref": {}}], "status": "open", "resolution": None, "created_at": now(), "resolved_at": None, "fingerprint": content_hash([entity_type, entity_id, field, kind, saved, current])}
