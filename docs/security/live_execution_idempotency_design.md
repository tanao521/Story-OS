# Live Execution Idempotency Design

## Boundary

The only public Live execution route is
`POST /api/reader-persona/model-panel/live/runs`. It accepts exactly a safe
`project_key`, server-issued `ticket_id`, and its matching opaque idempotency
key. It accepts no `force`, provider/model override, endpoint, credential,
budget override, project root, or source text.

All legacy Panel and single-Persona HTTP paths reject `mode=live` with
`LIVE_REQUIRES_CONSENT_TICKET` before resolving a project/provider. Their Mock
behavior remains unchanged.

## Atomic ownership

`LivePanelExecutionStore.reserve()` uses exclusive filesystem creation of
`data/simulator/live_panel_execution/ownership/{ticket_id}.json`. The order is:

```text
validate ticket + profile revision + source fingerprint
  -> atomically create ownership as in_progress
  -> append started audit
  -> execute exactly once
  -> atomically write final ownership state + append final audit
```

If reservation already exists, no provider execution is attempted. A duplicate
returns the same completed/failed state or the existing `in_progress` state.
The ownership record is deliberately separate from immutable ticket/audit
records because it is the single coordination record allowed to change.

## Recovery and crash rule

`GET /api/reader-persona/model-panel/live/status/{ticket_id}` requires the
matching `X-StoryOS-Idempotency-Key` header. It returns only ticket id, status,
panel execution id, safe error code, actual call count, usage completeness, and
update time. It contains no prompt, source text, path, endpoint, credential, or
raw exception.

If an `in_progress` ownership record has exceeded its reconciliation grace
period, status is reported as `reconciliation_required`; it is **not** retried.
An unexpected failure after ownership likewise becomes
`reconciliation_required`. This is intentionally conservative because the
provider may already have received a request.

## Evidence

`tests/test_phase0d3c2a_live_hardening.py` verifies sequential duplicate,
concurrent duplicate, response-loss recovery, stale in-progress reconciliation,
and exactly one injected fake-provider call. The test uses a temporary project
and socket canary only.
