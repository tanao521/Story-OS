# Phase 0D6-C-B — Explicit Start Action & Durable Context Rebind

Status: PASSED — READY FOR 0D6-C-FV AUTHORIZATION  
Date: 2026-07-28  
Authority: 0D6-A PASSED & SEALED; 0D6-B PASSED & SEALED; 0D6-C-A PASSED

## Purpose

Extend the C-A Simulator-only readiness surface with exactly one explicit READY action. The action freezes the sealed request snapshot, creates one in-memory operation ID, calls the sealed durable start route, safely handles replay/response loss, validates the durable result, and rebinds to the server-owned successor initial Turn.

## RC1 status

RC1 owns the post-start successor convergence correction. The progression module now releases readiness ownership while the authoritative Simulator read model reports an active successor Turn; the sealed readiness route remains the completion authority. See `PHASE_0D6_C_B_RC1.md` for the focused scope and evidence.

## Authority boundary

- The only new mutation call is `POST /api/chapter-progression/start-turn`.
- The browser never creates successor chapters, plans, transitions, files, branches, candidates, reviews, commits, Canon, Chroma, or Obsidian records directly.
- No backend, schema, sealed service, provider, dependency, or configuration file was changed.
- Start is never automatic on page load, readiness refresh, completion, context change, retryable state entry, or mode return.
- Recommended actions are not confirmed automatically; the successor Turn stops at `awaiting_action`.

## Legacy action audit

The earlier completion control (`data-start-next-chapter`) is implemented by `simulator-candidate-review.js::nextChapter()`, which only pushes an existing simulator URL using the advisory read model. It does not create a successor or call a write route. C-B marks it as legacy navigation and hides it whenever a valid progression context is available, making the progression surface the only same-level primary entry. The sealed start route is not duplicated.

## Start control contract

The progression panel renders exactly one `data-progression-start` button. It is visible only when all of the following are true:

```text
mode == simulator
state == READY
readiness_code == READY_TO_START_TURN
ready_to_start_turn == true
scope matches current context
successor_chapter_id present
authority_fingerprint is a 64-hex server value
```

The READY copy states that starting creates the initial action plan and does not confirm an action. `TURN_ALREADY_STARTED` uses the existing C-A continuation control and never displays or calls the start action.

## State machine extension

C-A states remain unchanged. C-B adds:

```text
STARTING
STARTED
START_RETRYABLE_ERROR
START_TERMINAL_ERROR
```

- `STARTING`: primary control disabled; one active request and frozen snapshot.
- `STARTED`: durable response validated; old readiness invalidated; server-owned successor rebind begins.
- `START_RETRYABLE_ERROR`: ambiguous network/timeout/unreadable response; same intent can retry with the same snapshot and operation ID.
- `START_TERMINAL_ERROR`: explicit conflict, corruption, malformed/mismatched response, or other safe terminal failure; current intent is cleared and no blind POST retry occurs.

## Operation ID lifecycle

1. The first explicit READY click creates one UUID (with a regex-safe fallback).
2. The ID is held only in the progression module memory.
3. Double click, keyboard repeat, and same-intent retry reuse the same ID and frozen body.
4. Context/mode change, readiness drift, operation conflict, corruption, terminal success, or rebind completion clears the intent.
5. No localStorage/sessionStorage, URL, hidden input, or browser authority stores the ID.

## Frozen request snapshot

The request is frozen from the current readiness DTO before the first POST:

```json
{
  "operation_id": "client-generated-id",
  "project_id": "authoritative project",
  "timeline_id": "main",
  "branch_id": "authoritative branch",
  "previous_chapter_id": 1,
  "successor_chapter_id": 2,
  "expected_readiness_fingerprint": "server authority fingerprint"
}
```

Retries serialize the identical frozen object. The client never recomputes the fingerprint or derives the successor.

## Response-loss replay

