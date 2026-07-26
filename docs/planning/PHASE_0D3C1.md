# Phase 0D3C1 — Safe Panel Planning & Mock Execution Workflow

## Result

**PASSED**

Phase 0D3B2 remains passed. This phase adds a safe, fixed-mode Mock workflow to the production Simulator / Panel Review surface:

`Context → Persona selection → Mock Plan → user confirmation → Mock Run → Saved Run refresh → explicit Review`.

## Persona options

The existing registry-backed `GET /api/simulator/reader/personas` was reused and exposed through the narrow alias `GET /api/reader-persona/options`. The response contains only `persona_id`, `display_name`, `short_description`, `enabled`, and stable `deterministic_order`. It contains no prompt, provider, credential, endpoint, absolute path, or internal exception.

## Plan and Run contract

- Plan: `POST /api/reader-persona/model-panel/plan`.
- Run: `POST /api/reader-persona/model-panel/runs`.
- Both requests are sent with `mode=mock`, `execution_profile=mock`, `max_provider_calls=0`, and selected Persona ids only.
- The UI has no live mode switch, `allow_model_call` control, API-key field, provider credential input, retry, fallback, repair, rerun, moderator, or synthesis control.
- Plan remains read-only; it does not create a Run.
- Run is submitted only after explicit user confirmation and returns the real `panel_execution_id`.
- Mock uses the existing deterministic `_MockProvider`, which performs no network access and no real provider/token call.

## Scope and safety

- `project_key` is a safe project identifier; the UI does not send an absolute path.
- `project_id` is resolved from the read-only context metadata and is checked against the bound project state.
- Missing source context blocks the UI before plan/run submission.
- Parent context changes abort the active request; duplicate submission is disabled.
- A successful Run updates the safe URL only after the server returns the real execution id, refreshes Saved Runs, and opens the existing explicit Review GET route. No automatic fallback is introduced.
- Story text, Canon, Summary, Chroma, Obsidian, and existing Runs are untouched except for the new Mock Panel Run record explicitly created by the user.

## Files

- `story-os-demo/web/routes.py`
- `story-os-demo/web/templates/index.html`
- `story-os-demo/web/static/app.js`
- `story-os-demo/web/static/simulator-context-navigator.js`
- `story-os-demo/web/static/simulator-panel-run.js`
- `story-os-demo/web/static/simulator-panel-review.css`
- `story-os-demo/tests/test_web_routes.py`
- `story-os-demo/tests/test_phase0d3b1_simulator_panel_frontend.py`

## Validation

- 0D2B1/0D2B2/0D2B3 plus 0D3B2 route/static suites: **148 passed**.
- 0D3C1 focused + context/route tests: **39 passed**.
- JavaScript syntax checks: app, context navigator, Review renderer, and panel-run module passed.
- `python -m compileall -q web system core`: passed.
- Mock temporary-project plan/run smoke: passed; no provider/network call.
- Production fixture fallback scan: NONE.
- Unsafe DOM/credential scan: NONE.
- No live-call UI or credential input exists.

Browser screenshots were not used as a gate, consistent with the owner decision in the 0D3B1 Final Seal.
