"""RC3 guardrails for authority-driven reactivation and delayed-scope work."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = (ROOT / "web" / "static" / "simulator-chapter-progression.js").read_text(encoding="utf-8")
FIXTURE = (ROOT / "tests" / "_phase0d6c_fv_browser_fixture_server.py").read_text(encoding="utf-8")


def test_reactivation_is_read_model_scoped_and_never_uses_client_persistence():
    assert "function modelMatchesContext(context)" in MODULE
    assert "function activeTurnOwnsWorkspace(context)" in MODULE
    assert "return !activeTurnOwnsWorkspace(context);" in MODULE
    assert "localStorage" not in MODULE
    assert "sessionStorage" not in MODULE


def test_mode_and_response_guards_remain_epoch_and_scope_bound():
    assert 'if (mode() !== "simulator")' in MODULE
    assert "state.context = null; state.contextKey = \"\"; state.model = null" in MODULE
    assert "epoch !== state.epoch || state.contextKey !== context.key" in MODULE
    assert "state.handoff.contextKey === context.key" in MODULE


def test_existing_fixture_has_only_start_response_fault_controls():
    assert "STORYOS_FV_DROP_START_RESPONSE" in FIXTURE
    assert "STORYOS_FV_START_DELAY" in FIXTURE
    assert "readiness" in FIXTURE
