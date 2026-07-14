import pytest

from evaluation_engine.improvement_policy import ImprovementPolicyError, budget, validate_actions


def test_budget_profiles_and_forbidden_action() -> None:
    assert budget("standard")["max_changed_paragraphs"] == 8
    assert budget("conservative")["max_changed_ratio"] == .06
    with pytest.raises(ImprovementPolicyError) as error:
        validate_actions([{"action": "rewrite_chapter", "anchor": "x"}], budget())
    assert error.value.code == "IMPROVEMENT_ACTION_FORBIDDEN"
