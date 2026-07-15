from __future__ import annotations

from tests.test_planning_evaluation_comparison import _issue, _report, _service


def test_proposals_are_deterministic_prioritized_and_author_only(tmp_path) -> None:
    history = _report("history", "2026-01-01T00:00:00+00:00", issues=[_issue("persistent", "high")])
    current = _report("current", "2026-01-02T00:00:00+00:00", issues=[_issue("low", "low"), _issue("medium", "medium"), _issue("persistent", "high", dimensions=["plot_progression", "character_arc"]), _issue("blocking", "blocking"), _issue("extra-a", "high"), _issue("extra-b", "high")])
    result = _service(tmp_path, [history, current]).proposals("current")
    assert result["proposal_status"] == "current" and len(result["proposals"]) == 5
    assert result["proposals"][0]["priority"] == "P0"
    assert all(item["risk"] == "author_decision_required" and item["auto_applicable"] is False for item in result["proposals"])
    persistent = next(item for item in result["proposals"] if item["issue_fingerprints"] == ["persistent"])
    assert persistent["persistence_count"] == 2


def test_stale_report_does_not_receive_current_proposals(tmp_path) -> None:
    stale = _report("stale", "2026-01-01T00:00:00+00:00", issues=[_issue("issue", "high")])
    stale["status"] = "stale"
    assert _service(tmp_path, [stale]).proposals("stale") == {"proposal_status": "source_stale", "proposals": [], "message": "The report is based on old planning sources; current proposals are not generated."}
