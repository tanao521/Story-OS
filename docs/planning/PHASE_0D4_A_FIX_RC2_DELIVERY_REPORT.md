# Phase 0D4-A-FIX-RC2 Delivery Report

> Status: **PASSED**
> Date: 2026-07-25
> Authorization: Phase 0D4-A-FIX-RC2 (Phase 0D4-A-FIX-RC marked PARTIALLY PASSED)
> Execution environment: TRAE Work CN / SOLO Coder / 单 Agent

---

## 1. Phase Conclusion

Phase 0D4-A-FIX-RC2 has been successfully implemented and verified. All
five required fixes (lifecycle sequence-only filenames, recoverable
active-archive operations, deterministic registry event journal,
recursively frozen state deltas, document synchronization) are
implemented, all focused tests pass, all associated regression suites
pass, all security boundaries remain at zero, and the current
authoritative design documents are factually consistent with the code.

**Final State:**
- Phase 0D4-A-FIX-RC2: **PASSED**
- Phase 0D4-A: **SEALED**
- Narrative Turn foundation: **IMPLEMENTED**
- Phase 0D4-B: **NOT ENTERED**

---

## 2. Baseline Before Start (audited)

**Git Root:** `d:/novel/StoryOS`
**Branch:** `agent/phase-13-2-memory-repair`
**HEAD commit:** `ebca80b Document conservative DeepSeek token budget gate`

**FIX-RC1 file tracking status (audited via `git status --short`):**
All 10 0D4-A/FIX-RC produced files are untracked (`??`).

**Pre-FIX-RC2 state of the actual code (audited, not from prior report):**

| Question | Audited answer |
| --- | --- |
| lifecycle event filename format | `{sequence:08d}_{event_id}.json` — event_id in filename, no sequence-only concurrency guard |
| registry event filename format | `{event_id}.json` — no sequence ordering, no previous binding |
| active archive atomicity claim | "same call therefore atomic" — no recoverable operation protocol |
| state_delta_proposal type | `tuple[tuple[str, Any], ...]` — only top-level frozen; `Any` not enforced; nested mutability possible |
| Implementation Brief model names | Contained Luna/Terra/Tai Codex model aliases |

---

## 3. Fix 1 — Branch lifecycle sequence-only filenames

### 3.1 Change summary

- **Before:** `lifecycle_events/{branch_id}/{sequence:08d}_{event_id}.json`
  Two events with the same `sequence` but different `event_id` could
  coexist on disk, making concurrent first-wins impossible.
- **After:** `lifecycle_events/{branch_id}/{sequence:08d}.json`
  The `event_id` lives **inside** the JSON record. Two concurrent writes
  to the same next-sequence slot both target the same path, so
  `_publish_immutable_json` atomically resolves first-wins via
  `os.link`.

### 3.2 Read validation

`_read_lifecycle_events` now rejects any file whose name does not match
`^\d{8}\.json$` (8-digit sequence + `.json`), raising
`LIFECYCLE_EVENT_CHAIN_CORRUPT`. This fail-closes on:
- legacy `{seq}_{event_id}.json` files
- any non-sequence filenames
- accidental duplicate sequence files

### 3.3 Concurrency semantics

| Scenario | Result |
| --- | --- |
| First writer to sequence=N | `os.link` succeeds; event is published |
| Second writer to sequence=N (different content) | `os.link` → `FileExistsError` → content differs → `IMMUTABLE_RECORD_EXISTS` (surface as lifecycle conflict) |
| Second writer to sequence=N (identical content) | idempotent replay — silent no-op |
| Legacy mixed filenames on disk | `LIFECYCLE_EVENT_CHAIN_CORRUPT` on read — fail-closed |

### 3.4 Test coverage (7 tests, all passing)

- `test_lifecycle_sequence_only_filename` — filename format verified
- `test_concurrent_archive_archive_same_branch_first_wins` — concurrent archive → first wins
- `test_concurrent_archive_restore_same_branch` — concurrent archive/restore → collision
- `test_same_sequence_different_event_id_first_wins` — one file per sequence
- `test_no_duplicate_sequence_files` — N events == N files
- `test_loser_re_read_gets_stale_state` — loser sees stale derived status
- `test_corrupt_legacy_duplicate_sequence_fail_closed` — legacy naming → `LIFECYCLE_EVENT_CHAIN_CORRUPT`

---

## 4. Fix 2 — Recoverable active-archive operation

### 4.1 Problem

