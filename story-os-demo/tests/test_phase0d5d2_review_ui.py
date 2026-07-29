from pathlib import Path


def test_review_payload_has_stable_operation_and_expected_fingerprint():
    source = (Path(__file__).resolve().parents[1] / "web" / "static" / "simulator-candidate-review.js").read_text(encoding="utf-8")
    assert "state.operation.review ||= opId(\"review\")" in source
    assert "expected_candidate_fingerprint" in source
    assert "reviewer_id" in source
    assert "decision" in source
    assert 'decision: decision === "approve" ? "approved" : "rejected"' in source
