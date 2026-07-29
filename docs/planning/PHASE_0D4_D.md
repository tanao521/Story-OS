# Phase 0D4-D — Transactional Turn Confirmation, Branch Event Journal, State Projection & Recovery

> Status: **SEALED**
>
> Phase 0D4-D-RC1: **PASSED**
>
> Phase 0D4-E: **NOT ENTERED / NOT AUTHORIZED**

## 1. RC1 authority decisions

### 1.1 Branch state

`ProjectContext.root` is one physical project root. The only Branch State
authority is therefore:

```text
<ProjectRoot>/data/narrative_memory/state/{timeline_id}/{branch_id}/current.json
```

`project_id` is not repeated in the relative path. The state envelope contains
`schema_version`, project/timeline/branch scope, narrative fields, deterministic
`revision`, application metadata, and `applied_result_fingerprints`.

The revision authority hashes narrative content while excluding self-reference
and mutable envelope metadata:

```text
revision
updated_at
last_applied_turn_id
last_event_sequence
last_result_fingerprint
applied_result_fingerprints
```

The Binder uses the stored revision only after validating the RC1 envelope,
scope, and recomputed revision. Tampered RC1 state fails closed as
`BRANCH_STATE_INVALID`. Legacy pre-RC1 state remains readable until its first
projection.

Post-confirm closure is:

```text
Binder R0
→ confirm
→ projection R1
→ same Binder reads R1 + applied delta
→ rebound context_fingerprint == Result.next_context_fingerprint
```

### 1.2 Operation ID

The confirm operation authority is project-root global:

```text
<ProjectRoot>/data/narrative_turn/operations/{operation_id}.json
```

It is immutable and created before confirmation side effects. It stores the
complete scope and canonical request fingerprint. Raw custom text is never
stored; only its SHA-256 participates in the request fingerprint.

Rules:

- same project + same operation ID + same request → replay;
- same project + same operation ID + different payload/scope → 409
  `OPERATION_ID_CONFLICT`;
- different project roots may reuse an operation ID;
- traversal or path separators are rejected;
- authority/phase scope mismatch fails closed.

The mutable phase marker is:

```text
<ProjectRoot>/data/narrative_turn/operations/{operation_id}.phase.json
```

It is recovery progress, not the authority for whether an artifact exists.

### 1.3 Turn artifacts

```text
data/narrative_turn/plans/{timeline_id}/{branch_id}/{turn_id}.json
data/narrative_turn/validations/{timeline_id}/{branch_id}/{validation_id}.json
data/narrative_turn/results/{timeline_id}/{branch_id}/{turn_id}.json
data/narrative_turn/transitions/{timeline_id}/{branch_id}/{turn_id}/{sequence:08d}.json
data/narrative_turn/events/{timeline_id}/{branch_id}/{sequence:08d}.json
data/narrative_turn/operations/{operation_id}.json
```

Result publication remains true create-if-absent (`tempfile + fsync + os.link`).
Different operations racing for the same Turn produce one winner and one 409
`TURN_ALREADY_CONFIRMED`.

## 2. Concurrency

Confirmation uses project-local cross-service/process arbitration:

- operation lock serializes same-operation replay and phase progression;
- branch transaction lock covers event sequence allocation and state
  projection as one unit;
- immutable Result publication remains the first-writer-wins Turn claim;
- transition collision is accepted only after semantic winner verification.

Two service instances confirming different Turns on one Branch produce a
single unbroken event fingerprint chain, unique contiguous sequence numbers,
two retained Results, and two recorded state applications.

## 3. Recovery phase authority

```text
PRECHECK_COMPLETE
RESULT_CLAIMED
TURN_CHAIN_PERSISTED
CONFIRMED_TRANSITION_APPENDED
BRANCH_EVENT_APPENDED
STATE_PROJECTED
APPLIED_TRANSITION_APPENDED
COMPLETED
```

`TURN_CHAIN_PERSISTED` owns Plan + Validation + transitions through
`previewed`. `CONFIRMED_TRANSITION_APPENDED` alone owns
`previewed → confirmed`.

Recovery checks the real Result, Plan, Validation, transition chain, exact
branch event, projected state application set, and applied transition. Missing
deterministic artifacts are repaired forward from the raw-text-free precheck
bundle. Duplicate, corrupt, or indeterminate artifacts return 409
`CONFIRM_RECOVERY_REQUIRED`.

## 4. Fault matrix

One parameterized case was executed for every point:

1. after Result publish;
2. after Plan append;
3. after Validation append;
4. after previewed transition;
5. after confirmed transition;
6. after branch event append;
7. before projection replace;
8. after projection replace;
9. after applied transition;
10. before completed marker.

Every case restarts with a new service instance, retries the same operation ID,
and verifies one Plan, one Validation, one Result, one event, one confirmed
transition, one applied transition, one state application, `COMPLETED`, the
same Result, and `recovery_performed=true`.

## 5. Browser confirmation

A real Chromium session against isolated fixtures verified:

- allowed recommended confirm;
- allowed-with-cost confirm (`partial`);
- custom action confirm;
- blocked, requires-clarification, inactive, and archived gates;
- stale custom action invalidates old Validation/Preview and disables confirm;
- double-click emits one confirm POST;
- a completed request whose first response is replaced by transient 503 keeps
  and reuses the same operation ID; retry returns idempotent replay;
- Result summary and consequence flags render;
- old Validation/Preview clear;
- Context Binder rebind reads the projected revision;
- Back/Forward and reload do not confirm again;
- confirm uses POST;
- success and error responses use `Cache-Control: no-store`;
- no unhandled browser Console warning/error was observed.

Random custom sentinel:

```text
D_RC1_BROWSER_SENTINEL_1785027850990_05ed394ef39228
```

The raw sentinel was present only in the textarea/current request memory. It
was absent from URL, reloaded DOM, and all isolated fixture files. The
persisted SHA-256 appeared in Validation, Result, operation recovery bundle,
event-derived state, and no raw text appeared.

## 6. Filesystem diff

The manifest test executes recommended confirm, custom confirm, idempotent
replay, competing operation, and injected recovery. Changed files are limited
to:

```text
data/narrative_turn/plans/
data/narrative_turn/validations/
data/narrative_turn/results/
data/narrative_turn/transitions/
data/narrative_turn/operations/
data/narrative_turn/events/
data/narrative_memory/state/{timeline_id}/{branch_id}/current.json
data/narrative_memory/state/{timeline_id}/{branch_id}/current.bak
```

Canon, Chroma/vector data, branch registry/lifecycle journal, legacy global
NarrativeMemory, planning sources, source versions, and unrelated branches do
not change.

## 7. Validation evidence

### Static / compile

```text
node --check web/static/simulator-narrative-turn.js
node --check web/static/simulator-context-navigator.js
node --check web/static/app.js
python -m compileall -q \
  system/narrative_turn_service.py \
  system/narrative_turn_context.py \
  system/narrative_turn_store.py \
  web/narrative_turn_routes.py \
  web/narrative_turn_wire.py
```

Result: all exit code 0.

### Focused pytest

```text
collected: 49
passed: 49
failed: 0
skipped: 0
warnings: 0
exit code: 0
```

### Related 0D4-A/B/C regression

```text
collected: 483
passed: 483
failed: 0
skipped: 0
warnings: 0
exit code: 0
```

### Category counts

```text
fault-injection cases: 10
concurrency cases: 2
filesystem diff cases: 1
browser scenario groups: 12
```

Category labels overlap with focused pytest and browser observations; they are
not additive.

## 8. Final state

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
