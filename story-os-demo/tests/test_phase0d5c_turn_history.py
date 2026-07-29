from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "web" / "static" / "simulator-usable-loop.js").read_text(encoding="utf-8")


def test_history_is_read_only_and_dense():
    assert "data-turn-history" in HTML
    assert "data-turn-history-item" in JS
    assert "state_delta_summary" in JS
    assert "No confirmed Turns" in JS
    assert "deleteturn" not in JS.lower()
    assert "delete turn" not in JS.lower()
