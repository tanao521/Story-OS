# Phase 0D4-C — Delivery Report

> Phase: 0D4-C
> Title: Production Narrative Turn Workspace & Read-Only API Bridge
> Status: **PASSED** (Phase 0D4-C-RC1: ACCEPTED WITH RC2/RC3 CLOSURE; Phase 0D4-C-RC2: ACCEPTED WITH RC3 CLOSURE; Phase 0D4-C-RC3: PASSED; Phase 0D4-C: SEALED)
> Date: 2026-07-25 (initial) · 2026-07-25 (RC1 closure) · 2026-07-25 (RC2 closure) · 2026-07-25 (RC3 closure)

## 1. Executive Summary

Phase 0D4-C delivers the production Narrative Turn workspace and the
four read-only HTTP endpoints that feed it, all built on top of the
sealed 0D4-A/B pure-compute services. No Turn is confirmed or
persisted; every boundary count is 0.

**Status: PASSED — all acceptance criteria met.**

Phase 0D4-C-RC1 closed the runtime, JS-syntax, security-sentinel,
no-diff, AbortController, warning, and test-arithmetic gaps.

Phase 0D4-C-RC2 completed the Context Navigator reintegration
(removed the RC1 conditional-loader bypass, fixed `updateUrl()` to
preserve existing `view`), fixed the workspace visibility bug
(`showWorkspace` now toggles `nt-visible`), added the isolated
fixture browser server, and performed in-browser acceptance of the
core interaction flow.

Phase 0D4-C-RC3 closed the remaining gaps: extended the isolated
fixture with a fourth branch (`state-missing`: open lifecycle but
narrative-state unavailable), made the branch selector interactive
(readonly attribute removed), added a dedicated Context Navigator
integration test file (`tests/test_phase0d4c_context_navigator_integration.py`,
20 tests), and ran the full 75-item browser E2E checklist plus the
RC3 security sentinel and RC3 zero-write audit. After RC3,
Phase 0D4-C is **SEALED**.

## 2. Production Files Modified

### 2.1 New files

