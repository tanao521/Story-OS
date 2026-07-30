"""RC13 static guards for branch-scoped readiness response ownership."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROGRESSION = (ROOT / "web" / "static" / "simulator-chapter-progression.js").read_text(encoding="utf-8")
NAVIGATOR = (ROOT / "web" / "static" / "simulator-context-navigator.js").read_text(encoding="utf-8")


def test_readiness_response_rechecks_the_live_full_context_key():
    assert "function responseStillOwnsCurrentContext(epoch, context)" in PROGRESSION
    guard = PROGRESSION[PROGRESSION.index("function responseStillOwnsCurrentContext"):PROGRESSION.index("function startFieldsValid")]
    assert "state.contextKey !== context.key" in guard
    assert "contextFromModel(state.model).key === context.key" in guard
    assert PROGRESSION.count("if (!responseStillOwnsCurrentContext(epoch, context)) return;") == 2


def test_branch_context_loss_invalidates_the_readiness_epoch_before_rendering():
    sync = PROGRESSION[PROGRESSION.index("function sync(force)"):PROGRESSION.index("function schedule(force)")]
    assert "const changed = context.key !== state.contextKey;" in sync
    assert "if (changed) state.epoch += 1;" in sync
    assert "if (state.controller) state.controller.abort();" in sync
    assert "clearTransient();" in sync


def test_context_navigator_normalizes_pushstate_into_one_context_change_path():
    bridge = NAVIGATOR[NAVIGATOR.index("function installHistoryContextBridge"):NAVIGATOR.index("function updateUrl")]
    assert "window.history.pushState = function" in bridge
    assert 'window.dispatchEvent(new PopStateEvent("popstate"));' in bridge
    update = NAVIGATOR[NAVIGATOR.index("function updateUrl"):NAVIGATOR.index("async function get")]
    assert "window.history.pushState" in update
    assert "dispatchEvent" not in update
    assert "installHistoryContextBridge();" in NAVIGATOR
