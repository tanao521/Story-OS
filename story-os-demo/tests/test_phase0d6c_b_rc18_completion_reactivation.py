from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROGRESSION = (ROOT / "web/static/simulator-chapter-progression.js").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "web/templates/index.html").read_text(encoding="utf-8")


def test_authoritative_completion_releases_the_scope_bound_handoff() -> None:
    assert "function completionReleasesHandoff(context)" in PROGRESSION
    release = PROGRESSION[
        PROGRESSION.index("function completionReleasesHandoff"):
        PROGRESSION.index("function canOwnReadiness")
    ]
    assert "handoffMatches(context)" in release
    assert "modelMatchesContext(context)" in release
    assert "chapter.completed === true" in release
    assert "if (completionReleasesHandoff(context)) state.handoff = null;" in PROGRESSION


def test_duplicate_completed_models_use_existing_readiness_coalescing() -> None:
    listener = PROGRESSION[
        PROGRESSION.index('window.addEventListener("storyos:simulator-state"'):
        PROGRESSION.index('window.addEventListener("storyos:panel-context-ready"')
    ]
    assert "const wasCompleted" in listener
    assert "const isCompleted" in listener
    assert "schedule(!wasCompleted && isCompleted);" in listener
    assert "requestStart" not in listener
    assert "window.setTimeout" not in listener


def test_rc18_progression_asset_is_cache_busted() -> None:
    assert "/static/simulator-chapter-progression.js?v=0d6c-b-rc19-1" in TEMPLATE
