# Live Execution RC Evidence

## Verdict

Phase 0D3C2-RC passed its safety-critical gates on 2026-07-23. Production Live
capability remains default-off. All execution tests used temporary projects and
in-process injected providers; no real Provider, socket/HTTP request,
credential read, or token consumption was authorized or observed.

## Fault and state matrix

The RC matrix covers successful output, timeout, rate limit, authentication
failure, generic failure, invalid JSON, schema-invalid output, grounding-invalid
output, missing usage, partial usage, partial Panel success, and all-child
failure. Existing A safety tests additionally cover source mutation before
ownership and after the first child, blocking/concurrent duplicate requests,
ticket expiry, profile-registry drift, cancellation, stale ownership, and
GET-only reconciliation.

Assertions establish:

- each uncached child makes exactly one provider call; there is no retry or
  fallback;
- timeout/rate-limit/auth failures persist only their safe codes;
- partial Panels preserve successful children and failed child codes;
- all-failed Panels never report completed or ready;
- invalid raw output is not persisted;
- missing/partial usage remains nullable and `partial`; cost remains absent;
- sequential duplicate, concurrent duplicate, completed/failed replay, and
  response-loss recovery return the same ownership/final Run with no extra
  provider call;
- source/profile/expiry failures before ownership make zero provider calls;
- stale in-progress ownership becomes `reconciliation_required` and never
  retries.

## Redaction and private state

The sentinel set `secret-key-sentinel`, `endpoint-sentinel`,
`prompt-sentinel`, `chapter-sentinel`, `exception-sentinel`, and
`path-sentinel` was injected into provider exceptions/raw output. Every
temporary JSON record was scanned; no sentinel persisted. The production
module uses no local/session storage, console logging, clipboard, hidden input,
or public global for ticket/idempotency values. Only the validated final
`panel_execution_id` may enter history, and only while the issued scope remains
current.

## Capability and network protection

Absent configuration and the values empty, `0`, `false`, `off`, `no`, and an
unknown string all project disabled. Only explicit server-side true values can
enable a test-scoped fake Live path. The Run route checks the server capability
before project/provider resolution. Request bodies, URL parameters, and browser
storage cannot enable it. Socket creation/connect were canaried in RC tests.

## Verification results

- Direct RC/A/C/Panel/Review safety set: **50 passed**.
- Complete relevant 0D2/0D3, web/route/static/context set: **302 passed**.
- `node --check web/static/simulator-live-consent.js`: passed.
- `python -m compileall -q core system web`: passed.
- Full repository test was attempted once as required, but the execution
  environment terminated it at 123 seconds before pytest produced a final
  summary. It was not rerun; no full-suite-green claim is made.
- Browser smoke was not run; RC browser evidence was optional and no screenshot
  was created.

## Protected-data comparison

The recorded 0D2B1 integrity manifest still matches all six Chroma files and
all sixteen authority-source assets by SHA-256. Obsidian bindings remain 30.
The real project contains model/panel Run JSON 0/0 and Live ticket/audit/
ownership JSON 0/0/0. `STORYOS_LIVE_EXECUTION_UI_ENABLED` is absent from the
parent environment. No novel, Canon, Summary, Chroma, Obsidian, production
configuration, or real execution record was written.
