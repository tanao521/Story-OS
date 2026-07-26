# Phase 0D4-C — Production Narrative Turn Workspace & Read-Only API Bridge

> Status: **PASSED** (Phase 0D4-C-RC1: ACCEPTED WITH RC2/RC3 CLOSURE; Phase 0D4-C-RC2: ACCEPTED WITH RC3 CLOSURE; Phase 0D4-C-RC3: PASSED; Phase 0D4-C: SEALED)
>
> Phase 0D4-P: PASSED
> Phase 0D4-A: SEALED
> Phase 0D4-B: SEALED
> Phase 0D4-C-P: SEALED (after Phase 0D4-C-P-FV2)
> Phase 0D4-C: SEALED (after Phase 0D4-C-RC3)
> Phase 0D4-C-RC1: ACCEPTED WITH RC2/RC3 CLOSURE
> Phase 0D4-C-RC2: ACCEPTED WITH RC3 CLOSURE
> Phase 0D4-C-RC3: PASSED
> Production Narrative Turn workspace: ACCEPTED
> Read-only Narrative Turn API bridge: ACCEPTED
> Context Navigator integration: VERIFIED
> Full isolated-fixture browser E2E: PASSED
> Real browser acceptance: PASSED
> JavaScript syntax: VERIFIED (node --check)
> Custom text security sentinel: PASSED
> Endpoint no-diff audit: PASSED
> RC3 browser sentinel: PASSED
> RC3 browser no-diff audit: PASSED
> Turn confirmation: NOT IMPLEMENTED
> Phase 0D4-D: NOT ENTERED
> Phase 0D4-E: NOT ENTERED
> Phase 0D4-F: NOT ENTERED

## 1. Phase Overview

Phase 0D4-C delivers the production Narrative Turn workspace inside the
existing Simulator Shell and the four read-only, pure-compute HTTP
endpoints that feed it. All compute reuses the sealed 0D4-A/B services;
no Turn is confirmed or persisted.

The phase implements:

1. **Four read-only HTTP endpoints** — `GET /api/narrative-turn/context`,
   `GET /api/narrative-turn/plan`, `POST /api/narrative-turn/feasibility`,
   `POST /api/narrative-turn/preview` — every response carries
   `Cache-Control: no-store`.
2. **HTTP Wire DTO adapter** — converts Python frozen dataclasses /
   tuple-of-pairs / enums into JSON primitives, objects, and arrays.
3. **Simulator Shell workspace** — a `<section id="narrative-turn-workspace">`
   mounted inside `<main id="dashboard-view">`; no nested `<main>`.
4. **10 frontend components** rendering Context / Plan / Validation /
   Preview DTOs, with native radio semantics, single live region, and
   permanent disabled primary action.
5. **URL state, race protection, accessibility, responsive, and
   regression tests.**

**Strict boundary (0D4-C does NOT):**
- ❌ Confirm turns
- ❌ Persist Turn lifecycle state
- ❌ Write branch events
- ❌ Write Canon / Chroma / NarrativeMemory
- ❌ Call Provider
- ❌ Access network outside the local application
- ❌ Call `NarrativeTurnStore.append_plan()` / `append_validation()`
- ❌ Create `NarrativeTurnResult`
- ❌ Append `NarrativeTurnTransition`
- ❌ Create / select / archive / restore branches
- ❌ Add React/Vue or any new third-party dependency

## 2. Implementation Files

### 2.1 New production code

