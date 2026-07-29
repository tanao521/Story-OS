# Phase 0D6-C-A — Read-Only Cross-Chapter Progression Status Surface

Status: PASSED — READY FOR 0D6-C-B AUTHORIZATION  
Date: 2026-07-28  
Authority: 0D6-A PASSED & SEALED; 0D6-B PASSED & SEALED; 0D6-C-P PASSED

## Purpose

Expose a Simulator-only, read-only view of the sealed cross-chapter readiness authority. The surface reads `GET /api/chapter-progression/readiness`, maps safe readiness codes to user-facing states, and never starts a Turn.

## Authority boundary

- No `POST` progression route is referenced or called.
- No operation ID is generated or persisted.
- Successor, lifecycle operation, branch authority, and fingerprints are never derived in the browser.
- No readiness DTO, sealed service, backend route, branch registry, Turn store, provider, or external network contract was changed.
- Existing Traditional mode remains outside the progression module and issues zero progression requests.

## Frontend placement

The panel is mounted once inside `#simulator-loop-shell`, below the existing completion/recovery surfaces and adjacent to the current Turn workspace. It is hidden until a valid Simulator context is supplied by the existing context navigator and simulator state read model.

Valid initialization requires:

```text
mode == simulator
timeline == main
project_id present
active branch present and active
current/previous chapter identity present
```

Invalid context enters `UNAVAILABLE`, aborts any prior request, and sends no readiness request.

## Module architecture

- `web/static/simulator-chapter-progression.js` owns the read-only state machine, GET helper, safe-code presentation map, epoch/context-key stale protection, rendering, and existing-Turn continuation.
- `web/static/simulator-chapter-progression.css` owns the existing Simulator visual language, mobile layout, focus treatment, and reduced-motion rules.
- `web/static/simulator-context-navigator.js` exposes the minimal existing-context `rebind()` helper. It remains the owner of URL/context navigation.
- `web/templates/index.html` adds one panel, CSS/script assets, status live-region, and existing-Turn continuation control. It adds no progression start control.

## Context subscription and stale protection

The module consumes `storyos:simulator-state`, `storyos:panel-context-ready`, `popstate`, and dashboard-ready events. The authoritative context key is `(project_id, timeline_id, branch_id, previous_chapter_id)`. Each GET owns an `AbortController` and epoch. On context change, the previous request is aborted, transient readiness is cleared, and a stale response is silently discarded without rendering, navigation, or Turn-workspace mutation.

## Readiness fetch contract

The only new route call is:

```text
GET /api/chapter-progression/readiness
  ?project_id=<authoritative project>
  &timeline_id=main
  &branch_id=<authoritative branch>
  &previous_chapter_id=<authoritative current chapter>
```

The response is accepted only when its scope matches the current context and it contains a string `readiness_code`. The route's `Cache-Control: no-store` policy is preserved by an explicit `cache: "no-store"` request option.

## State machine

Implemented C-A states:

```text
UNAVAILABLE
LOADING_READINESS
BLOCKED
READY
EXISTING_TURN
RECOVERY_REQUIRED
CORRUPT
NETWORK_OR_ROUTE_ERROR
```

`STARTING` and `STARTED` remain C-B-only and are absent from the C-A module. `READY_TO_START_TURN` renders status copy only; no start button is rendered. `TURN_ALREADY_STARTED` renders a continuation button only when the sealed DTO supplies both `existing_turn_id` and `successor_chapter_id`.

## Safe-code mapping

The centralized presentation map covers the required lifecycle, completion, branch, planning, source, canon, scope, timeline, corrupt-authority, existing-Turn, stale-source, and recovery codes. Unknown codes fail closed to `CORRUPT`; they are never interpreted as READY. Internal paths, operation files, lock owners, full fingerprints, tracebacks, and process identifiers are not rendered.

## Existing Turn continuation

Continuation validates the DTO-provided `existing_turn_id` and `successor_chapter_id`, then delegates to `StoryOSContextNavigator.rebind()`. It updates only safe URL context IDs, selects the successor chapter supplied by the authority, opens the existing narrative-turn view, and passes the existing Turn identity through the normal workspace load. It does not call a start route, create a plan, create a transition, confirm an action, or infer a chapter by arithmetic.

## Traditional mode isolation

The module has a JavaScript mode gate, not merely CSS visibility. In Traditional mode it aborts any outstanding request, resets to `UNAVAILABLE`, hides the surface, and issues no progression GET. No progression listener is registered for a Traditional-only view.

## Mobile and accessibility

- 320–480px layouts stack the existing-Turn action and preserve a 44px touch target.
- Status text uses `aria-live="polite"`; errors remain explicit text rather than color-only signals.
- Existing-Turn continuation is keyboard activatable and has a visible `:focus-visible` outline.
- Context/status text uses `overflow-wrap`; no horizontal scrolling is required.
- Reduced-motion preferences disable transition/animation additions.

## Filesystem boundary

The C-A frontend performs no filesystem operation. It creates no operation artifact and cannot mutate Chapter, Version, Canon, Branch, Turn plan, Turn transition, Candidate, Review, Commit, Chroma, or Obsidian state.

## Test matrix and browser gate

Static contract tests cover asset wiring, readiness-only route usage, no operation ID, no local persistence, no successor arithmetic, fail-closed unknown codes, existing-Turn rebind, mobile/focus/reduced-motion CSS, and sealed route no-store preservation. Targeted backend and frontend regressions remain green. Real Chromium smoke is deferred to 0D6-C-FV, as permitted by the C-A prompt.

## Accepted limitations and non-goals

- The current completion panel's pre-existing next-chapter navigation remains owned by the earlier usable-loop/candidate surface; C-A adds no new start action and does not call the sealed progression start route.
- No readiness polling, automatic refresh loop, automatic repair, automatic start, action confirmation, Candidate, Review, Commit, successor creation, provider call, or non-main timeline support is included.

## C-B authorization gate

The C-A implementation is safe to advance to `0D6-C-B AUTHORIZATION`. C-B may add one explicit start action, operation-id lifecycle, durable-start retry/replay, and post-start context rebind only after explicit authorization.

