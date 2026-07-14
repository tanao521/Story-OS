from __future__ import annotations

from pathlib import Path


def test_narrative_evaluation_has_one_navigation_entry_and_safe_controls() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    script = (root / "web" / "static" / "narrative-evaluation.js").read_text(encoding="utf-8")
    assert html.count('data-section="narrative-evaluation-center"') == 1
    assert "叙事评估中心" in html
    assert "章节成绩" not in html  # no separate scoring product page
    assert "一键提升质量" not in html
    assert "generateNarrativeEvaluation" in html
    assert "/api/evaluations" in script
    assert "openNarrativeImprovement" in script
    assert "不会自动采用" in script
    assert "operation_id" in script
