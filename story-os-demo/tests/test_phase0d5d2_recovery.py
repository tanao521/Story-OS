from pathlib import Path


def test_unknown_mutation_outcome_recovers_by_reading_state_without_repost():
    source = (Path(__file__).resolve().parents[1] / "web" / "static" / "simulator-candidate-review.js").read_text(encoding="utf-8")
    assert "state.unknown.compile = true" in source
    assert "state.unknown.review = true" in source
    assert "state.unknown.commit = true" in source
    assert "window.StoryOSSimulatorLoop.loadState()" in source
    assert "no mutation will be repeated automatically" in source
    assert "const kind = state.unknown.compile ? \"Compile\"" in source


def test_rejected_candidate_exposes_safe_recompile_path_and_hides_commit():
    source = (Path(__file__).resolve().parents[1] / "web" / "static" / "simulator-candidate-review.js").read_text(encoding="utf-8")
    template = (Path(__file__).resolve().parents[1] / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    assert "Candidate rejected. Commit is unavailable. Return or recompile" in source
    assert "open.classList.toggle(\"hidden\", !authoritativeCommit)" in source
    assert "Refresh / recompile" in template
