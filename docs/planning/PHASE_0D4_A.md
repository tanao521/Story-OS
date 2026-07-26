# Phase 0D4-A — Narrative Turn Contracts, Immutable State Journal & Append-Only Stores

> Status: **PASSED**
>
> **Phase 0D4-A-FIX-RC2: PASSED**
> **Phase 0D4-A: SEALED**
> **Phase 0D4-B: NOT ENTERED**
>
> This document is the authoritative phase document for 0D4-A as of
> FIX-RC2-FV. The initial delivery report
> (`PHASE_0D4_A_DELIVERY_REPORT.md`) is retained as **historical
> evidence only** and is **NOT authoritative for the current
> implementation**; see its top-of-file banner.
>
> FIX-RC2 修复点（均已在代码、测试和文档中验证）：
> 1. Lifecycle event 路径改为 sequence-only
> 2. Registry event 确定性 sequence journal 可重建（显式字段 Schema A）
> 3. Active archive 多文件操作可恢复（REGISTRY-FIRST 安全顺序）
> 4. State delta 递归冻结
> 5. 文档同步更新

## 1. Phase Overview

Phase 0D4-A implements the foundational layer for Narrative Turn:

- Immutable data contracts with strict validation
- Append-only lifecycle transition journal
- Branch registry store with lifecycle management
- Path containment and atomic write safety
- Comprehensive unit tests

**Scope Boundary:**
- ✅ Contracts: `core/contracts/narrative_turn.py`
- ✅ Turn Store: `system/narrative_turn_store.py`
- ✅ Branch Store: `system/narrative_branch_store.py`
- ✅ Tests: `tests/test_phase0d4a_narrative_turn_foundation.py`
- ❌ Planner (0D4-B)
- ❌ Feasibility engine (0D4-B)
- ❌ API endpoints (0D4-E)
- ❌ UI (0D4-C)
- ❌ Chapter compilation (0D4-F)

## 2. OWNER Decisions Applied

| Decision | Implementation |
| --- | --- |
| `TimelineContext` independent of `ProjectContext` | `core/contracts/narrative_turn.py:TimelineContext` |
| `NarrativeScope` combines project_id + timeline_id + branch_id | `core/contracts/narrative_turn.py:NarrativeScope` |
| Branch `lifecycle_status` ("open"/"archived") separated from `active_branch_id` | `NarrativeBranch.lifecycle_status` + registry `active_branch_id` |
| Immutable records + append-only transition journal | `NarrativeTurnTransition` + transition journal store |
| Plan creation is a non-canonical write | Plan appended via `append_plan()` |
| Validation scope fields completed | `NarrativeActionValidation` includes full scope |

## 3. Contract Summary

### 3.1 TimelineContext

```python
@dataclass(frozen=True)
class TimelineContext:
    project_id: str
    timeline_id: str
```

### 3.2 NarrativeScope

```python
@dataclass(frozen=True)
class NarrativeScope:
    project_id: str
    timeline_id: str
    branch_id: str
```

### 3.3 Core Contracts

| Contract | Purpose |
| --- | --- |
| `NarrativeTurnPlan` | Immutable Turn plan record |
| `NarrativeActionOption` | Recommended action option |
| `NarrativeCustomActionPolicy` | Custom action constraints |
| `NarrativeActionValidation` | Action validation result |
| `NarrativeTurnResult` | Confirmed Turn result |
| `NarrativeBranch` | Branch entity |
| `NarrativeTurnTransition` | Lifecycle state transition |

### 3.4 Enums

| Enum | Values |
| --- | --- |
| `TurnState` | planned, awaiting_action, validating, validated, blocked, requires_clarification, previewed, confirmed, applied_to_branch, included_in_chapter, committed, superseded |
| `ValidationStatus` | allowed, allowed_with_cost, requires_clarification, blocked |
| `BranchLifecycleStatus` | open, archived |

## 4. Store Design

