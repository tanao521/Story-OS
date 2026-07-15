from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from core.project_context import get_project_context
from evaluation_engine.planning_comparison import PlanningComparisonError, PlanningEvaluationComparisonService


DIMENSIONS = (
    "structural_completeness", "causal_dependency", "plot_progression", "pacing_tension",
    "character_arc", "foreshadowing", "chapter_load", "milestone_alignment",
)


class _Reports:
    def __init__(self, reports: list[dict]) -> None:
        self.reports = {report["evaluation_id"]: report for report in reports}

    def detail(self, evaluation_id: str) -> dict:
        try:
            return deepcopy(self.reports[evaluation_id])
        except KeyError as exc:
            from evaluation_engine.planning_evaluation import PlanningEvaluationError
            raise PlanningEvaluationError("PLANNING_EVALUATION_SCOPE_NOT_FOUND", "missing") from exc

    def list_reports(self, *, limit: int = 100, **_kwargs) -> list[dict]:
        return sorted((deepcopy(report) for report in self.reports.values()), key=lambda item: item["created_at"], reverse=True)[:limit]


def _issue(fingerprint: str, severity: str = "high", *, title: str | None = None, dimensions: list[str] | None = None) -> dict:
    return {"fingerprint": fingerprint, "severity": severity, "title": title or fingerprint, "description": title or fingerprint, "affected_dimensions": dimensions or ["plot_progression"], "evidence_refs": [f"evidence:{fingerprint}"], "node_refs": [], "slot_refs": [], "schedule_refs": [], "suggestion": "Review this planning evidence.", "evidence_reliability": 0.8}


def _report(evaluation_id: str, created_at: str, *, gate: str = "attention", score: float = 70, issues: list[dict] | None = None, profile: int = 1, target: str = "near_planning_window", scope: dict | None = None) -> dict:
    return {"evaluation_id": evaluation_id, "project_id": "project-a", "target_type": target, "target_ref": {"scope_ref": scope or {"window_id": "window-a", "volume_id": "volume-a"}}, "profile_id": "planning-default-v1", "profile_version": profile, "created_at": created_at, "status": "current", "gate_status": gate, "overall_score": score, "overall_coverage": 0.7, "overall_confidence": 0.8, "dimensions": [{"dimension_id": dimension, "display_name": dimension, "score": score, "coverage": 0.7, "confidence": 0.8, "status": "ok"} for dimension in DIMENSIONS], "hard_issues": [], "priority_issues": issues or []}


def _service(tmp_path: Path, reports: list[dict]) -> PlanningEvaluationComparisonService:
    service = PlanningEvaluationComparisonService(get_project_context(tmp_path))
    service.planning = _Reports(reports)  # type: ignore[assignment]
    return service


def test_same_scope_reports_are_compared_and_issue_changes_are_classified(tmp_path: Path) -> None:
    baseline = _report("baseline", "2026-01-01T00:00:00+00:00", issues=[_issue("stable"), _issue("resolved"), _issue("changed", "medium")], score=70)
    current = _report("current", "2026-01-02T00:00:00+00:00", gate="pass", issues=[_issue("stable"), _issue("changed", "high"), _issue("new", "blocking")], score=82, scope={"volume_id": "volume-a", "window_id": "window-a"})
    comparison = _service(tmp_path, [baseline, current]).comparison("current")
    assert comparison["baseline_evaluation_id"] == "baseline"
    assert comparison["gate_change"] == "improved" and comparison["overall_delta"] == 12
    assert [item["fingerprint"] for item in comparison["new_issues"]] == ["new"]
    assert [item["fingerprint"] for item in comparison["resolved_issues"]] == ["resolved"]
    assert [item["fingerprint"] for item in comparison["persistent_issues"]] == ["stable"]
    assert comparison["changed_issues"][0]["fingerprint"] == "changed"
    assert comparison["persistence"][0]["persistence_count"] >= 1


def test_comparison_handles_no_baseline_null_scores_and_invalid_gate(tmp_path: Path) -> None:
    only = _report("only", "2026-01-02T00:00:00+00:00")
    assert _service(tmp_path, [only]).comparison("only")["comparison_status"] == "no_baseline"
    baseline = _report("baseline", "2026-01-01T00:00:00+00:00", gate="blocked")
    current = _report("current", "2026-01-02T00:00:00+00:00", gate="invalid")
    current["dimensions"][0]["score"] = None
    result = _service(tmp_path, [baseline, current]).comparison("current", "baseline")
    assert result["gate_change"] == "not_comparable"
    assert result["comparison_status"] == "insufficient_evidence"
    assert next(item for item in result["dimension_deltas"] if item["dimension_id"] == "structural_completeness")["score_delta"] is None


@pytest.mark.parametrize(("field", "value", "code"), [("target_type", "current_volume", "PLANNING_COMPARISON_TARGET_MISMATCH"), ("profile_version", 2, "PLANNING_COMPARISON_PROFILE_MISMATCH")])
def test_non_comparable_reports_are_rejected(tmp_path: Path, field: str, value: object, code: str) -> None:
    baseline = _report("baseline", "2026-01-01T00:00:00+00:00")
    current = _report("current", "2026-01-02T00:00:00+00:00")
    baseline[field] = value
    with pytest.raises(PlanningComparisonError) as error:
        _service(tmp_path, [baseline, current]).comparison("current", "baseline")
    assert error.value.code == code


def test_project_scope_and_dimension_mismatches_are_rejected(tmp_path: Path) -> None:
    baseline = _report("baseline", "2026-01-01T00:00:00+00:00")
    current = _report("current", "2026-01-02T00:00:00+00:00")
    baseline["project_id"] = "project-b"
    with pytest.raises(PlanningComparisonError, match="different projects") as error:
        _service(tmp_path, [baseline, current]).comparison("current", "baseline")
    assert error.value.code == "PLANNING_COMPARISON_PROJECT_MISMATCH"
    baseline["project_id"] = "project-a"; baseline["target_ref"]["scope_ref"] = {"window_id": "window-b"}
    with pytest.raises(PlanningComparisonError) as error:
        _service(tmp_path, [baseline, current]).comparison("current", "baseline")
    assert error.value.code == "PLANNING_COMPARISON_SCOPE_MISMATCH"
    baseline["target_ref"]["scope_ref"] = {"window_id": "window-a", "volume_id": "volume-a"}; baseline["dimensions"] = baseline["dimensions"][:-1]
    with pytest.raises(PlanningComparisonError) as error:
        _service(tmp_path, [baseline, current]).comparison("current", "baseline")
    assert error.value.code == "PLANNING_COMPARISON_INVALID_REPORT"