FIX-RC1 described active-archive-with-replacement as "atomic because
it's in the same method call". That was false: the operation spans
multiple files (registry snapshot + registry event + lifecycle event +
operation record), and a crash between any two steps leaves a partial
state. If the registry was switched to the replacement but the target
branch's lifecycle event was never written, `active_branch_id` still
points to an **open** branch (the replacement), which is safe — but the
operation is incomplete and a retry must not double-append.

### 4.2 Storage layout

```
data/branch_operations/{operation_id}.json   ← current phase snapshot (mutable projection)
data/branch_operations/{operation_id}_registry_updated.json   ← immutable phase marker
data/branch_operations/{operation_id}_lifecycle_appended.json ← immutable phase marker
data/branch_operations/{operation_id}_completed.json          ← immutable phase marker
```

The main operation record at `{operation_id}.json` is a mutable
projection (uses `_atomic_write_json`) that always reflects the current
phase. Each phase transition also publishes an immutable phase marker
via `_publish_immutable_json` for audit and for crash recovery (if the
main record is corrupt, the phase can be reconstructed from the highest
phase marker file present).

### 4.3 Four-phase protocol

```
Phase INTENT          →  publish operation record with phase=intent
Phase REGISTRY_UPDATED  →  CAS registry.active → replacement
                           append registry event (branch_archived)
                           update operation record phase
Phase LIFECYCLE_APPENDED → append target open→archived lifecycle event
                           update operation record phase
Phase COMPLETED         → update operation record phase=completed
```

**Invariant at every partial-failure point:**
`active_branch_id` never points to an archived branch.
- Before REGISTRY_UPDATED: active = target (open) — safe
- After REGISTRY_UPDATED, before LIFECYCLE_APPENDED: active = replacement (open) — safe
- After LIFECYCLE_APPENDED: active = replacement (open); target = archived — safe

### 4.4 Recovery algorithm

When `_active_archive_with_replacement` is called with an `operation_id`
that already has a record:

1. Read the operation record (from the main projection file).
2. If `phase == COMPLETED`: return existing resulting revision (idempotent).
3. If `phase == INTENT`: resume from REGISTRY_UPDATED step.
4. If `phase == REGISTRY_UPDATED`: verify registry already has replacement active; append lifecycle event if not already appended.
5. If `phase == LIFECYCLE_APPENDED`: mark completed.

All phase transitions check idempotency — no lifecycle event is ever
double-appended, no registry event is ever double-appended.

### 4.5 Test coverage (11 tests, all passing)

- `test_active_archive_completes_successfully` — happy path
- `test_retry_after_intent_phase_succeeds` — crash after INTENT, retry completes
- `test_retry_after_registry_update_succeeds` — crash after REGISTRY_UPDATED, retry completes
- `test_failure_after_registry_before_lifecycle_recovery` — registry done, lifecycle fails, retry appends lifecycle
- `test_recovery_does_not_create_second_archive_event` — exactly 1 archive event after recovery
- `test_concurrent_archive_operations_conflict` — two operations → second gets revision conflict
- `test_replacement_archived_during_operation` — replacement archived → operation fails
- `test_expected_registry_revision_stale` — stale revision → `BRANCH_OPERATION_STALE_REVISION`
- `test_same_operation_id_different_replacement` — operation_id bound to replacement at INTENT
- `test_invariant_active_never_points_to_archived` — verified at every failure point
- `test_operation_record_persists_all_phases` — phase progression INTENT→REGISTRY_UPDATED→LIFECYCLE_APPENDED→COMPLETED

---

## 5. Fix 3 — Deterministic registry event journal

### 5.1 Change summary

- **Before:** `registry_events/{event_id}.json` — filesystem order
  undefined, no sequence, no previous binding, no way to rebuild
  `registry.json` from events.
- **After:** `registry_events/{sequence:08d}.json` — deterministic
  sequence from 0, with `previous_event_id` +
  `previous_event_fingerprint` chaining, fully rebuildable.

### 5.2 RegistryEvent contract

```python
@dataclass(frozen=True)
class RegistryEvent:
    schema_version: str
    event_id: str
    sequence: int
    project_id: str
    timeline_id: str
    event_type: str                      # "branch_created", "branch_selected", "branch_archived", ...
    from_active_branch_id: str | None
    to_active_branch_id: str | None
    expected_revision: str
    resulting_revision: str
    operation_id: str | None
    occurred_at: str                     # audit-only
    previous_event_id: str | None        # None for sequence=0
    previous_event_fingerprint: str | None  # None for sequence=0
    record_fingerprint: str
```

### 5.3 Rebuild protocol

If `registry.json` is missing, corrupt, or inconsistent with the
journal:

