from __future__ import annotations

from tools.manual_history_recovery import pair_compatibility


def _blueprint(project_id: str = "p") -> dict:
    return {"project_id": project_id, "title": "Story", "chapter_plan": [{"chapter_id": 7}], "story_phases": [{"phase_id": 2}]}


def _plan(project_id: str = "p", chapter_id: int = 7, phase_id: int = 2) -> dict:
    return {"project_id": project_id, "story_title": "Story", "chapter_id": chapter_id, "phase_position": {"phase_id": phase_id}}


def test_compatible_pair_is_not_auto_selected() -> None:
    result = pair_compatibility(_blueprint(), _plan(), {"current_chapter": 6})
    assert result["status"] == "compatible"
    assert result["manual_review_only"] is True


def test_incompatible_pair_detects_project_or_phase_conflict() -> None:
    result = pair_compatibility(_blueprint("a"), _plan("b", phase_id=9), {"current_chapter": 6})
    assert result["status"] == "incompatible"


def test_insufficient_pair_is_not_treated_as_compatible() -> None:
    result = pair_compatibility({}, {}, {})
    assert result["status"] == "insufficient_evidence"


def test_missing_identity_information_requires_attention() -> None:
    result = pair_compatibility({"chapter_plan": [{"chapter_id": 7}]}, {"chapter_id": 7}, {"current_chapter": 6})
    assert result["status"] == "attention"
