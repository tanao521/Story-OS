from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_narrative_evaluation_is_the_only_visible_evaluation_navigation_entry() -> None:
    template = (ROOT / "web/templates/index.html").read_text(encoding="utf-8")
    navigation = template.split("</nav>", 1)[0]
    assert navigation.count('href="#narrative-evaluation-center"') == 1
    assert 'href="#quality-panel"' not in navigation
    assert 'href="#continuity-panel"' not in navigation


def test_legacy_quality_quick_action_is_hidden_and_deep_link_code_remains() -> None:
    script = (ROOT / "web/static/app.js").read_text(encoding="utf-8")
    assert "qualityCheckCurrentVersion" in script and "checkContinuity" in script
    assert "setAttribute(\"hidden\", \"\")" in script
    assert "async function qualityCheck" in script
