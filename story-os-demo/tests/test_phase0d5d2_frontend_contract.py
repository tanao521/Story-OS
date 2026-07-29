from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_candidate_review_module_is_loaded_with_required_authority_selectors():
    template = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    for selector in (
        "data-chapter-progress-rail", "data-candidate-list", "data-candidate-review",
        "data-candidate-content", "data-candidate-evidence", "data-candidate-approve",
        "data-candidate-reject", "data-candidate-recovery", "data-commit-dialog",
        "data-commit-confirm", "data-commit-recovery", "data-chapter-completion",
        "data-start-next-chapter", "simulator-candidate-review.js",
    ):
        assert selector in template


def test_candidate_module_uses_existing_routes_and_url_read_model_only():
    script = (ROOT / "web" / "static" / "simulator-candidate-review.js").read_text(encoding="utf-8")
    for route in ("/api/narrative-chapter/compile", "/review", "/api/narrative-chapter/commit", "StoryOSSimulatorLoop.loadState"):
        assert route in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script
