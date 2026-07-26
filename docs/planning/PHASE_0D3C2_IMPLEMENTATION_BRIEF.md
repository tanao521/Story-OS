# Phase 0D3C2 Implementation Brief

## Current authorization

0D3C2-A completed the required server hardening. 0D3C2-B and 0D3C2-C are
separately authorized as bounded UI/Run wiring phases only.

**0D3C2-A status: PASSED.** The consent, audit, idempotency, recovery, source,
budget, redaction, and public-profile foundations described below are now
implemented. 0D3C2-B is sealed and 0D3C2-C is the current controlled,
default-off Run phase.

## 0D3C2-A — Server Hardening (required first)

1. Eliminate body-supplied `project_root` for Live-capable routes and bind the
   selected project server-side.
2. Add a server-owned, public-safe profile projection and registry revision;
   disallow endpoint/model/provider overrides from client input.
3. Add an expiring consent ticket and append-only audit attempt record. Record
   safe scope, profile revision, ordered Personas, hard budget, consent text
   version/time, idempotency key, status, safe code, and usage completeness.
4. Add atomic idempotency/in-flight ownership keyed by consent + canonical
   request fingerprint. Include response-loss recovery and concurrency tests.
5. Remove/privilege-gate Live `force`; define `retry=0` and `fallback=none`.
6. Enforce server timeout/cancellation/reconciliation semantics and an explicit
   in-progress status.
7. Add a token/cost policy with provenance, hard ceiling, and unavailable
   representation where a reliable estimate cannot be made.
8. Strengthen redaction assertions across adapters, HTTP errors, persistence,
   and logs.

Exit evidence: fake-provider failure matrix, network canary, no duplicate
provider calls under duplicate/concurrent/recovery tests, no secret/path/raw
exception persistence, and protection checks unchanged.

## 0D3C2-B — Read-only Live Plan and Consent UI

The implementation uses `/static/simulator-live-consent.js`, safe profiles and
Persona options GETs, and one explicit consent POST. It keeps full ticket and
idempotency values in closure memory only, blocks profiles without an exact
input-token counter, and does not contain a Live Run endpoint in production
frontend source before C; Browser screenshots are not a gate for this phase.

## 0D3C2-C — Controlled Live Run

The C implementation adds a server capability projection and default-off Run
gate, a second explicit confirmation, one POST with a private idempotency
header, GET-only response-loss recovery, and final explicit Review handoff.
It must stop before 0D3C2-RC.

Only after 0D3C2-A/B pass, add one guarded execution action using the
idempotency key and consent ticket. There is no automatic retry/fallback. The
result updates only the explicit run URL and existing Review handoff.

## 0D3C2-RC — Safety closure

Use temporary projects and injected providers only for automation. Cover
timeout, rate limit, auth error, invalid output, partial success, all failure,
source change, missing/partial usage, concurrency, response loss, and
redaction. Confirm no real provider/token activity and that protected data
remains unchanged.

## Stop rule

0D3C2-A, B, B-FIX, and C are complete under their separate authorizations.
0D3C2-RC is now complete. The production capability remains default-off; the
RC authorization sealed safety behavior and did not authorize production Live
enablement or a subsequent phase.

RC added an in-process fault matrix and closed two bounded safety defects:
Panel-level results now retain a unanimous child safe provider error code, and
a completed response issued for an old context cannot hand off its Run into a
new project/timeline/chapter URL. Mixed failures remain the generic safe
`PROVIDER_ERROR`; cross-context completion remains recoverable through Saved
Runs without URL mutation.
