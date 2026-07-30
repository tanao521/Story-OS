"""RC19 canonical project URL identity and split-context fail-closed contracts."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NAVIGATOR = (ROOT / "web" / "static" / "simulator-context-navigator.js").read_text(encoding="utf-8")
PROGRESSION = (ROOT / "web" / "static" / "simulator-chapter-progression.js").read_text(encoding="utf-8")


def test_canonical_reader_supports_equal_and_legacy_single_key_identity():
    reader = NAVIGATOR[NAVIGATOR.index("function readCanonicalProjectIdentity"):NAVIGATOR.index("function canonicalContext")]
    assert "const project = current.get(\"project\") || \"\";" in reader
    assert "const projectId = current.get(\"project_id\") || \"\";" in reader
    assert "canonical_project_id: mismatch ? \"\" : (projectId || project)" in reader
    assert "consistent: !mismatch" in reader


def test_mismatched_dual_keys_are_explicitly_inconsistent_and_fail_closed():
    reader = NAVIGATOR[NAVIGATOR.index("function readCanonicalProjectIdentity"):NAVIGATOR.index("function canonicalContext")]
    assert "const mismatch = !!project && !!projectId && project !== projectId;" in reader
    assert "canonical_project_id: mismatch ? \"\"" in reader
    assert "storyos:canonical-context-invalid" in NAVIGATOR
    scope = PROGRESSION[PROGRESSION.index("function urlProjectIdentity"):PROGRESSION.index("function validContext")]
    assert "identity.consistent ? identity.canonical_project_id : \"\"" in scope
    assert "url.identity_consistent ? text(url.project_id" in PROGRESSION


def test_project_dropdown_commits_both_url_identity_keys_atomically():
    bind = NAVIGATOR[NAVIGATOR.index("function bindChanges"):NAVIGATOR.index("async function load")]
    assert "updateUrl({ project: event.target.value, project_id: event.target.value" in bind
    update = NAVIGATOR[NAVIGATOR.index("function updateUrl"):NAVIGATOR.index("async function get")]
    assert "next.set(\"project\", String(identityValue));" in update
    assert "next.set(\"project_id\", String(identityValue));" in update
    assert "Object.entries(changes).forEach" in update


def test_context_navigator_exports_the_shared_canonical_reader():
    assert "window.StoryOSContextNavigator = { rebind, load, readCanonicalProjectIdentity };" in NAVIGATOR


def test_progression_reactivates_authority_after_model_catches_up_to_new_url_scope():
    sync = PROGRESSION[PROGRESSION.index("function sync(force)"):PROGRESSION.index("function schedule(force)")]
    assert 'state.status === "UNAVAILABLE" && state.readinessModelEpoch !== state.modelEpoch' in sync
    assert "state.modelEpoch += 1;" in PROGRESSION
