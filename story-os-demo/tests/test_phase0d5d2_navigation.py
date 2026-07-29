from pathlib import Path


def test_navigation_keeps_operation_and_approval_out_of_url():
    source = (Path(__file__).resolve().parents[1] / "web" / "static" / "simulator-candidate-review.js").read_text(encoding="utf-8")
    assert "window.history.pushState" in source
    assert "candidate_id" in source
    assert "operation_id" not in source.split("function push(changes)", 1)[1].split("async function request", 1)[0]