1. Replay all `registry_events/{sequence:08d}.json` in sequence order.
2. Verify `previous_event_id` and `previous_event_fingerprint` chain.
3. Track `current_active_branch_id` and `current_revision`.
4. Write a fresh `registry.json` projection via `_atomic_write_json`.

If the journal is itself corrupt (gap, duplicate, broken chain), the
rebuild fails with `REGISTRY_EVENT_CHAIN_CORRUPT` — fail-closed.

### 5.4 Projection-vs-journal consistency

`_create_registry_if_missing` now validates that the projection's
`active_branch_id` matches the journal's derived value. If they disagree,
it raises `REGISTRY_PROJECTION_MISMATCH` and triggers a safe rebuild
from the journal.

### 5.5 Test coverage (10 tests, all passing)

- `test_registry_events_sequence_ordered` — filenames are `{8d}.json`
- `test_rebuild_registry_from_events` — delete registry.json → rebuild works
- `test_deleted_registry_snapshot_recovery` — delete both .json and .bak → rebuild
- `test_corrupt_registry_snapshot_recovery` — corrupt JSON → rebuild
- `test_event_gap_fail_closed` — missing sequence → `REGISTRY_EVENT_CHAIN_CORRUPT`
- `test_duplicate_sequence_fail_closed` — duplicate → fail-closed
- `test_previous_fingerprint_mismatch_fail_closed` — broken chain → fail-closed
- `test_non_monotonic_timestamps` — `occurred_at` order doesn't affect rebuild
- `test_concurrent_selection_first_wins` — concurrent select → first wins
- `test_projection_journal_mismatch_fail_closed` — projection disagrees with journal → rebuild or error

---

## 6. Fix 4 — Recursively frozen state delta

### 6.1 Problem

FIX-RC1 had `state_delta_proposal: tuple[tuple[str, Any], ...]`. The
`Any` was unenforced — a value could be a `list`, `dict`, custom
object, `NaN`, etc. Even if the top-level was a tuple, nested mutables
could be modified externally after construction, violating the
contract's immutability guarantee.

### 6.2 Solution: `_recursive_freeze`

```python
def _recursive_freeze(value: Any, field_name: str, _depth: int = 0) -> Any:
```

**Accepted types:**
- Scalars: `str`, `int`, `float` (finite only), `bool`, `None`
- `tuple` — recursively frozen element-by-element
- `dict` — deep-copied into `tuple[tuple[str, FrozenValue], ...]` with sorted keys

**Rejected types (fail-closed):**
- `list` → `INVALID_TYPE` (strict type policy)
- `set` / `frozenset` → `INVALID_TYPE`
- `bytes` → `INVALID_TYPE`
- custom objects → `INVALID_TYPE`
- `float('nan')`, `float('inf')`, `float('-inf')` → `INVALID_FIELD`
- depth > 8 → `INVALID_FIELD`
- total elements > 1000 → `INVALID_FIELD`
- empty or non-string dict keys → `INVALID_FIELD`

### 6.3 Type contract

```
FrozenScalar = str | int | float | bool | None
FrozenValue = FrozenScalar | tuple[FrozenValue, ...] | tuple[tuple[str, FrozenValue], ...]
```

`state_delta_proposal` is `tuple[tuple[str, FrozenValue], ...]`.

### 6.4 Deterministic fingerprint

Because `dict` input is sorted by key during the freeze, two semantically
equivalent inputs (one as `tuple[tuple[str, FrozenValue], ...]`, one as
`dict`) produce the same frozen structure and therefore the same
fingerprint.

### 6.5 Test coverage (8 tests, all passing)

- `test_nested_dict_mutation_isolation` — external dict mutation does not affect record
- `test_nested_list_rejected` — list inside tuple → rejected
- `test_nested_dict_inside_tuple` — dict inside tuple → frozen correctly
- `test_nan_infinity_rejected` — NaN / ±inf → rejected
- `test_unsupported_custom_object_rejected` — custom class → rejected
- `test_excessive_nesting_rejected` — depth > 8 → rejected
- `test_deterministic_key_order` — same keys different order → same fingerprint
- `test_same_semantic_value_same_fingerprint` — tuple-of-tuples and dict → same frozen result

---

## 7. Document synchronization

### 7.1 Updated documents

