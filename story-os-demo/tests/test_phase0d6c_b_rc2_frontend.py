"""RC2 closure guards for replay and ownership-isolation verification."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = (ROOT / "web" / "static" / "simulator-chapter-progression.js").read_text(encoding="utf-8")
FIXTURE = (ROOT / "tests" / "_phase0d6c_fv_browser_fixture_server.py").read_text(encoding="utf-8")


def test_response_loss_fixture_keeps_the_real_app_and_audits_two_posts():
    assert "STORYOS_FV_DROP_START_RESPONSE" in FIXTURE
    assert "ProgressionAuditMiddleware" in FIXTURE
    assert "await self.downstream" in FIXTURE


def test_retry_reuses_the_frozen_intent_and_shared_handoff():
    assert 'state.status === "START_RETRYABLE_ERROR" && state.startIntent' in MODULE
    assert "return state.startIntent" in MODULE
    assert "JSON.stringify(snapshot)" in MODULE
    assert "handoffToSuccessor(intent.snapshot, result.successor_chapter_id, result.turn_id);" in MODULE


def test_active_turn_releases_only_its_matching_scope_and_traditional_clears_state():
    assert "function modelMatchesContext(context)" in MODULE
    assert "function activeTurnOwnsWorkspace(context)" in MODULE
    assert "state.handoff.contextKey === context.key" in MODULE
    assert 'if (mode() !== "simulator")' in MODULE
    assert "state.context = null; state.contextKey = \"\"; state.model = null" in MODULE
