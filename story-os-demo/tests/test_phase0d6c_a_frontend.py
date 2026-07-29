"""Phase 0D6-C-A compatibility/static frontend contract tests.

C-B extends the C-A surface with one explicit start path; these assertions
retain the read-only context, safe-code, and fail-closed guarantees.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "web" / "templates" / "index.html"
MODULE = ROOT / "web" / "static" / "simulator-chapter-progression.js"
CSS = ROOT / "web" / "static" / "simulator-chapter-progression.css"
NAVIGATOR = ROOT / "web" / "static" / "simulator-context-navigator.js"
ROUTE = ROOT / "web" / "chapter_progression_routes.py"


def test_progression_surface_is_simulator_only_and_loaded():
    template = TEMPLATE.read_text(encoding="utf-8")
    assert "data-chapter-progression" in template
    assert "simulator-chapter-progression.css" in template
    assert "simulator-chapter-progression.js" in template
    assert "aria-live=\"polite\"" in template
    assert "data-existing-turn-continue" in template
    assert "data-legacy-next-chapter" in template


def test_progression_module_keeps_readiness_and_fails_closed():
    source = MODULE.read_text(encoding="utf-8")
    assert "/api/chapter-progression/readiness" in source
    assert "cache: \"no-store\"" in source
    assert "AbortController" in source
    assert "contextKey" in source
    assert "READY_TO_START_TURN" in source
    assert "TURN_ALREADY_STARTED" in source
    for code in (
        "BLOCKED_PREVIOUS_CHAPTER_NOT_COMPLETE",
        "BLOCKED_COMPLETION_RECOVERY_REQUIRED",
        "BLOCKED_LIFECYCLE_NOT_CREATED",
        "BLOCKED_LIFECYCLE_INCOMPLETE",
        "BLOCKED_LIFECYCLE_CONFLICT",
        "BLOCKED_SUCCESSOR_NOT_VISIBLE",
        "BLOCKED_SUCCESSOR_ASSETS_INCOMPLETE",
        "BLOCKED_BRANCH_NOT_ACTIVE",
        "BLOCKED_BRANCH_ARCHIVED",
        "BLOCKED_PLANNING_MISSING",
        "BLOCKED_PLANNING_STALE",
        "BLOCKED_SOURCE_MISSING",
        "BLOCKED_SOURCE_CHANGED",
        "BLOCKED_CANON_CHANGED",
        "BLOCKED_SCOPE_MISMATCH",
        "BLOCKED_TIMELINE_UNSUPPORTED",
        "BLOCKED_EXISTING_TURN_CORRUPT",
        "BLOCKED_CORRUPT_AUTHORITY",
    ):
        assert code in source
    assert "localStorage" not in source
    assert "sessionStorage" not in source
    assert "operation_id" in source
    assert "/api/chapter-progression/start-turn" in source
    assert "startIntentForClick" in source
    assert "activeStartPromise" in source
    assert "chapter_id + 1" not in source
    assert "successor_chapter_id =" not in source


def test_c_b_renders_one_ready_start_control_and_gates_legacy_navigation():
    source = MODULE.read_text(encoding="utf-8")
    template = TEMPLATE.read_text(encoding="utf-8")
    assert template.count('data-progression-start') == 1
    assert "readyAllowed" in source
    assert "start.textContent = retryAllowed ? \"Retry start safely\" : \"Start next chapter\"" in source
    assert "continueExistingTurn" in source
    assert "data-legacy-next-chapter" in source


def test_existing_turn_rebind_uses_existing_context_navigator():
    module = MODULE.read_text(encoding="utf-8")
    navigator = NAVIGATOR.read_text(encoding="utf-8")
    assert "StoryOSContextNavigator" in module
    assert "StoryOSContextNavigator = { rebind" in navigator
    assert "successor_chapter_id" in module
    assert "existing_turn_id" in module
    assert "view: \"narrative-turn\"" in module


def test_progression_css_covers_mobile_focus_and_reduced_motion():
    source = CSS.read_text(encoding="utf-8")
    assert "@media (max-width: 720px)" in source
    assert "min-height: 44px" in source
    assert "focus-visible" in source
    assert "prefers-reduced-motion" in source


def test_sealed_route_remains_no_store_and_read_only_get_is_available():
    source = ROUTE.read_text(encoding="utf-8")
    assert '@router.get("/readiness")' in source
    assert '"Cache-Control": "no-store"' in source
    assert '@router.post("/start-turn")' in source  # sealed backend route remains unchanged
