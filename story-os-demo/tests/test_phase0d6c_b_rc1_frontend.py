"""Phase 0D6-C-B-RC1 successor handoff ownership guards."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = (ROOT / "web" / "static" / "simulator-chapter-progression.js").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")


def test_readiness_requires_matching_simulator_scope_without_active_turn():
    assert "function modelMatchesContext(context)" in MODULE
    assert "function activeTurnOwnsWorkspace(context)" in MODULE
    assert "function canOwnReadiness(context)" in MODULE
    assert "sealed readiness endpoint remains the completion authority" in MODULE
    assert "!activeTurnOwnsWorkspace(context)" in MODULE


def test_validated_handoff_releases_readiness_ownership_for_successor_turn():
    assert "state.handoff = { contextKey: successorContext.key" in MODULE
    assert "setStatus(handoffMatches(context) || activeTurnOwnsWorkspace(context) ? \"HANDOFF_COMPLETE\" : \"UNAVAILABLE\")" in MODULE
    assert "state.status === \"HANDOFF_COMPLETE\"" in MODULE
    assert "panel.classList.toggle(\"hidden\", !available || state.status === \"HANDOFF_COMPLETE\")" in MODULE


def test_start_replay_and_existing_turn_use_one_handoff_helper():
    assert "function handoffToSuccessor(scope, successorChapterId, turnId)" in MODULE
    assert "handoffToSuccessor(intent.snapshot, result.successor_chapter_id, result.turn_id);" in MODULE
    assert "handoffToSuccessor(state.context, result.successor_chapter_id, result.existing_turn_id);" in MODULE
    assert 'result.existing_turn_status !== "awaiting_action"' in MODULE


def test_handoff_is_in_memory_and_scope_bound():
    assert "contextKey: successorContext.key" in MODULE
    assert "turn_id: String(turnId)" in MODULE
    assert "localStorage" not in MODULE
    assert "sessionStorage" not in MODULE


def test_rc1_module_version_is_cache_busted_without_ui_markup_changes():
    assert '/static/simulator-chapter-progression.js?v=0d6c-b-rc19-1' in TEMPLATE
