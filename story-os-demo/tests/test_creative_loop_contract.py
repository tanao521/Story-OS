from pathlib import Path


def test_creative_loop_api_and_ui_contracts_are_present():
    root = Path(__file__).resolve().parents[1]
    routes = (root / "web" / "creative_loop_routes.py").read_text(encoding="utf-8")
    app = (root / "web" / "app.py").read_text(encoding="utf-8")
    html = (root / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    script = (root / "web" / "static" / "creative-evolution.js").read_text(encoding="utf-8")
    for path in ("/reflections", "/health", "/system-health", "/analysis-profile", "/issues", "/proposals", "/experiments", "/patterns", "/outcomes", "/evolution"):
        assert path in routes
    assert "creative_loop_router" in app
    assert "creative-evolution-center" in html
    assert "/api/creative-loop/overview" in script
    assert "proposal-decision" in script
    assert "creative-evolution-experiments" in html