An unreadable body, fetch/network failure, timeout-like failure, or ambiguous 5xx enters `START_RETRYABLE_ERROR`. The UI retains the frozen intent and offers a clearly labelled safe retry. The retry submits the same operation ID and field-equivalent body. A parseable safe error is handled by its code; it is not blindly retried.

## Safe error mapping

| Code | Result |
|---|---|
| `OPERATION_CONFLICT` | terminal error; clear intent; allow readiness recheck |
| `TURN_START_READINESS_CHANGED` | stale; clear intent; fresh readiness GET |
| `TURN_START_SOURCE_CHANGED` | stale; clear intent; fresh readiness GET |
| `CORRUPT_OPERATION` | terminal error; fail closed; no automatic POST |
| `TURN_ALREADY_STARTED` | clear intent; fresh readiness GET converges to `EXISTING_TURN` |
| blocked/recovery/corrupt authority codes | preserve sealed presentation and no blind start |
| network/unreadable/ambiguous transport | retryable error; same intent only |
| unknown explicit code | terminal error; never treated as success |

## Response validation

Before any rebind, the durable result must match the frozen project, main timeline, branch, previous chapter, authoritative successor, operation ID, readiness fingerprint, and include a Turn ID with `turn_status == "awaiting_action"`. Missing, malformed, mismatched, or stale results enter `START_TERMINAL_ERROR` and do not navigate.

## Context race contract

The start intent is bound to the original context key and epoch. A project, branch, chapter, timeline, or mode change during POST clears the local intent and prevents the old response from rendering or rebinding the new context. The server operation may continue; aborting the browser fetch is not treated as server rollback. Returning to the old context performs a fresh readiness GET and never auto-replays.

## Context rebind and convergence

On a validated durable success, the module aborts obsolete readiness work, invalidates the old epoch, and calls `StoryOSContextNavigator.rebind()` with only server-returned successor and Turn identities. The existing Narrative Turn workspace then loads the successor context and initial plan through its existing GET paths. Focus moves to the successor Turn heading/workspace. The same rebind helper is used for C-A existing-Turn continuation, C-B success, and C-B replay success.

## Reload limitation

Operation memory is intentionally not persisted. Reloading loses the client intent and returns through C-A readiness GET. The server's durable state therefore determines `TURN_ALREADY_STARTED`, READY, or recovery status; the browser never guesses an old operation ID.

## Traditional isolation

Traditional mode has no progression start control or listener, creates no operation ID, and sends zero progression POSTs. Pending Simulator responses are ignored after the mode gate clears the intent.

## Accessibility and mobile

- Pending state uses `aria-busy="true"`, a readable live status, and a disabled 44px-capable primary control.
- Retry and terminal messages are explicit text and focusable via the existing status/control semantics.
- Success focus targets the successor Turn heading, falling back to the workspace.
- 320–480px layouts keep the primary action full width without horizontal scrolling.
- Reduced-motion and visible keyboard focus rules remain in the C-A stylesheet.

## Filesystem and authority boundary

Only the sealed backend start service can create the durable claim, phase, result, one initial Turn plan, and sequence-0 transition. The browser creates no operation artifact and performs no direct filesystem or data write.

## Test matrix

Static C-B tests cover explicit-click reachability, no auto-start, frozen snapshot, single-flight, same-ID retry, response-loss classification, safe errors, response validation, context races, rebind, legacy gating, Traditional isolation, and accessible control wiring. Existing 0D6-B authority/FV, Narrative Turn, context, Traditional, 0D5, and static-path tests remain green.

## Browser gate

Chromium smoke is recommended but not claimed in C-B. Formal browser, accessibility, response-loss, reload, and mobile acceptance remain 0D6-C-FV.

## Accepted limitations and non-goals

No automatic start, automatic retry, action confirmation, prose generation, Candidate/Review/Commit, non-main timeline support, provider call, sealed backend change, or C-FV browser seal is included.

## C-FV authorization gate

C-B is complete and safe to advance to `0D6-C-FV AUTHORIZATION`.
