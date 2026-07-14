from pathlib import Path


def test_partial_adoption_ui_only_submits_patch_ids_and_preconditions() -> None:
    script = (Path(__file__).parents[1] / "web" / "static" / "narrative-evaluation.js").read_text(encoding="utf-8")
    assert "partial-adoption-preview" in script
    assert "partial-adopt" in script
    assert "selected_patch_ids" in script
    assert "replacement_text: preview" not in script
    assert "partialPatchState" in script
    assert "合并后完整 Diff" in script
    assert "原文：" in script and "候选文本：" in script
    assert "采用整稿" in script and "放弃候选" in script