### 4.1 NarrativeTurnStore

**Path Structure (authoritative as of FIX-RC2-FV):**
```
data/narrative_turns/{timeline_id}/{branch_id}/
  plans/{turn_id}.json
  validations/{validation_id}.json
  results/{turn_id}.json
  transitions/{turn_id}/{sequence:08d}.json     ← sequence-only filename (FIX-RC)
  operations/{operation_id}.json                ← branch-local index (rebuildable projection)

data/narrative_turn_operations/{operation_id}.json  ← project-root operation authority (FIX-RC)
```

**Immutable publication (`_publish_immutable_json`):**
- `tempfile.mkstemp` (in target dir) → write → `flush` → `fsync` → `os.link` (create-if-absent).
- `FileExistsError` + identical content → idempotent replay (silent success).
- `FileExistsError` + differing content → `IMMUTABLE_RECORD_EXISTS` (fail-closed).
- Never uses `os.replace` for immutable records.
- Temp file cleaned up in `finally`.

**Mutable projections (`_atomic_write_json`):**
- `tempfile.mkstemp` → write → `fsync` → `os.replace` with expected-revision CAS.
- Used only for `registry.json`, branch operation main record, and the
  branch-local operation index — never for immutable entity records.

**Capabilities:**
- Append immutable plan/validation/result
- Append transition journal entry (sequence + previous binding)
- Derive current state from transitions (sequence-ordered replay)
- Operation authority replay with idempotency (project-root scope)
- Scope-safe read/write
- Path containment validation

### 4.2 NarrativeBranchStore

**Path Structure (authoritative as of FIX-RC2-FV):**
```
data/branches/{timeline_id}/
  branches/{branch_id}.json                            ← immutable branch IDENTITY record
  lifecycle_events/{branch_id}/{sequence:08d}.json     ← append-only lifecycle journal (FIX-RC2 sequence-only)
  registry.json                                        ← mutable projection of active pointer
  registry_events/{sequence:08d}.json                  ← append-only registry events (FIX-RC2 sequence-only)

data/branch_operations/                                ← project-root branch operations (FIX-RC2; NOT timeline-isolated)
  {operation_id}.json                                  ← main operation record (mutable projection)
  {operation_id}_registry_updated.json                 ← immutable phase marker
  {operation_id}_lifecycle_appended.json               ← immutable phase marker
  {operation_id}_completed.json                        ← immutable phase marker
```

**Active archive recovery protocol (REGISTRY-FIRST safe order):**
1. `INTENT` — `_write_operation_phase(operation_id, intent_payload)`; no side effects.
2. `REGISTRY_UPDATED` — verify target/replacement → `_update_registry` (CAS active pointer → replacement) → `_append_registry_event(event_type="branch_archived", from=target, to=replacement, expected_revision, resulting_revision)` → publish `{operation_id}_registry_updated.json` immutable marker → `_atomic_write_json` main record → `REGISTRY_UPDATED`.
3. `LIFECYCLE_APPENDED` — `_derive_lifecycle_status(target)` (idempotent skip if already archived) → `_append_lifecycle_event(target, OPEN → ARCHIVED)` → publish `{operation_id}_lifecycle_appended.json` immutable marker → `_atomic_write_json` main record → `LIFECYCLE_APPENDED`.
4. `COMPLETED` — publish `{operation_id}_completed.json` immutable marker → `_atomic_write_json` main record → `COMPLETED`.

**Safe invariant:** `active_branch_id` never points to an archived branch
in any observable or recoverable state:
- Before `REGISTRY_UPDATED`: active = target (still open) — safe.
- After `REGISTRY_UPDATED`, before `LIFECYCLE_APPENDED`: active = replacement (open), target still open — safe.
- After `LIFECYCLE_APPENDED`: active = replacement (open), target = archived — safe.

