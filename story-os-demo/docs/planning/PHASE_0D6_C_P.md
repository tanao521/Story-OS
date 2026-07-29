# Phase 0D6-C-P — Cross-Chapter Progression UI Preflight

Status: PASSED — READY FOR 0D6-C-A AUTHORIZATION
Date: 2026-07-28
Scope: read-only preflight, contract mapping, state-machine planning

## Authority and boundaries

- Phase 0D6-A is PASSED & SEALED.
- Phase 0D6-B is PASSED & SEALED (Owner Seal Date 2026-07-28).
- This document authorizes only the planning/specification work in 0D6-C-P.
- Production progression UI, frontend mutation code, new tests, route changes, and data changes are not authorized by this phase.
- 0D7, 0E, provider-live work, and non-main successor creation remain out of scope.

## Preflight finding

The simulator already has a safe mode gate, URL-driven context navigation, abort/generation race protection, a narrative-turn workspace, and a usable-loop completion/result surface. It does not yet call the sealed progression endpoints:

- `GET /api/chapter-progression/readiness`
- `POST /api/chapter-progression/start-turn`

`simulator-usable-loop.js::continueNextTurn()` currently changes the view to `narrative-turn`; it does not perform readiness aggregation or durable start. The current `chapter_progression.next_chapter_available` evidence in simulator state is therefore not a substitute for the sealed readiness authority.

## Recommended placement

Add one simulator-only progression panel inside `#simulator-loop-shell`, adjacent to the existing completion/result evidence (`#simulator-turn-result`) and before the narrative-turn workspace. The panel should expose one primary action, “Start next chapter initial Turn”, only when readiness is `READY_TO_START_TURN`. It must not appear or poll in Traditional mode.

## Audited integration surface

| Concern | Existing surface | Preflight result |
|---|---|---|
| Mode isolation | `web/templates/index.html`, `simulator-context-navigator.js`, `simulator-narrative-turn.js`, `simulator-usable-loop.js` | reusable simulator gate exists |
| Context binding | `simulator-context-navigator.js` and `/api/simulator/context` | URL/context state exists; progression fields are not yet bound |
| Existing Turn UI | `simulator-narrative-turn.js` | can load/read/confirm an existing Turn; no progression start bridge |
| Readiness authority | `web/chapter_progression_routes.py`, `CrossChapterReadinessService` | sealed GET contract exists; no caller |
| Durable start authority | `web/chapter_progression_routes.py`, `CrossChapterTurnStartService` | sealed POST contract exists; no caller |
| Lifecycle resolver | `ChapterLifecycleService` | remains the authoritative successor resolver |
| Cache policy | progression routes return `Cache-Control: no-store` | UI must not cache readiness/start payloads |

## Required next phase split

### 0D6-C-A — Read-only status surface

Implement only the simulator panel, readiness GET helper, state rendering, error/status envelope handling, and Traditional-mode isolation. No POST and no automatic start. Add focused DOM/route contract tests.

### 0D6-C-B — Explicit start and context rebind

After C-A authorization, add a single explicit READY action. Generate one in-memory `operation_id` per user intent, send the sealed POST request with the readiness fingerprint, handle replay/response loss, and rebind to the returned `turn_id` in the existing narrative-turn workspace. Do not auto-confirm an action or generate prose.

### 0D6-C-FV — Browser, accessibility, and recovery verification

Verify mobile widths, keyboard/focus behavior, double-click protection, stale-response suppression, response-loss retry, reload/back/forward, Traditional-mode isolation, no-store behavior, and filesystem/authority regressions in a real browser.

## Anticipated production file impact (not changed in C-P)

- `web/templates/index.html`: simulator-only panel markup and accessible status/description hooks.
- `web/static/simulator-progression.js`: readiness/start client state machine, envelope parsing, operation-id lifecycle, and rebind events.
- `web/static/simulator-progression.css`: responsive panel, blocked/loading/error states, and reduced-motion rules.
- `web/static/simulator-usable-loop.js`: replace the current view-only next-turn handoff with an event/bridge to the progression panel.
- `web/static/simulator-context-navigator.js` and `web/static/simulator-narrative-turn.js`: consume the rebind event without duplicating authority or changing Traditional mode.
- focused frontend/route tests: added only after C-A/C-B authorization.

## Gate

All required mappings are complete and no sealed authority contradiction was found. The next gate is `0D6-C-A AUTHORIZATION`; implementation must not begin until that gate is explicitly opened.
