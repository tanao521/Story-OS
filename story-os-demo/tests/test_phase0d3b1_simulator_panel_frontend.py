from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
MODULE = (ROOT / "web" / "static" / "simulator-panel-review.js").read_text(encoding="utf-8")
RUN_MODULE = (ROOT / "web" / "static" / "simulator-panel-run.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "static" / "simulator-panel-review.css").read_text(encoding="utf-8")
HARNESS = (ROOT.parent / "docs" / "design" / "qa" / "simulator-panel-review-production" / "harness.js").read_text(encoding="utf-8")
HARNESS_HTML = (ROOT.parent / "docs" / "design" / "qa" / "simulator-panel-review-production" / "harness.html").read_text(encoding="utf-8")


def test_production_shell_wires_mode_switch_and_module():
    assert "storyos-mode-switch" in TEMPLATE
    assert 'data-storyos-mode="traditional"' in TEMPLATE
    assert 'data-storyos-mode="simulator"' in TEMPLATE
    assert 'id="simulator-panel-review"' in TEMPLATE
    assert "/static/simulator-panel-review.css" in TEMPLATE
    assert "/static/simulator-panel-review.js" in TEMPLATE


def test_app_exposes_existing_read_helper_and_dashboard_lifecycle():
    assert "window.storyosApiGet = apiGet" in APP
    assert 'new CustomEvent("storyos:dashboard-ready")' in APP
    assert "window.storyosApiRequest = apiRequest" in APP


def test_module_uses_validated_context_and_read_only_endpoints():
    for field in ("mode", "view", "project", "timeline_id", "chapter_id", "panel_execution_id"):
        assert f'params.get("{field}")' in MODULE
    assert "/api/projects/active" in MODULE
    assert "/api/reader-persona/model-panel/review" in MODULE
    assert "/api/reader-persona/model-panel/runs/" in MODULE
    assert "PANEL_RUN_NOT_FOUND" in MODULE
    assert "window.storyosApiGet" in MODULE
    assert "fetch(" not in MODULE
    assert "project_root" not in MODULE
    assert "fixtures" not in MODULE and "docs/design" not in MODULE
    assert "POST" not in MODULE and "PUT" not in MODULE and "PATCH" not in MODULE and "DELETE" not in MODULE
    assert "innerHTML" not in MODULE
    assert "unresolved" in MODULE
    assert "textContent" in MODULE


def test_production_styles_are_feature_namespaced_and_responsive():
    assert ".storyos-simulator-" in CSS
    assert "#dashboard-view.storyos-simulator-active" in CSS
    assert "@media (max-width: 900px)" in CSS
    assert "@media (max-width: 760px)" in CSS
    assert "!important" not in CSS


def test_qa_fallback_lists_eleven_redacted_fixtures():
    assert HARNESS.count('"') >= 22
    assert "ready-current" in HARNESS and "explicit-run-404" in HARNESS


def test_mock_panel_run_ui_has_no_live_controls_or_unsafe_inputs():
    assert "mode: \"mock\"" in RUN_MODULE
    assert "execution_profile: \"mock\"" in RUN_MODULE
    assert "max_provider_calls: 0" in RUN_MODULE
    assert "allow_model_call" not in RUN_MODULE
    assert "api_key" not in RUN_MODULE and "credentials" not in RUN_MODULE
    assert "storyosApiRequest(\"/api/reader-persona/model-panel/plan\"" in RUN_MODULE
    assert "storyosApiRequest(\"/api/reader-persona/model-panel/runs\"" in RUN_MODULE
    assert "AbortController" in RUN_MODULE
    assert "innerHTML" not in RUN_MODULE
    assert "Create Mock Panel Run" in TEMPLATE


def test_rc3_harness_uses_full_width_mount_and_fixture_contract_fields():
    assert "grid-template-columns: minmax(0, 1fr)" in HARNESS_HTML
    assert "width: 100%" in HARNESS_HTML
    assert "authority.panel_status" in MODULE
    assert "selectedRun.execution_id" in MODULE
    assert "Array.isArray(feedback?.concerns)" in MODULE
