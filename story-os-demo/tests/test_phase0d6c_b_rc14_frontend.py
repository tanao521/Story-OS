"""RC14 history bridge and Narrative Turn action-state contracts."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NAVIGATOR = (ROOT / "web" / "static" / "simulator-context-navigator.js").read_text(encoding="utf-8")
NARRATIVE = (ROOT / "web" / "static" / "simulator-narrative-turn.js").read_text(encoding="utf-8")


def test_history_bridge_compares_the_canonical_context_before_dispatching():
    bridge = NAVIGATOR[NAVIGATOR.index("function canonicalContext"):NAVIGATOR.index("function updateUrl")]
    assert "readCanonicalProjectIdentity" in bridge
    assert "identity.mismatch" in bridge
    assert "current.get(\"timeline_id\")" in bridge
    assert "current.get(\"branch_id\")" in bridge
    assert "current.get(\"chapter_id\")" in bridge
    assert "const before = canonicalContext();" in bridge
    assert "if (before !== canonicalContext())" in bridge
    assert bridge.count('window.dispatchEvent(new PopStateEvent("popstate"));') == 1


def test_non_context_action_history_does_not_synthesize_navigation():
    bridge = NAVIGATOR[NAVIGATOR.index("function installHistoryContextBridge"):NAVIGATOR.index("function updateUrl")]
    assert "nativePushState.apply(this, args)" in bridge
    assert "before !== canonicalContext()" in bridge
    assert "pushState === context navigation" not in bridge


def test_narrative_action_state_remains_owned_by_the_narrative_turn_module():
    action = NARRATIVE[NARRATIVE.index("function handleRecommendedSelected"):NARRATIVE.index("function handleSubmitCustomAction")]
    assert "state.selectedActionId = actionId;" in action
    assert 'state.actionSource = "recommended";' in action
    assert "requestFeasibilityAndPreview();" in action
    assert "function resetActionState()" in NARRATIVE
    assert "custom_action_text" not in action
