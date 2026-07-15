"""Read-only historical comparison for long-form planning evaluations."""
from __future__ import annotations

from hashlib import sha256
from typing import Any

from core.project_context import ProjectContext
from .planning_evaluation import PlanningEvaluationError, PlanningEvaluationService, SEVERITY_RANK


GATE_RANK = {"pass": 3, "attention": 2, "blocked": 1}


class PlanningComparisonError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _scope(report: dict[str, Any]) -> dict[str, Any]:
    target = report.get("target_ref") if isinstance(report.get("target_ref"), dict) else {}
    value = target.get("scope_ref") if isinstance(target.get("scope_ref"), dict) else report.get("scope_ref")
    return _normalise(value) if isinstance(value, dict) else {}


def _normalise(value: Any) -> Any:
    """Return a comparison-safe, order-independent planning reference."""
    if isinstance(value, dict):
        return {str(key): _normalise(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, list):
        return [_normalise(item) for item in value]
    return value


def _issues(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for key in ("hard_issues", "priority_issues"):
        for issue in report.get(key, []) if isinstance(report.get(key), list) else []:
            if isinstance(issue, dict) and issue.get("fingerprint"):
                rows.setdefault(str(issue["fingerprint"]), issue)
    return rows


class PlanningEvaluationComparisonService:
    """Compares persisted reports only; it writes neither reports nor plans."""

    def __init__(self, context: ProjectContext) -> None:
        self.context = context
        self.planning = PlanningEvaluationService(context)

    def comparable_reports(self, evaluation_id: str) -> list[dict[str, Any]]:
        current = self._report(evaluation_id)
        rows: list[dict[str, Any]] = []
        for item in self.planning.list_reports(limit=100):
            if item.get("evaluation_id") == evaluation_id or str(item.get("created_at") or "") >= str(current.get("created_at") or ""):
                continue
            try:
                candidate = self._report(str(item.get("evaluation_id") or ""))
                self._assert_comparable(candidate, current)
                if candidate.get("status") == "invalid" or candidate.get("gate_status") == "invalid":
                    continue
            except PlanningComparisonError:
                continue
            rows.append({"evaluation_id": candidate["evaluation_id"], "created_at": candidate.get("created_at"), "overall_score": candidate.get("overall_score"), "gate_status": candidate.get("gate_status"), "coverage": candidate.get("overall_coverage"), "status": candidate.get("status"), "target_type": candidate.get("target_type"), "scope_ref": _scope(candidate), "profile_id": candidate.get("profile_id"), "profile_version": candidate.get("profile_version")})
        return sorted(rows, key=lambda row: str(row.get("created_at") or ""), reverse=True)

    def comparison(self, evaluation_id: str, baseline_evaluation_id: str | None = None) -> dict[str, Any]:
        current = self._report(evaluation_id)
        if baseline_evaluation_id:
            baseline = self._report(baseline_evaluation_id)
            self._assert_comparable(baseline, current)
        else:
            choices = self.comparable_reports(evaluation_id)
            if not choices:
                return {"comparison_status": "no_baseline", "current_evaluation_id": evaluation_id, "baseline_evaluation_id": None, "message": "No comparable historical planning evaluation exists."}
            baseline = self._report(str(choices[0]["evaluation_id"]))
        return self._build(baseline, current)

    def proposals(self, evaluation_id: str) -> dict[str, Any]:
        report = self._report(evaluation_id)
        if report.get("status") == "stale":
            return {"proposal_status": "source_stale", "proposals": [], "message": "The report is based on old planning sources; current proposals are not generated."}
        if report.get("status") == "invalid":
            raise PlanningComparisonError("PLANNING_PROPOSAL_SOURCE_INVALID", "The planning report is invalid.")
        history = self._same_scope_reports(report)
        proposals = []
        for issue in sorted(_issues(report).values(), key=lambda item: (SEVERITY_RANK.get(str(item.get("severity")), 9), -len(item.get("affected_dimensions") or []), -float(item.get("evidence_reliability") or 0))):
            severity = str(issue.get("severity") or "low")
            priority = "P0" if severity == "blocking" else "P1" if severity == "high" else "P2" if severity == "medium" else "P3"
            fingerprint = str(issue.get("fingerprint"))
            seen = [entry for entry in history if fingerprint in _issues(entry)]
            proposals.append({"proposal_id": sha256(f"{report['evaluation_id']}|{fingerprint}".encode()).hexdigest()[:16], "source_evaluation_id": report["evaluation_id"], "title": str(issue.get("title") or "Planning issue"), "priority": priority, "issue_fingerprints": [fingerprint], "affected_dimensions": list(issue.get("affected_dimensions") or []), "evidence_refs": list(issue.get("evidence_refs") or []), "scope_refs": [_scope(report)], "reason": str(issue.get("description") or issue.get("title") or ""), "suggested_actions": [str(issue.get("suggestion") or "Review the related planning evidence with the author.")], "expected_effect": "Improve the evidence and consistency of the affected planning dimensions after author review.", "persistence_count": len(seen), "first_seen_at": min((str(item.get("created_at") or "") for item in seen), default=str(report.get("created_at") or "")), "last_seen_at": max((str(item.get("created_at") or "") for item in seen), default=str(report.get("created_at") or "")), "risk": "author_decision_required", "auto_applicable": False})
        return {"proposal_status": "current", "proposals": proposals[:5]}

    def _report(self, evaluation_id: str) -> dict[str, Any]:
        try:
            return self.planning.detail(evaluation_id)
        except PlanningEvaluationError as exc:
            raise PlanningComparisonError("PLANNING_COMPARISON_REPORT_NOT_FOUND", "Planning evaluation report was not found.") from exc

    def _same_scope_reports(self, report: dict[str, Any]) -> list[dict[str, Any]]:
        output = []
        for item in self.planning.list_reports(limit=100):
            try:
                candidate = self._report(str(item.get("evaluation_id") or ""))
                self._assert_comparable(candidate, report)
                if candidate.get("status") == "invalid" or candidate.get("gate_status") == "invalid":
                    continue
                output.append(candidate)
            except PlanningComparisonError:
                continue
        return output

    def _assert_comparable(self, baseline: dict[str, Any], current: dict[str, Any]) -> None:
        if baseline.get("project_id") != current.get("project_id"):
            raise PlanningComparisonError("PLANNING_COMPARISON_PROJECT_MISMATCH", "Planning reports belong to different projects.")
        if baseline.get("target_type") != current.get("target_type"):
            raise PlanningComparisonError("PLANNING_COMPARISON_TARGET_MISMATCH", "Planning report target types differ.")
        if _scope(baseline) != _scope(current):
            raise PlanningComparisonError("PLANNING_COMPARISON_SCOPE_MISMATCH", "Planning report scopes differ.")
        if baseline.get("profile_id") != current.get("profile_id") or baseline.get("profile_version") != current.get("profile_version"):
            raise PlanningComparisonError("PLANNING_COMPARISON_PROFILE_MISMATCH", "Planning report profiles differ.")
        if {str(row.get("dimension_id")) for row in baseline.get("dimensions", []) if isinstance(row, dict)} != {str(row.get("dimension_id")) for row in current.get("dimensions", []) if isinstance(row, dict)}:
            raise PlanningComparisonError("PLANNING_COMPARISON_INVALID_REPORT", "Planning reports have different dimension sets.")

    def _build(self, baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
        baseline_dimensions = {str(item.get("dimension_id")): item for item in baseline.get("dimensions", []) if isinstance(item, dict)}
        current_dimensions = {str(item.get("dimension_id")): item for item in current.get("dimensions", []) if isinstance(item, dict)}
        deltas = []
        insufficient = False
        for dimension_id in sorted(current_dimensions):
            before, after = baseline_dimensions[dimension_id], current_dimensions[dimension_id]
            score_before, score_after = before.get("score"), after.get("score")
            score_delta = None if score_before is None or score_after is None else round(float(score_after) - float(score_before), 1)
            insufficient = insufficient or score_delta is None
            deltas.append({"dimension_id": dimension_id, "display_name": after.get("display_name") or dimension_id, "score_before": score_before, "score_after": score_after, "score_delta": score_delta, "coverage_before": before.get("coverage"), "coverage_after": after.get("coverage"), "coverage_delta": self._delta(before.get("coverage"), after.get("coverage")), "confidence_before": before.get("confidence"), "confidence_after": after.get("confidence"), "confidence_delta": self._delta(before.get("confidence"), after.get("confidence")), "status_before": before.get("status"), "status_after": after.get("status"), "comparison_status": "insufficient_evidence" if score_delta is None else "improved" if score_delta > 0 else "worsened" if score_delta < 0 else "unchanged"})
        before_gate, after_gate = str(baseline.get("gate_status")), str(current.get("gate_status"))
        gate_change = "not_comparable" if "invalid" in {before_gate, after_gate} else "improved" if GATE_RANK.get(after_gate, -1) > GATE_RANK.get(before_gate, -1) else "worsened" if GATE_RANK.get(after_gate, -1) < GATE_RANK.get(before_gate, -1) else "unchanged"
        before_issues, after_issues = _issues(baseline), _issues(current)
        changed = [self._changed_issue(before_issues[key], after_issues[key]) for key in sorted(before_issues.keys() & after_issues.keys()) if self._changed_issue(before_issues[key], after_issues[key])]
        persistence = self._persistence(current, after_issues)
        return {"comparison_id": sha256(f"{baseline['evaluation_id']}|{current['evaluation_id']}".encode()).hexdigest()[:16], "comparison_status": "insufficient_evidence" if insufficient else "comparable", "project_id": current.get("project_id"), "baseline_evaluation_id": baseline["evaluation_id"], "current_evaluation_id": current["evaluation_id"], "target_type": current.get("target_type"), "scope_ref": _scope(current), "profile_id": current.get("profile_id"), "profile_version": current.get("profile_version"), "baseline_status": baseline.get("status"), "current_status": current.get("status"), "gate_before": before_gate, "gate_after": after_gate, "gate_change": gate_change, "overall_score_before": baseline.get("overall_score"), "overall_score_after": current.get("overall_score"), "overall_delta": self._delta(baseline.get("overall_score"), current.get("overall_score")), "coverage_before": baseline.get("overall_coverage"), "coverage_after": current.get("overall_coverage"), "coverage_delta": self._delta(baseline.get("overall_coverage"), current.get("overall_coverage")), "confidence_before": baseline.get("overall_confidence"), "confidence_after": current.get("overall_confidence"), "confidence_delta": self._delta(baseline.get("overall_confidence"), current.get("overall_confidence")), "dimension_deltas": deltas, "new_issues": [after_issues[key] for key in sorted(after_issues.keys() - before_issues.keys())], "resolved_issues": [before_issues[key] for key in sorted(before_issues.keys() - after_issues.keys())], "persistent_issues": [after_issues[key] for key in sorted(before_issues.keys() & after_issues.keys()) if not self._changed_issue(before_issues[key], after_issues[key])], "changed_issues": changed, "persistence": persistence, "historical_reference_only": baseline.get("status") == "stale" or current.get("status") == "stale"}

    def _persistence(self, current: dict[str, Any], current_issues: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        rows = self._same_scope_reports(current)
        output = []
        for fingerprint, issue in current_issues.items():
            seen = [report for report in rows if fingerprint in _issues(report)]
            output.append({"fingerprint": fingerprint, "persistence_count": len(seen), "first_seen_at": min((str(item.get("created_at") or "") for item in seen), default=""), "last_seen_at": max((str(item.get("created_at") or "") for item in seen), default="")})
        return output

    @staticmethod
    def _delta(before: Any, after: Any) -> float | None:
        return None if before is None or after is None else round(float(after) - float(before), 2)

    @staticmethod
    def _changed_issue(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any] | None:
        keys = ("severity", "affected_dimensions", "scope", "evidence_refs", "node_refs", "slot_refs", "schedule_refs")
        changed = [key for key in keys if _normalise(before.get(key)) != _normalise(after.get(key))]
        return {"fingerprint": after.get("fingerprint"), "before": {key: before.get(key) for key in changed}, "after": {key: after.get(key) for key in changed}, "changed_fields": changed} if changed else None
