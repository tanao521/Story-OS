# Phase 0D3C2-C — Controlled Live Run Wiring (Default-Off)

## Result

**PASSED.** The Live Consent surface now has a controlled execution handoff,
but production capability remains disabled by default. This phase stops before
0D3C2-RC.

## Implemented

- Added server-owned `live_execution_ui_enabled` capability projection with a
  safe `LIVE_EXECUTION_DISABLED` response. URL, storage, client state, and
  request bodies cannot enable execution.
- Added a second unchecked-by-default confirmation and an exact action:
  `Execute one Live Panel Run`.
- Added one-shot Run POST with only `project_key` and `ticket_id` in the body
  plus `X-StoryOS-Idempotency-Key` header. No provider/model/endpoint/path,
  credential, prompt, force, retry, fallback, or budget override is sent.
- Added private response-uncertain handling and user-triggered GET-only
  recovery. Recovery never sends another Run POST and surfaces
  `reconciliation_required` without retry.
- Added final safe handoff: clear opaque ticket/key, refresh Saved Runs, and
  write only a validated `panel_execution_id` into the explicit Review URL.
  Review failure cannot trigger another POST or automatic fallback.
- Preserved B-FIX context/selection invalidation, expiry, Mock semantics, and
  authoritative/model separation.

## Safety boundary

Automatic validation uses only temporary projects, injected fake providers,
exact token counters, and network canaries. No real Provider, external network,
real token/cost, user-project Run, ticket/audit/ownership, story/Canon/Summary,
Chroma, or Obsidian mutation was performed.

## Validation

- C/B/A/Web focused regression set: passed.
- Node syntax and compileall: passed.
- Production frontend scan: Live Run endpoint is present only in this
  controlled module; no credential/path/unsafe DOM injection is present.
- Protected-data comparison remains Chroma 6/6, authority assets 16,
  Obsidian bindings 30, real model/panel runs 0/0.
- Browser smoke is optional and not a gate; no screenshot RC was created.

## Stop rule

0D3C2-C is complete. Do not enter 0D3C2-RC.
