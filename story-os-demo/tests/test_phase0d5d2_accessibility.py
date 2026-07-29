from pathlib import Path


def test_commit_dialog_has_focus_management_and_native_escape_support():
    source = (Path(__file__).resolve().parents[1] / "web" / "static" / "simulator-candidate-review.js").read_text(encoding="utf-8")
    template = (Path(__file__).resolve().parents[1] / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    assert "function trap(event)" in source
    assert "node?.addEventListener(\"close\"" in source
    assert "<dialog id=\"simulator-commit-dialog\"" in template
    assert 'role="dialog"' in template