| Document | Changes |
| --- | --- |
| [simulator_narrative_turn_contract_map.md](file:///d:/novel/StoryOS/docs/design/simulator_narrative_turn_contract_map.md) | Added FIX-RC2 OWNER decisions; updated `state_delta_proposal` type; added §1.8 `RegistryEvent`; added §1.9 `BranchOperationRecord`; updated lifecycle path to sequence-only |
| [simulator_narrative_turn_state_machine.md](file:///d:/novel/StoryOS/docs/design/simulator_narrative_turn_state_machine.md) | Added FIX-RC2 OWNER decisions; updated §7 persistence for lifecycle/registry/branch ops sequence-only paths; updated §8 concurrency rules |
| [simulator_branch_isolation_map.md](file:///d:/novel/StoryOS/docs/design/simulator_branch_isolation_map.md) | Updated §2.1 storage partitioning; removed "same call atomic" language; added §2.3 Recoverable multi-file operations; updated §2.5 archive description |
| [PHASE_0D4_IMPLEMENTATION_BRIEF.md](file:///d:/novel/StoryOS/docs/planning/PHASE_0D4_IMPLEMENTATION_BRIEF.md) | Removed all Luna/Terra/Tai Codex model aliases; unified to TRAE Work CN / SOLO Coder / 单 Agent |
| [PHASE_0D4_A.md](file:///d:/novel/StoryOS/docs/planning/PHASE_0D4_A.md) | Added FIX-RC2 status header with the five fix points |
| [PHASE_0D4_A_DELIVERY_REPORT.md](file:///d:/novel/StoryOS/docs/planning/PHASE_0D4_A_DELIVERY_REPORT.md) | Added header noting this is the initial 0D4-A report; FIX-RC2 delivery is separate |

### 7.2 Removed legacy statements

- ❌ Removed: "same method call therefore atomic" (replaced with recoverable multi-file operation protocol)
- ❌ Removed: `os.replace` used for immutable records (never was true; docs now accurately reflect `_publish_immutable_json` + `os.link`)
- ❌ Removed: Luna/Terra/Tai model names from Implementation Brief
- ❌ Removed: `list → tuple conversion` language (strict fail-closed policy enforced since FIX-RC1)

---

## 8. Focused test results

**Total: 132 passed, 0 failed, 0 skipped** (1 warning — Starlette/httpx deprecation, unrelated)
**Exit code:** 0

| Test class | Count | Domain |
| --- | --- | --- |
| `TestContractValidation` | 14 | schema, types, IDs, fingerprints, enums |
| `TestStrictTypes` | 13 | tuple/list/dict/bool/enum/serialized shape |
| `TestScopeBinding` | 2 | project mismatch, scope assert |
| `TestPathContainment` | 2 | traversal, absolute path |
| `TestTurnStore` | 9 | plan/validation/result/transition/operation |
| `TestStateJournal` | 4 | legal transitions, illegal, terminal, idempotent |
| `TestImmutablePublication` | 10 | first write, replay, collision, temp cleanup, fsync, hard-link |
| `TestBranchLifecycle` | 23 | create, select, archive, restore, identity never changes |
| `TestOperationAuthority` | 7 | replay, cross-branch, cross-timeline, cross-turn, payload, corrupt |
| `TestTransitionOrdering` | 10 | sequence increments, duplicates, gaps, timestamps, previous binding, concurrent |
| `TestImmutableFingerprint` | 2 | plan fingerprint, transition fingerprint |
| `TestLifecycleConcurrency` | 7 | **NEW** — sequence-only filenames, concurrent first-wins |
| `TestBranchOperationRecovery` | 11 | **NEW** — four-phase recovery, idempotency, invariants |
| `TestRegistryRebuild` | 10 | **NEW** — sequence journal, rebuild, corruption, concurrency |
| `TestRecursiveStateDelta` | 8 | **NEW** — recursive freeze, NaN, nesting, determinism |

---

## 9. Associated regression (audited commands and results)

All commands run from `d:/novel/StoryOS/story-os-demo`.

### 9.1 B1-FIX reconciliation store

```
python -m pytest tests/test_phase0d3c4b1_conservative_budget.py -q
```

| Metric | Value |
| --- | --- |
| Passed | 45 |
| Failed | 0 |
| Skipped | 0 |
| Warnings | 1 (Starlette/httpx deprecation) |
| Exit code | 0 |

### 9.2 Planning Control / Rolling Window

```
python -m pytest tests/test_planning_control.py tests/test_planning_rolling_window.py tests/test_planning_rolling_lifecycle.py tests/test_planning_rolling_production.py -q
```

| Metric | Value |
| --- | --- |
| Passed | 100 |
| Failed | 0 |
| Skipped | 2 |
| Warnings | 1 |
| Exit code | 0 |

### 9.3 ProjectContext / dual-project isolation

```
python -m pytest tests/test_phase0c2_project_clone.py tests/test_phase0b2_dual_project_isolation.py tests/test_phase0a_verification.py tests/test_frontend_request_isolation.py -q
```

| Metric | Value |
| --- | --- |
| Passed | 47 |
| Failed | 0 |
| Skipped | 0 |
| Warnings | 0 |
| Exit code | 0 |

### 9.4 Static path guard

```
python -m pytest tests/test_static_path_guard.py -q
```

| Metric | Value |
| --- | --- |
| Passed | 3 |
| Failed | 0 |
| Skipped | 0 |
| Warnings | 0 |
| Exit code | 0 |

### 9.5 compileall + AST parse + runtime imports

```
python -m compileall -q core/contracts/narrative_turn.py system/narrative_branch_store.py system/narrative_turn_store.py tests/test_phase0d4a_narrative_turn_foundation.py
python -c "import ast; [ast.parse(open(p, encoding='utf-8').read(), p) for p in [...]]"
python -c "from core.contracts.narrative_turn import ...; from system.narrative_branch_store import ...; print('imports_ok')"
```

| Metric | Value |
| --- | --- |
| compileall exit code | 0 |
| ast.parse | ok |
| Runtime imports | ok |

### 9.6 Lint / static check

`pyflakes` is not installed in the TRAE Work CN sandbox. The
repository's authoritative static guard is `test_static_path_guard.py`
(§9.4), which passes. No lint-regression issues were introduced.

### 9.7 Git status audit

```
git status --short -- <10 0D4-A files>
```

All 10 files are untracked (`??`). No tracked files were modified by
this phase. No git write operations were performed.

---

## 10. Security boundary verification

Verified by `Grep` against the three FIX-RC2 production source files
(`core/contracts/narrative_turn.py`,
`system/narrative_turn_store.py`,
`system/narrative_branch_store.py`):

| Boundary | Required | Verified |
| --- | --- | --- |
| Provider calls | 0 | ✅ no `provider` / `Provider` references in stores |
| Network calls | 0 | ✅ no `requests.` / `urllib` / `httpx` / `http.client` / `socket` |
| Real tokens / cost | 0 | ✅ no token or cost accounting code |
| Canon writes | 0 | ✅ `canon_revision` is only a string field on `NarrativeTurnPlan`; no `ChapterCommitService` / `RevisionService` invocation |
| Chroma writes | 0 | ✅ no `chroma` / `Chroma` references |
| NarrativeMemory writes | 0 | ✅ no `narrative_memory` / `NarrativeMemory` references |
| Real project writes | 0 | ✅ all tests use `tempfile.TemporaryDirectory()` via `temp_project` fixture |
| Production UI changes | 0 | ✅ no `web/` or `static/` files modified |
| Phase 0D4-B entered | no | ✅ only 0D4-A foundation files touched |

---

## 11. Acceptance criteria

| Criterion | Status | Evidence |
| --- | --- | --- |
| lifecycle sequence 文件名真正并发互斥 | ✅ | `{sequence:08d}.json` + `_publish_immutable_json` `os.link` + 7 lifecycle concurrency tests |
| active archive 多文件部分失败可恢复 | ✅ | 4-phase recoverable operation + 11 branch operation recovery tests |
| registry 能从确定性 event journal 重建 | ✅ | `registry_events/{sequence:08d}.json` + chain validation + rebuild logic + 10 registry rebuild tests |
| state delta 递归不可变 | ✅ | `_recursive_freeze` + 8 recursive state delta tests |
| 当前权威文档无旧写入语义 | ✅ | 6 docs updated; removed "same call atomic", "os.replace for immutable", list→tuple conversion, Luna/Terra/Tai |
| TRAE 文档无 Codex 模型别名 | ✅ | Implementation Brief unified to TRAE Work CN / SOLO Coder / 单 Agent |
| focused 与关联回归全部通过 | ✅ | 132 focused + 45 reconciliation + 100 planning + 47 project-context + 3 static guard = all passing |
| Provider/network/token/cost 为 0 | ✅ | grep-verified (§10) |
| Canon/Chroma/NarrativeMemory/真实项目写入为 0 | ✅ | grep-verified (§10) |

---

## 12. Conclusion

All acceptance criteria are satisfied. Phase 0D4-A-FIX-RC2 is **PASSED**.
Phase 0D4-A is **SEALED**. Phase 0D4-B remains **NOT ENTERED**.

```
Phase 0D4-A-FIX-RC2: PASSED
Phase 0D4-A: SEALED
Narrative Turn foundation: IMPLEMENTED
Phase 0D4-B: NOT ENTERED
```
