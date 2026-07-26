# Phase 0D3B1-RC1 — Production Browser QA and Regression Closure

## Result

**PARTIALLY PASSED / not sealed.** The CLI regression is closed and the production route is reachable. Browser automation remains unavailable, so the screenshot, console, Network, popstate, and responsive visual gates are intentionally open.

## CLI UTF-8 closure

Failing node: `tests/test_phase0d2b3_panel_review_model.py::test_cli_and_web_review_queries_are_read_only`.

Root cause: `story-os-demo/main.py` printed `json.dumps(..., ensure_ascii=False)` for `--json`. The Windows child process used `gbk` stdout (`chcp=936`, Python 3.14.5, `sys.stdout.encoding=gbk`), while the parent test requested UTF-8 decoding. The reader thread raised `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xbd in position 3243`, leaving `cli.stdout` unavailable before JSON assertion.

Minimal fix: only the `show-reader-persona-panel-review --json` branch now uses `ensure_ascii=True`, producing a stable ASCII JSON stream without changing review semantics, routes, or service behavior.

Closure evidence: the failing node passed three consecutive independent runs. No CLI helper, Review contract, or backend route was changed.

## QA harness isolation audit

- Harness: `docs/design/qa/simulator-panel-review-production/harness.html` and `harness.js`.
- It is outside the production template and loads the production renderer/CSS by an isolated relative path.
- It enumerates exactly eleven redacted fixtures.
- Production `simulator-panel-review.js` contains no fixture path, `localStorage`, `sessionStorage`, or fixture fallback branch.
- Production served HTML contains no `docs/design/fixtures` reference.
- Explicit 404 harness state calls the exported production `renderState`; it does not duplicate rendering.

## Real server evidence

Command: `python -m uvicorn web.app:app --host 127.0.0.1 --port 4181`, cwd `D:\novel\StoryOS\story-os-demo`, PID 8144; process stopped after checks.

- `GET /` → HTTP 200; response contained the mode switch and production module.
- Automatic Review GET → HTTP 200, current workspace result `source_missing` (active project was not configured).
- Explicit missing execution GET → HTTP 404, `PANEL_RUN_NOT_FOUND`.
- Active-project GET returned `project: null`; no project configuration was changed to manufacture a deep-link context.

## Browser runtime blocker

The bundled in-app browser failed to resolve `classic-level.mjs`. The Chrome connector reported `Browser is not available: extension`; no system Edge/Chrome executable and no Selenium/Playwright package were available. Per the browser troubleshooting rules, no unrelated browser substitute, dependency installation, browser-cache mutation, fake screenshot, or fabricated console result was used.

## Regression evidence

- 0D3B1 frontend tests: 5 passed.
- 0D2B3 panel review suite: 11 passed.
- Web/route/static regression: 48 passed.
- Node syntax checks: `app.js`, `simulator-panel-review.js`, QA harness — passed.
- `python -m compileall -q .` — passed.

## Required before PASS

Restore a supported browser, then capture the seven required production screenshots and verify traditional default, automatic `not_run`, explicit 404 without fallback, all four viewports, console zero, Network no writes/no fixture requests, mode switching, popstate, deep-link copy, and responsive geometry. Until then, do not seal 0D3B1 or advance to a later phase.
