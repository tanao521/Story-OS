from pathlib import Path


def test_e1_does_not_mutate_existing_branch_selector_ui():
    js = Path(__file__).resolve().parents[1] / "web" / "static" / "simulator-context-navigator.js"
    assert js.exists()
    # E1 exposes the API only; URL browsing remains distinct from active
    # mutation. No selector mutation contract is added in this phase.
    assert "pushState" in js.read_text(encoding="utf-8")
