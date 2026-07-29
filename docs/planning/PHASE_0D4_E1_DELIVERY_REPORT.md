# Phase 0D4-E1 Delivery Report

> Phase 0D4-E1-RC2: **PASSED**
>
> Phase 0D4-E1: **SEALED**
>
> Branch Lifecycle HTTP API: **IMPLEMENTED**
>
> Branch operation idempotency: **VERIFIED**
>
> Registry cross-process arbitration: **VERIFIED**

## 1. HTTP endpoint inventory

Implemented in `story-os-demo/web/narrative_branch_routes.py` and registered
by `story-os-demo/web/app.py`:

```text
GET  /api/narrative-branches
GET  /api/narrative-branches/{branch_id}
POST /api/narrative-branches/create
POST /api/narrative-branches/select
POST /api/narrative-branches/archive
POST /api/narrative-branches/restore
```

The DTO exposes only JSON-safe branch identity, lifecycle, activity, registry
revision, operation id, active pointer, replay, and recovery fields.

## 2. Store / service call graph

```text
HTTP route
  -> BranchLifecycleService
       -> project/timeline/id validation
       -> operation authority claim
       -> project/timeline registry lock
       -> NarrativeBranchStore.create/select/archive/restore
       -> operation phase + completion marker
       -> BranchWireDTO
```

No route calls NarrativeMemory, vector, Canon, Provider, or Turn confirmation
services.

## 3. Operation authority

Each request claims `data/branch_operations/{operation_id}.json` using atomic
create-if-absent. The record contains schema version, operation ID/type,
project/timeline/target scope, expected registry revision, canonical request
fingerprint, and timestamps. Mutable phase data is isolated in the sibling
`.phase.json` file. Raw user text is not accepted or stored by this API.

Replay behavior:

- same project root + operation ID + same payload: successful idempotent replay;
- same operation ID + different payload/scope: `409 OPERATION_ID_CONFLICT`;
- operation IDs reject separators, `..`, and path traversal forms;
- different project roots may reuse the same operation ID.

## 4. Registry transaction lock

`BranchLifecycleService` uses an atomic-directory lock keyed by
`project_id:timeline_id`. The lock covers claim, expected revision validation,
Branch Store mutation, and completion publication. Different timelines use
different locks. Ownership is recorded as PID plus nonce; dead owners are
reclaimed, live owners are never removed by a competitor, and final cleanup
requires the matching owner tuple. Lock timeout fails safely with
recovery-required semantics.

## 5. Lifecycle and recovery phases

Create and select publish operation phases before completion. Archive reuses the
existing Branch Store active-replacement recovery path and the same external
operation ID. Restore records lifecycle publication and completion. A retry
checks durable branch/registry artifacts rather than trusting only the phase
marker.

## 6. Persistent path inventory

E1 writes only:

```text
data/branches/{timeline_id}/...
data/branch_operations/...
```

It does not write `data/narrative_memory/`, `data/narrative_turn/`,
`data/chroma/`, Canon, planning, source versions, or real project data during
the temporary-project tests.

## 7. Concurrency evidence

Temporary-root tests verified:

- competing create operations produce one branch identity and one safe loser;
- distinct timelines progress concurrently;
- active archive replacement leaves the active pointer on an open branch;
- stale expected revision returns `409 REGISTRY_REVISION_CONFLICT`;
- repeated lifecycle requests do not duplicate lifecycle events.

## 8. Fault / recovery matrix

| Scenario | Verification |
|---|---|
| operation claim then retry | same authority is reused |
| phase marker missing | durable completed authority replays successfully |
| active archive replacement | existing Store multi-phase recovery is reused |
| repeated archive | no duplicate lifecycle event |
| repeated restore | no duplicate lifecycle event |
| operation payload collision | safe 409 conflict |

## 9. Filesystem diff

E1 temporary operations produced only `data/branches/` and
`data/branch_operations/`. No NarrativeMemory, Turn, Chroma, Canon, planning,
source-version, provider, or real-project writes were observed.

## 10. Tests and arithmetic

Focused E1-RC1 suite (including real multi-process tests and the four-point
fault matrix):

```text
python -m pytest tests/test_phase0d4e1_branch_routes.py \
  tests/test_phase0d4e1_branch_operations.py \
  tests/test_phase0d4e1_branch_concurrency.py \
  tests/test_phase0d4e1_branch_recovery.py \
  tests/test_phase0d4e1_branch_process.py \
  tests/test_phase0d4e1_frontend_contract.py -q

33 passed in 15.72s
```

Related regression/security suite:

```text
python -m pytest tests/test_phase0d4a_narrative_turn_foundation.py \
  tests/test_phase0d4d_rc1.py tests/test_phase0d4d_filesystem_diff.py \
  tests/test_real_data_protection.py tests/test_static_path_guard.py -q

166 passed in 23.94s
```

Python compilation of all changed Python modules passed. No browser run was
needed because the existing UI was not modified; the frontend contract test
records that E1 keeps URL browsing distinct from active mutation.

## 11. Git status

No Git write operation was performed. Existing D-RC1 changes and the user's
`.rc3_ibr/` directory were preserved. E1 additions are unstaged.

## 12. E2 / E3 boundaries

E2 remains unauthorized: no NarrativeMemory migration, no legacy copy, no
branch-aware event schema, and no retrieval changes were made.

E3 remains unauthorized: no Chroma access, metadata mutation, re-index,
legacy-vector removal, or query filter changes were made.

## 13. Model / reasoning / Agent usage

```text
Model: Luna
Reasoning: medium
Agents: single agent
External network/provider calls: 0
```

## Final verdict

```text
Phase 0D4-E1-RC1: PASSED
Phase 0D4-E1: SEALED
Branch lifecycle HTTP API: IMPLEMENTED
Branch operation idempotency: VERIFIED
Registry cross-process arbitration: VERIFIED (real processes)
Create/select/archive/restore recovery: VERIFIED
Active and lifecycle dimensions: VERIFIED
Active archive replacement: VERIFIED
Path containment: VERIFIED
Expected-only filesystem writes: VERIFIED
NarrativeMemory migration: NOT ENTERED
Chroma mutation: 0
Canon writes: 0
Provider calls: 0
Phase 0D4-E2: NOT ENTERED
Phase 0D4-E3: NOT ENTERED
```
