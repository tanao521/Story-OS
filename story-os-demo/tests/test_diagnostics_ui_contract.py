from pathlib import Path


def test_diagnostics_ui_and_api_contract_are_present() -> None:
    root = Path(__file__).resolve().parents[1]
    routes = (root / "web" / "routes.py").read_text(encoding="utf-8")
    page = (root / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    view = (root / "web" / "static" / "diagnostics-center.js").read_text(encoding="utf-8")
    for path in ("/api/system/health", "/api/system/diagnostics", "/api/system/check", "/api/system/logs", "/api/system/export-report"):
        assert path in routes
    assert "diagnostics-center-panel" in page
    assert "storyos:project-changed" in view
