from pathlib import Path


def test_planning_evaluation_ui_stays_in_narrative_evaluation_center() -> None:
    root = Path(__file__).parents[1]
    page = (root / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    script = (root / "web" / "static" / "narrative-evaluation.js").read_text(encoding="utf-8")
    assert "planning-evaluation-controls" in page and "生成规划评估" in page
    # Scope values are deliberately owned by the existing center's HTML control;
    # the script receives availability and defaults from the overview endpoint.
    assert "near_planning_window" in page and "current_volume" in page and "whole_book_planning" in page
    assert "/api/evaluations/planning" in script
    assert "硬性门禁" in script and "最高优先级问题" in script
    assert "自动修复规划" not in script and "AI 重规划" not in script
