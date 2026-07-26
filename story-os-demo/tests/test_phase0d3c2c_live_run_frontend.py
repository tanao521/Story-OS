"""Static contract checks for controlled, default-off Live Run wiring."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = (ROOT / "web" / "static" / "simulator-live-consent.js").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
ROUTES = (ROOT / "web" / "routes.py").read_text(encoding="utf-8")


def test_run_surface_is_second_confirmation_and_default_off():
    assert 'id="simulator-live-execution"' in TEMPLATE
    assert 'id="simulator-live-execution-checkbox"' in TEMPLATE
    assert 'Execute one Live Panel Run' in TEMPLATE
    assert 'const RUN_URL = "/api/reader-persona/model-panel/live/runs"' in MODULE
    assert 'capabilityEnabled' in MODULE
    assert 'LIVE_EXECUTION_DISABLED' in MODULE
    assert '"ready"' in MODULE and 'executionState' in MODULE


def test_run_contract_uses_private_header_and_no_client_overrides():
    assert '"X-StoryOS-Idempotency-Key": idempotencyKey' in MODULE
    assert 'body: JSON.stringify({ project_key: projectKey, ticket_id: ticketId })' in MODULE
    for forbidden in ("project_root", "provider:", "endpoint:", "credential:", "source_text", "prompt:", "force:", "retry:", "fallback:", "budget_override"):
        assert forbidden not in MODULE
    assert "idempotency_key" in MODULE
    assert "no automatic retry" in MODULE.lower() or "no automatic" in MODULE.lower()


def test_run_recovery_and_handoff_are_get_only_after_uncertain_response():
    assert 'const STATUS_URL = "/api/reader-persona/model-panel/live/status/"' in MODULE
    assert '"Reading the existing Live execution state; no POST will be sent' in MODULE
    assert "response_uncertain" in MODULE
    assert "reconciliation_required" in MODULE
    assert "panel_execution_id" in MODULE
    assert "storyos:panel-run-created" in MODULE
    assert "history.pushState" in MODULE
    assert 'url.searchParams.set("panel_execution_id", executionId)' in MODULE
    assert "privateExecutionContextKey" in MODULE
    assert "contextStillCurrent" in MODULE
    assert "no cross-context handoff was performed" in MODULE
    assert 'url.searchParams.set("project", issuedScope.projectKey)' in MODULE


def test_server_capability_is_default_off_and_run_route_uses_header():
    assert "STORYOS_LIVE_EXECUTION_UI_ENABLED" in ROUTES or "STORYOS_LIVE_EXECUTION_UI_ENABLED" in (ROOT / "system" / "live_panel_execution_service.py").read_text(encoding="utf-8")
    assert '"LIVE_EXECUTION_DISABLED"' in ROUTES
    assert 'alias="X-StoryOS-Idempotency-Key"' in ROUTES
    assert 'allowed = {"project_key", "ticket_id"}' in ROUTES
