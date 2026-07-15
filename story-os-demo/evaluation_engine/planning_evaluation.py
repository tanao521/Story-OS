"""Read-only long-form planning evaluation for Stage 15.3A.

The evaluator consumes existing planning-control services and persists only an
evaluation report.  It never changes slots, schedules, dependencies, contracts,
or other planning sources, and it has no model dependency.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from statistics import median
from typing import Any
from uuid import uuid4

from core.project_context import ProjectContext
from planning_engine import PlanningControlError, PlanningDependencyService
from planning_engine.control_service import PlanningControlService
from planning_engine.rolling_service import RollingWindowService
from planning_engine.scheduling_service import NarrativeSchedulingService
from system.data_store import DataReadError, DataStore, DataWriteError
from system.planning_service import load_planning

from .adapters.common import evidence, fingerprint
from .adapters.dependency_graph_adapter import adapt as adapt_dependency_graph
from .adapters.milestone_contract_adapter import adapt as adapt_milestone_contract
from .adapters.narrative_schedule_adapter import adapt as adapt_narrative_schedule
from .adapters.planning_strategy_adapter import adapt as adapt_planning_strategy
from .adapters.rolling_window_adapter import adapt as adapt_rolling_window
from .profiles import planning_default_profile


PLANNING_TARGETS = {"near_planning_window", "current_volume", "whole_book_planning"}
SEVERITY_RANK = {"blocking": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


class PlanningEvaluationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _now() -> str: return datetime.now(timezone.utc).isoformat()
def _hash(value: str) -> str: return sha256(value.encode("utf-8")).hexdigest()


class PlanningEvaluationService:
    """Materialize project-scoped planning reports from existing service output."""

    def __init__(self, context: ProjectContext) -> None:
        self.context, self.store = context, DataStore(context)
        self.project_id = context.root.resolve().as_posix()

    def overview(self) -> dict[str, Any]:
        sources = self._sources()
        scopes = self._available_scopes(sources)
        latest = self.list_reports(limit=50)
        by_scope: dict[str, dict[str, Any]] = {}
        for report in latest:
            key = self._scope_key(report.get("target_type", ""), report.get("target_ref", {}).get("scope_ref", {}))
            by_scope.setdefault(key, report)
        return {
            "available_scopes": scopes, "current_volume_id": sources["current_volume_id"],
            "current_window_id": (sources["window"] or {}).get("window_id"),
            "latest_reports": list(by_scope.values()), "source_health": sources["source_health"],
            "hard_issue_summary": [item for report in latest[:5] for item in report.get("hard_issues", [])][:5],
        }

    def generate(self, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        target_type = str(payload.get("target_type") or "")
        if target_type not in PLANNING_TARGETS:
            raise PlanningEvaluationError("PLANNING_EVALUATION_SCOPE_INVALID", "Unsupported planning evaluation target.")
        profile_id = str(payload.get("profile_id") or "planning-default-v1")
        profile = planning_default_profile() if profile_id == "planning-default-v1" else None
        if not profile:
            raise PlanningEvaluationError("PLANNING_EVALUATION_PROFILE_NOT_FOUND", "Planning evaluation profile was not found.")
        sources = self._sources()
        scope = self._resolve_scope(target_type, payload.get("scope_ref"), sources)
        snapshots = self._snapshots(sources, scope, profile)
        operation_id = str(payload.get("operation_id") or "").strip()
        if operation_id:
            previous = self._find_operation(operation_id)
            if previous:
                if previous.get("target_type") != target_type or previous.get("target_ref", {}).get("scope_ref") != scope or previous.get("source_snapshots") != snapshots:
                    raise PlanningEvaluationError("PLANNING_EVALUATION_OPERATION_CONFLICT", "operation_id belongs to a different planning scope or source snapshot.")
                return self._public(previous), True
        report = self._build(target_type, scope, profile, sources, snapshots, operation_id)
        self._persist(report)
        return self._public(report), False

    def list_reports(self, *, target_type: str = "", volume_id: str = "", window_id: str = "", status: str = "", limit: int = 30) -> list[dict[str, Any]]:
        rows = self._index().get("reports", [])
        reports: list[dict[str, Any]] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or row.get("category") != "planning": continue
            if target_type and row.get("target_type") != target_type: continue
            scope = row.get("scope_ref") if isinstance(row.get("scope_ref"), dict) else {}
            if volume_id and str(scope.get("volume_id") or "") != volume_id: continue
            if window_id and str(scope.get("window_id") or "") != window_id: continue
            item = self.store.read_json(str(row.get("path") or ""), default=None, expected_type=dict)
            if not item: continue
            item_status = self._status(item)
            if status and item_status != status: continue
            reports.append(self._public(item, status=item_status, compact=True))
        return sorted(reports, key=lambda item: str(item.get("created_at") or ""), reverse=True)[:max(1, min(int(limit or 30), 100))]

    def detail(self, evaluation_id: str) -> dict[str, Any]:
        row = next((item for item in self._index().get("reports", []) if isinstance(item, dict) and item.get("evaluation_id") == evaluation_id and item.get("category") == "planning"), None)
        if not row: raise PlanningEvaluationError("PLANNING_EVALUATION_SCOPE_NOT_FOUND", "Planning report was not found.")
        report = self.store.read_json(str(row.get("path") or ""), default=None, expected_type=dict)
        if not report: raise PlanningEvaluationError("PLANNING_EVALUATION_SOURCE_INVALID", "Planning report cannot be read.")
        return self._public(report)

    def _sources(self) -> dict[str, Any]:
        try:
            self._validate_project_sources()
            control = PlanningControlService(self.context)._read()
            rolling = RollingWindowService(self.context)
            dependency = PlanningDependencyService(self.context)
            scheduler = NarrativeSchedulingService(self.context)
            planning = load_planning(self.context)
            window = control.get("rolling_window") if isinstance(control.get("rolling_window"), dict) else None
            rolling_health = rolling.check_window_health()
            dependency_description, dependency_health = dependency.describe(), dependency.health()
            schedule_description, schedule_health = scheduler.describe(), scheduler.health()
            return {
                "control": control, "planning": planning, "window": window,
                "rolling_health": rolling_health, "dependency": dependency_description,
                "schedule": schedule_description, "current_volume_id": self._current_volume(control, planning),
                "source_health": {"rolling_window": rolling_health, "dependencies": dependency_health, "schedule": schedule_health},
                "adapters": {
                    "strategy": adapt_planning_strategy(control),
                    "rolling_window": adapt_rolling_window(window, rolling_health),
                    "dependency_graph": adapt_dependency_graph(dependency_description, dependency_health),
                    "narrative_schedule": adapt_narrative_schedule(schedule_description, schedule_health),
                    "milestone_contract": adapt_milestone_contract(control),
                },
            }
        except (DataReadError, PlanningControlError, OSError, ValueError, TypeError) as exc:
            raise PlanningEvaluationError("PLANNING_EVALUATION_SOURCE_INVALID", "Planning source data is invalid or unavailable.") from exc

    def _validate_project_sources(self) -> None:
        """Reject malformed or foreign materialized planning documents before adapters consume them."""
        paths = (
            self.context.planning_strategy_path, self.context.planning_milestones_path,
            self.context.volume_contracts_path, self.context.phase_contracts_path,
            self.context.rolling_window_path, self.context.planning_dependencies_path,
            self.context.planning_schedules_path, self.context.planning_locks_path,
            self.context.planning_conflicts_path,
        )
        for path in paths:
            if not self.store.exists(path):
                continue
            raw = self.store.read_json(path, strict=True)
            rows = raw if isinstance(raw, list) else [raw]
            if not isinstance(raw, (dict, list, type(None))):
                raise PlanningEvaluationError("PLANNING_EVALUATION_SOURCE_INVALID", "A planning source document has an invalid shape.")
            for row in rows:
                if isinstance(row, dict) and row.get("project_id") not in (None, "", self.project_id):
                    raise PlanningEvaluationError("PLANNING_EVALUATION_PROJECT_MISMATCH", "A planning source belongs to another project.")

    def _available_scopes(self, sources: dict[str, Any]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        window = sources["window"]
        output.append({"target_type": "near_planning_window", "scope_ref": {"window_id": (window or {}).get("window_id", "")}, "available": bool(window), "reason": "" if window else "rolling window is not materialized"})
        volumes = self._volumes(sources)
        output.append({"target_type": "current_volume", "scope_ref": {"volume_id": sources["current_volume_id"]}, "available": bool(sources["current_volume_id"]), "reason": "" if sources["current_volume_id"] else "current volume is unavailable", "volumes": volumes})
        output.append({"target_type": "whole_book_planning", "scope_ref": {}, "available": bool(sources["control"].get("strategy") or sources["planning"].get("volumes") or window), "reason": "planning strategy, volume, and window are all unavailable"})
        return output

    def _resolve_scope(self, target_type: str, raw_scope: Any, sources: dict[str, Any]) -> dict[str, Any]:
        scope = dict(raw_scope) if isinstance(raw_scope, dict) else {}
        if target_type == "near_planning_window":
            window = sources["window"]
            window_id = str(scope.get("window_id") or (window or {}).get("window_id") or "")
            if not window or not window_id or str(window.get("window_id")) != window_id:
                raise PlanningEvaluationError("PLANNING_EVALUATION_SCOPE_NOT_FOUND", "The requested rolling window does not exist.")
            return {"window_id": window_id}
        if target_type == "current_volume":
            volume_id = str(scope.get("volume_id") or sources["current_volume_id"] or "")
            if not volume_id or volume_id not in {str(item.get("volume_id")) for item in self._volumes(sources)}:
                raise PlanningEvaluationError("PLANNING_EVALUATION_SCOPE_NOT_FOUND", "The requested volume does not exist.")
            return {"volume_id": volume_id}
        return {}

    def _build(self, target_type: str, scope: dict[str, Any], profile: dict[str, Any], sources: dict[str, Any], snapshots: dict[str, Any], operation_id: str) -> dict[str, Any]:
        scoped = self._scoped(target_type, scope, sources)
        dimensions, issues = self._dimensions(scoped, sources, profile)
        gate_status, gate_reasons = self._gate(issues, sources, scoped)
        available = [row for row in dimensions if row["score"] is not None]
        denominator = sum(float(row["weight"]) for row in available)
        overall = round(sum(float(row["score"]) * float(row["weight"]) for row in available) / denominator, 1) if denominator else None
        confidence = round(sum(float(row["confidence"]) * float(row["weight"]) for row in available) / denominator, 2) if denominator else 0.0
        coverage = round(sum(float(row["coverage"]) * float(row["weight"]) for row in dimensions), 2)
        priority = sorted(self._dedupe(issues), key=lambda item: (SEVERITY_RANK.get(item["severity"], 9), -len(item["affected_dimensions"]), -float(item.get("evidence_reliability", 0))))
        return {"evaluation_id": f"planning_evaluation_{uuid4().hex}", "project_id": self.project_id, "category": "planning", "target_type": target_type, "target_ref": {"target_type": target_type, "scope_ref": scope}, "profile_id": profile["profile_id"], "profile_version": profile["version"], "scoring_rules_version": profile["scoring_rules_version"], "operation_id": operation_id, "gate_status": gate_status, "gate_reasons": gate_reasons, "overall_score": overall, "overall_confidence": confidence, "overall_coverage": coverage, "confidence": confidence, "dimensions": dimensions, "hard_issues": [item for item in priority if item["severity"] == "blocking"], "priority_issues": [item for item in priority if item["severity"] in {"blocking", "high", "medium"}], "suggestions": list(dict.fromkeys(item["suggestion"] for item in priority if item.get("suggestion"))), "source_snapshots": snapshots, "source_health": sources["source_health"], "model_usage_refs": [], "created_at": _now(), "created_by": "user"}

    def _scoped(self, target_type: str, scope: dict[str, Any], sources: dict[str, Any]) -> dict[str, Any]:
        window = sources["window"] or {}; all_slots = list(window.get("near_slots", [])) + list(window.get("mid_slots", []))
        schedules = list((sources["schedule"].get("schedules") or []))
        planning = sources["planning"]
        if target_type == "near_planning_window":
            slots = list(window.get("near_slots", [])); slot_ids = {str(item.get("slot_id")) for item in slots}
            schedules = [item for item in schedules if str(item.get("target_slot_id")) in slot_ids]
        elif target_type == "current_volume":
            volume_id = scope["volume_id"]
            chapters = [item for item in planning.get("chapters", []) if str(item.get("volume_id") or "") == volume_id]
            chapter_numbers = {int(item.get("chapter_number") or item.get("chapter_id") or 0) for item in chapters}
            slots = [item for item in all_slots if int(item.get("planned_chapter_number") or 0) in chapter_numbers or str(item.get("volume_id") or "") == volume_id]
            slot_ids = {str(item.get("slot_id")) for item in slots}; schedules = [item for item in schedules if str(item.get("target_slot_id")) in slot_ids]
        else:
            slots = all_slots
        return {"slots": slots, "schedules": schedules, "planning": planning, "scope": scope, "target_type": target_type}

    def _dimensions(self, scoped: dict[str, Any], sources: dict[str, Any], profile: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        slots, schedules, control, planning = scoped["slots"], scoped["schedules"], sources["control"], scoped["planning"]
        issues: list[dict[str, Any]] = []
        def row(key: str, score: float | None, coverage: float, confidence: float, evidence_rows: list[Any], local_issues: list[dict[str, Any]] = []) -> dict[str, Any]:
            spec = next(item for item in profile["dimensions"] if item["dimension_id"] == key)
            issues.extend(local_issues)
            return {"dimension_id": key, "display_name": spec["display_name"], "weight": spec["weight"], "score": None if score is None else round(max(0, min(100, score)), 1), "coverage": round(max(0, min(1, coverage)), 2), "confidence": round(max(0, min(1, confidence)), 2), "status": "available" if score is not None else "insufficient_evidence", "source_type": "planning_services", "evidence": [self._public_evidence(item) for item in evidence_rows], "issues": local_issues, "suggestions": list(dict.fromkeys(item["suggestion"] for item in local_issues if item.get("suggestion")))}
        strategy = control.get("strategy") or {}; milestones = control.get("milestones") or []; contracts = (control.get("volume_contracts") or []) + (control.get("phase_contracts") or [])
        structural_coverage = sum(bool(value) for value in (strategy, milestones, contracts, slots)) / 4
        structural_issues = [] if structural_coverage >= .75 else [self._issue("structural_gap", "high" if structural_coverage < .5 else "medium", "Planning structure has incomplete strategic coverage.", "Check strategy, milestones, contracts, and rolling slots before committing downstream plans.", "structural_completeness")]
        dimensions = [row("structural_completeness", 45 + structural_coverage * 55 if structural_coverage else None, structural_coverage, .8 * structural_coverage, [evidence("planning_strategy", "strategy", "planning strategy") ] if strategy else [], structural_issues)]

        dep = sources["dependency"]; dep_health = sources["source_health"].get("dependencies") or {}; dep_issues = []
        for item in dep_health.get("issues", []):
            code = str(item.get("code") or "")
            severity = "blocking" if code in {"PLANNING_DEPENDENCY_CYCLE", "PLANNING_DEPENDENCY_SOURCE_MISSING"} else "high"
            dep_issues.append(self._issue("dependency_cycle" if "CYCLE" in code else "invalid_reference", severity, code.replace("_", " "), "Review the referenced dependency nodes and ordering.", "causal_dependency", node_refs=[str(item.get("dependency_id") or "")]))
        dependency_count = len(dep.get("dependencies") or [])
        dimensions.append(row("causal_dependency", 92 - min(60, len(dep_issues) * 25) if dependency_count or dep_issues else None, 1.0 if dependency_count else 0, .88 if dependency_count else 0, [evidence("dependency_graph", "dependencies", f"{dependency_count} dependencies")], dep_issues))

        plot_rows = [item for item in schedules if item.get("subject_type") == "plot_thread" and item.get("status") not in {"cancelled", "elapsed"}]
        plot_issues = [] if plot_rows else [self._issue("plot_progression_gap", "high", "No active plot-thread progression is scheduled in this scope.", "Check whether the main plot is intentionally paused or needs an advance, escalation, or reveal.", "plot_progression")]
        dimensions.append(row("plot_progression", 80 if plot_rows else None, min(1, len(plot_rows) / 2), .72 if plot_rows else 0, [evidence("narrative_schedule", str(item.get("schedule_id")), str(item.get("schedule_action") or "plot action")) for item in plot_rows], plot_issues))

        intensities = [float(item.get("intensity") or item.get("tension") or 0) for item in slots if item.get("intensity") is not None or item.get("tension") is not None]
        pacing_issues: list[dict[str, Any]] = []
        if len(intensities) >= 3 and max(intensities) == min(intensities): pacing_issues.append(self._issue("pacing_flat", "medium", "Planning intensity is flat across the evaluated slots.", "Check conflict, escalation, reveal, and recovery distribution.", "pacing_tension"))
        inferred = bool(slots) and not intensities
        dimensions.append(row("pacing_tension", (75 if inferred else 82 - len(pacing_issues) * 15) if slots else None, 1 if intensities else .45 if slots else 0, .45 if inferred else .75 if intensities else 0, [evidence("rolling_window", str(item.get("slot_id")), "slot tension" if intensities else "slot purpose inferred") for item in slots], pacing_issues))

        character_rows = [item for item in schedules if item.get("subject_type") == "character_arc" and item.get("status") not in {"cancelled", "elapsed"}]
        character_issues = [] if character_rows else [self._issue("character_arc_insufficient", "medium", "No structured character-arc schedule exists in this scope.", "Review character arc coverage; absence is insufficient evidence, not a zero score.", "character_arc")]
        dimensions.append(row("character_arc", 78 if character_rows else None, min(1, len(character_rows) / 2), .7 if character_rows else 0, [evidence("narrative_schedule", str(item.get("schedule_id")), "character arc action") for item in character_rows], character_issues))

        foreshadow_rows = [item for item in schedules if item.get("subject_type") == "foreshadowing" and item.get("status") not in {"cancelled", "elapsed"}]
        foreshadow_issues = self._foreshadow_issues(foreshadow_rows)
        dimensions.append(row("foreshadowing", 85 - len(foreshadow_issues) * 25 if foreshadow_rows else None, min(1, len(foreshadow_rows) / 2), .78 if foreshadow_rows else 0, [evidence("narrative_schedule", str(item.get("schedule_id")), str(item.get("schedule_action") or "foreshadow action")) for item in foreshadow_rows], foreshadow_issues))

        load_issues, load_score = self._load(slots, schedules)
        dimensions.append(row("chapter_load", load_score, 1 if slots else 0, .75 if slots else 0, [evidence("rolling_window", str(item.get("slot_id")), "chapter slot load") for item in slots], load_issues))

        milestone_actions = [item for item in schedules if item.get("subject_type") in {"milestone", "volume_contract", "phase_contract"} and item.get("status") not in {"cancelled", "elapsed"}]
        milestone_coverage = min(1, len(milestone_actions) / max(1, len(milestones) + len(contracts))) if (milestones or contracts) else 0
        milestone_issues = [] if milestone_coverage >= .5 else [self._issue("milestone_alignment_gap", "high" if milestones or contracts else "medium", "Milestones or contracts lack executable schedule coverage.", "Check preparation and consequence slots for each key milestone or contract.", "milestone_alignment")]
        dimensions.append(row("milestone_alignment", 50 + milestone_coverage * 50 if (milestones or contracts) else None, milestone_coverage, .8 * milestone_coverage, [evidence("planning_control", str(item.get("schedule_id")), "milestone or contract schedule") for item in milestone_actions], milestone_issues))
        return dimensions, issues

    def _gate(self, issues: list[dict[str, Any]], sources: dict[str, Any], scoped: dict[str, Any]) -> tuple[str, list[str]]:
        gate_issues = issues
        rolling = sources["rolling_health"]
        if rolling.get("status") == "reanchor_required": gate_issues.append(self._issue("reanchor_required", "blocking", "Rolling window requires re-anchoring.", "Resolve rolling-window anchor sources before using this plan.", "structural_completeness"))
        for item in (sources["source_health"].get("schedule") or {}).get("issues", []):
            code = str(item.get("code") or "")
            if code in {"NARRATIVE_SCHEDULE_INVALID_SLOT", "NARRATIVE_SCHEDULE_INVALID_SUBJECT"}:
                gate_issues.append(self._issue("invalid_reference", "blocking", code, "Repair the invalid planning reference before evaluation can pass.", "causal_dependency"))
            elif "ORDER" in code and "DEPENDENCY" in code:
                gate_issues.append(self._issue("hard_dependency_order", "blocking", code, "Restore the required dependency order before using this plan.", "causal_dependency"))
        for conflict in (sources["control"].get("conflicts") or []):
            if not isinstance(conflict, dict):
                continue
            kind = " ".join(str(conflict.get(key) or "") for key in ("entity_type", "conflict_type", "code", "message")).lower()
            if "contract" in kind and str(conflict.get("status") or "open").lower() not in {"resolved", "closed"}:
                gate_issues.append(self._issue("locked_contract_conflict", "blocking", "A locked planning contract conflicts with the current plan.", "Resolve the contract conflict through an author decision before using this plan.", "milestone_alignment"))
        if any(item["issue_type"] == "invalid_reference" for item in gate_issues): return "invalid", [item["title"] for item in gate_issues if item["issue_type"] == "invalid_reference"]
        if any(item["severity"] == "blocking" for item in gate_issues): return "blocked", [item["title"] for item in gate_issues if item["severity"] == "blocking"]
        if any(item["severity"] == "high" for item in gate_issues): return "attention", [item["title"] for item in gate_issues if item["severity"] == "high"]
        return "pass", []

    def _foreshadow_issues(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in rows: groups.setdefault(str((item.get("subject_ref") or {}).get("subject_id") or ""), []).append(item)
        issues = []
        for subject, entries in groups.items():
            positions = [(int(item.get("target_chapter_number") or 0), str(item.get("schedule_action") or "")) for item in entries]
            plants = [chapter for chapter, action in positions if action in {"plant", "reinforce", "misdirect"}]
            payoffs = [chapter for chapter, action in positions if action == "payoff"]
            if payoffs and (not plants or min(payoffs) < min(plants)):
                issues.append(self._issue("payoff_before_plant", "blocking", f"Foreshadow payoff precedes its plant: {subject}.", "Move or clarify the plant/reinforcement before the payoff.", "foreshadowing", schedule_refs=[subject]))
        return issues

    def _load(self, slots: list[dict[str, Any]], schedules: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float | None]:
        if not slots: return [], None
        counts = {str(slot.get("slot_id")): 1 if slot.get("purpose") else 0 for slot in slots}
        for item in schedules:
            slot = str(item.get("target_slot_id") or "")
            if slot in counts and item.get("status") not in {"cancelled", "elapsed"}: counts[slot] += 1
        values = list(counts.values()); middle = median(values); issues = []
        for slot_id, value in counts.items():
            if value >= middle + 3: issues.append(self._issue("chapter_overload", "medium", f"Chapter slot {slot_id} is relatively overloaded.", "Review whether too many planning duties converge in this slot.", "chapter_load", slot_refs=[slot_id]))
            if value == 0: issues.append(self._issue("chapter_underload", "low", f"Chapter slot {slot_id} has no structured planning duty.", "Check whether this slot intentionally provides recovery or needs a defined purpose.", "chapter_load", slot_refs=[slot_id]))
        return issues, 90 - min(50, len(issues) * 12)

    def _issue(self, issue_type: str, severity: str, title: str, suggestion: str, dimension: str, *, node_refs: list[str] | None = None, slot_refs: list[str] | None = None, schedule_refs: list[str] | None = None) -> dict[str, Any]:
        refs = {"node_refs": [item for item in node_refs or [] if item], "slot_refs": [item for item in slot_refs or [] if item], "schedule_refs": [item for item in schedule_refs or [] if item]}
        value = {"issue_id": fingerprint(self.project_id, issue_type, *refs["node_refs"], *refs["slot_refs"], *refs["schedule_refs"], title), "issue_type": issue_type, "severity": severity, "title": title, "description": title, "source_adapter": "planning_evaluation", "fixability": "author_decision_required" if severity != "info" else "not_actionable", "evidence_refs": [], "location_refs": [], "affected_dimensions": [dimension], "suggestion": suggestion, "fingerprint": fingerprint(self.project_id, issue_type, *refs["node_refs"], *refs["slot_refs"], *refs["schedule_refs"]), "evidence_reliability": .8, **refs}
        return value

    def _dedupe(self, issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: dict[str, dict[str, Any]] = {}
        for item in issues:
            key = str(item["fingerprint"])
            if key not in rows: rows[key] = dict(item)
            else: rows[key]["affected_dimensions"] = sorted(set(rows[key]["affected_dimensions"]) | set(item["affected_dimensions"]))
        return list(rows.values())

    def _snapshots(self, sources: dict[str, Any], scope: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
        def file(path: Any) -> str:
            value = self.store.read_text(path, default="") or ""
            return _hash(value) if value else ""
        window = sources["window"] or {}
        return {"strategy_hash": file(self.context.planning_strategy_path), "milestone_hash": file(self.context.planning_milestones_path), "contract_hash": _hash(file(self.context.volume_contracts_path) + file(self.context.phase_contracts_path)), "rolling_window_hash": file(self.context.rolling_window_path), "dependency_hash": file(self.context.planning_dependencies_path), "schedule_hash": file(self.context.planning_schedules_path), "planning_hash": file(self.context.data_dir / "story_planning.json"), "dependency_revision": (sources["dependency"].get("dependency_revision") or 0), "schedule_revision": (sources["schedule"].get("schedule_revision") or 0), "window_revision": window.get("window_revision", 0), "slot_hash": _hash(str(list(window.get("near_slots", [])) + list(window.get("mid_slots", [])))), "scope_ref": scope, "planning_profile_version": profile["version"]}

    def _status(self, report: dict[str, Any]) -> str:
        if report.get("status_override") == "superseded": return "superseded"
        try:
            sources = self._sources(); profile = planning_default_profile(); current = self._snapshots(sources, dict(report.get("target_ref", {}).get("scope_ref") or {}), profile)
            return "current" if current == report.get("source_snapshots") else "stale"
        except PlanningEvaluationError: return "invalid"

    def _persist(self, report: dict[str, Any]) -> None:
        key = self._scope_key(report["target_type"], report["target_ref"]["scope_ref"]); path = f"data/evaluations/planning/{key}/{report['evaluation_id']}.json"
        try:
            self.store.write_json(path, report)
            index = self._index(); rows = [row for row in index.get("reports", []) if isinstance(row, dict)]
            for row in rows:
                if row.get("category") == "planning" and self._scope_key(str(row.get("target_type") or ""), row.get("scope_ref") if isinstance(row.get("scope_ref"), dict) else {}) == key:
                    previous = self.store.read_json(str(row.get("path") or ""), default=None, expected_type=dict)
                    if previous and self._status(previous) == "current": previous["status_override"] = "superseded"; self.store.write_json(str(row["path"]), previous)
            rows.append({"evaluation_id": report["evaluation_id"], "category": "planning", "target_type": report["target_type"], "scope_ref": report["target_ref"]["scope_ref"], "created_at": report["created_at"], "path": path})
            self.store.write_json("data/evaluations/index.json", {"reports": rows})
        except DataWriteError as exc:
            raise PlanningEvaluationError("PLANNING_EVALUATION_WRITE_FAILED", "Planning evaluation report could not be saved.") from exc

    def _index(self) -> dict[str, Any]: return self.store.read_json("data/evaluations/index.json", default={"reports": []}, expected_type=dict) or {"reports": []}
    def _find_operation(self, operation_id: str) -> dict[str, Any] | None:
        row = next((item for item in self._index().get("reports", []) if isinstance(item, dict) and item.get("category") == "planning" and item.get("operation_id") == operation_id), None)
        # operation_id is stored in the report, not duplicated in the compact index.
        for item in self._index().get("reports", []):
            if isinstance(item, dict) and item.get("category") == "planning":
                report = self.store.read_json(str(item.get("path") or ""), default=None, expected_type=dict)
                if report and report.get("operation_id") == operation_id: return report
        return None
    def _scope_key(self, target_type: str, scope: dict[str, Any]) -> str:
        raw = f"{target_type}|{scope.get('window_id','')}|{scope.get('volume_id','')}"; return sha256(raw.encode("utf-8")).hexdigest()[:16]
    def _public_evidence(self, item: Any) -> dict[str, Any]:
        return {"evidence_id": item.evidence_id, "source_type": item.source_type, "source_ref": item.source_ref, "summary": item.summary, "reliability": item.reliability, "location": item.location} if hasattr(item, "evidence_id") else dict(item)
    def _public(self, report: dict[str, Any], *, status: str | None = None, compact: bool = False) -> dict[str, Any]:
        value = dict(report); value["status"] = status or self._status(report)
        if compact: value.pop("source_snapshots", None); value.pop("source_health", None)
        return value
    def _current_volume(self, control: dict[str, Any], planning: dict[str, Any]) -> str:
        state = self.store.read_json("data/state.json", default={}, expected_type=dict) or {}
        explicit = str(state.get("current_volume_id") or "")
        volumes = self._volumes({"control": control, "planning": planning})
        if explicit and any(str(item.get("volume_id")) == explicit for item in volumes): return explicit
        return str(volumes[0].get("volume_id") or "") if volumes else ""
    def _volumes(self, sources: dict[str, Any]) -> list[dict[str, Any]]:
        planning = sources["planning"]; rows = planning.get("volumes", []) if isinstance(planning.get("volumes"), list) else []
        return [item for item in rows if isinstance(item, dict) and item.get("volume_id")]
