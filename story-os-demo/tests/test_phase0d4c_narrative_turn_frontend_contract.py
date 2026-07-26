"""Phase 0D4-C focused tests: Narrative Turn frontend DOM/contract tests.

Verifies that the production HTML template, CSS, and JS module satisfy the
component, accessibility, race protection, and security contracts defined
in the sealed UI specification.

Covers:
- workspace is <section>, not nested <main>
- 10 component mount points present
- exactly 3 native radios via <fieldset> + <legend>
- unavailable radio uses data-unavailable + aria-describedby (no aria-disabled)
- stale group uses native disabled
- single business live region (TurnStatusNotice)
- other components have no aria-live / role=alert
- primary button permanently disabled with visible reason
- custom action character boundary 200/201
- recommended ↔ custom mutual exclusion (clear selection, retain text)
- stale response guard (generation counter)
- AbortController usage
- Back/Forward (popstate) handler
- no raw custom_action_text in URL / localStorage
- no full fingerprint display in UI
- reduced motion media query
- responsive breakpoints (desktop ≥1280, narrow ≤900, mobile ≤760)
- no horizontal overflow contract (min-width: 0 on row/container)
- JS module never calls innerHTML for untrusted content
- JS module never persists custom_action_text to localStorage
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "web" / "static" / "simulator-narrative-turn.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "static" / "simulator-narrative-turn.css").read_text(encoding="utf-8")


# ===========================================================================
# Section 1: Workspace mount + DOM structure
# ===========================================================================

class TestWorkspaceMount:
    def test_workspace_is_section_not_nested_main(self) -> None:
        assert '<section id="narrative-turn-workspace"' in TEMPLATE
        # The workspace is inside <main id="dashboard-view">; it must not be
        # a nested <main> element.
        ws_start = TEMPLATE.index('<section id="narrative-turn-workspace"')
        ws_end = TEMPLATE.index("</section>", ws_start)
        ws_block = TEMPLATE[ws_start:ws_end]
        assert "<main" not in ws_block
        assert "</main" not in ws_block

    def test_workspace_has_region_role_and_aria_labelledby(self) -> None:
        assert 'role="region"' in TEMPLATE
        assert 'aria-labelledby="nt-heading"' in TEMPLATE

    def test_workspace_has_aria_busy_and_data_context_state(self) -> None:
        assert 'aria-busy="false"' in TEMPLATE
        assert 'data-context-state="initial"' in TEMPLATE

    def test_workspace_has_nt_heading(self) -> None:
        assert 'id="nt-heading"' in TEMPLATE


# ===========================================================================
# Section 2: 10 component mount points
# ===========================================================================

class TestComponentMountPoints:
    def test_narrative_situation_header_mounted(self) -> None:
        assert 'class="nt-situation-header"' in TEMPLATE
        assert 'id="nt-situation-meta"' in TEMPLATE
        assert 'id="nt-situation-chips"' in TEMPLATE

    def test_narrative_evidence_summary_mounted(self) -> None:
        assert 'id="nt-evidence-summary"' in TEMPLATE
        assert 'id="nt-evidence-body"' in TEMPLATE
        assert 'id="nt-evidence-heading"' in TEMPLATE

    def test_recommended_action_group_mounted(self) -> None:
        assert 'id="nt-recommended-action-group"' in TEMPLATE
        assert 'id="nt-action-form"' in TEMPLATE
        assert 'id="nt-actions-heading"' in TEMPLATE

    def test_custom_action_composer_mounted(self) -> None:
        assert 'id="nt-custom-action-composer"' in TEMPLATE
        assert 'id="nt-custom-action-textarea"' in TEMPLATE
        assert 'id="nt-custom-action-counter"' in TEMPLATE
        assert 'id="nt-custom-action-submit"' in TEMPLATE

    def test_feasibility_panel_mounted(self) -> None:
        assert 'id="nt-feasibility-panel"' in TEMPLATE
        assert 'id="nt-feasibility-body"' in TEMPLATE
        assert 'id="nt-feasibility-heading"' in TEMPLATE

    def test_consequence_preview_mounted(self) -> None:
        assert 'id="nt-consequence-preview"' in TEMPLATE
        assert 'id="nt-preview-body"' in TEMPLATE
        assert 'id="nt-preview-heading"' in TEMPLATE

    def test_turn_primary_action_mounted(self) -> None:
        assert 'id="nt-primary-action"' in TEMPLATE
        assert 'id="nt-confirm-result"' in TEMPLATE

    def test_turn_status_notice_mounted(self) -> None:
        assert 'id="nt-status-notice"' in TEMPLATE

    def test_evidence_rail_mounted(self) -> None:
        assert 'id="nt-evidence-rail"' in TEMPLATE
        assert 'id="nt-evidence-rail-body"' in TEMPLATE


# ===========================================================================
# Section 3: Recommended action contract (native radios + fieldset)
# ===========================================================================

class TestRecommendedActionContract:
    def test_js_uses_fieldset_and_legend(self) -> None:
        assert "fieldset" in JS
        assert "legend" in JS

    def test_js_creates_native_radio_inputs(self) -> None:
        assert 'radio.type = "radio"' in JS
        assert 'radio.name = "narrative-turn-action"' in JS

    def test_js_does_not_add_duplicate_role_radio(self) -> None:
        # Native <input type="radio"> already exposes role=radio; we must not
        # duplicate it.
        assert 'setAttribute("role", "radio")' not in JS
        assert "role=\"radio\"" not in JS

    def test_js_does_not_add_aria_checked(self) -> None:
        # Native <input type="radio"> already exposes aria-checked via :checked.
        assert 'setAttribute("aria-checked"' not in JS

    def test_js_does_not_autoselect_first_action(self) -> None:
        # The renderer must not set radio.checked = true on the first action
        # by default. It should only check the action that matches
        # state.selectedActionId (which starts as null).
        # We look for the pattern where radio.checked is set ONLY inside the
        # selectedActionId equality branch.
        assert "state.selectedActionId === action.action_id" in JS or \
               "state.selectedActionId === action.action_id && state.actionSource === \"recommended\"" in JS

    def test_js_preserves_deterministic_order(self) -> None:
        # The renderer iterates over plan.recommended_actions in order.
        assert "actions.forEach" in JS or "for (const action of actions)" in JS

    def test_js_renders_exactly_3_actions_from_plan(self) -> None:
        # The renderer does not hard-code a count; it iterates the plan.
        # The 0D4-C contract guarantees plan.recommended_actions.length == 3.
        # We verify the renderer does not slice or limit the list.
        assert ".slice(0, 3)" not in JS
        assert ".slice(0,3)" not in JS

    def test_js_unavailable_row_uses_data_unavailable(self) -> None:
        assert "row.dataset.unavailable" in JS or 'data-unavailable="true"' in JS

    def test_js_unavailable_radio_uses_aria_describedby(self) -> None:
        assert 'setAttribute("aria-describedby", reasonId)' in JS

    def test_js_unavailable_radio_does_not_use_aria_disabled(self) -> None:
        # Find the action row rendering section and verify aria-disabled is
        # not set on the radio.
        # We look for "aria-disabled" anywhere in the JS and ensure it only
        # appears on the primary button (which is allowed) — not on radios.
        radio_block_start = JS.index("function renderActionRow")
        radio_block_end = JS.index("function circleNumber", radio_block_start)
        radio_block = JS[radio_block_start:radio_block_end]
        assert "aria-disabled" not in radio_block

    def test_js_unavailable_radio_does_not_use_native_disabled(self) -> None:
        radio_block_start = JS.index("function renderActionRow")
        radio_block_end = JS.index("function circleNumber", radio_block_start)
        radio_block = JS[radio_block_start:radio_block_end]
        assert "radio.disabled = true" not in radio_block

    def test_js_stale_group_uses_native_disabled(self) -> None:
        # markActionGroupStale(stale=true) sets radio.disabled = true.
        stale_start = JS.index("function markActionGroupStale")
        stale_end = JS.index("function renderCustomActionComposer", stale_start)
        stale_block = JS[stale_start:stale_end]
        assert "radio.disabled = true" in stale_block

    def test_js_unavailable_action_does_not_enable_primary(self) -> None:
        # The primary button is permanently disabled in 0D4-C.
        # The action row renderer must never enable it.
        # We verify the primary button renderer keeps it disabled.
        primary_start = JS.index("function renderPrimaryAction")
        primary_end = JS.index("function renderContextBar", primary_start)
        primary_block = JS[primary_start:primary_end]
        assert "btn.disabled = true" in primary_block
        assert "btn.disabled = false" not in primary_block


# ===========================================================================
# Section 4: Single live region contract
# ===========================================================================

class TestSingleLiveRegion:
    def test_template_has_single_business_live_region(self) -> None:
        # nt-status-notice is the ONLY element with aria-live in the workspace
        # template block.
        ws_start = TEMPLATE.index('<section id="narrative-turn-workspace"')
        ws_end = TEMPLATE.index("</section>", ws_start)
        ws_block = TEMPLATE[ws_start:ws_end]
        # The status notice div carries aria-live.
        assert 'id="nt-status-notice"' in ws_block
        assert 'aria-live="polite"' in ws_block
        # Count aria-live occurrences in the workspace block.
        live_count = ws_block.count("aria-live")
        assert live_count == 1, f"expected exactly 1 aria-live in workspace, got {live_count}"

    def test_template_other_components_have_no_role_alert(self) -> None:
        ws_start = TEMPLATE.index('<section id="narrative-turn-workspace"')
        ws_end = TEMPLATE.index("</section>", ws_start)
        ws_block = TEMPLATE[ws_start:ws_end]
        # role="alert" must not appear anywhere in the workspace template
        # (it is only set dynamically by noticeError on the same nt-status-notice).
        assert 'role="alert"' not in ws_block

    def test_js_role_alert_only_on_status_notice(self) -> None:
        # role="alert" must only be set on #nt-status-notice.
        # We verify every occurrence of 'role", "alert"' is inside noticeError.
        for m in re.finditer(r'setAttribute\("role", "alert"\)', JS):
            # Walk backwards to find the enclosing function.
            pos = m.start()
            # Look for the nearest preceding "function " declaration.
            fn_start = JS.rfind("function ", 0, pos)
            fn_end = JS.index("(", fn_start)
            fn_name = JS[fn_start + len("function "):fn_end].strip()
            assert fn_name == "noticeError", \
                f'role="alert" set outside noticeError (in {fn_name})'

    def test_js_role_status_only_on_status_notice(self) -> None:
        # role="status" must only be set on #nt-status-notice.
        for m in re.finditer(r'setAttribute\("role", "status"\)', JS):
            pos = m.start()
            fn_start = JS.rfind("function ", 0, pos)
            fn_end = JS.index("(", fn_start)
            fn_name = JS[fn_start + len("function "):fn_end].strip()
            assert fn_name in ("noticeAnnounce", "noticeClear"), \
                f'role="status" set outside notice* (in {fn_name})'

    def test_js_no_aria_live_outside_notice_functions(self) -> None:
        # aria-live may only be set inside noticeAnnounce / noticeError / noticeClear.
        for m in re.finditer(r'setAttribute\("aria-live"', JS):
            pos = m.start()
            fn_start = JS.rfind("function ", 0, pos)
            fn_end = JS.index("(", fn_start)
            fn_name = JS[fn_start + len("function "):fn_end].strip()
            assert fn_name in ("noticeAnnounce", "noticeError", "noticeClear"), \
                f'aria-live set outside notice* (in {fn_name})'

    def test_js_counter_uses_aria_describedby_not_live(self) -> None:
        # The character counter must not have aria-live.
        # It is associated via aria-describedby on the textarea (already in template).
        assert 'id="nt-custom-action-textarea"' in TEMPLATE
        assert 'aria-describedby="nt-custom-action-counter' in TEMPLATE
        # The counter element in the template must not have aria-live.
        counter_start = TEMPLATE.index('id="nt-custom-action-counter"')
        counter_end = TEMPLATE.index(">", counter_start)
        counter_tag = TEMPLATE[counter_start:counter_end]
        assert "aria-live" not in counter_tag


# ===========================================================================
# Section 5: Primary action contract
# ===========================================================================

class TestPrimaryAction:
    def test_primary_button_permanently_disabled_in_template(self) -> None:
        # The button must be born disabled in the static template.
        btn_start = TEMPLATE.index('id="nt-primary-action"')
        # Walk back to the opening <button
        open_start = TEMPLATE.rfind("<button", 0, btn_start)
        btn_end = TEMPLATE.index(">", btn_start)
        btn_open_tag = TEMPLATE[open_start:btn_end]
        assert "disabled" in btn_open_tag

    def test_primary_button_has_aria_disabled(self) -> None:
        btn_start = TEMPLATE.index('id="nt-primary-action"')
        open_start = TEMPLATE.rfind("<button", 0, btn_start)
        btn_end = TEMPLATE.index(">", btn_start)
        btn_open_tag = TEMPLATE[open_start:btn_end]
        assert 'aria-disabled="true"' in btn_open_tag

    def test_primary_button_starts_disabled(self) -> None:
        btn_start = TEMPLATE.index('id="nt-primary-action"')
        open_start = TEMPLATE.rfind("<button", 0, btn_start)
        btn_end = TEMPLATE.index(">", btn_start)
        btn_open_tag = TEMPLATE[open_start:btn_end]
        assert "disabled" in btn_open_tag

    def test_primary_button_label_is_confirm_action(self) -> None:
        assert "确认行动" in TEMPLATE

    def test_primary_button_has_confirm_result_panel(self) -> None:
        assert 'id="nt-confirm-result"' in TEMPLATE
        assert 'id="nt-confirm-summary"' in TEMPLATE
        assert 'id="nt-confirm-status"' in TEMPLATE
        assert 'id="nt-confirm-flags"' in TEMPLATE
        assert 'id="nt-confirm-next-fp"' in TEMPLATE

    def test_primary_button_does_not_rely_on_title_only(self) -> None:
        btn_start = TEMPLATE.index('id="nt-primary-action"')
        open_start = TEMPLATE.rfind("<button", 0, btn_start)
        btn_end = TEMPLATE.index("</button>", btn_start)
        btn_block = TEMPLATE[open_start:btn_end]
        assert "确认行动" in btn_block

    def test_js_toggles_primary_enabled(self) -> None:
        primary_start = JS.index("function renderPrimaryAction")
        primary_end = JS.index("function renderContextBar", primary_start)
        primary_block = JS[primary_start:primary_end]
        assert "btn.disabled = true" in primary_block
        assert "btn.disabled = !enabled" in primary_block
        assert 'aria-disabled", enabled ? "false" : "true"' in primary_block


# ===========================================================================
# Section 6: Custom action contract
# ===========================================================================

class TestCustomActionContract:
    def test_max_custom_length_is_200(self) -> None:
        assert "MAX_CUSTOM_LENGTH = 200" in JS

    def test_js_implements_nfkc_normalization(self) -> None:
        assert "normalize" in JS
        assert "NFKC" in JS

    def test_js_rejects_nul_and_control_chars(self) -> None:
        assert "\\u0000" in JS

    def test_js_character_counter_uses_normalized_text(self) -> None:
        # The counter text is "{count}/{MAX_CUSTOM_LENGTH}" where count is
        # the normalized length.
        assert "counter.textContent" in JS
        assert "${MAX_CUSTOM_LENGTH}" in JS or "{MAX_CUSTOM_LENGTH}" in JS

    def test_js_200_chars_submittable_201_not_submittable(self) -> None:
        # canSubmit requires count <= MAX_CUSTOM_LENGTH (strict).
        assert "count <= MAX_CUSTOM_LENGTH" in JS or "count <= 200" in JS
        # The submit button is disabled when count > MAX_CUSTOM_LENGTH.
        assert "submit.disabled = !canSubmit" in JS or "submit.disabled = !canSubmit;" in JS

    def test_js_does_not_implicit_submit_on_enter(self) -> None:
        # The textarea must not submit on Enter. We verify that
        # handleSubmitCustomAction is only called from a button click handler,
        # not from a textarea Enter / keydown / keypress handler.
        # Find all call sites (skip the function definition itself).
        call_sites = []
        for m in re.finditer(r"handleSubmitCustomAction\(\)", JS):
            pos = m.start()
            # Skip the function definition: "function handleSubmitCustomAction() {"
            prefix = JS[max(0, pos - 12):pos]
            if "function " in prefix:
                continue
            call_sites.append(pos)
        assert call_sites, "expected at least one call to handleSubmitCustomAction"
        for pos in call_sites:
            # Walk back to find the nearest addEventListener("click", ...).
            ctx_start = max(0, pos - 500)
            ctx_block = JS[ctx_start:pos]
            assert '"click"' in ctx_block or "'click'" in ctx_block, \
                "handleSubmitCustomAction must be called from a click handler, not Enter"
            # The handler must NOT be a keydown / keypress / Enter handler.
            assert '"keydown"' not in ctx_block and "'keydown'" not in ctx_block
            assert '"keypress"' not in ctx_block and "'keypress'" not in ctx_block

    def test_js_uses_explicit_secondary_button(self) -> None:
        assert 'id="nt-custom-action-submit"' in TEMPLATE
        # The submit button text must be an explicit action verb, not a chat
        # icon or arrow.
        btn_start = TEMPLATE.index('id="nt-custom-action-submit"')
        btn_end = TEMPLATE.index("</button>", btn_start)
        btn_block = TEMPLATE[btn_start:btn_end]
        assert "分析可行性" in btn_block

    def test_js_no_chat_bubble_or_avatar_or_autocomplete(self) -> None:
        assert "chat-bubble" not in JS and "chatBubble" not in JS
        assert "avatar" not in JS.lower()
        assert "autocomplete" not in JS.lower() or 'autocomplete="off"' in TEMPLATE

    def test_template_textarea_has_autocomplete_off(self) -> None:
        textarea_start = TEMPLATE.index('id="nt-custom-action-textarea"')
        textarea_end = TEMPLATE.index(">", textarea_start)
        textarea_tag = TEMPLATE[textarea_start:textarea_end]
        assert 'autocomplete="off"' in textarea_tag

    def test_js_does_not_compute_final_hash_in_browser(self) -> None:
        # The browser must not compute the final SHA-256 hash.
        # We verify that "sha256" or "sha-256" or "crypto.subtle" is not used
        # to compute the custom_action_text_hash.
        assert "crypto.subtle" not in JS
        assert "sha256" not in JS.lower()

    def test_js_uses_backend_response_hash(self) -> None:
        # The custom_action_text_hash comes from the backend response.
        assert "custom_action_text_hash" in JS

    def test_js_selecting_recommended_clears_custom_selection(self) -> None:
        # handleRecommendedSelected must clear custom selection (selectedActionId
        # is set, actionSource becomes "recommended", custom is no longer the source).
        fn_start = JS.index("function handleRecommendedSelected")
        fn_end = JS.index("function handleSubmitCustomAction", fn_start)
        fn_block = JS[fn_start:fn_end]
        assert 'state.actionSource = "recommended"' in fn_block
        assert "state.selectedActionId = actionId" in fn_block or \
               "state.selectedActionId = action.id" in fn_block

    def test_js_selecting_custom_clears_recommended_selection(self) -> None:
        fn_start = JS.index("function handleSubmitCustomAction")
        fn_end = JS.index("function requestFeasibilityAndPreview", fn_start)
        fn_block = JS[fn_start:fn_end]
        assert 'state.actionSource = "custom"' in fn_block
        assert "state.selectedActionId = null" in fn_block

    def test_js_retains_custom_text_after_recommended_selection(self) -> None:
        # handleRecommendedSelected must NOT clear state.customText.
        fn_start = JS.index("function handleRecommendedSelected")
        fn_end = JS.index("function handleSubmitCustomAction", fn_start)
        fn_block = JS[fn_start:fn_end]
        assert "state.customText = \"\"" not in fn_block
        assert "state.customText = ''" not in fn_block


# ===========================================================================
# Section 7: Race protection
# ===========================================================================

class TestRaceProtection:
    def test_js_uses_abort_controller(self) -> None:
        assert "AbortController" in JS
        assert "new AbortController()" in JS

    def test_js_uses_generation_counter(self) -> None:
        assert "state.generation" in JS
        assert "generation: 0" in JS
        assert "state.generation += 1" in JS or "state.generation++" in JS

    def test_js_aborts_previous_request_on_context_change(self) -> None:
        # bumpGeneration() calls state.controller.abort().
        fn_start = JS.index("function bumpGeneration")
        fn_end = JS.index("function isStale", fn_start)
        fn_block = JS[fn_start:fn_end]
        assert "state.controller.abort()" in fn_block

    def test_js_checks_response_generation_before_rendering(self) -> None:
        # Every async response handler must check isStale(generation) before
        # rendering.
        assert "isStale(generation)" in JS
        assert "if (isStale(generation)) return" in JS

    def test_js_silent_discard_does_not_announce(self) -> None:
        # The stale-response guard must NOT call noticeAnnounce or noticeError.
        # Find every "if (isStale(generation)) return" block and verify no
        # notice* call precedes the return on the same logical line.
        for m in re.finditer(r"if \(isStale\(generation\)\)\s*return", JS):
            # Look at the surrounding ~80 chars before the return.
            ctx_start = max(0, m.start() - 80)
            ctx_block = JS[ctx_start:m.end()]
            assert "noticeAnnounce" not in ctx_block
            assert "noticeError" not in ctx_block


# ===========================================================================
# Section 8: URL state contract
# ===========================================================================

class TestUrlStateContract:
    def test_js_parses_allowed_url_params(self) -> None:
        # parseUrl must read exactly: mode, view, project_id, timeline_id,
        # branch_id, chapter_id, source_version_id, turn_id, action_id.
        for field in (
            "mode", "view", "project_id", "timeline_id", "branch_id",
            "chapter_id", "source_version_id", "turn_id", "action_id",
        ):
            assert f'params.get("{field}")' in JS, f"parseUrl must read {field}"

    def test_js_does_not_parse_forbidden_url_params(self) -> None:
        # parseUrl must NOT read custom_action_text, custom_action_text_hash,
        # context_fingerprint, validation payload, or preview payload.
        forbidden = (
            "custom_action_text", "custom_action_text_hash",
            "context_fingerprint", "validation_payload", "preview_payload",
        )
        # We need to look only at the parseUrl function body.
        fn_start = JS.index("function parseUrl")
        fn_end = JS.index("function pushUrl", fn_start)
        fn_block = JS[fn_start:fn_end]
        for field in forbidden:
            assert f'params.get("{field}")' not in fn_block, \
                f"parseUrl must not read forbidden URL param {field}"

    def test_js_does_not_push_forbidden_url_params(self) -> None:
        # pushUrl must never set custom_action_text, custom_action_text_hash,
        # context_fingerprint, validation payload, or preview payload.
        fn_start = JS.index("function pushUrl")
        fn_end = JS.index("function apiGet", fn_start)
        fn_block = JS[fn_start:fn_end]
        forbidden = (
            "custom_action_text", "custom_action_text_hash",
            "context_fingerprint", "validation_payload", "preview_payload",
        )
        for field in forbidden:
            assert f'next.set("{field}"' not in fn_block
            assert f"next.set('{field}'" not in fn_block

    def test_js_handles_popstate_for_back_forward(self) -> None:
        assert 'addEventListener("popstate"' in JS or "addEventListener('popstate'" in JS

    def test_js_does_not_persist_custom_text_to_local_storage(self) -> None:
        # localStorage.setItem / getItem / removeItem must never be called.
        # (Comments mentioning localStorage as forbidden are OK.)
        assert "localStorage.setItem" not in JS
        assert "localStorage.getItem" not in JS
        assert "localStorage.removeItem" not in JS
        assert "window.localStorage" not in JS

    def test_js_does_not_display_full_fingerprint(self) -> None:
        # shortenFp truncates the fingerprint to 8 chars.
        assert "function shortenFp" in JS
        fn_start = JS.index("function shortenFp")
        fn_end = JS.index("function parseUrl", fn_start)
        fn_block = JS[fn_start:fn_end]
        assert "slice(0, 8)" in fn_block or "slice(0,8)" in fn_block


# ===========================================================================
# Section 9: Responsive + visual contract
# ===========================================================================

class TestResponsiveContract:
    def test_css_has_desktop_breakpoint(self) -> None:
        # Desktop ≥1280 — expressed as max-width: 1279px (mobile-down) or
        # min-width: 1280px (desktop-up). Either form is acceptable.
        assert "min-width: 1280px" in CSS or "min-width:1280px" in CSS or \
               "max-width: 1279px" in CSS or "max-width:1279px" in CSS

    def test_css_has_narrow_desktop_breakpoint(self) -> None:
        # Narrow desktop/tablet ≤900
        assert "max-width: 900px" in CSS or "max-width:900px" in CSS

    def test_css_has_mobile_breakpoint(self) -> None:
        # Mobile ≤760
        assert "max-width: 760px" in CSS or "max-width:760px" in CSS

    def test_css_has_reduced_motion_media_query(self) -> None:
        assert "prefers-reduced-motion" in CSS

    def test_css_no_horizontal_overflow(self) -> None:
        # Workspace + action row must have min-width: 0 to prevent overflow.
        assert "min-width: 0" in CSS or "min-width:0" in CSS

    def test_css_uses_only_nt_alias_tokens(self) -> None:
        # The CSS may only define --nt-* alias tokens.
        assert "--nt-authority-rule" in CSS or "--nt-supplement-inset" in CSS
        # We do not introduce new fonts.
        assert "@font-face" not in CSS

    def test_css_no_neon_or_scifi_palette(self) -> None:
        # We must not introduce neon / sci-fi colors in actual style rules.
        # Comments may reference these terms to forbid them.
        # Strip /* ... */ comments before checking.
        css_no_comments = re.sub(r"/\*.*?\*/", "", CSS, flags=re.DOTALL)
        neon_keywords = ("neon", "cyber", "sci-fi", "scifi")
        for kw in neon_keywords:
            assert kw not in css_no_comments.lower()

    def test_template_links_narrative_turn_css(self) -> None:
        assert "/static/simulator-narrative-turn.css" in TEMPLATE

    def test_template_loads_narrative_turn_js(self) -> None:
        assert "/static/simulator-narrative-turn.js" in TEMPLATE


# ===========================================================================
# Section 10: JS security boundaries
# ===========================================================================

class TestJsSecurityBoundaries:
    def test_js_does_not_use_innerhtml_for_untrusted_content(self) -> None:
        # innerHTML must never be used to insert Wire DTO data.
        # We allow it nowhere in the module (the renderer uses textContent).
        assert "innerHTML" not in JS

    def test_js_does_not_call_python_accessors(self) -> None:
        # The browser must not call or simulate Python accessor methods.
        for accessor in (
            "planning_data_dict", "chapter_plan_dict", "world_data_dict",
            "character_data_dict", "narrative_state_dict",
            "rolling_window_dict", "dependencies_dict",
        ):
            assert accessor not in JS

    def test_js_only_consumes_wire_dtos(self) -> None:
        # The JS must reference the four Wire DTO names.
        for dto in ("contextDto", "planDto", "validationDto", "previewDto"):
            assert dto in JS

    def test_js_sends_confirm_request(self) -> None:
        # 0D4-D must POST to a confirm endpoint.
        assert "/api/narrative-turn/confirm" in JS
        assert "handleConfirmClick" in JS
        assert "generateOperationId" in JS
        assert "operation_id" in JS

    def test_js_uses_only_allowed_endpoints(self) -> None:
        assert "/api/narrative-turn/context" in JS
        assert "/api/narrative-turn/plan" in JS
        assert "/api/narrative-turn/feasibility" in JS
        assert "/api/narrative-turn/preview" in JS

    def test_js_does_not_fake_success(self) -> None:
        # The renderer must not synthesize a fake validation/preview DTO.
        # We verify it does not construct hardcoded "allowed" statuses.
        assert 'status: "allowed"' not in JS
        assert "validationDto = {" not in JS
        assert "previewDto = {" not in JS


# ===========================================================================
# Section 11: Template wires workspace visibility to mode/view
# ===========================================================================

class TestWorkspaceVisibility:
    def test_workspace_hidden_by_default(self) -> None:
        # The workspace must be hidden by default; JS toggles visibility when
        # mode=simulator & view=narrative-turn.
        assert "hidden" in TEMPLATE

    def test_js_toggles_visibility_on_mode_and_view(self) -> None:
        # The JS must check mode === "simulator" and view === "narrative-turn".
        assert '"simulator"' in JS
        assert '"narrative-turn"' in JS


# ===========================================================================
# Section 12: Endpoint method enforcement (no GET for feasibility/preview)
# ===========================================================================

class TestEndpointMethodEnforcementInJs:
    def test_js_uses_get_for_context(self) -> None:
        # apiGet is used for context and plan.
        assert "apiGet" in JS

    def test_js_uses_post_for_feasibility_and_preview(self) -> None:
        # apiPost is used for feasibility and preview.
        assert "apiPost" in JS
        # The custom_action_text is sent in the POST body, never in URL.
        # Find the apiPost call for feasibility and verify custom_action_text
        # is in the body object.
        feas_start = JS.index("/api/narrative-turn/feasibility")
        # Walk forward to find the apiPost call.
        ctx_start = max(0, feas_start - 200)
        ctx_end = min(len(JS), feas_start + 400)
        ctx_block = JS[ctx_start:ctx_end]
        assert "apiPost" in ctx_block
        # custom_action_text is sent as a body field.
        assert "custom_action_text" in JS
