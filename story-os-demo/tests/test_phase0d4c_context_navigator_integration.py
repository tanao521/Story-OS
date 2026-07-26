"""Phase 0D4-C-RC3: Context Navigator integration tests.

Verifies the RC2/RC3 fixes:
1. existing view preserved — updateUrl does not overwrite an existing valid view
2. missing view defaults correctly — only defaults to reader-panel-review when view absent
3. Narrative Turn view survives Project/Timeline/Chapter/Source changes
4. Reader Panel default behaviour not broken
5. no document.write bypass — navigator loads via normal <script> tag
6. workspace visibility uses nt-visible class
7. Branch URL scope selection does not mutate registry (read-only endpoint)

These are static contract tests (reading the production JS/HTML source)
plus an integration test that uses the isolated fixture to verify the
/api/simulator/context endpoint returns a branches list without writing
to the branch registry.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
NAVIGATOR_JS = (ROOT / "web" / "static" / "simulator-context-navigator.js").read_text(encoding="utf-8")
NARRATIVE_TURN_JS = (ROOT / "web" / "static" / "simulator-narrative-turn.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")


# ===========================================================================
# 1. Existing view preserved
# ===========================================================================

class TestExistingViewPreserved:
    """updateUrl must not overwrite an existing valid view."""

    def test_updateUrl_reads_current_view_before_setting(self) -> None:
        # The updateUrl function must check the current view in the URL
        # and only set the default when it is absent.
        assert "next.get(\"view\")" in NAVIGATOR_JS or "next.get('view')" in NAVIGATOR_JS

    def test_updateUrl_does_not_unconditionally_set_reader_panel(self) -> None:
        # Must NOT contain an unconditional next.set("view", "reader-panel-review")
        # that ignores the current view. The only set should be inside an
        # if (!currentView) block.
        lines = NAVIGATOR_JS.split("\n")
        for i, line in enumerate(lines):
            stripped = line.strip()
            if 'next.set("view"' in stripped and "reader-panel-review" in stripped:
                # This line must be inside a conditional that checks currentView
                # Look backwards for an if statement
                found_if = False
                for j in range(i - 1, max(i - 5, -1), -1):
                    if "if" in lines[j] and ("currentView" in lines[j] or "!currentView" in lines[j]):
                        found_if = True
                        break
                assert found_if, (
                    f"updateUrl sets view=reader-panel-review unconditionally at line {i+1}: {stripped}"
                )

    def test_updateUrl_preserves_view_when_changes_include_view(self) -> None:
        # When changes object has a view key, it should use that value.
        assert 'key === "view"' in NAVIGATOR_JS or "key === 'view'" in NAVIGATOR_JS


# ===========================================================================
# 2. Missing view defaults correctly
# ===========================================================================

class TestMissingViewDefaults:
    """When no view is in the URL, default to reader-panel-review."""

    def test_default_view_is_reader_panel_review(self) -> None:
        assert "reader-panel-review" in NAVIGATOR_JS

    def test_default_only_set_when_view_absent(self) -> None:
        # The condition must check for absence (!currentView or currentView is falsy)
        assert '!currentView' in NAVIGATOR_JS or 'if (!currentView)' in NAVIGATOR_JS


# ===========================================================================
# 3. Narrative Turn view survives context changes
# ===========================================================================

class TestNarrativeTurnViewSurvivesChanges:
    """Changing Project/Timeline/Chapter/Source must preserve view=narrative-turn."""

    def test_navigator_does_not_hardcode_view_in_change_handlers(self) -> None:
        # The change event handlers for project/timeline/chapter/source
        # must NOT include view in their updateUrl calls.
        # Find all updateUrl calls in bindChanges
        bind_start = NAVIGATOR_JS.find("function bindChanges")
        if bind_start == -1:
            pytest.skip("bindChanges not found")
        bind_end = NAVIGATOR_JS.find("}", bind_start + 100)
        bind_section = NAVIGATOR_JS[bind_start:bind_end]
        # None of the updateUrl calls in bindChanges should set view
        update_calls = [line for line in bind_section.split("\n") if "updateUrl" in line]
        for call in update_calls:
            assert "view" not in call, (
                f"bindChanges updateUrl call includes view: {call.strip()}"
            )

    def test_autocomplete_preserves_existing_view(self) -> None:
        # The autocomplete section in load() that calls updateUrl with
        # project/timeline/chapter should preserve the current view.
        load_section = NAVIGATOR_JS[NAVIGATOR_JS.find("async function load"):]
        # Find the updateUrl call in the autocomplete section
        update_idx = load_section.find("updateUrl(")
        if update_idx == -1:
            pytest.skip("No updateUrl in load()")
        # Get context around the call
        context = load_section[update_idx:update_idx + 300]
        # It should either include view: currentParams.get("view") or
        # spread ...(view ? { view } : {})
        assert "view" in context, (
            "updateUrl in load() does not reference view — existing view may be lost"
        )


# ===========================================================================
# 4. Reader Panel default behaviour not broken
# ===========================================================================

class TestReaderPanelDefaultNotBroken:
    """When no view is present, navigator still defaults to reader-panel-review."""

    def test_reader_panel_review_still_in_navigator(self) -> None:
        assert "reader-panel-review" in NAVIGATOR_JS

    def test_index_html_has_reader_panel_review_section(self) -> None:
        assert 'id="simulator-panel-review"' in INDEX_HTML or "simulator-panel-review" in INDEX_HTML


# ===========================================================================
# 5. No document.write bypass
# ===========================================================================

class TestNoDocumentWriteBypass:
    """navigator-context-navigator.js must load via normal <script> tag."""

    def test_no_document_write_in_index_html(self) -> None:
        # index.html must NOT contain document.write for conditional loading
        assert "document.write" not in INDEX_HTML, (
            "index.html contains document.write — RC1 conditional loader not removed"
        )

    def test_navigator_loaded_via_script_tag(self) -> None:
        # The navigator must be loaded via a normal <script src=...> tag
        assert 'src="/static/simulator-context-navigator.js' in INDEX_HTML

    def test_navigator_script_not_conditional(self) -> None:
        # The script tag must not be inside a conditional block
        nav_idx = INDEX_HTML.find('simulator-context-navigator.js')
        assert nav_idx != -1
        # Check surrounding context for document.write or inline conditionals
        surrounding = INDEX_HTML[max(0, nav_idx - 200):nav_idx + 100]
        assert "document.write" not in surrounding
        assert "<!--" not in surrounding or "-->" in surrounding[:200]


# ===========================================================================
# 6. Workspace visibility uses nt-visible
# ===========================================================================

class TestWorkspaceVisibilityNtVisible:
    """showWorkspace/hideWorkspace must toggle nt-visible class."""

    def test_showWorkspace_adds_nt_visible(self) -> None:
        assert 'classList.add("nt-visible")' in NARRATIVE_TURN_JS or \
               "classList.add('nt-visible')" in NARRATIVE_TURN_JS

    def test_hideWorkspace_removes_nt_visible(self) -> None:
        assert 'classList.remove("nt-visible")' in NARRATIVE_TURN_JS or \
               "classList.remove('nt-visible')" in NARRATIVE_TURN_JS

    def test_showWorkspace_also_removes_hidden(self) -> None:
        # showWorkspace should also remove the hidden class for completeness
        show_start = NARRATIVE_TURN_JS.find("function showWorkspace")
        assert show_start != -1
        show_section = NARRATIVE_TURN_JS[show_start:show_start + 200]
        assert "hidden" in show_section

    def test_panel_review_css_does_not_hide_narrative_turn(self) -> None:
        panel_css = (ROOT / "web" / "static" / "simulator-panel-review.css").read_text(encoding="utf-8")
        # The hide rule must exclude narrative-turn-workspace
        if "simulator-panel-review" in panel_css and "dashboard-main" in panel_css:
            assert "narrative-turn-workspace" in panel_css, (
                "simulator-panel-review.css hide rule does not exclude #narrative-turn-workspace"
            )


# ===========================================================================
# 7. Branch URL scope selection does not mutate registry
# ===========================================================================

class TestBranchSelectionNoMutation:
    """Branch selection via URL must not call mutation endpoints."""

    def test_narrative_turn_js_branch_change_only_updates_url(self) -> None:
        # The branch selector change handler should only call pushUrl
        # with branch_id, not call any mutation endpoint.
        nt_branch_section = NARRATIVE_TURN_JS[NARRATIVE_TURN_JS.find("branchSel.addEventListener(\"change\""):]
        # Get the handler body (up to the closing })
        handler_end = nt_branch_section.find("});")
        handler = nt_branch_section[:handler_end]
        # Must contain pushUrl with branch_id
        assert "pushUrl" in handler
        assert "branch_id" in handler
        # Must NOT contain fetch/POST to mutation endpoints
        assert "/activate" not in handler
        assert "/select" not in handler or "select_branch" not in handler
        assert "/archive" not in handler
        assert "/create" not in handler
        assert "/restore" not in handler

    def test_loadContextBar_does_not_mutate(self) -> None:
        # loadContextBar should only GET /api/simulator/context
        load_start = NARRATIVE_TURN_JS.find("async function loadContextBar")
        assert load_start != -1
        load_section = NARRATIVE_TURN_JS[load_start:load_start + 600]
        # Must use GET (apiGet), not POST
        assert "apiGet" in load_section
        assert "apiPost" not in load_section

    def test_simulator_context_endpoint_returns_branches_readonly(self) -> None:
        """Integration test: /api/simulator/context returns branches without mutation."""
        from tests._rc2_browser_fixture_server import setup_workspace

        tmp_dir = Path(tempfile.mkdtemp(prefix="rc3_nav_test_"))
        info = setup_workspace(tmp_dir)

        # Record registry revision before
        from core.project_context import get_project_context
        from core.contracts.narrative_turn import TimelineContext
        from system.narrative_branch_store import NarrativeBranchStore

        project_root = tmp_dir / "projects" / info["project_id"]
        ctx = get_project_context(project_root)
        tl_ctx = TimelineContext(project_id=info["project_id"], timeline_id=info["timeline_id"])
        store = NarrativeBranchStore(ctx)
        revision_before = store.get_registry_revision(tl_ctx)
        active_before = store.get_active_branch_id(tl_ctx)

        # Start the app pointing at this workspace
        import os
        original_cwd = os.getcwd()
        os.chdir(tmp_dir)
        try:
            from web.app import app
            client = TestClient(app)

            # Call /api/simulator/context
            resp = client.get(f"/api/simulator/context?project_id={info['project_id']}&timeline_id={info['timeline_id']}")
            assert resp.status_code == 200
            data = resp.json().get("result", resp.json())
            assert "branches" in data
            branches = data["branches"]
            assert len(branches) == 4  # root, alternate, old-route, state-missing

            branch_ids = {b["branch_id"] for b in branches}
            assert branch_ids == {"root", "alternate", "old-route", "state-missing"}

            # Verify lifecycle statuses
            for b in branches:
                if b["branch_id"] == "old-route":
                    assert b["lifecycle_status"] == "archived"
                else:
                    assert b["lifecycle_status"] == "open"
        finally:
            os.chdir(original_cwd)

        # Record registry revision after — must be unchanged
        revision_after = store.get_registry_revision(tl_ctx)
        active_after = store.get_active_branch_id(tl_ctx)
        assert revision_before == revision_after, (
            f"Registry revision mutated: {revision_before} → {revision_after}"
        )
        assert active_before == active_after, (
            f"Active branch mutated: {active_before} → {active_after}"
        )

    def test_state_missing_branch_has_unavailable_narrative_state(self) -> None:
        """state-missing branch should return narrative_state_data=unavailable."""
        from tests._rc2_browser_fixture_server import setup_workspace

        tmp_dir = Path(tempfile.mkdtemp(prefix="rc3_nav_sm_"))
        info = setup_workspace(tmp_dir)

        import os
        original_cwd = os.getcwd()
        os.chdir(tmp_dir)
        try:
            from web.app import app
            client = TestClient(app)

            # Call /api/narrative-turn/context with state-missing branch
            resp = client.get(
                f"/api/narrative-turn/context"
                f"?project_id={info['project_id']}"
                f"&timeline_id={info['timeline_id']}"
                f"&branch_id=state-missing"
                f"&chapter_id={info['chapter_id']}"
            )
            assert resp.status_code == 200
            data = resp.json().get("result", resp.json())
            branch = data.get("branch", {})
            assert branch.get("lifecycle") == "open"
            assert branch.get("narrative_state_data") == "unavailable"
        finally:
            os.chdir(original_cwd)
