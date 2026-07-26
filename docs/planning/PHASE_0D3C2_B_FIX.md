# Phase 0D3C2-B-FIX — Consent State Integrity Closure

## Result

**PASSED.** This repair closes four front-end state-integrity gaps in the
read-only Live Plan/Consent surface. It does not add execution capability and
does not enter 0D3C2-C.

## Fixes

- Live entry now remains disabled until the authoritative Context Navigator
  projection confirms project, timeline, chapter, and source availability.
  URL-only values cannot enable the entry; the disabled reason is visible and
  screen-reader readable.
- A single `invalidateConsent()` path aborts in-flight consent work, advances
  the generation, clears the private ticket/key state and result, unchecks
  consent, and marks the review as invalidated whenever context, Persona,
  profile, or requested call limit changes.
- Server `expires_at` is the only expiry authority. A bounded local timer,
  visibility recheck, dialog reopen check, invalid-date rejection, and expiry
  cleanup prevent an old opaque ticket from remaining usable. No renew,
  status, or automatic POST is issued.
- Successful consent immediately unchecks the checkbox and leaves submission
  disabled for the same selection fingerprint. A separate “Start a new
  consent review” action is required before a new explicit confirmation can
  create another ticket.

## Safety boundary

No Provider, network model request, token use, Live Run endpoint, backend
change, Mock change, Review renderer change, storage, URL, clipboard, console,
dependency installation, browser screenshot, commit, push, reset, clean, or
rebase was performed.

## Validation

- B-FIX focused tests: **30 passed**.
- Node syntax check for `simulator-live-consent.js`: passed.
- Existing B/A/preflight/0D3B1 focused regressions: passed.
- Production frontend scan for Live Run endpoint: none.
- Protected data remains unchanged: Chroma 6/6, authority assets 16,
  Obsidian bindings 30, real model/panel runs 0/0.

## Stop rule

0D3C2-B-FIX is complete. 0D3C2-B is PASSED AND SEALED. Stop before 0D3C2-C.
