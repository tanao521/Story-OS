from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "web" / "static" / "simulator-usable-loop.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "static" / "simulator-usable-loop.css").read_text(encoding="utf-8")


def test_loop_shell_and_stable_selectors_exist():
    for selector in ("data-simulator-loop-shell", "data-simulator-context-bar", "data-chapter-progress-rail", "data-branch-control-panel", "data-turn-result", "data-continue-next-turn", "data-turn-history", "data-simulator-recovery"):
        assert selector in HTML
    assert "/static/simulator-usable-loop.js" in HTML
    assert "/static/simulator-usable-loop.css" in HTML


def test_loop_uses_authoritative_state_and_existing_mutation_routes():
    assert "/api/simulator/state" in JS
    assert "/api/narrative-branches/" in JS
    assert "/api/narrative-turn/confirm" not in JS
    assert "localStorage" not in JS
    assert "ChapterCommitService" not in JS


def test_loop_has_no_inline_handlers_and_respects_reduced_motion():
    assert "onclick=" not in HTML[HTML.find('id="simulator-loop-shell"'):HTML.find('id="simulator-panel-review"')]
    assert "prefers-reduced-motion" in CSS
    assert "data-branch-action" in JS

