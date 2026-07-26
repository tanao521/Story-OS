# Phase 0D4-D — Transactional Turn Confirmation, Branch Event Journal, State Projection & Recovery

> Status: **PASSED**
>
> Phase 0D4-P: PASSED
> Phase 0D4-A: SEALED
> Phase 0D4-B: SEALED
> Phase 0D4-C-P: SEALED
> Phase 0D4-C-RC1: ACCEPTED WITH RC2/RC3 CLOSURE
> Phase 0D4-C-RC2: ACCEPTED WITH RC3 CLOSURE
> Phase 0D4-C-RC3: PASSED
> Phase 0D4-C: SEALED
> Phase 0D4-D: PASSED
> Transactional Turn confirmation: IMPLEMENTED
> Idempotent operation replay: VERIFIED
> Concurrent confirmation first-writer-wins: VERIFIED
> Forward recovery: VERIFIED
> Branch-local event journal: VERIFIED
> Branch-local state projection: VERIFIED
> Turn lifecycle through applied_to_branch: VERIFIED
> Turn confirmation UI: IMPLEMENTED
> Raw custom text persistence: 0
> Canon writes: 0
> Chroma writes: 0
> Provider calls: 0
> Phase 0D4-E: NOT ENTERED
> Phase 0D4-F: NOT ENTERED

## 1. Phase Overview

Phase 0D4-D implements transactional Turn confirmation with the following
guarantees:

1. **Immutable Turn record** — Plan, Validation, Result, and Transition
   chain are append-only and frozen after publication.
2. **Idempotent operation replay** — Same `operation_id` + same payload
   returns the same Result; no duplicate records.
3. **First-writer-wins concurrency** — Competing operations on the same
   Turn are arbitrated by immutable Result claim; only one succeeds.
4. **Forward recovery** — Partial failure at any phase resumes from the
   last completed phase; no rollback of immutable records.
5. **Branch-local event journal** — Append-only, fingerprint-chained
   event log scoped to a single branch.
6. **Branch-local state projection** — CAS-updated, deterministic
   projection of narrative state derived from applied Results.
7. **No side effects outside narrow scope** — Zero Canon writes, zero
   Chroma writes, zero Provider calls, zero global NarrativeMemory
   mutation.

## 2. Implementation Files

### 2.1 New production code

