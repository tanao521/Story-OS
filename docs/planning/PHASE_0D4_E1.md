# Phase 0D4-E1 — Branch Lifecycle HTTP API, Idempotency & Registry Transaction Safety

> Status: **SEALED** (RC2)
>
> Phase 0D4-E1: **IMPLEMENTED / VERIFIED**
>
> Phase 0D4-E2: **NOT ENTERED / NOT AUTHORIZED**
>
> Phase 0D4-E3: **NOT ENTERED / NOT AUTHORIZED**

## Scope

E1 implements only Branch lifecycle HTTP operations and registry transaction
safety. It does not migrate NarrativeMemory, modify retrieval entry points,
open Chroma, re-index vectors, write Canon, call providers, or redesign the
product UI.

## HTTP endpoints

| Method | Endpoint | Behavior |
|---|---|---|
| GET | `/api/narrative-branches?project_id=&timeline_id=` | Lists branches and registry active pointer |
| GET | `/api/narrative-branches/{branch_id}?project_id=&timeline_id=` | Returns one branch projection |
| POST | `/api/narrative-branches/create` | Creates an open, inactive branch |
| POST | `/api/narrative-branches/select` | Selects an open branch as active |
| POST | `/api/narrative-branches/archive` | Archives inactive branch or atomically moves active pointer to an open replacement |
| POST | `/api/narrative-branches/restore` | Restores archived → open without auto-select |

All responses use the safe envelope and `Cache-Control: no-store`. Error
responses do not expose paths, fingerprints, lock details, tracebacks, or raw
request text.

## Authority and transaction model

- Registry authority remains `data/branches/{timeline_id}/registry.json`.
- Registry and lifecycle journals remain append-only and rebuildable.
- Operation authority is `data/branch_operations/{operation_id}.json`.
- The immutable operation authority is `data/branch_operations/{operation_id}.json`;
  mutable progress is isolated in `{operation_id}.phase.json`.
- Phase scope and canonical fingerprint are checked against the authority on
  every retry; mismatches fail closed.
- A project/timeline lock is an atomic directory under
  `data/branch_operations/.locks/`; different timelines can proceed in
  parallel.
- Lock ownership records PID plus nonce; dead owners can be reclaimed and a
  live owner cannot be removed by another process.
- Operation claims happen before Branch Store side effects and include a
  canonical request fingerprint.
- Replaying the same operation and payload is idempotent. Reusing an operation
  ID with a different payload returns `409 OPERATION_ID_CONFLICT`.

## Lifecycle semantics

- `lifecycle_status` and `activity` are separate dimensions.
- Create never auto-selects a branch.
- Select never changes lifecycle status.
- Archived branches cannot be selected.
- Active archive requires a different open replacement in the same
  project/timeline; replacement becomes active before the target is archived.
- Restore changes only archived → open and never auto-selects.
- Repeated archive/restore operations do not append duplicate lifecycle events.

## Changed files

- `story-os-demo/system/narrative_branch_lifecycle_service.py`
- `story-os-demo/system/narrative_branch_store.py`
- `story-os-demo/core/contracts/narrative_turn.py`
- `story-os-demo/web/narrative_branch_routes.py`
- `story-os-demo/web/narrative_branch_wire.py`
- `story-os-demo/web/app.py`
- E1 tests under `story-os-demo/tests/test_phase0d4e1_*.py`
- RC2 evidence: `docs/planning/PHASE_0D4_E1_RC2.md` and its delivery report.

## Explicit boundaries

```text
NarrativeMemory migration: NOT ENTERED
Chroma mutation: 0
Retrieval changes: 0
Canon writes: 0
Provider calls: 0
Phase 0D4-E2: NOT ENTERED
Phase 0D4-E3: NOT ENTERED
```
