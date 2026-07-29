from pathlib import Path


def test_candidate_ui_does_not_import_direct_canon_or_vector_authorities():
    source = (Path(__file__).resolve().parents[1] / "web" / "static" / "simulator-candidate-review.js").read_text(encoding="utf-8")
    for forbidden in ("Chroma", "Canonical", "CanonService", "ChapterCommitService"):
        assert forbidden not in source
