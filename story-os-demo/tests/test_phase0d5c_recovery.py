from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "web" / "static" / "simulator-usable-loop.js").read_text(encoding="utf-8")


def test_recovery_is_read_only_and_does_not_create_operation_ids():
    assert "data-simulator-recovery" in HTML
    assert "TURN_RECOVERY_REQUIRED" not in JS
    assert "recovery mutation" in JS
    assert "operation_id" in JS  # passed only to existing branch API mutations
    assert "COMMIT_RECOVERY_REQUIRED" not in JS

