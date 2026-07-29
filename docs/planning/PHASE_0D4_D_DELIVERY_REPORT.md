# Phase 0D4-D-RC1 — Delivery Report

> Status: **PASSED**
>
> Phase 0D4-D: **SEALED**
>
> Phase 0D4-E: **NOT ENTERED**

## Goal and root cause

RC1 closed five verification gaps left by the initial 0D4-D delivery:

1. projection and Context Binder documented different Branch State paths;
2. projection and Binder computed different state revisions;
3. operation replay was keyed by a mutable phase marker without a request
   fingerprint;
4. event/state read-modify-write was not arbitrated across service instances;
5. recovery and browser claims exceeded the artifacts/tests actually executed.

The single state authority is now:

```text
<ProjectRoot>/data/narrative_memory/state/{timeline_id}/{branch_id}/current.json
```

The single confirm operation authority is:

```text
<ProjectRoot>/data/narrative_turn/operations/{operation_id}.json
```

## Delivered files

### Production

```text
story-os-demo/core/contracts/narrative_turn.py
story-os-demo/system/narrative_turn_context.py
story-os-demo/system/narrative_turn_service.py
story-os-demo/system/narrative_turn_store.py
story-os-demo/web/narrative_turn_routes.py
story-os-demo/web/narrative_turn_wire.py
story-os-demo/web/static/simulator-narrative-turn.js
```

### Tests and browser fixture

```text
story-os-demo/tests/test_phase0d4d_rc1.py
story-os-demo/tests/test_phase0d4d_filesystem_diff.py
story-os-demo/tests/test_phase0d4d_frontend_contract.py
story-os-demo/tests/_rc1_browser_fixture_server.py
story-os-demo/tests/test_phase0d4a_narrative_turn_foundation.py
```

### Documents

```text
docs/planning/PHASE_0D4_A.md
docs/planning/PHASE_0D4_D.md
docs/planning/PHASE_0D4_D_DELIVERY_REPORT.md
docs/planning/PHASE_0D4_IMPLEMENTATION_BRIEF.md
```

`PHASE_0D4_A.md` and its contract test changed only to follow the unified
`data/narrative_turn/{record_type}/...` persistence layout.

## Implementation result

### State path and revision

- ProjectContext-root relative state path; no duplicate `project_id` segment.
- Shared canonical revision function used by projection and Binder.
- RC1 state envelope validates schema, complete scope, application list, and
  revision integrity.
- Projection is idempotent by Result fingerprint.
- Result `next_context_fingerprint` equals the rebound Binder fingerprint.

### Operation ID

- Immutable create-if-absent authority before side effects.
- Full scope + request fingerprint; custom action contributes SHA-256 only.
- Same request replays; different payload/branch/timeline conflicts.
- Separate project roots may reuse the same ID.
- Traversal is rejected and tampered scope fails closed.

### Concurrency

- Atomic Result create-if-absent remains the Turn first-writer claim.
- Same-operation calls serialize through an operation lock.
- Branch event allocation + state projection serialize through one branch
  transaction lock.
- Event chain collisions never adopt an unrelated winner.
- Transition collisions are treated as idempotent only after semantic match.

### Recovery

Recovery verifies or reconstructs:

```text
Result
Plan
Validation
transitions through previewed
confirmed transition
exact branch event
state application fingerprint
applied_to_branch transition
COMPLETED marker
```

An indeterminate or corrupt chain returns `CONFIRM_RECOVERY_REQUIRED`.

Ten fault points were actually parameterized; this is not a two-test proxy.

### Frontend

- Strict context/validation/preview/action freshness gate.
- Custom text changes invalidate old Validation, Preview, and pending
  operation ID.
- `pushState` no longer synthesizes `popstate`.
- null-safe post-success cleanup.
- successful confirm displays Result and flags, then rebinds Context without
  erasing the Result.
- double-click is guarded before the first await.
- transient/response-loss class failures retain operation ID; semantic 4xx
  conflicts discard it.
- Back/Forward and reload never auto-confirm.

## Real browser evidence

The browser run used real Chromium with isolated temporary projects and zero
external network.

Observed scenario groups:

1. allowed recommended confirm;
2. allowed-with-cost confirm;
3. custom action confirm;
4. blocked/inactive gate;
5. requires-clarification gate;
6. archived gate;
7. stale preview after text edit;
8. double-click single POST;
9. post-success Result/flags/cleanup/rebind;
10. Back/Forward and reload no-repeat;
11. completed-first-response-replaced-by-503, retry same operation ID;
12. random custom sentinel lifecycle and persistence scan.

The response-loss fixture recorded:

```text
confirm requests: 2
logical operation IDs: 1
operation authority records: 1
phase records: 1
Results: 1
events: 1
second response: idempotent replay
```

No browser Console warning/error was observed. Confirm traffic was POST and
confirm envelopes were `no-store`.

## Test results

### Focused

Command:

```text
python -m pytest \
  tests/test_phase0d4d_narrative_turn_service.py \
  tests/test_phase0d4d_confirm_routes.py \
  tests/test_phase0d4d_rc1.py \
  tests/test_phase0d4d_filesystem_diff.py \
  tests/test_phase0d4d_frontend_contract.py -v
```

Result:

```text
collected: 49
passed: 49
failed: 0
skipped: 0
warnings: 0
exit code: 0
```

### Related regression

Command:

```text
python -m pytest \
  tests/test_phase0d4a_narrative_turn_foundation.py \
  tests/test_phase0d4b_narrative_turn_planner.py \
  tests/test_phase0d4c_narrative_turn_routes.py \
  tests/test_phase0d4c_narrative_turn_wire_dto.py \
  tests/test_phase0d4c_narrative_turn_frontend_contract.py \
  tests/test_phase0d4c_context_navigator_integration.py -q
```

Result:

```text
collected: 483
passed: 483
failed: 0
skipped: 0
warnings: 0
exit code: 0
```

### Static / compile

```text
node checks: 3 passed, exit code 0
compileall: 5 files passed, exit code 0
```

### Non-additive categories

```text
fault-injection cases: 10
concurrency cases: 2
filesystem diff cases: 1
browser scenario groups: 12
```

Category labels overlap; they are not additive to pytest collected counts.

## Security boundary audit

```text
Provider calls: 0
External network: 0
Canon writes: 0
Chroma writes: 0
Vector index calls: 0
Global NarrativeMemory migration: 0
Branch lifecycle mutation during confirm: 0
Chapter compilation: 0
Raw custom action persistence: 0
Real project writes: 0
New dependencies: 0
Git write operations: 0
```

The random raw sentinel was absent from URL, reloaded DOM, server output,
exceptions, Console, Result, Plan, Validation, transitions, operation
authority/phase, event journal, state projection, backup state, and all
isolated fixture files. Only its SHA-256 persisted.

## Final acceptance

```text
Phase 0D4-D-RC1: PASSED
Phase 0D4-D: SEALED
State projection authority: VERIFIED
Post-confirm Context rebind: VERIFIED
Operation-ID authority: VERIFIED
Result first-writer-wins: VERIFIED
Branch event concurrency: VERIFIED
Forward recovery at all 10 fault points: VERIFIED
Full browser confirmation E2E: PASSED
Custom-action browser sentinel: PASSED
Expected-only filesystem diff: PASSED
Raw custom text persistence: 0
Canon writes: 0
Chroma writes: 0
Provider calls: 0
Phase 0D4-E: NOT ENTERED
```
