from pathlib import Path


def test_planning_comparison_and_proposals_stay_inside_existing_center() -> None:
    root = Path(__file__).parents[1]
    page = (root / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    script = (root / "web" / "static" / "narrative-evaluation.js").read_text(encoding="utf-8")
    assert "planning-evaluation-history" in page and "planning-evaluation-proposals" in page
    assert "planning-comparison-baseline" in page and "叙事评估中心" in page
    assert "/comparison" in script and "/comparable-reports" in script and "/planning-proposals" in script
    assert "dimension_deltas" in script and "gate_change" in script and "persistence_count" in script
    assert "自动应用建议" not in page and "立即修复" not in page and "AI 重规划" not in page
