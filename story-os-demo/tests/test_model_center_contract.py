from pathlib import Path


def test_model_center_has_real_api_and_project_switch_refresh() -> None:
    root = Path(__file__).resolve().parents[1]
    routes = (root / "web" / "routes.py").read_text(encoding="utf-8")
    view = (root / "web" / "static" / "model-center.js").read_text(encoding="utf-8")
    page = (root / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    for path in ("/api/models/routes", "/api/models/runs", "/api/models/usage", "/api/prompts"):
        assert path in routes
    assert "storyos:project-changed" in view
    assert "model-center-panel" in page