**Registry rebuild (`_rebuild_registry_from_journal`):**
- Replays `registry_events/{sequence:08d}.json` in ascending `sequence` order.
- Verifies `previous_event_id` + `previous_event_fingerprint` chain.
- Takes the last event's `to_active_branch_id` as `active_branch_id` and
  the last event's `resulting_revision` as `revision`.
- Writes a fresh `registry.json` projection via `_atomic_write_json`.
- Any chain break raises `REGISTRY_EVENT_CHAIN_CORRUPT` (fail-closed).

**Recursive state delta (`_recursive_freeze`):**
- `state_delta_proposal: tuple[tuple[str, FrozenValue], ...]` where
  `FrozenValue = str|int|float|bool|None|tuple[FrozenValue, ...]`.
- `dict` input is deep-copied into `tuple[tuple[str, FrozenValue], ...]`
  with sorted keys (boundary-only conversion; stored form is deep-immutable).
- `list` / `set` / `bytes` / custom objects → `INVALID_TYPE` (fail-closed).
- `NaN` / `±inf` → `INVALID_FIELD`; depth > 8 → `INVALID_FIELD`;
  total elements > 1000 → `INVALID_FIELD`.

**Capabilities:**
- Create branch (root or child)
- Select branch as active
- Archive branch (with replacement if active) — recoverable four-phase operation
- Restore branch (append-only lifecycle event; does NOT auto-select)
- Cycle prevention
- Revision-based registry updates with backup/recovery
- Deterministic registry rebuild from event journal

### 4.3 Path constants (authoritative)

The following flat list is the single source of truth for path layout.
Static doc-contract tests (`test_phase_document_paths_match_store_constants`)
assert these literal strings are present in this document.

```
data/narrative_turns/{timeline_id}/{branch_id}/plans/{turn_id}.json
data/narrative_turns/{timeline_id}/{branch_id}/validations/{validation_id}.json
data/narrative_turns/{timeline_id}/{branch_id}/results/{turn_id}.json
data/narrative_turns/{timeline_id}/{branch_id}/transitions/{turn_id}/{sequence:08d}.json
data/narrative_turns/{timeline_id}/{branch_id}/operations/{operation_id}.json
data/narrative_turn_operations/{operation_id}.json
data/branches/{timeline_id}/branches/{branch_id}.json
data/branches/{timeline_id}/lifecycle_events/{branch_id}/{sequence:08d}.json
data/branches/{timeline_id}/registry.json
data/branches/{timeline_id}/registry_events/{sequence:08d}.json
data/branch_operations/{operation_id}.json
data/branch_operations/{operation_id}_registry_updated.json
data/branch_operations/{operation_id}_lifecycle_appended.json
data/branch_operations/{operation_id}_completed.json
```

## 5. State Machine

### 5.1 Legal Transitions

- `planned` → `awaiting_action`
- `planned` → `superseded`
- `awaiting_action` → `validating`
- `validating` → `validated` / `blocked` / `requires_clarification`
- `requires_clarification` → `awaiting_action`
- `validated` → `previewed`
- `previewed` → `confirmed`
- `confirmed` → `applied_to_branch`
- `applied_to_branch` → `included_in_chapter`
- `included_in_chapter` → `committed`

### 5.2 Terminal States

- `blocked`
- `committed`
- `superseded`

### 5.3 Illegal Transitions

- `confirmed` → `planned`
- `committed` → any
- `blocked` → `validated`
- `planned` → `confirmed`
- Cross-scope transitions
- Transition replay with different content

## 6. Security Features

### 6.1 Path Containment

