# Phase 0D6-C-B Delivery Report

## Outcome

`PASSED — READY FOR 0D6-C-FV AUTHORIZATION`

The C-A readiness panel now supports one explicit durable start action and safe successor context rebind. The implementation does not auto-start, auto-confirm, or alter sealed backend authority.

## Changed files

Production frontend:

- `web/templates/index.html`
- `web/static/simulator-chapter-progression.js`
- `web/static/simulator-chapter-progression.css`
- `web/static/simulator-context-navigator.js` (existing rebind helper only)

Tests:

- `tests/test_phase0d6c_a_frontend.py` (updated compatibility assertions for the authorized C-B extension)
- `tests/test_phase0d6c_b_frontend.py`

Documentation:

- `docs/planning/PHASE_0D6_C_B.md`
- `docs/planning/PHASE_0D6_C_B_DELIVERY_REPORT.md`

No backend, sealed contract, provider, dependency, configuration, or data file was changed.

## Legacy Action Audit

The prior completion control only navigates to an advisory next chapter URL. C-B adds a UI gate that hides it whenever a valid progression context exists, leaving the progression panel as the only same-level primary start entry. No legacy write fallback or duplicate progression POST exists.

## Start Control Evidence

Exactly one `data-progression-start` control is rendered. It is enabled only for validated READY DTOs. It is disabled during STARTING, hidden for all other states, and relabelled to “Retry start safely” only for the same-intent retryable state. Existing-Turn continuation remains a separate secondary action and never invokes the start route.

## Endpoint Usage Evidence

The module uses:

```text
GET  /api/chapter-progression/readiness
POST /api/chapter-progression/start-turn
```

The POST body is the sealed seven-field DTO and is frozen before dispatch. The frontend does not add authority fields.

## No-Auto-Start Evidence

Initialization, readiness responses, simulator-state events, completion events, context changes, mode changes, and refreshes call only readiness synchronization. `requestStart()` is reachable only through the explicit start button handler.

## Operation ID and double-click evidence

The first explicit click creates one UUID/fallback ID in memory. `activeStartPromise`, STARTING state, disabled control, and frozen snapshot prevent concurrent duplicate POSTs. Retryable transport failures reuse the same operation ID and serialized request body.

## Response-Loss Replay Evidence

Unreadable responses, network failures, and ambiguous transport failures enter `START_RETRYABLE_ERROR` while retaining the intent. Explicit safe retry uses the same frozen snapshot. Parseable terminal codes clear the intent and do not create a replacement ID automatically.

## Safe Error Mapping

`OPERATION_CONFLICT`, `TURN_START_READINESS_CHANGED`, `TURN_START_SOURCE_CHANGED`, `CORRUPT_OPERATION`, and `TURN_ALREADY_STARTED` are handled explicitly. Unknown codes fail closed. `TURN_ALREADY_STARTED` converges through a fresh readiness GET rather than trusting a second client-created operation.

## Response Validation

Before rebind, the response must match frozen project, timeline, branch, previous chapter, successor, readiness fingerprint, operation ID, and Turn identity, with `turn_status == "awaiting_action"`. Invalid responses never navigate.

## Context Race Evidence

Context key and epoch checks prevent old responses from rebinding a changed project, branch, chapter, or mode. A context change clears the pending intent and triggers fresh readiness; it cannot reuse the old operation for the new context.

## Rebind Evidence

Both C-A existing-Turn continuation and C-B durable success call `StoryOSContextNavigator.rebind()`. The server-returned `successor_chapter_id` and `turn_id` are passed to the existing Narrative Turn URL/context path. The workspace loads the initial Turn and remains at `awaiting_action`; no action confirmation is issued.

## Traditional Isolation

Traditional mode clears pending progression state, hides the panel, and produces no progression POST or operation ID. The JavaScript gate is independent of CSS visibility.

## Accessibility/Mobile Evidence

The primary action has an accessible name and `aria-describedby` status, uses `aria-busy` during POST, remains keyboard operable, is 44px-capable on mobile, and focuses the successor Turn heading/workspace after rebind. C-FV remains responsible for real viewport and focus smoke.

## Filesystem Boundary

Frontend writes: 0. Backend sealed operation artifacts: created only by the existing service when a real explicit start is exercised, not by tests or frontend code. No Chapter, Version, Canon, Branch, Candidate, Review, Commit, Chroma, Obsidian, Provider, or external data writes were introduced by this implementation.

## Targeted Regression Ledger

| Command | Result |
|---|---:|
| `python -m pytest -q tests/test_phase0d6c_a_frontend.py tests/test_phase0d6c_b_frontend.py` | 14 passed, 0 failed, 0 skipped, exit 0 |
| `python -m pytest -q tests/test_phase0d6b_authority.py tests/test_phase0d6b_fv1.py tests/test_phase0d6b_fv2.py tests/test_phase0d4c_narrative_turn_frontend_contract.py tests/test_phase0d4c_narrative_turn_routes.py tests/test_phase0d4d_frontend_contract.py tests/test_phase0d4d_confirm_routes.py tests/test_phase0d5c_frontend_contract.py tests/test_phase0d5d1_traditional_isolation.py tests/test_phase0d5d2_frontend_contract.py tests/test_static_path_guard.py` | 211 passed, 0 failed, 0 skipped, exit 0 |
| `node --check web/static/simulator-chapter-progression.js; node --check web/static/simulator-context-navigator.js; node --check web/static/simulator-narrative-turn.js` | passed, exit 0 |

## Browser Verification

Chromium smoke was not run in C-B. It is explicitly deferred to `0D6-C-FV`; no browser acceptance is claimed here.

## Safety Ledger

| Item | Count/result |
|---|---:|
| Production frontend changes | 4 files |
| Production backend changes | 0 |
| Test changes | 2 files |
| Provider calls | 0 |
| External network calls from tests | 0 |
| Token/API cost | 0 |
| Real project/data writes | 0 |
| Chroma writes | 0 |
| Obsidian writes | 0 |
| ChapterLifecycleService changes | 0 |
| CrossChapterReadinessService changes | 0 |
| CrossChapterTurnStartService changes | 0 |
| NarrativeTurnService changes | 0 |
| ChapterCommitService changes | 0 |
| New dependencies | 0 |
| Git write operations | 0 |

## Remaining Limitations

Real browser double-click, response-loss, reload, back/forward, mobile, accessibility, and filesystem acceptance remain C-FV work. Operation memory intentionally disappears on reload; the next load returns to authoritative readiness.

## Next Authorization Recommendation

Keep 0D6-A and 0D6-B sealed. Authorize `0D6-C-FV` for browser and recovery verification; do not extend beyond C-FV.

