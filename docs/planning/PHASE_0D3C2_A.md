# Phase 0D3C2-A — Live Server Hardening

## Result

**PASSED.** The dormant Live path is now server-gated and remains unavailable
from the Mock-only production UI. This phase does not enter 0D3C2-B.

## Implemented hardening

- Added immutable server-owned `LiveExecutionConsentTicket`, safe public
  profile projection, registry revision, budget policy, append-only attempt
  audit, and recovery state contracts.
- Added atomic `O_EXCL` ticket ownership before provider work. Duplicate,
  concurrent, refresh, and response-loss requests reuse the same ownership and
  never start a second provider call.
- Rejected all Live requests through legacy single/Panel routes with
  `LIVE_REQUIRES_CONSENT_TICKET`. The new Live routes require only `project_key`
  plus a server-issued ticket/key. Body/query `project_root` is rejected from
  every Live-capable route.
- Public Live `force` is forbidden. Internal legacy `force` remains outside the
  public Live flow and is retained only for compatibility/testing.
- Added server-owned call/output/input/total token policies, timeout, retry
  `0`, fallback `none`, and explicit unavailable cost (`null`, never zero).
- Added exact provider token-counter gate before Live provider calls; adapters
  without that capability block safely before network/provider execution.
- Bound consent to source/context hashes and revalidated both before ownership
  and before every sequential child call. A mid-run change blocks later
  children; no Plan-A/Run-B source substitution occurs.
- Added truthful cancellation/reconciliation states. Cancellation before
  ownership prevents a call; a later request is only `cancel_requested`.

## New server endpoints (no UI caller)

```text
GET  /api/reader-persona/live/profiles
POST /api/reader-persona/model-panel/live/consent
POST /api/reader-persona/model-panel/live/runs
POST /api/reader-persona/model-panel/live/cancel
GET  /api/reader-persona/model-panel/live/status/{ticket_id}
```

The status route requires `X-StoryOS-Idempotency-Key`, rather than placing the
key in a deep-link URL. All responses are safe projections only.

## Changed implementation

- `story-os-demo/core/contracts/live_panel_execution.py`
- `story-os-demo/system/live_panel_execution_store.py`
- `story-os-demo/system/live_panel_execution_service.py`
- existing model/persona contracts, Panel execution/store, child execution,
  HTTP routes, API README, and focused tests.

## Safety boundary

No Live UI, browser acceptance gate, real Provider call, network request,
credential value read/print, token consumption, user-project Run, Story/Canon/
Summary write, Chroma/Obsidian operation, dependency installation, commit,
push, reset, clean, or rebase was performed.

The test-only fake provider and socket canary use temporary projects. They do
not use the user project or any external endpoint.

## Stop rule

0D3C2-A is complete. Stop here; 0D3C2-B requires separate authorization.
