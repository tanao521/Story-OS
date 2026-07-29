from pathlib import Path


def test_completion_and_next_chapter_are_authoritative_read_model_outcomes():
    source = (Path(__file__).resolve().parents[1] / "web" / "static" / "simulator-candidate-review.js").read_text(encoding="utf-8")
    assert "chapter_progression" in source
    assert "next_chapter_available" in source
    assert 'view: "narrative-turn"' in source
    assert 'await refresh(); push({ view: "complete" });' in source
    assert "Commit result recovered from the authoritative read model." in source
