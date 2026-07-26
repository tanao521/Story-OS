# Phase 0D3B1 Delivery Report

## Result

**PARTIALLY PASSED — production integration and CLI regression closure are complete; browser QA closure remains blocked by unavailable browser automation.**

## Delivered

- Added the existing-shell mode switch (`传统写作 | 模拟器`) with keyboard/focus semantics through native buttons and `aria-pressed`.
- Added the production simulator panel mount without changing the traditional writing sections or adding a second shell.
- Reused `window.storyosApiGet`, the existing request generation, `AbortController`, and stale-project response protection.
- Added safe URL parsing and active-project validation. No absolute path is accepted or sent.
- Added automatic and explicit review endpoint selection; explicit `PANEL_RUN_NOT_FOUND` is terminal with no fallback.
- Added DOM-safe rendering for review metadata, authoritative panel, ordered persona cards, separated model supplements, agreement/conflict groups, evidence/execution/usage/staleness, warnings, and safe error states.
- Added feature-scoped responsive CSS at the RC2 thresholds (900px and 760px).
- Added a QA-only eleven-fixture fallback harness using the real production renderer and CSS.
- Stabilized `show-reader-persona-panel-review --json` on Windows by emitting ASCII-escaped JSON, avoiding GBK console-code-page corruption for UTF-8 subprocess consumers.

## Files

- `story-os-demo/web/templates/index.html`
- `story-os-demo/web/static/app.js`
- `story-os-demo/web/static/simulator-panel-review.js`
- `story-os-demo/web/static/simulator-panel-review.css`
- `story-os-demo/tests/test_phase0d3b1_simulator_panel_frontend.py`
- `docs/design/qa/simulator-panel-review-production/harness.html`
- `docs/design/qa/simulator-panel-review-production/harness.js`
- `docs/design/qa/simulator-panel-review-production/README.md`

## Validation

- `python -m pytest -q tests/test_phase0d3b1_simulator_panel_frontend.py` — **5 passed**.
- `python -m pytest -q tests/test_phase0d2b3_panel_review_model.py` — **11 passed**, including the CLI/Web read-only test.
- The previously failing CLI test was run independently **3 consecutive times** — **3/3 passed**.
- Web/route/static regression (`test_web_routes.py`, `test_web_api_contract.py`, `test_recovered_routes.py`, and the frontend contract) — **48 passed**.
- `node --check story-os-demo/web/static/simulator-panel-review.js` — **passed**.
- `node --check story-os-demo/web/static/app.js` — **passed**.
- `node --check` for `app.js`, `simulator-panel-review.js`, and the QA harness — **passed**.
- `python -m compileall -q .` — **passed**.
- Backend routes/contracts were not modified by this phase.

## Outstanding browser evidence

The in-app browser bootstrap failed because the bundled browser client could not resolve `./node_modules/classic-level.mjs`. The available Chrome connector also reported `Browser is not available: extension`, and no system Edge/Chrome executable or Selenium/Playwright package was present. Therefore no live production screenshots, console-zero result, popstate/back-forward run, or route-interception fixture screenshots are claimed here.

The real Story OS server was nevertheless started with `python -m uvicorn web.app:app --host 127.0.0.1 --port 4181` from `story-os-demo` (PID 8144; stopped after QA). Evidence: `GET /` returned HTTP 200; automatic Review returned HTTP 200 with the current workspace's `source_missing` result; explicit missing execution returned HTTP 404 with `PANEL_RUN_NOT_FOUND`; the served template contained the mode switch and production module and no fixture path. The active-project endpoint returned `project: null`, so a safe deep-link could not be exercised without changing project configuration.

Restore a supported browser runtime and run the required 1440×900, 1280×800, 768×1024, and 390×844 production captures plus real `not_run` and explicit-404 captures before sealing RC1.

## Dirty-worktree attribution

Existing unrelated dirty entries and prior RC2 prototype/docs/artifacts were preserved. No reset, clean, rebase, commit, push, backend contract change, provider/model invocation, or project-data write was performed.
