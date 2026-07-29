from pathlib import Path


def test_commit_is_gated_by_approved_read_model_and_uses_existing_commit_route():
    source = (Path(__file__).resolve().parents[1] / "web" / "static" / "simulator-candidate-review.js").read_text(encoding="utf-8")
    assert 'approval.status !== "approved"' in source
    assert '"/api/narrative-chapter/commit"' in source
    assert "state.operation.commit ||= opId(\"commit\")" in source
    assert 'open.classList.toggle("hidden", !authoritativeCommit)' in source
