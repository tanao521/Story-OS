"""Phase 0D6-C-B explicit-start frontend contract tests."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
MODULE = (ROOT / "web" / "static" / "simulator-chapter-progression.js").read_text(encoding="utf-8")


def test_start_route_is_reachable_only_from_explicit_start_path():
    assert 'fetch("/api/chapter-progression/start-turn"' in MODULE
    assert "function onStartClick" in MODULE
    assert "startFromIntent(intent)" in MODULE
    init = MODULE[MODULE.index("function init()"):MODULE.index("window.StoryOSChapterProgression")]
    assert "requestStart(" not in init
    assert "startFromIntent(" not in init


def test_start_control_has_single_flight_and_frozen_snapshot_guards():
    assert "activeStartPromise" in MODULE
    assert "if (state.activeStartPromise || state.status === \"STARTING\") return;" in MODULE
    assert "Object.freeze({ operation_id" in MODULE
    assert "expected_readiness_fingerprint" in MODULE
    assert "state.status = \"STARTING\"" in MODULE
    assert "start.disabled = state.status === \"STARTING\"" in MODULE


def test_request_snapshot_uses_sealed_fields_without_client_authority():
    for field in (
        "operation_id", "project_id", "timeline_id", "branch_id",
        "previous_chapter_id", "successor_chapter_id",
        "expected_readiness_fingerprint",
    ):
        assert field in MODULE
    assert "chapter_id + 1" not in MODULE
    assert "successor_chapter_id =" not in MODULE
    assert "localStorage" not in MODULE
    assert "sessionStorage" not in MODULE


def test_retry_reuses_same_intent_and_response_loss_is_retryable():
    assert 'state.status === "START_RETRYABLE_ERROR" && state.startIntent' in MODULE
    assert "return state.startIntent" in MODULE
    assert 'error.code = "RESPONSE_UNREADABLE"' in MODULE
    assert "error.ambiguous = true" in MODULE
    assert "same frozen request can be retried safely" in MODULE
    assert "JSON.stringify(snapshot)" in MODULE


def test_terminal_errors_clear_intent_and_do_not_blind_retry():
    for code in ("OPERATION_CONFLICT", "TURN_START_READINESS_CHANGED", "TURN_START_SOURCE_CHANGED", "CORRUPT_OPERATION", "TURN_ALREADY_STARTED"):
        assert code in MODULE
    assert "clearStartIntent(); state.status = \"STALE\"" in MODULE
    assert "clearStartIntent(); state.status = PRESENTATION[code]" in MODULE
    assert "beginReadiness(state.context)" in MODULE


def test_success_validates_scope_turn_and_rebinds_server_identity():
    assert "startFieldsValid(result, intent)" in MODULE
    assert 'result.turn_status === "awaiting_action"' in MODULE
    assert "rebindStarted(result, intent)" in MODULE
    assert "result.successor_chapter_id" in MODULE
    assert "result.turn_id" in MODULE
    assert 'view: "narrative-turn"' in MODULE
    assert "focusTurnWorkspace" in MODULE
    assert "automatic" in MODULE.lower()


def test_context_race_and_traditional_mode_clear_pending_intent():
    assert "sameCurrentContext(intent)" in MODULE
    assert "if (!sameCurrentContext(intent))" in MODULE
    assert "clearStartIntent(); state.startedResult = null; schedule(true);" in MODULE
    assert "if (mode() !== \"simulator\")" in MODULE
    assert "clearStartIntent(); state.context = null" in MODULE


def test_ready_and_retry_controls_are_single_and_accessible():
    assert TEMPLATE.count('data-progression-start') == 1
    assert 'aria-describedby="simulator-chapter-progression-status"' in TEMPLATE
    assert "data-existing-turn-continue" in TEMPLATE
    assert "data-legacy-next-chapter" in TEMPLATE
    assert "legacyNext.classList.toggle(\"hidden\", available)" in MODULE