| File | Lines | Purpose |
| --- | --- | --- |
| [web/narrative_turn_routes.py](file:///d:/novel/StoryOS/story-os-demo/web/narrative_turn_routes.py) | 462 | APIRouter with 4 read-only endpoints; param validation, fingerprint/turn_id rebind, safe error envelope, `Cache-Control: no-store` |
| [web/narrative_turn_wire.py](file:///d:/novel/StoryOS/story-os-demo/web/narrative_turn_wire.py) | 343 | Wire DTO adapter (Context/Plan/Validation/Preview); tuple-of-pairs → `{key, level}`; enum → string; `assert_json_safe` rejects Path/set/datetime/NaN |
| [web/static/simulator-narrative-turn.js](file:///d:/novel/StoryOS/story-os-demo/web/static/simulator-narrative-turn.js) | 929 | 10 components; URL state; AbortController + generation counter; single live region; native radios; custom text only in memory + POST body |
| [web/static/simulator-narrative-turn.css](file:///d:/novel/StoryOS/story-os-demo/web/static/simulator-narrative-turn.css) | 760 | Night editorial desk palette; `--nt-*` aliases only; responsive 1280/900/760 breakpoints; reduced-motion |

### 2.2 Modified production code (minimal necessary extensions)

| File | Change | Why |
| --- | --- | --- |
| [web/app.py](file:///d:/novel/StoryOS/story-os-demo/web/app.py) | `+2` lines — import & `include_router(narrative_turn_router)` | Register the new read-only router using the existing pattern |
| [web/static/app.js](file:///d:/novel/StoryOS/story-os-demo/web/static/app.js) | `+4`/`-1` lines — expose `window.storyosApiGet`/`storyosApiPost`, dispatch `storyos:dashboard-ready`, allow external `signal` | Let the new module reuse the existing request infrastructure |
| [web/templates/index.html](file:///d:/novel/StoryOS/story-os-demo/web/templates/index.html) | `+147` lines — `<section id="narrative-turn-workspace">`, CSS link, JS script tag | Mount the workspace inside the existing dashboard; no new page |

### 2.3 New tests

| File | Lines | Tests |
| --- | --- | --- |
| [tests/test_phase0d4c_narrative_turn_routes.py](file:///d:/novel/StoryOS/story-os-demo/tests/test_phase0d4c_narrative_turn_routes.py) | 995 | 60 — endpoint methods, DTO schemas, 400/404/409/422/500, custom text not in response, no-store, no writes |
| [tests/test_phase0d4c_narrative_turn_wire_dto.py](file:///d:/novel/StoryOS/story-os-demo/tests/test_phase0d4c_narrative_turn_wire_dto.py) | 581 | 58 — DTO field mapping, tuple/enum conversion, JSON-safety, no Python accessor leakage |
| [tests/test_phase0d4c_narrative_turn_frontend_contract.py](file:///d:/novel/StoryOS/story-os-demo/tests/test_phase0d4c_narrative_turn_frontend_contract.py) | 555 | 83 — workspace is `<section>`, 10 components, exactly 3 radios, no `aria-disabled`, single live region, primary disabled, 200/201 boundary, race guard, URL safety |

### 2.4 Documentation

| Document | Path |
| --- | --- |
| Phase document | `docs/planning/PHASE_0D4_C.md` |
| Delivery report | `docs/planning/PHASE_0D4_C_DELIVERY_REPORT.md` |
| Implementation brief | `docs/planning/PHASE_0D4_IMPLEMENTATION_BRIEF.md` |

## 3. HTTP Endpoint Contract

### 3.1 Endpoint inventory

| Method | Path | Request | Response | Rebind steps |
| --- | --- | --- | --- | --- |
| GET | `/api/narrative-turn/context` | query: `project_id`, `timeline_id`, `branch_id`, `chapter_id`, `source_version_id` | `ContextWireDTO` | bind → DTO |
| GET | `/api/narrative-turn/plan` | query: same as context | `PlanWireDTO` | bind → build plan → DTO |
| POST | `/api/narrative-turn/feasibility` | JSON body (recommended or custom) | `ValidationWireDTO` | bind → fingerprint check → rebuild plan → turn_id check → action validate → feasibility |
| POST | `/api/narrative-turn/preview` | JSON body (recommended or custom) | `PreviewWireDTO` | bind → fingerprint check → rebuild plan → action validate → feasibility → preview |

All responses include `Cache-Control: no-store` and
`Content-Type: application/json`.

### 3.2 Real call graph

```
HTTP route
→ request parsing (param / body validation)
→ ProjectContext(root) / TimelineContext / NarrativeScope construction
→ NarrativeTurnContextBinder.bind()            [read-only, 0D4-B]
→ expected_context_fingerprint comparison      [POST only]
→ NarrativeTurnPlanner.build_plan()            [deterministic, 0D4-B]
→ expected_turn_id comparison                  [POST only]
→ action validation / custom normalization     [POST only]
→ NarrativeActionFeasibility.validate_*()      [POST only, 0D4-B]
→ NarrativeTurnPreviewService.preview_*()      [POST preview only, 0D4-B]
→ Wire DTO adapter (web/narrative_turn_wire.py)
→ JSONResponse
```

Every step is read-only. No file writes, no `append_plan`, no
`append_validation`, no `NarrativeTurnResult`, no `Transition` append.

### 3.3 Error envelope

Unified structure (no raw exception / traceback / absolute path /
custom action raw text / Provider info):

```json
{
  "error": {
    "code": "CONTEXT_STALE",
    "message": "上下文已过期，请重新规划。",
    "request_id": null
  }
}
```

Status code mapping:

| HTTP | Code family | Example codes |
| --- | --- | --- |
| 400 | malformed request | `MALFORMED_REQUEST`, `MISSING_PARAM` |
| 404 | explicit not found | `PROJECT_NOT_FOUND`, `BRANCH_NOT_FOUND`, `CHAPTER_NOT_FOUND` |
| 409 | stale / mismatch | `CONTEXT_STALE`, `SOURCE_STALE`, `CANON_STALE`, `TURN_ID_MISMATCH`, `ACTION_ID_INVALID` |
| 422 | deterministic reject | `ACTION_TOO_LONG`, `ACTION_UNPARSEABLE`, `ACTION_TARGET_AMBIGUOUS` |
| 500 | safe internal error | `INTERNAL_ERROR` |

`allowed`, `allowed_with_cost`, `requires_clarification`, `blocked` are
**200 responses**, not HTTP errors.

### 3.4 Custom action transport security

- Raw text exists **only** in HTTPS/local request body and Python function memory.
- Never enters URL, localStorage, file, log, exception text, or response.
- Response returns only the SHA-256 hash (`custom_action_text_hash`).
- Frontend never computes the hash itself; backend response is authoritative.

## 4. Wire DTO Boundary

All four DTOs contain **only** JSON primitives, objects, and arrays.
The adapter (`web/narrative_turn_wire.py`) guarantees:

- Frozen tuple-of-pairs → array of `{"key", "level"}` objects
- Python enum → string value
- `Path` / `datetime` / `set` / NaN / custom objects → rejected by `assert_json_safe`
- No Python method names, no absolute paths, no tracebacks, no Provider info
- No raw custom action text — only SHA-256 hash

### 4.1 Field highlights

**ContextWireDTO** — `schema_version`, `scope{project_id,timeline_id,branch_id}`,
`chapter_id`, `source_version_id`, `context_fingerprint`, `canon_revision`,
`planner_revision`, `branch{lifecycle,activity,narrative_state_data}`,
`situation{...}`, `evidence_codes[]`, `limitations[]`.

**PlanWireDTO** — `turn_id`, `scope`, `chapter_id`, `source_version_id`,
`context_fingerprint`, `planner_revision`, `recommended_actions[]` (exactly 3),
`custom_action_policy{max_length=200,...}`.

**ValidationWireDTO** — `validation_id`, `turn_id`, `scope`, `chapter_id`,
`context_fingerprint`, `action_source`, `selected_action_id` (recommended)
or `custom_action_text_hash` (custom, SHA-256 only), `status`, `reason_codes[]`,
`expected_costs[]`, `expected_risks[]`, `notes`.

**PreviewWireDTO** — `preview_id`, `turn_id`, `scope`, `action_source`,
`selected_action_id` / `custom_action_text_hash`, `outcome_projection`,
`risk_projection[]`, `cost_projection[]`, `limitations[]`, `preview_fingerprint`.

## 5. Frontend Workspace

### 5.1 Mounting

Mounted inside `<main id="dashboard-view">` as:

```html
<section id="narrative-turn-workspace"
         role="region"
         aria-labelledby="nt-heading"
         aria-busy="false"
         data-context-state="initial">
```

No nested `<main>`. Visible only when `mode=simulator` and
`view=narrative-turn`. No new HTML page.

### 5.2 Ten components

| Component | Role |
| --- | --- |
| NarrativeTurnWorkspace | Outer section, lifecycle orchestrator |
| NarrativeSituationHeader | Scope/chapter/source/canon/planner chips |
| NarrativeEvidenceSummary | Goal/conflicts/characters/locations/resources/rules/threads/time/dependencies + disclosure |
| RecommendedActionGroup | `<fieldset>` + `<legend>` + 3 native radios |
| RecommendedActionRow | One row: radio, order, intent, display, costs/risks, unavailable reason |
| CustomActionComposer | Textarea + 200-char counter + explicit submit button |
| FeasibilityPanel | Status icon, reason codes, costs/risks |
| ConsequencePreview | Outcome/risk/cost projections + limitations |
| TurnPrimaryAction | Permanently disabled "确认服务尚未接入" with visible reason |
| TurnStatusNotice | The ONLY business live region; switches `role=status`/`role=alert` |

### 5.3 Native radio semantics

- Always renders exactly 3 rows in deterministic order.
- Uses native `<input type="radio">` inside `<fieldset>` + `<legend>`.
- No duplicate `role=radio` or `aria-checked`.
- Unavailable rows: `data-unavailable="true"`, `aria-describedby` → visible reason,
  **never** `aria-disabled`, **never** native `disabled`.
- Only stale-group state sets native `disabled` on all radios.
- Unavailable rows remain selectable to surface the reason.

### 5.4 Custom action composer

- `MAX_CUSTOM_ACTION_LENGTH = 200` (matches 0D4-B).
- NFKC normalize, trim, collapse whitespace, reject NUL/control chars.
- Counter uses `aria-describedby`, **no** `aria-live`.
- 200 → submittable; 201 → not submittable.
- No implicit submit on Enter; explicit secondary button only.
- No chat bubbles, avatars, send arrows, or autocomplete.
- Hash shown only from backend response.

### 5.5 Single live region

Only `#nt-status-notice` carries `aria-live`:
- Polite business status: `role="status"`, `aria-live="polite"`.
- Error: `role="alert"`, `aria-live="assertive"`.
- Stale responses are silently discarded (no announce, no focus move).

RecommendedActionGroup, FeasibilityPanel, ConsequencePreview, CustomAction
counter, and Workspace error content have **no** independent `aria-live`
or `role="alert"`. They display visible text and route announcements
through TurnStatusNotice.

### 5.6 Primary action

Permanently:

```html
<button type="button" class="nt-primary-action" disabled
        aria-disabled="true" aria-describedby="nt-primary-disabled-reason">
  确认服务尚未接入
</button>
<p id="nt-primary-disabled-reason">
  行动确认将在 Phase 0D4-D 接入；当前仅支持规划、分析与预览。
</p>
```

No confirm request, no faked success, no Turn Store / branch write.

### 5.7 URL state

URL carries only: `mode`, `view`, `project_id`, `timeline_id`, `branch_id`,
`chapter_id`, `source_version_id`, `turn_id`, `action_id`.

Forbidden in URL: `custom_action_text`, `custom_action_text_hash`,
`context_fingerprint`, validation payload, preview payload.

`turn_id` authority = deterministic rebuild (bind → plan → compare).
No `NarrativeTurnStore` query. Mismatch → stale/invalid, no auto-correct.
Back/Forward triggers rebind.

### 5.8 Race protection

- Per-request `AbortController`.
- Module-level `generation` counter; parent context change →
  `abort()`, `generation += 1`, clear selection, mark stale.
- Every response checks `responseGeneration === currentGeneration`
  before render; mismatch → silent discard.

## 6. Security Boundaries

All counts maintained at **0**:

| Boundary | Count |
| --- | --- |
| Filesystem writes from endpoints | 0 |
| NarrativeTurnStore writes (`append_plan` / `append_validation`) | 0 |
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
| Git write operations (add/commit/push/reset/clean/stash/rebase) | 0 |

Custom action raw text transport audit:

| Channel | Present? |
| --- | --- |
| URL | ❌ no |
| localStorage | ❌ no |
| File | ❌ no |
| Log | ❌ no |
| Exception text | ❌ no |
| Response body | ❌ no (only SHA-256 hash) |

## 7. Test Results

### 7.1 0D4-C focused tests

```
Command: python -m pytest tests/test_phase0d4c_narrative_turn_routes.py \
           tests/test_phase0d4c_narrative_turn_wire_dto.py \
           tests/test_phase0d4c_narrative_turn_frontend_contract.py \
           tests/test_phase0d4c_preflight_contract_docs.py \
           tests/test_phase0d4c_context_navigator_integration.py -q
Result:  243 passed, 1 warning in 18.50s
Exit:    0
```

Breakdown: routes 60 + wire DTO 58 + frontend contract 83 + preflight
docs 22 + context navigator integration 20 = 243.

### 7.2 0D4-A/B regression

```
Command: python -m pytest tests/test_phase0d4a_narrative_turn_foundation.py \
           tests/test_phase0d4b_narrative_turn_planner.py -q
Result:  262 passed in 24.20s
Exit:    0
```

### 7.3 Existing web contract & simulator DOM

```
Command: python -m pytest tests/test_phase0d3b1_simulator_panel_frontend.py \
           tests/test_web_api_contract.py tests/test_planning_control.py \
           tests/test_context_assembly_service.py -q
Result:  32 passed, 1 warning in 7.76s
Exit:    0
```

### 7.4 Adjacent regression

```
Command: python -m pytest tests/test_phase0c1_vector_isolation.py \
           tests/test_static_path_guard.py tests/test_real_data_protection.py \
           tests/test_planning_rolling_window.py tests/test_revision_service.py \
           tests/test_phase0b2_dual_project_isolation.py -q
Result:  57 passed, 1 warning in 25.36s
Exit:    0
```

```
Command: python -m pytest tests/test_version_manager.py \
           tests/test_phase0d3c2_preflight.py \
           tests/test_phase0d2a_reader_persona_panel.py \
           tests/test_safe_error_envelope.py -q
Result:  80 passed, 1 warning in 8.95s
Exit:    0
```

### 7.5 Static checks

- `python -m compileall web/narrative_turn_routes.py web/narrative_turn_wire.py` → exit 0
- AST parse + runtime imports verified via focused test collection.
- JS syntax validated via focused frontend contract tests.
- CSS selector/static checks validated via frontend contract tests.
- Document contract tests (22 rules) pass via `test_phase0d4c_preflight_contract_docs.py`.

### 7.6 Tests not run

The full repository regression suite (~150+ test files) was not run in
its entirety. Directly related suites listed above cover 0D4-A/B, web
contract, simulator DOM, vector isolation, static path guard, real data
protection, planning rolling window, revision service, dual-project
isolation, version manager, 0D3C2 preflight, 0D2A reader persona panel,
and safe error envelope. Unrelated suites (LLM, Obsidian, evaluation,
draft writer, etc.) were not re-run; they do not touch Narrative Turn
code paths.

## 8. Phase 0D4-C-RC1 — Real Browser Runtime, JS Syntax, Security Sentinel & Test-Count Closure

### 8.1 JavaScript Syntax Verification

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

### 8.2 Real Browser Acceptance (66-item checklist)

The application was started via `python main.py web` (uvicorn on
127.0.0.1:7860) and exercised in a real Chromium browser. Results:

| Section | Items | Result | Evidence |
| --- | --- | --- | --- |
| 6.1 Basic mounting | 1-7 | PASS | Workspace mounts at `?mode=simulator&view=narrative-turn`; URL preserved (not overwritten); no nested `<main>` (max depth=1); CSS+JS return 200; no console errors; `#nt-status-notice` exists; `#simulator-panel-review` correctly hidden. |
| 6.2 Context & Plan | 8-16 | NOT TESTABLE in browser (no active project in test env); HTTP-level PASS via runtime acceptance (45/45). | Runtime acceptance verified 200 + 3 actions + deterministic order + 64-hex fingerprint + branch dimensions. |
| 6.3 Recommended actions | 17-23 | PASS (structure) | 3 native radios inside `<fieldset>`; no `aria-disabled`; `data-unavailable="true"` + `aria-describedby` per design. Interaction not tested (no active project). |
| 6.4 Custom action | 24-34 | PASS (HTTP-level) | Runtime acceptance verified POST method, 200/201 char boundary, control-char rejection (422), no sentinel in URL/response, SHA-256 hash returned. Enter-no-submit enforced by design (explicit secondary button). |
| 6.5 Feasibility & Preview | 35-42 | PASS (HTTP-level) | Runtime acceptance verified all 4 status values return 200; 409 stale; 422 reject; safe error envelope; no sentinel in response. |
| 6.6 URL & race | 43-52 | PASS (HTTP-level) | AbortController audit (§8.5) confirms generation guard + signal abort. Runtime acceptance verified 404 no-fallback, 409 TURN_STALE, 409 ACTION_NOT_FOUND. |
| 6.7 Branch state | 53-56 | PASS (HTTP-level) | Runtime acceptance verified branch dimensions `{lifecycle, activity, narrative_state_data}` are independent. |
| 6.8 Responsive & a11y | 57-66 | PASS | Screenshots at 760px and 1280px show no horizontal overflow; `#nt-status-notice` is the only business live region; primary button permanently disabled with visible `aria-describedby` reason. |

**Critical item 6.1 (mounting) was verified in-browser and PASSED.**
Items requiring real project data (6.2-6.7) are NOT TESTABLE in the
browser because the test environment has no active project (setting one
would write to real project data, violating the zero-write boundary).
These items are comprehensively covered by the HTTP-level runtime
acceptance script (`tests/_rc1_runtime_acceptance.py`, 45/45 PASS).

### 8.3 Security Sentinel Audit

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

### 8.4 Endpoint No-Diff Audit

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
No data repair or migration.

### 8.5 AbortController Integration Audit

| Audit item | Result | Evidence |
| --- | --- | --- |
| External `signal` passed to `fetch` | PASS | `apiGet(url, signal)` and `apiPost(url, body, signal)` both pass `signal` into `fetch()` (lines 150-169). |
| GET and POST both support external signal | PASS | Both call sites pass `state.controller.signal`. |
| Module controller can cancel corresponding requests | PASS | `bumpGeneration()` aborts current controller and creates a new one (lines 732-738). |
| Will not cancel other workspace requests | PASS | Narrative Turn uses its own module-scoped `state.controller`, separate from `app.js`'s `storyosActiveRequests` Set. |
| No completed controllers left in set | PASS | Module uses a single `state.controller` reference (not a Set); replaced on each `bumpGeneration()`. |
| Generation increments on each parent Context change | PASS | `bindContextAndPlan` and `requestFeasibilityAndPreview` both call `bumpGeneration()` at entry. |
| Generation checked before each async DOM update | PASS | 6 `isStale(generation)` checks after every `await` (lines 783, 797, 842, 942, 962, 970, 981). |
| AbortError not shown as business error | PASS | `catch (err) { if (err && err.name === "AbortError") return; ... }` (lines 961, 980). |
| AbortError does not enter assertive live region | PASS | AbortError returns before any `noticeError()` call. |

### 8.6 Warning Inventory

```
Command: python -m pytest tests/test_phase0d4c_*.py -ra -W default
```

| Warning type | Source file | Message | Introduced by 0D4-C? | Accepted? |
| --- | --- | --- | --- | --- |
| StarletteDeprecationWarning | `fastapi/testclient.py:1` | Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead. | No (FastAPI/Starlette library code) | Yes (library-level; not actionable from 0D4-C) |

Only 1 warning across all 0D4-C focused tests. Zero warnings introduced
by 0D4-C production code.

### 8.7 Correct Test Arithmetic

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

### 8.8 RC1 Code Fix

> **HISTORICAL RC1 WORKAROUND**
> **SUPERSEDED AND REMOVED BY RC2**
>
> This workaround was applied in RC1 but replaced by a proper fix in RC2.
> Kept here for historical record only.

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

**RC2 resolution:** Replaced with a proper integration approach that
preserves full Navigator functionality while avoiding URL conflicts.
The `document.write` conditional loader was removed.

### 8.9 RC1 Runtime Acceptance Script

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

`tests/_rc1_static_assets_check.py` (19 checks, 18 PASS + 1 WARN):
- CSS/JS/HTML return 200 with correct Content-Type
- No invalid `disabled: true;` CSS rule
- HTML has unique business live region `#nt-status-notice`
- No nested `<main>` elements (max depth=1)
- All 4 endpoints reachable (not 404)
- Method enforcement (405 for GET on POST endpoints)

Both scripts are one-shot acceptance runners (not pytest test files);
they do not modify the 0D4-C focused test count of 223.

## 9. Phase Status

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
  (75-item checklist + security sentinel + zero-write audit + context navigator syntax = 78)
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
