from pathlib import Path


def test_production_usage_stays_inside_narrative_evaluation_center() -> None:
    root = Path(__file__).parents[1]
    script = (root / "web" / "static" / "narrative-evaluation.js").read_text(encoding="utf-8")
    assert "ensureEvaluationUsagePanel" in script and "evaluation-usage-summary" in script
    assert "/api/evaluations/usage/summary" in script
    assert "renderEvaluationUsage" in script and "token_status" in script
