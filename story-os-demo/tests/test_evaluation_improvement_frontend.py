from pathlib import Path


def test_quality_refresh_ui_has_confirmation_and_no_adoption() -> None:
    text = (Path(__file__).parents[1] / "web" / "static" / "narrative-evaluation.js").read_text(encoding="utf-8")
    assert "openNarrativeImprovement" in text
    assert "确认生成候选" in text
    assert "不会自动采用" in text
    assert "apply" not in text.lower().replace("applicable", "")