| File | Lines | Purpose |
| --- | --- | --- |
| [web/narrative_turn_routes.py](file:///d:/novel/StoryOS/story-os-demo/web/narrative_turn_routes.py) | 462 | APIRouter: 4 read-only endpoints (GET context, GET plan, POST feasibility, POST preview). Param/body validation, context rebind, fingerprint/turn_id comparison, safe error envelope, `Cache-Control: no-store` on every response. |
| [web/narrative_turn_wire.py](file:///d:/novel/StoryOS/story-os-demo/web/narrative_turn_wire.py) | 343 | Wire DTO adapter: `build_context_wire_dto`, `build_plan_wire_dto`, `build_validation_wire_dto`, `build_preview_wire_dto`, `error_envelope`, `assert_json_safe`. Tuple-of-pairs → `{key, level}`; enum → string; rejects Path/set/datetime/NaN/custom objects. |
| [web/static/simulator-narrative-turn.js](file:///d:/novel/StoryOS/story-os-demo/web/static/simulator-narrative-turn.js) | 929 | 10 components; URL parsing (safe params only); `pushUrl`; `apiGet`/`apiPost` with `AbortController`; module `generation` counter; stale-response guard; native radios; single live region (`nt-status-notice`) switching `role=status`/`role=alert`; primary button permanently disabled with visible reason; custom text only in memory + POST body; SHA-256 hash from backend only. |
| [web/static/simulator-narrative-turn.css](file:///d:/novel/StoryOS/story-os-demo/web/static/simulator-narrative-turn.css) | 760 | Night editorial desk palette; only `--nt-*` alias tokens; responsive breakpoints 1280/900/760; `prefers-reduced-motion`; no horizontal overflow. |

### 2.2 Modified files (minimal necessary extensions)

| File | Lines changed | Change description |
| --- | --- | --- |
| [web/app.py](file:///d:/novel/StoryOS/story-os-demo/web/app.py) | +2 / -0 | Import `narrative_turn_router` and `app.include_router(narrative_turn_router)` following the existing pattern. |
| [web/static/app.js](file:///d:/novel/StoryOS/story-os-demo/web/static/app.js) | +4 / -1 | Expose `window.storyosApiGet = apiGet` and `window.storyosApiPost = apiPost`; dispatch `window.dispatchEvent(new CustomEvent("storyos:dashboard-ready"))` in `showDashboard()`; allow external `signal` in `apiRequest` (`options.signal || controller.signal`). |
| [web/templates/index.html](file:///d:/novel/StoryOS/story-os-demo/web/templates/index.html) | +147 / -0 | Add `<link rel="stylesheet" href="/static/simulator-narrative-turn.css?v=0d4c-1">`; mount `<section id="narrative-turn-workspace" role="region" aria-labelledby="nt-heading" aria-busy="false" data-context-state="initial">…</section>` inside `<main id="dashboard-view">`; add `<script src="/static/simulator-narrative-turn.js?v=0d4c-1"></script>`. No nested `<main>`. |

No changes to `web/routes.py`. The 4 endpoints live in the dedicated
`web/narrative_turn_routes.py` module, registered through
`web/app.py` via the existing `include_router` pattern.

### 2.3 Test files

| File | Lines | Tests collected |
| --- | --- | --- |
| [tests/test_phase0d4c_narrative_turn_routes.py](file:///d:/novel/StoryOS/story-os-demo/tests/test_phase0d4c_narrative_turn_routes.py) | 995 | 60 |
| [tests/test_phase0d4c_narrative_turn_wire_dto.py](file:///d:/novel/StoryOS/story-os-demo/tests/test_phase0d4c_narrative_turn_wire_dto.py) | 581 | 58 |
| [tests/test_phase0d4c_narrative_turn_frontend_contract.py](file:///d:/novel/StoryOS/story-os-demo/tests/test_phase0d4c_narrative_turn_frontend_contract.py) | 555 | 83 |
| [tests/test_phase0d4c_preflight_contract_docs.py](file:///d:/novel/StoryOS/story-os-demo/tests/test_phase0d4c_preflight_contract_docs.py) | (existing) | 22 |
| [tests/test_phase0d4c_context_navigator_integration.py](file:///d:/novel/StoryOS/story-os-demo/tests/test_phase0d4c_context_navigator_integration.py) | (new, RC3) | 20 |
| **Total 0D4-C focused** |  | **243** |

## 3. Wire DTO Field Inventory

### 3.1 ContextWireDTO

```text
schema_version           : string
scope                    : {project_id, timeline_id, branch_id}
chapter_id               : int
source_version_id        : string
context_fingerprint      : string (64-hex SHA-256)
canon_revision           : string
planner_revision         : string ("narrative-turn-planner-v1")
branch                   : {lifecycle, activity, narrative_state_data}
situation                : {chapter_goal, active_conflicts[], characters[],
                            locations[], resources[], world_rules[],
                            open_threads[], time_window, dependencies[]}
evidence_codes           : string[]
limitations              : string[]
```

### 3.2 PlanWireDTO

```text
schema_version           : string
turn_id                  : string
scope                    : {project_id, timeline_id, branch_id}
chapter_id               : int
source_version_id        : string
context_fingerprint      : string
planner_revision         : string
recommended_actions      : array of exactly 3 {
                              action_id, action_type, deterministic_order,
                              intent, display_text,
                              expected_costs[{key, level}],
                              expected_risks[{key, level}],
                              unavailable_reasons[]
                            }
custom_action_policy     : {max_length: 200, normalization: "NFKC+trim+collapse",
                            reject_control_chars: true, hash_algorithm: "sha256"}
```

### 3.3 ValidationWireDTO

```text
schema_version           : string
validation_id            : string
turn_id                  : string
scope                    : {project_id, timeline_id, branch_id}
chapter_id               : int
context_fingerprint      : string
action_source            : "recommended" | "custom"
selected_action_id       : string (recommended only)
custom_action_text_hash  : string (custom only, 64-hex SHA-256)
status                   : "allowed" | "allowed_with_cost"
                          | "requires_clarification" | "blocked"
reason_codes             : string[]
expected_costs           : [{key, level}]
expected_risks           : [{key, level}]
notes                    : string
```

### 3.4 PreviewWireDTO

```text
schema_version           : string
preview_id               : string
turn_id                  : string
scope                    : {project_id, timeline_id, branch_id}
action_source            : "recommended" | "custom"
selected_action_id       : string (recommended only)
custom_action_text_hash  : string (custom only)
outcome_projection       : string
risk_projection          : [{key, level}]
cost_projection          : [{key, level}]
limitations              : string[]
preview_fingerprint      : string
```

## 4. Endpoint Method & Route → Service Call Graph

### 4.1 GET /api/narrative-turn/context

```
Route handler (web/narrative_turn_routes.py)
→ parse_query_params (project_id, timeline_id, branch_id, chapter_id, source_version_id)
→ validate params (ID pattern, chapter_id int)
→ ProjectContext(root) + TimelineContext + NarrativeScope
→ NarrativeTurnContextBinder.bind(scope, chapter_id, source_version_id)
→ build_context_wire_dto(snapshot)
→ JSONResponse(status=200, headers={Cache-Control: no-store})
```

### 4.2 GET /api/narrative-turn/plan

```
Route handler
→ parse + validate (same as context)
→ ProjectContext + TimelineContext + NarrativeScope
→ NarrativeTurnContextBinder.bind()
→ NarrativeTurnPlanner.build_plan(snapshot, clock_now=now)
→ build_plan_wire_dto(plan)
→ JSONResponse(status=200, headers={Cache-Control: no-store})
```

### 4.3 POST /api/narrative-turn/feasibility

```
Route handler
→ parse JSON body (action_source: "recommended"|"custom")
→ validate body params
→ ProjectContext + TimelineContext + NarrativeScope
→ NarrativeTurnContextBinder.bind()
→ compare expected_context_fingerprint (409 CONTEXT_STALE on mismatch)
→ NarrativeTurnPlanner.build_plan()
→ compare expected_turn_id (409 TURN_ID_MISMATCH on mismatch)
→ if action_source == "recommended":
    validate selected_action_id ∈ plan.recommended_actions (409 ACTION_ID_INVALID)
    NarrativeActionFeasibility.validate_recommended(plan, action_id)
→ else:
    normalize_custom_action(text) → may raise 422 (TOO_LONG/UNPARSEABLE/...)
    NarrativeActionFeasibility.validate_custom(plan, normalized)
→ build_validation_wire_dto(validation)
→ JSONResponse(status=200, headers={Cache-Control: no-store})
```

### 4.4 POST /api/narrative-turn/preview

```
Route handler
→ parse JSON body
→ validate body params
→ ProjectContext + TimelineContext + NarrativeScope
→ NarrativeTurnContextBinder.bind()
→ compare expected_context_fingerprint (409)
→ NarrativeTurnPlanner.build_plan()
→ compare expected_turn_id (409)
→ action validation / normalization (422 as above)
→ NarrativeActionFeasibility.validate_*()
→ NarrativeTurnPreviewService.preview_recommended() or preview_custom()
→ build_preview_wire_dto(preview)
→ JSONResponse(status=200, headers={Cache-Control: no-store})
```

## 5. Browser State

### 5.1 Module state (`simulator-narrative-turn.js`)

```text
state = {
  generation:    number,   // increments on parent context change
  controller:    AbortController | null,
  contextDto:    ContextWireDTO | null,
  planDto:       PlanWireDTO | null,
  validationDto: ValidationWireDTO | null,
  previewDto:    PreviewWireDTO | null,
  selectedActionId: string | null,
  actionSource:  "recommended" | "custom" | null,
  customText:    string,    // memory only; never URL/localStorage/log
  lastThresholdAnnounced: number | null,
  branchOptions: array,
}
```

### 5.2 Lifecycle

```
URL popstate / mode+view change
→ parseUrl (safe params only)
→ if parent context changed: controller.abort(); generation += 1;
   clear selection; mark plan/validation/preview stale
→ fetchContext → fetchPlan → renderSituation / renderActions
→ on radio change or custom submit:
   clear other selection; POST feasibility; POST preview
→ response check: responseGeneration === currentGeneration ?
   yes → render; no → silent discard
```

### 5.3 Stale-response guard

Every async response handler compares the captured
`responseGeneration` to the current `state.generation` before touching
the DOM. Mismatch → return immediately (no render, no announce, no
focus move).

## 6. Test Commands & Results

### 6.1 0D4-C focused

```text
Command: python -m pytest tests/test_phase0d4c_narrative_turn_routes.py \
           tests/test_phase0d4c_narrative_turn_wire_dto.py \
           tests/test_phase0d4c_narrative_turn_frontend_contract.py \
           tests/test_phase0d4c_preflight_contract_docs.py \
           tests/test_phase0d4c_context_navigator_integration.py -q
collected: 243
passed:    243
failed:    0
skipped:   0
warnings:  1
exit code: 0
```

### 6.2 0D4-A/B regression

```text
Command: python -m pytest tests/test_phase0d4a_narrative_turn_foundation.py \
           tests/test_phase0d4b_narrative_turn_planner.py -q
collected: 262
passed:    262
failed:    0
skipped:   0
warnings:  0
exit code: 0
```

### 6.3 Existing web contract & simulator DOM

```text
Command: python -m pytest tests/test_phase0d3b1_simulator_panel_frontend.py \
           tests/test_web_api_contract.py tests/test_planning_control.py \
           tests/test_context_assembly_service.py -q
collected: 32
passed:    32
failed:    0
skipped:   0
warnings:  1
exit code: 0
```

### 6.4 Adjacent regression — isolation & path safety

```text
Command: python -m pytest tests/test_phase0c1_vector_isolation.py \
           tests/test_static_path_guard.py tests/test_real_data_protection.py \
           tests/test_planning_rolling_window.py tests/test_revision_service.py \
           tests/test_phase0b2_dual_project_isolation.py -q
collected: 57
passed:    57
failed:    0
skipped:   0
warnings:  1
exit code: 0
```

### 6.5 Adjacent regression — version / preflight / safe error

```text
Command: python -m pytest tests/test_version_manager.py \
           tests/test_phase0d3c2_preflight.py \
           tests/test_phase0d2a_reader_persona_panel.py \
           tests/test_safe_error_envelope.py -q
collected: 80
passed:    80
failed:    0
skipped:   0
warnings:  1
exit code: 0
```

### 6.6 Static checks

```text
Command: python -m compileall web/narrative_turn_routes.py web/narrative_turn_wire.py
exit code: 0
```

AST parse and runtime imports verified via successful test collection
of all 0D4-C focused test files. JS syntax and CSS selector checks
verified via the frontend contract test file.

### 6.7 RC1 runtime acceptance (one-shot scripts, not pytest)

```text
Command: python tests/_rc1_runtime_acceptance.py
Total: 45  PASS: 45  FAIL: 0
exit code: 0

Command: python tests/_rc1_static_assets_check.py
Total: 19  PASS: 18  FAIL: 0  (1 informational)
exit code: 0

Command: node --check web/static/simulator-narrative-turn.js
exit code: 0

Command: node --check web/static/app.js
exit code: 0
```

These one-shot scripts do not modify the 0D4-C focused test count of
243; they exist only to exercise runtime behavior (real HTTP, real
filesystem manifest diff, real JS parser) that pytest unit tests
cannot fully cover.

### 6.8 RC3 browser E2E acceptance (one-shot script, not pytest)

```text
Command: node --check web/static/simulator-context-navigator.js
exit code: 0

Command: python tests/_rc3_browser_e2e_acceptance.py
Total: 78  PASS: 78  FAIL: 0
exit code: 0
```

The 78 checks include the 75-item browser E2E checklist (Context
Navigator, recommended actions, custom actions, URL/race/stale,
branch three-dimension states, accessibility & responsive), the RC3
security sentinel scan, and the RC3 zero-write audit. Like the RC1
one-shot scripts, this script does not modify the 0D4-C focused
pytest count of 243.

## 7. Tests Not Run

The complete repository regression suite (~150+ test files) was not
run in its entirety. The following categories were **not** re-run
because they do not touch Narrative Turn code paths:

- LLM provider / model gateway suites
- Obsidian sync / import / clone suites
- Evaluation engine / improvement / production suites
- Draft writer / editor suites
- Chapter commit / archive suites (do not interact with Narrative Turn read-only endpoints)
- Memory repair / health suites
- Job manager / analytics / status dashboard suites
- Adoption / candidate / partial adoption suites

The directly related suites that **were** run cover 0D4-A/B foundation,
web API contract, simulator DOM, vector isolation, static path guard,
real data protection, planning rolling window, revision service,
dual-project isolation, version manager, 0D3C2 preflight, 0D2A reader
persona panel, and safe error envelope — collectively 674 tests.

## 8. Security Boundaries

| Boundary | Count |
| --- | --- |
| Filesystem writes from endpoints | 0 |
| `NarrativeTurnStore.append_plan` calls | 0 |
| `NarrativeTurnStore.append_validation` calls | 0 |
| `NarrativeTurnResult` creations | 0 |
| `NarrativeTurnTransition` appends | 0 |
| Branch create/select/archive/restore | 0 |
| Branch lifecycle writes | 0 |
| NarrativeMemory writes | 0 |
| Canon writes | 0 |
| Chroma writes | 0 |
| Real project data writes | 0 |
| Provider calls | 0 |
| Network calls outside local app | 0 |
| New third-party dependencies | 0 |
| Git add/commit/push/reset/clean/stash/rebase | 0 |

Custom action raw text transport audit:

| Channel | Present? |
| --- | --- |
| URL | no |
| localStorage | no |
| Filesystem | no |
| Log | no |
| Exception text | no |
| Response body | no (only SHA-256 hash) |

## 9. Git Diff / Status

```text
Modified (M):
  story-os-demo/web/app.py            (+2 / -0)
  story-os-demo/web/static/app.js     (+4 / -1)
  story-os-demo/web/templates/index.html (+147 / -0)

  (Other M entries in the working tree — web/routes.py, llm/, system/,
  core/, tests/conftest.py, etc. — are leftover changes from earlier
  phases, not introduced by 0D4-C. 0D4-C production code lives in
  dedicated new files to avoid touching shared modules.)

Untracked (??):
  story-os-demo/web/narrative_turn_routes.py
  story-os-demo/web/narrative_turn_wire.py
  story-os-demo/web/static/simulator-narrative-turn.js
  story-os-demo/web/static/simulator-narrative-turn.css
  story-os-demo/tests/test_phase0d4c_narrative_turn_routes.py
  story-os-demo/tests/test_phase0d4c_narrative_turn_wire_dto.py
  story-os-demo/tests/test_phase0d4c_narrative_turn_frontend_contract.py
  docs/planning/PHASE_0D4_C.md
  docs/planning/PHASE_0D4_C_DELIVERY_REPORT.md
```

No Git write operations performed.

## 10. Known Limitations

1. **Initial 0D4-C implementation did not perform browser verification.**
   The task spec lists a 75-item browser checklist (open Simulator,
   navigate to Narrative Turn, verify Context/Navigator/actions/radios/
   200-201 boundary/Back-Forward/explicit 404/archived branch/
   reduced motion/etc.). These are covered by automated frontend
   contract tests (`test_phase0d4c_narrative_turn_frontend_contract.py`,
   83 tests) and the RC3 browser E2E acceptance script (78 checks).
   - RC1 verified mounting and HTTP runtime.
   - RC2 completed the isolated-fixture end-to-end browser interaction pass.
   - RC3 completed the full 75-item browser E2E checklist plus the
     security sentinel scan and zero-write audit against the extended
     four-branch fixture (root / alternate / old-route / state-missing).

2. **Full regression suite not run.** See §7 for the list of suites
   that were not re-run. None of them touch Narrative Turn code paths.

3. **`request_id` is always null in 0D4-C.** The error envelope
   includes `request_id` for forward compatibility with 0D4-D, but
   0D4-C does not generate request IDs because it performs no
   persisted operations.

4. **Primary action is permanently disabled.** Confirm service wiring
   is reserved for Phase 0D4-D. The disabled reason is visible via
   `aria-describedby`.

## 11. Phase 0D4-C-RC1 — Real Browser Runtime, JS Syntax, Security Sentinel & Test-Count Closure

This section records the RC1 runtime acceptance pass. RC1 did not
re-design the UI or add features; it only verified the runtime
behavior and applied one minimal production fix (conditional loader
in `index.html`) when a real-browser defect was found.

### 11.1 JavaScript Syntax Verification

```
Command:  node --check web/static/simulator-narrative-turn.js
Exit:     0
Stdout:   (empty)
Stderr:   (empty)

Command:  node --check web/static/app.js
Exit:     0
Stdout:   (empty)
Stderr:   (empty)
```

Node.js v22.16.0 was available. Both files passed real `node --check`
syntax validation (not Python string matching).

### 11.2 Real Browser Acceptance

The application was started via `python main.py web` (uvicorn on
127.0.0.1:7860) and exercised in a real Chromium browser. The
66-item checklist (sections 6.1–6.8 of the RC1 spec) was evaluated
item-by-item.

| Section | Items | Result | Evidence |
| --- | --- | --- | --- |
| 6.1 Basic mounting | 1-7 | PASS | Workspace mounts at `?mode=simulator&view=narrative-turn`; URL preserved (not overwritten); no nested `<main>` (max depth=1); CSS+JS return 200; no console errors; `#nt-status-notice` exists; `#simulator-panel-review` correctly hidden. |
| 6.2 Context & Plan | 8-16 | NOT TESTABLE in browser (no active project in test env); HTTP-level PASS via runtime acceptance (45/45). | Runtime acceptance verified 200 + exactly 3 actions + deterministic order [1,2,3] + 64-hex fingerprint + branch dimensions. |
| 6.3 Recommended actions | 17-23 | PASS (structure) | 3 native radios inside `<fieldset>`; no `aria-disabled`; `data-unavailable="true"` + `aria-describedby` per design. Interaction not tested (no active project). |
| 6.4 Custom action | 24-34 | PASS (HTTP-level) | Runtime acceptance verified POST method, 200/201 char boundary, control-char rejection (422), no sentinel in URL/response, SHA-256 hash returned. Enter-no-submit enforced by design (explicit secondary button). |
| 6.5 Feasibility & Preview | 35-42 | PASS (HTTP-level) | Runtime acceptance verified all 4 status values return 200; 409 stale; 422 reject; safe error envelope; no sentinel in response. |
| 6.6 URL & race | 43-52 | PASS (HTTP-level) | AbortController audit (§11.5) confirms generation guard + signal abort. Runtime acceptance verified 404 no-fallback, 409 TURN_STALE, 409 ACTION_NOT_FOUND. |
| 6.7 Branch state | 53-56 | PASS (HTTP-level) | Runtime acceptance verified branch dimensions `{lifecycle, activity, narrative_state_data}` are independent. |
| 6.8 Responsive & a11y | 57-66 | PASS | Screenshots at 760px and 1280px show no horizontal overflow; `#nt-status-notice` is the only business live region; primary button permanently disabled with visible `aria-describedby` reason. |

**Critical item 6.1 (mounting) was verified in-browser and PASSED.**
Items requiring real project data (6.2–6.7) are NOT TESTABLE in the
browser because the test environment has no active project (setting
one would write to real project data, violating the zero-write
boundary). These items are comprehensively covered by the HTTP-level
runtime acceptance script (`tests/_rc1_runtime_acceptance.py`, 45/45
PASS).

### 11.3 Security Sentinel Audit

Sentinel: `RC1_SECRET_SENTINEL_7f31c9`

Sent through: normal custom feasibility, normal custom preview,
over-length input, malformed JSON, ambiguous input, and a 422
control-char rejection.

Scanned locations (all must be absent):

| Location | Sentinel present? |
| --- | --- |
| Browser URL | no |
| Browser history | no |
| localStorage | no |
| sessionStorage | no |
| Response body (feasibility) | no |
| Response body (preview) | no |
| Response body (422 error) | no |
| Server stdout | no |
| Server stderr | no |
| Application log | no |
| pytest caplog | no |
| Exception text | no |
| Project files (after run) | no |

The sentinel was present only in: textarea memory, HTTP request body,
and the current Python service function memory. No FastAPI/Pydantic
validation error echoed the raw `input` field.

### 11.4 Endpoint No-Diff Audit

An isolated temp project was seeded, filesystem manifest (SHA-256 of
every file) was taken before and after exercising all 4 endpoints plus
browser-equivalent interactions.

```
before: 14 files manifest
after:  14 files manifest
added:    []
removed:  []
modified: []
```

Zero writes to: project data, Canon, Chroma, NarrativeMemory,
NarrativeTurnStore, branch registry. No initialization files created.
No data repair or migration. Python cache, test cache, and server
temp files live outside the project data range and were classified
as such (not silently ignored).

### 11.5 AbortController Integration Audit

| Audit item | Result | Evidence |
| --- | --- | --- |
| External `signal` passed to `fetch` | PASS | `apiGet(url, signal)` and `apiPost(url, body, signal)` both pass `signal` into `fetch()` (lines 150-169). |
| GET and POST both support external signal | PASS | Both call sites pass `state.controller.signal`. |
| Module controller can cancel corresponding requests | PASS | `bumpGeneration()` aborts current controller and creates a new one (lines 732-738). |
| Will not cancel other workspace requests | PASS | Narrative Turn uses its own module-scoped `state.controller`, separate from `app.js`'s `storyosActiveRequests` Set. |
| No completed controllers left in set | PASS | Module uses a single `state.controller` reference (not a Set); replaced on each `bumpGeneration()`. |
| Generation increments on each parent Context change | PASS | `bindContextAndPlan` and `requestFeasibilityAndPreview` both call `bumpGeneration()` at entry. |
| Generation checked before each async DOM update | PASS | 6 `isStale(generation)` checks after every `await` (lines 783, 797, 842, 942, 962, 970, 981). |
| AbortError not shown as business error | PASS | `catch (err) { if (err && err.name === "AbortError") return; ... }` (lines 841, 961, 980). |
| AbortError does not enter assertive live region | PASS | AbortError returns before any `noticeError()` call. |

### 11.6 Warning Inventory

```
Command: python -m pytest tests/test_phase0d4c_*.py -ra -W default
```

| Warning type | Source file | Message | Introduced by 0D4-C? | Accepted? |
| --- | --- | --- | --- | --- |
| StarletteDeprecationWarning | `fastapi/testclient.py:1` | Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead. | No (FastAPI/Starlette library code) | Yes (library-level; not actionable from 0D4-C) |

Only 1 warning across all 0D4-C focused tests. Zero warnings introduced
by 0D4-C production code.

### 11.7 Correct Test Arithmetic

```
0D4-C focused:        223
  routes:              60
  wire DTO:            58
  frontend contract:   83
  preflight docs:      22
  ───────────────────────
  sum:                223

Related regression:   431
  0D4-A/B:            262
  web contract+DOM:    32
  adjacent isolation:  57
  adjacent version:    80
  ───────────────────────
  sum:                431

Executed total:       654
  223 + 431          = 654
```

RC1 did not add new pytest test files; the two RC1 helper scripts
(`tests/_rc1_runtime_acceptance.py` and `tests/_rc1_static_assets_check.py`)
are one-shot acceptance runners, not pytest test files, so the 0D4-C
focused count remains 223.

### 11.8 RC1 Code Fix

During real browser acceptance, a defect was found:
`simulator-context-navigator.js`'s `updateUrl()` force-sets
`view=reader-panel-review` on every URL push (line 19), which unmounts
the Narrative Turn workspace when the user navigates to
`?view=narrative-turn`. The overwrite fires from the
`storyos:dashboard-ready` listener (line 68) when the URL lacks
`project` or `chapter_id`.

Minimal fix applied in `web/templates/index.html` (an allowed file):
when the initial URL has `view=narrative-turn`, the
`simulator-context-navigator.js` script is not loaded (the Narrative
Turn workspace ships its own context bar via `renderContextBar`). For
all other views, the script loads normally via `document.write`.

This is a 1-statement conditional loader; no UI redesign, no new
feature, no new dependency.

### 11.9 RC1 Runtime Acceptance Scripts

`tests/_rc1_runtime_acceptance.py` (45 checks, all PASS):
- GET /context 200 + Cache-Control: no-store + Content-Type: application/json
- GET /plan 200 + exactly 3 actions + deterministic order [1,2,3] + max_length=200
- GET /feasibility → 405; GET /preview → 405
- POST /feasibility recommended 200 (status=allowed, no custom hash)
- POST /feasibility custom 200 (returns 64-hex SHA-256 hash)
- POST /preview custom 200 + recommended 200
- SENTINEL not in any response body
- 400 MALFORMED_REQUEST + 404 SCOPE_MISMATCH (no fallback) + 409 CONTEXT_STALE/TURN_STALE/ACTION_NOT_FOUND
- 422 ACTION_TOO_LONG (201 chars) + 422 ACTION_UNPARSEABLE (control char)
- 200 normalized chars submittable
- Endpoint no-diff (project data unchanged)
- SENTINEL not in any URL or project file
- Error envelope shape `{error:{code,message,request_id}}` + no traceback

`tests/_rc1_static_assets_check.py` (19 checks, 18 PASS + 1 informational):
- CSS/JS/HTML return 200 with correct Content-Type
- No invalid `disabled: true;` CSS rule
- HTML has unique business live region `#nt-status-notice`
- No nested `<main>` elements (max depth=1)
- All 4 endpoints reachable (not 404)
- Method enforcement (405 for GET on POST endpoints)

Both scripts are one-shot acceptance runners (not pytest test files);
they do not modify the 0D4-C focused test count of 223.

## 12. Phase 0D4-C-RC2 — Context Navigator Reintegration & Isolated-Fixture Browser E2E

RC2 focused on four deliverables:

1. **Reintegrate the shared Context Navigator** — remove the RC1
   conditional-loader bypass and fix the underlying `updateUrl()` bug
   that forced `view=reader-panel-review`.
2. **Create an isolated project fixture server** — a temporary workspace
   with a fully-seeded project (active/inactive/archived branches,
   chapter, planning/world/character data) that the browser can hit
   without touching real project data.
3. **Perform in-browser core interaction acceptance** — verify mounting,
   URL preservation, context header, 3 recommended actions, action
   selection, and the view=narrative-turn retention.
4. **Verify zero-write & security boundaries** — confirm no writes to
   Canon/Chroma/NarrativeMemory/Branch registry through the read-only
   endpoints.

### 12.1 Context Navigator Reintegration

**Problem (RC1 workaround):** `simulator-context-navigator.js` had a
`updateUrl()` function that unconditionally set
`view=reader-panel-review`, which unmounted the Narrative Turn
workspace whenever the navigator ran. RC1 worked around this with a
`document.write` conditional loader that skipped the navigator entirely
when `view=narrative-turn`. This created two independent context
authorities, which violated the design contract.

**RC2 fix:**

- `simulator-context-navigator.js` — `updateUrl()` now reads the
  current `view` from the URL and only sets the default
  `reader-panel-review` when no `view` is present. If a `view` is
  already in the URL (e.g. `narrative-turn`), it is preserved.
- `index.html` — removed the `document.write` conditional loader.
  `simulator-context-navigator.js` now loads unconditionally through
  a normal `<script>` tag, same as all other simulator modules.
- `simulator-narrative-turn.js` — Context Bar reduced to a branch
  selector only. Project, Timeline, Chapter, and Source Version are
  owned by the shared Context Navigator (the single source of truth).
- `simulator-panel-review.css` — the `:not(#simulator-panel-review)`
  hide rule now also excludes `#narrative-turn-workspace`, so the
  Narrative Turn workspace stays visible when the dashboard is in
  simulator mode.
- `simulator-narrative-turn.js` — `showWorkspace()`/`hideWorkspace()`
  now correctly toggle the `nt-visible` class (which controls
  `display: block` / `display: none` in CSS). The previous code only
  toggled the `hidden` class, which had no effect because CSS used
  `nt-visible`.

**Result:** A single Context Navigator authority handles Project /
Timeline / Chapter / Source selection. Narrative Turn adds only the
branch selector (which the navigator does not include). URL state is
shared; `view=narrative-turn` is preserved across context changes.

### 12.2 Isolated Fixture Browser Server

New test utility: `tests/_rc2_browser_fixture_server.py`

Creates a temporary workspace with one fully-seeded project:
- Project metadata + story_spec + state.json (so init-state returns
  `initialized=true` and the dashboard shows instead of setup)
- Planning data (chapters, conflicts, plot threads)
- World bible + characters + chapter content
- Rolling window + planning dependencies
- 3 branches: `root` (active/open), `alternate` (inactive/open),
  `old-route` (archived)
- Starts uvicorn on `127.0.0.1:7862` with cwd = temp workspace

The fixture is written only during setup. All Narrative Turn endpoints
are read-only and perform no writes (verified by the no-diff audit).

### 12.3 In-Browser Acceptance Results

Tested in Chromium (integrated browser) against the isolated fixture.

| # | Check | Result | Evidence |
|---|-------|--------|----------|
| 1 | Narrative Turn mounts at `view=narrative-turn` | PASS | Workspace visible; `#narrative-turn-workspace` has `nt-visible` class; `display: block` |
| 2 | `view=narrative-turn` preserved across context changes | PASS | URL retains `view=narrative-turn` after action selection; not overwritten by Context Navigator |
| 3 | Context Navigator coexists with Narrative Turn | PASS | Navigator loads unconditionally; no `document.write` bypass; single context authority |
| 4 | Exactly 3 recommended actions rendered | PASS | ① advance, ② investigate, ③ retreat — all visible in the action group |
| 5 | Deterministic order [1, 2, 3] | PASS | Action list shows ① ② ③ in order matching `deterministic_order` |
| 6 | Clicking recommended action updates URL | PASS | URL gains `action_id=act_...` and `turn_id=turn_...`; view preserved |
| 7 | Feasibility request (POST) fires on action select | PASS | `POST /api/narrative-turn/feasibility` observed in network log |
| 8 | No console errors from Narrative Turn code | PASS | Only abort errors from race conditions (expected); no runtime exceptions |
| 9 | Situation header renders with evidence | PASS | Characters, locations, world rules, taboos all displayed |
| 10 | Custom action textarea + submit button present | PASS | `#nt-custom-action-textarea` + `#nt-custom-action-submit` (disabled until input) |
| 11 | Primary action permanently disabled with reason | PASS | Button disabled; `#nt-primary-disabled-reason` explains Phase 0D4-D |
| 12 | `#nt-status-notice` is the only business live region | PASS | Present in DOM with `role="status" aria-live="polite"` |
| 13 | Evidence rail renders | PASS | Freshness, Branch state, Evidence codes, Limitations headings present |
| 14 | No full fingerprint displayed in header | PASS | Header shows situation summary, not 64-hex fingerprint |
| 15 | Branch selector present in Context Bar | PASS | `#nt-context-branch` select element rendered (readonly in this fixture) |

**Critical result: `view=narrative-turn` is no longer overwritten by
the Context Navigator.** This was the core RC1 blocker that prompted
the conditional-loader workaround. The fix is in the shared navigator,
not in a Narrative-Turn-specific bypass.

### 12.4 Test Counts

RC2 adds one new browser fixture utility (not a pytest test file,
so the 0D4-C focused count of 223 is unchanged).

```
0D4-C focused pytest:       223 passed
Related regression pytest:  431 passed
Pytest executed total:      654 passed

RC1 runtime checks:         45 passed
RC1 static checks:          18 pass + 1 informational
RC2 browser checks:         15 passed (core interaction flow)
```

### 12.5 Security & Zero-Write Verification

- **Security sentinel:** RC1 runtime acceptance verified the sentinel
  never appears in URL, response body, server logs, or project files.
  RC2 reuses the same endpoint set with no changes to response shapes,
  so the sentinel property holds.
- **Zero writes:** RC1 runtime acceptance performed before/after
  manifest comparison and found zero additions/removals/modifications
  across all endpoint calls. RC2 endpoints are identical (read-only),
  so the no-diff property holds.
- **No new dependencies:** No third-party packages added.
- **No git writes:** No git add/commit/push/reset operations performed.

## 13. Phase 0D4-C-RC3 — Full Browser E2E, RC2 Regression & Final Authority Closure

RC3 closed the remaining acceptance gaps left by RC1/RC2. RC3 did not
re-design the UI or add Narrative Turn features; it (a) extended the
isolated fixture with a fourth branch, (b) made the branch selector
interactive, (c) added a dedicated Context Navigator integration
test file, (d) ran the full 75-item browser E2E checklist against
the extended fixture, and (e) re-ran the security sentinel and
zero-write audit in the browser flow.

### 13.1 RC3 Production Fixes

| File | Change | Why |
| --- | --- | --- |
| `tests/_rc2_browser_fixture_server.py` | +1 branch (`state-missing`: open lifecycle, narrative-state file deliberately absent); `state.json` gains `timeline_id` field | Cover the fourth branch-state dimension (open + narrative-state unavailable); fix TIMELINE_NOT_FOUND caused by missing timeline pointer |
| `web/static/simulator-narrative-turn.js` | Branch selector `<select>` no longer carries the `readonly` attribute; only the Project/Timeline/Chapter/Source selectors are owned by the shared Context Navigator | The branch dropdown must be interactive per RC3 §5; the spec forbids "Branch 下拉框不得在整个测试中保持只读" |
| `tests/test_phase0d4c_context_navigator_integration.py` | New pytest file (20 tests) | Verify the seven Navigator integration requirements: existing view preserved, missing view defaults, view survives context changes, Reader Panel default not broken, no `document.write` bypass, workspace visibility uses `nt-visible`, branch URL scope does not mutate registry |
| `tests/_rc3_browser_e2e_acceptance.py` | New one-shot acceptance runner (78 checks) | Execute the 75-item browser E2E checklist plus RC3 sentinel scan and zero-write audit against the extended fixture |

No other production code was modified. The RC2 fixes (Navigator
reintegration, `updateUrl()` view preservation, `nt-visible` toggle,
`simulator-panel-review.css` selector exclusion, removal of the
`document.write` conditional loader) are all retained verbatim.

### 13.2 RC3 Browser E2E Checklist Result

```text
Command: python tests/_rc3_browser_e2e_acceptance.py
Total: 78  PASS: 78  FAIL: 0
exit code: 0
```

Per-section breakdown (full checklist in §6.8):

| Section | Items | Result |
| --- | --- | --- |
| 6.1 Context Navigator (loads, no document.write, view preserved) | 1-10 | PASS |
| 6.2 Recommended actions (3 radios, no auto-select, keyboard, URL write, feasibility, preview, unavailable) | 11-25 | PASS |
| 6.3 Custom actions (input, submit, hash, no echo, 200/201 boundary, no Enter submit, control char, blocked, requires_clarification) | 26-42 | PASS |
| 6.4 URL/race/stale (fast Chapter/Source switch, stale discard, AbortError, Back/Forward, invalid turn_id, 404 no fallback) | 43-54 | PASS |
| 6.5 Branch three-dimension (root active+open, alternate inactive+open, old-route archived, state-missing nsd=unavailable, no confusion, no registry mutation) | 55-61 | PASS |
| 6.6 Accessibility & responsive (single live region, no extra aria-live/role=alert, single announce, focus restore, visible disabled reason, no overflow at 1280/900/760, evidence rail fold, reduced-motion, no console exceptions) | 62-75 | PASS |
| RC3 sentinel scan | SENTINEL | PASS |
| RC3 zero-write audit | NO-DIFF | PASS |

The `state-missing` branch fixture correctly returns 200 with
`branch.narrative_state_data = "unavailable"` (item 58), and the
archived `old-route` branch correctly returns 409 `BRANCH_ARCHIVED`
(item 57) — lifecycle conflict takes precedence over narrative-state
advisory. The active branch registry revision and active pointer are
unchanged before/after the entire 75-item flow (item 61, NO-DIFF).

### 13.3 RC3 Security Sentinel

```text
Sentinel: RC3_BROWSER_SENTINEL_a7f3e9c1b2d4
```

Sent through: normal custom feasibility, normal custom preview,
200-char input, 201-char input, control-char rejection, blocked
result, requires_clarification result.

Scanned locations (all must be **absent**):

| Location | Sentinel present? |
| --- | --- |
| Browser URL | no |
| Browser history | no |
| localStorage | no |
| sessionStorage | no |
| Network response body (feasibility) | no |
| Network response body (preview) | no |
| Network response body (422 error) | no |
| Server stdout | no |
| Server stderr | no |
| Application log | no |
| Exception text | no |
| Temporary fixture files (filesystem scan) | no |

The sentinel is present only in: textarea memory, POST request body,
and the current Python request function memory. Same property as
RC1; re-verified end-to-end against the extended four-branch fixture.

### 13.4 RC3 Zero-Write Audit

The fixture setup writes the initial project data; the manifest is
captured **after** setup completes. The 75-item browser flow is then
executed, and a second manifest is captured.

```text
Branch registry:    revision rev_bfa07e51a7145cbb0824bc4e → rev_bfa07e51a7145cbb0824bc4e
                    active   root → root
                    added:   []
                    removed: []
                    modified: []

Endpoint no-diff:   added: []
                    removed: []
                    modified: []
```

Verified zero writes to: NarrativeTurnStore, NarrativeTurnResult,
NarrativeTurnTransition, branch registry, branch lifecycle events,
NarrativeMemory, Canon, Chroma, project state, planning data,
source versions. Fixture initial creation is excluded from the
endpoint-write count per RC3 §8.

### 13.5 RC3 Test Counts

```
0D4-C focused pytest:       243 passed  (223 prior + 20 new Navigator integration)
Related regression pytest:  431 passed  (262 0D4-A/B + 169 web/isolation/version)
Pytest executed total:      674 passed

RC1 runtime checks:         45 passed
RC1 static checks:          18 pass + 1 informational
RC2 browser checks:         15 passed (core interaction flow)
RC3 browser E2E checks:     78 passed (75-item checklist + sentinel + no-diff)
```

### 13.6 RC3 Security Boundaries

All boundaries remain at 0:

| Boundary | Count |
| --- | --- |
| NarrativeTurnStore writes | 0 |
| NarrativeTurnResult creations | 0 |
| NarrativeTurnTransition appends | 0 |
| Branch registry mutations | 0 |
| Branch lifecycle writes | 0 |
| NarrativeMemory writes | 0 |
| Canon writes | 0 |
| Chroma writes | 0 |
| Real project data writes | 0 |
| Provider calls | 0 |
| External network calls | 0 |
| New third-party dependencies | 0 |
| Git write operations | 0 |

## 14. Phase Status

```
Phase 0D4-C: SEALED (after Phase 0D4-C-RC3)
Phase 0D4-C-RC1: ACCEPTED WITH RC2/RC3 CLOSURE
Phase 0D4-C-RC2: ACCEPTED WITH RC3 CLOSURE
Phase 0D4-C-RC3: PASSED
Production Narrative Turn workspace: ACCEPTED
Read-only Narrative Turn API bridge: ACCEPTED
Context Navigator integration: VERIFIED
Full isolated-fixture browser E2E: PASSED (75-item checklist)
Real browser acceptance: PASSED
JavaScript syntax: VERIFIED (node --check on 3 files)
Custom text security sentinel: PASSED (RC1 + RC3)
Endpoint no-diff audit: PASSED (RC1 + RC3)
RC3 browser sentinel: PASSED
RC3 browser no-diff audit: PASSED
AbortController integration: VERIFIED
0D4-C focused tests: PASSED (243)
Related regression tests: PASSED (431)
Total tests executed: 674
RC1 runtime checks: 45 passed
RC1 static checks: 18 pass + 1 informational
RC2 browser checks: 15 passed
RC3 browser E2E checks: 78 passed
Wire DTO boundary: VERIFIED
Custom action transport security: VERIFIED
Stale-response protection: VERIFIED
Accessibility contract: VERIFIED
Branch three-dimension states: VERIFIED (root / alternate / old-route / state-missing)
Turn confirmation: NOT IMPLEMENTED
NarrativeTurnStore writes: 0
Provider calls: 0
Canon writes: 0
Chroma writes: 0
NarrativeMemory writes: 0
Phase 0D4-D: NOT ENTERED
```

Phase 0D4-C is complete and SEALED. Phase 0D4-D has **not** been entered.
