from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "web" / "static" / "simulator-usable-loop.js").read_text(encoding="utf-8")


def test_traditional_shell_and_mode_switch_remain_present():
    assert 'id="storyos-mode-switch"' in HTML
    assert 'data-storyos-mode="traditional"' in HTML
    assert "runChapter" in HTML
    assert "manualEditor" in HTML
    assert "mode" in JS
    assert "localStorage" not in JS

