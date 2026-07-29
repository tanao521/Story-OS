from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "web" / "static" / "simulator-usable-loop.js").read_text(encoding="utf-8")


def test_browse_and_select_are_distinct():
    assert '"browse"' in JS
    assert '"select"' in JS
    assert "/api/narrative-branches/select" in JS
    assert "askConfirm" in JS


def test_create_archive_restore_are_explicit_and_not_auto_selected():
    assert "/api/narrative-branches/create" in JS
    assert "/api/narrative-branches/archive" in JS
    assert "/api/narrative-branches/restore" in JS
    assert "replacement_branch_id" in JS
    assert "Select as Active" in JS