- ID pattern validation: `^[A-Za-z0-9_-]+$`
- Reject: `..`, `/`, `\`, NUL, drive letters, UNC paths
- Resolved parent containment check
- Root symlink/reparse fail-closed

### 6.2 Immutable Publication vs Mutable Projection

**Immutable records** (Plan, Validation, Result, Transition, BranchIdentity,
BranchLifecycleEvent, RegistryEvent, BranchOperation phase markers):
- `_publish_immutable_json` uses `tempfile.mkstemp` → `flush` → `fsync` →
  `os.link` (atomic create-if-absent).
- Existing identical record → idempotent replay (silent success).
- Existing differing record → `IMMUTABLE_RECORD_EXISTS` (fail-closed).
- **Never** uses `os.replace` for immutable records.

**Mutable projections** (registry snapshot, branch operation main record,
branch-local operation index):
- `_atomic_write_json` uses `tempfile.mkstemp` → `fsync` → `os.replace`
  with expected-revision CAS.
- Always rebuildable from the corresponding append-only journal.
- Backup/recovery on write errors (old version preserved on failure).

### 6.3 Idempotency

- `operation_id` collision detection
- Identical transition replay returns same result
- Different payload with same operation_id → collision error

## 7. Test Coverage

**Focused tests (as of FIX-RC2-FV): 132 passed, 0 failed, 0 skipped**
in `tests/test_phase0d4a_narrative_turn_foundation.py`.

| Category | Count | Domain |
| --- | --- | --- |
| Contract validation | 14 | schema, types, IDs, fingerprints, enums |
| Strict types | 13 | tuple/list/dict/bool/enum/serialized shape |
| Scope binding | 2 | project mismatch, scope assert |
| Path containment | 2 | traversal, absolute path |
| Turn store | 9 | plan/validation/result/transition/operation |
| State journal | 4 | legal transitions, illegal, terminal, idempotent |
| Immutable publication | 10 | first write, replay, collision, temp cleanup, fsync, hard-link |
| Branch lifecycle | 23 | create, select, archive, restore, identity never changes |
| Operation authority | 7 | replay, cross-branch, cross-timeline, cross-turn, payload, corrupt |
| Transition ordering | 10 | sequence increments, duplicates, gaps, timestamps, previous binding, concurrent |
| Immutable fingerprint | 2 | plan fingerprint, transition fingerprint |
| Lifecycle concurrency (FIX-RC2) | 7 | sequence-only filenames, concurrent first-wins |
| Branch operation recovery (FIX-RC2) | 11 | four-phase recovery, idempotency, invariants |
| Registry rebuild (FIX-RC2) | 10 | sequence journal, rebuild, corruption, concurrency |
| Recursive state delta (FIX-RC2) | 8 | recursive freeze, NaN, nesting, determinism |
| Fact-locking tests (FIX-RC2-FV) | 6 | registry-first order, active-pointer invariant, path layout, schema, rebuild, doc-path constants |

## 8. Files Created

| File | Purpose |
| --- | --- |
| `core/contracts/narrative_turn.py` | Immutable contracts and validation |
| `system/narrative_turn_store.py` | Append-only Turn store |
| `system/narrative_branch_store.py` | Branch registry store |
| `tests/test_phase0d4a_narrative_turn_foundation.py` | Focused tests |

## 9. Files Updated

| File | Changes |
| --- | --- |
| `docs/design/simulator_narrative_turn_contract_map.md` | Update to implementation artifact |
| `docs/design/simulator_narrative_turn_state_machine.md` | Update transition rules and persistence |
| `docs/design/simulator_branch_isolation_map.md` | Update branch registry schema |
| `docs/planning/PHASE_0D4_IMPLEMENTATION_BRIEF.md` | Mark 0D4-A as PASSED |

## 10. Exit Criteria

- ✅ All focused tests pass (132 + 6 fact-locking = 138 as of FIX-RC2-FV)
- ✅ No Provider calls
- ✅ No Canon writes
- ✅ No Chroma writes
- ✅ Compile clean
- ✅ Static checks pass
- ✅ Documents factually consistent with code (verified in FIX-RC2-FV)

**Phase 0D4-A-FIX-RC2: PASSED**
**Phase 0D4-A: SEALED**
**Phase 0D4-B: NOT ENTERED**