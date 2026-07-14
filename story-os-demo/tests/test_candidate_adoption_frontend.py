from pathlib import Path


def test_candidate_adoption_ui_has_whole_draft_confirmation_and_partial_adoption() -> None:
    script = (Path(__file__).parents[1] / "web" / "static" / "narrative-evaluation.js").read_text(encoding="utf-8")
    assert "采用整稿" in script
    assert "放弃候选" in script
    assert "review_required" in script
    assert "不会自动提交正史" in script
    assert "partial-adoption-preview" in script
    assert "partial-adopt" in script