| File | Lines | Purpose |
| --- | --- | --- |
| [system/narrative_turn_service.py](file:///d:/novel/StoryOS/story-os-demo/system/narrative_turn_service.py) | ~1200 | NarrativeTurnService: confirm_turn core logic, operation authority, forward recovery, branch event journal, state projection with CAS |
| [web/narrative_turn_routes.py](file:///d:/novel/StoryOS/story-os-demo/web/narrative_turn_routes.py) | +180 | POST /confirm endpoint: request validation, scope parsing, safe error envelope, Cache-Control: no-store |
| [web/narrative_turn_wire.py](file:///d:/novel/StoryOS/story-os-demo/web/narrative_turn_wire.py) | +90 | ConfirmResult Wire DTO builder: ConfirmResult → JSON-safe response |

### 2.2 Modified production code

| File | Change | Why |
| --- | --- | --- |
| [web/static/simulator-narrative-turn.js](file:///d:/novel/StoryOS/story-os-demo/web/static/simulator-narrative-turn.js) | +320 / -15 | Confirm button enable logic, handleConfirmClick, operation_id management, confirm result rendering, double-click protection, retry with same operation_id |
| [web/templates/index.html](file:///d:/novel/StoryOS/story-os-demo/web/templates/index.html) | +20 / -5 | Replace "确认服务尚未接入" with "确认行动"; add nt-confirm-result panel |
| [web/static/simulator-narrative-turn.css](file:///d:/novel/StoryOS/story-os-demo/web/static/simulator-narrative-turn.css) | +60 | Confirm result panel styles, confirm button states, consequence flag chips |

### 2.3 New tests

| File | Tests | Purpose |
| --- | --- | --- |
| [tests/test_phase0d4d_narrative_turn_service.py](file:///d:/novel/StoryOS/story-os-demo/tests/test_phase0d4d_narrative_turn_service.py) | 14 | Service-layer: idempotency, concurrency, validation, persistence, recovery, isolation, custom action security |
| [tests/test_phase0d4d_confirm_routes.py](file:///d:/novel/StoryOS/story-os-demo/tests/test_phase0d4d_confirm_routes.py) | 8 | Route-layer: success, idempotent replay, malformed request, custom text not leaked, archived branch, no-store header, conflict |

## 3. HTTP Endpoint Contract

### 3.1 POST /api/narrative-turn/confirm

Request body (recommended action):

```json
{
  "operation_id": "op-...",
  "project_id": "...",
  "timeline_id": "...",
  "branch_id": "...",
  "chapter_id": 1,
  "source_version_id": "...",
  "expected_context_fingerprint": "...",
  "expected_turn_id": "...",
  "expected_validation_id": "...",
  "expected_preview_fingerprint": "...",
  "action_source": "recommended",
  "selected_action_id": "..."
}
```

Request body (custom action):

```json
{
  "operation_id": "op-...",
  "project_id": "...",
  "timeline_id": "...",
  "branch_id": "...",
  "chapter_id": 1,
  "source_version_id": "...",
  "expected_context_fingerprint": "...",
  "expected_turn_id": "...",
  "expected_validation_id": "...",
  "expected_preview_fingerprint": "...",
  "action_source": "custom",
  "custom_action_text": "..."
}
```

Constraints:
- `selected_action_id` XOR `custom_action_text` (exactly one)
- Client-submitted status/result/event summary/state delta/cost/risk/consequence flags are rejected
- Raw custom action text exists only in request body and function memory
- Only `custom_action_text_hash` and structured deterministic results are persisted

Success response:

```json
{
  "schema_version": "1.0",
  "operation_id": "op-...",
  "idempotent_replay": false,
  "recovery_performed": false,
  "turn_state": "applied_to_branch",
  "result": {
    "turn_id": "...",
    "scope": {
      "project_id": "...",
      "timeline_id": "...",
      "branch_id": "..."
    },
    "chapter_id": 1,
    "selected_action_id": "...",
    "custom_action_text_hash": null,
    "result_status": "success",
    "event_summary": "...",
    "consequence_flags": [],
    "next_context_fingerprint": "...",
    "execution_revision": "...",
    "source_fingerprint": "...",
    "confirmed_at": "..."
  },
  "branch_state_revision": "..."
}
```

All responses carry `Cache-Control: no-store`.

### 3.2 Error codes

| Code | HTTP | Meaning |
| --- | --- | --- |
| MALFORMED_REQUEST | 400 | Missing required fields, invalid action_source, both selected_action_id and custom_action_text |
| PROJECT_NOT_FOUND | 404 | Project does not exist |
| TIMELINE_NOT_FOUND | 404 | Timeline does not exist |
| BRANCH_NOT_FOUND | 404 | Branch does not exist |
| CHAPTER_NOT_FOUND | 404 | Chapter does not exist |
| SOURCE_NOT_FOUND | 404 | Source version does not exist |
| CONTEXT_STALE | 409 | Expected context fingerprint does not match |
| SOURCE_STALE | 409 | Source version is outdated |
| CANON_STALE | 409 | Canon revision is outdated |
| TURN_ID_MISMATCH | 409 | Expected turn_id does not match rebuilt plan |
| VALIDATION_STALE | 409 | Expected validation_id does not match |
| PREVIEW_STALE | 409 | Expected preview fingerprint does not match |
| ACTION_ID_INVALID | 409 | Selected action ID not found in plan |
| BRANCH_ARCHIVED | 409 | Branch is archived, cannot confirm |
| BRANCH_INACTIVE | 409 | Branch is not active, cannot confirm |
| OPERATION_ID_CONFLICT | 409 | Same operation_id with different payload/scope |
| TURN_ALREADY_CONFIRMED | 409 | Different operation_id on already-confirmed turn |
| BRANCH_STATE_REVISION_CONFLICT | 409 | State projection CAS failed |
| CONFIRMATION_BLOCKED | 422 | Validation status is blocked |
| CONFIRMATION_REQUIRES_CLARIFICATION | 422 | Validation status is requires_clarification |
| CONFIRM_RECOVERY_REQUIRED | 500 | Operation in inconsistent state requiring manual recovery |
| INTERNAL_ERROR | 500 | Safe internal error (no traceback) |

## 4. Transactional Confirmation Flow

### 4.1 Call graph

```
POST /confirm
  → request validation (Wire DTO)
  → operation replay / collision check (operation authority)
  → current context rebind (NarrativeTurnContext)
    → verify branch lifecycle = open
    → verify branch activity = active
    → compare expected context fingerprint
  → plan deterministic rebuild (NarrativeTurnPlanner)
    → compare expected turn_id
  → action validation + feasibility rerun (NarrativeActionFeasibility)
    → reject blocked
    → reject requires_clarification
    → compare expected validation_id
  → preview deterministic rebuild (NarrativeTurnPreview)
    → compare expected preview_fingerprint
  → deterministic result construction
  → immutable Result claim (first-writer-wins)
  → Turn transition chain persistence
    → append Plan (planned → awaiting_action)
    → awaiting_action → validating
    → append Validation (validating → validated)
    → validated → previewed
    → append Result (previewed → confirmed)
  → branch event append
  → branch-state projection (CAS)
  → applied_to_branch transition
  → operation completion marker
  → response Wire DTO
```

### 4.2 Operation phase machine

```
PRECHECK_COMPLETE
  ↓
RESULT_CLAIMED  ← first-writer-wins arbitration point
  ↓
TURN_CHAIN_PERSISTED
  ↓
CONFIRMED_TRANSITION_APPENDED
  ↓
BRANCH_EVENT_APPENDED
  ↓
STATE_PROJECTED
  ↓
APPLIED_TRANSITION_APPENDED
  ↓
COMPLETED
```

Each phase:
- Detectable via operation authority marker
- Idempotent on replay
- Has immutable authority (not timestamp-ordered)
- Recoverable after restart

### 4.3 Concurrency arbitration

**Claim authority:** Immutable `NarrativeTurnResult` at
`data/narrative_turn/results/{turn_id}.json`.

Rules:
- Same operation_id + same request → 200 + idempotent_replay=true
- Same operation_id + different request → 409 OPERATION_ID_CONFLICT
- Different operation_id + same turn → first Result writer wins; second gets 409 TURN_ALREADY_CONFIRMED
- Different turns + same branch → CAS on branch_state revision ensures no lost updates

## 5. Branch-Local Event Journal

### 5.1 Path

```
data/narrative_turn/events/{project_id}/{timeline_id}/{branch_id}/events.jsonl
```

### 5.2 Event schema

```python
schema_version: str
event_id: str
sequence: int
scope: NarrativeScope
turn_id: str
result_fingerprint: str
operation_id: str
previous_event_id: str | None
previous_event_fingerprint: str | None
occurred_at: datetime
record_fingerprint: str
```

### 5.3 Constraints

- Append-only (JSONL)
- Sequence numbers are continuous
- Previous fingerprint chain is verified
- create-if-absent semantics (same event is idempotent)
- Different content at same sequence fails closed
- Branch-scoped (Branch A events never appear in Branch B)
- Archived/inactive branches reject appends

## 6. Branch State Projection

### 6.1 Path

```
data/narrative_memory/state/{project_id}/{timeline_id}/{branch_id}/current.json
```

### 6.2 Schema

```python
schema_version: str
scope: NarrativeScope
revision: str
last_applied_turn_id: str | None
last_event_sequence: int | None
last_result_fingerprint: str | None
state: dict  # recursive-freeze compatible
updated_at: datetime
record_fingerprint: str
```

### 6.3 Update mechanism

1. Read current state + revision
2. Verify expected_revision matches (CAS precondition)
3. Apply state_delta_proposal from Result
4. Compute new deterministic revision (fingerprint of new state)
5. Write to temp file + fsync
6. Atomic replace (os.replace)
7. Backup of previous state retained

## 7. Test Results

### 7.1 0D4-D focused tests

```
Command: python -m pytest tests/test_phase0d4d_narrative_turn_service.py \
           tests/test_phase0d4d_confirm_routes.py -v
Result:  22 passed, 1 warning
Exit:    0
```

Breakdown: service 14 + routes 8 = 22.

### 7.2 0D4-A/B/C regression

```
Command: python -m pytest tests/test_phase0d4a_narrative_turn_foundation.py \
           tests/test_phase0d4b_narrative_turn_planner.py \
           tests/test_phase0d4c_narrative_turn_routes.py \
           tests/test_phase0d4c_narrative_turn_wire_dto.py \
           tests/test_phase0d4c_narrative_turn_frontend_contract.py \
           tests/test_phase0d4c_context_navigator_integration.py -v
Result:  483 passed, 1 warning
Exit:    0
```

### 7.3 Total 0D4 tests

```
0D4-D focused:         22
0D4-C focused:        243
0D4-A/B regression:   262
─────────────────────────
Total:                527
```

## 8. Security Boundaries

| Boundary | Count |
| --- | --- |
| Provider calls | 0 |
| External network | 0 |
| Canon writes | 0 |
| Chroma writes | 0 |
| Vector index calls | 0 |
| Global NarrativeMemory migration | 0 |
| Branch lifecycle mutations | 0 |
| Raw custom action persistence | 0 |
| New dependencies | 0 |
| Git write operations | 0 |

Custom action raw text audit:
- Not in URL
- Not in localStorage / sessionStorage
- Not in response body
- Not in Result.event_summary
- Not in state projection
- Not in event journal
- Only custom_action_text_hash (SHA-256) is persisted

## 9. Phase Status

```
Phase 0D4-D: PASSED
Transactional Turn confirmation: IMPLEMENTED
Idempotent operation replay: VERIFIED
Concurrent confirmation first-writer-wins: VERIFIED
Forward recovery: VERIFIED
Branch-local event journal: VERIFIED
Branch-local state projection: VERIFIED
Turn lifecycle through applied_to_branch: VERIFIED
Turn confirmation UI: IMPLEMENTED
Raw custom text persistence: 0
Canon writes: 0
Chroma writes: 0
Provider calls: 0
Phase 0D4-E: NOT ENTERED
Phase 0D4-F: NOT ENTERED
```

Phase 0D4-D is complete. Phase 0D4-E has **not** been entered.
