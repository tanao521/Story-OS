"""Static contract checks for the read-only Live Plan/Consent surface."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
MODULE = (ROOT / "web" / "static" / "simulator-live-consent.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "static" / "simulator-panel-review.css").read_text(encoding="utf-8")
CONTRACT = (ROOT / "core" / "contracts" / "live_panel_execution.py").read_text(encoding="utf-8")


def test_live_surface_is_wired_as_an_accessible_read_only_dialog():
    assert 'id="simulator-live-consent"' in TEMPLATE
    assert 'id="simulator-live-consent-dialog"' in TEMPLATE
    assert 'role="dialog"' in TEMPLATE and 'aria-labelledby="simulator-live-consent-dialog-title"' in TEMPLATE
    assert 'aria-describedby="simulator-live-consent-dialog-description"' in TEMPLATE
    assert 'id="simulator-live-consent-checkbox"' in TEMPLATE
    assert 'id="simulator-live-consent-submit"' in TEMPLATE
    assert 'id="simulator-live-consent-open-reason"' in TEMPLATE
    assert 'id="simulator-live-consent-reset"' in TEMPLATE
    assert 'Create consent ticket' in TEMPLATE
    assert '/static/simulator-live-consent.js' in TEMPLATE


def test_live_module_uses_only_safe_profiles_and_consent_contracts():
    assert 'const PROFILE_URL = "/api/reader-persona/live/profiles"' in MODULE
    assert 'const CONSENT_URL = "/api/reader-persona/model-panel/live/consent"' in MODULE
    assert "storyosApiRequest" in MODULE and "AbortController" in MODULE
    assert "localStorage" not in MODULE and "sessionStorage" not in MODULE
    assert "innerHTML" not in MODULE and "console." not in MODULE
    assert "project_root" not in MODULE and "api_key" not in MODULE and "credentials" not in MODULE
    assert "provider_endpoint" not in MODULE and "source_text" not in MODULE


def test_consent_payload_is_minimal_and_ticket_is_memory_only():
    for field in ("project_key", "chapter_id", "source_version_id", "persona_ids", "profile_id", "max_provider_calls", "consent_text_version"):
        assert f"{field}:" in MODULE
    assert "window.__storyosLive" not in MODULE
    assert "navigator.clipboard" not in MODULE
    assert "Provider calls: 0" in MODULE and "Token usage: 0" in MODULE
    assert "Live Run remains disabled" in MODULE


def test_live_budget_and_readiness_are_server_owned():
    for field in ("max_input_tokens", "max_total_tokens", "cost_estimate_available", "token_counter_available", "ready_for_consent", "readiness_code"):
        assert f'"{field}"' in CONTRACT
    assert "Cost estimate unavailable" in MODULE
    assert "Retry: 0 · Fallback: none" in MODULE
    assert "INPUT_TOKEN_BUDGET_UNAVAILABLE" in MODULE


def test_live_surface_is_responsive_and_namespaced():
    assert ".storyos-live-consent" in CSS
    assert ".storyos-live-persona-options" in CSS
    assert "@media (max-width: 900px)" in CSS
    assert "@media (max-width: 760px)" in CSS
    assert "!important" not in CSS


def test_consent_state_integrity_has_authoritative_gate_and_expiry_lifecycle():
    for marker in ("authoritativeContextReady", "ticketExpiryTimer", "issuedSelectionFingerprint", "consentIssuedForFingerprint", "invalidateConsent", "scheduleTicketExpiry", "clearTicketExpiryTimer", "expireTicket", "visibilitychange"):
        assert marker in MODULE
    assert "open.disabled = !entryReady()" in MODULE
    assert "Waiting for authoritative project context." in MODULE
    assert "source_available" in MODULE
    assert "selectionFingerprint" in MODULE
    assert "busy = false" in MODULE
    assert "Profile selection changed" in MODULE
    assert "Persona selection changed" in MODULE
    assert "Requested call limit changed" in MODULE
    assert "Consent ticket expired" in MODULE


def test_consent_success_requires_fresh_confirmation_and_disables_repeat_submit():
    assert 'if (!canSubmit() || busy) return;' in MODULE
    assert 'consentIssuedForFingerprint !== fingerprint' in MODULE
    assert '$("check").checked = false' in MODULE
    assert '$("reset")?.classList.remove("hidden")' in MODULE
    assert 'startNewConsentReview' in MODULE
    assert 'New consent review started' in MODULE
