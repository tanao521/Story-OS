# Phase 0D4-A-FIX-RC Delivery Report

> ```text
> HISTORICAL FIX-RC1 DELIVERY
> SUPERSEDED BY PHASE_0D4-A-FIX-RC2
> NOT AUTHORITATIVE FOR CURRENT IMPLEMENTATION
> ```
>
> Status (historical): **PASSED**
> Date: 2026-07-25
> Authorization: Phase 0D4-A-FIX-RC (Phase 0D4-A marked PARTIALLY PASSED — FIX REQUIRED)
>
> **重要：** 本报告为 Phase 0D4-A-FIX-RC（RC1）的历史交付报告，仅作为
> 历史证据保留。RC1 中描述的 `registry_events/{event_id}.json` 路径、
> `{seq}_{event_id}.json` lifecycle 文件名等已在 RC2 中被替代。当前权威
> 实现以 `PHASE_0D4_A.md`（FIX-RC2-FV 版本）和
> `PHASE_0D4_A_FIX_RC2_DELIVERY_REPORT.md` 为准。

---

## 1. Phase Conclusion

Phase 0D4-A-FIX-RC has been successfully implemented and verified. All
five required fixes (immutable publication, branch lifecycle, strict
types, full-scope operation collision, transition ordering) are
implemented, all focused tests pass, all associated regression suites
pass, all security boundaries remain at zero, and the design documents
are now factually consistent with the code.

**Final State:**
- Phase 0D4-A-FIX-RC: **PASSED**
- Phase 0D4-A: **SEALED**
- Narrative Turn foundation: **IMPLEMENTED**
- Phase 0D4-B: **NOT ENTERED**

---

## 2. Baseline Before Start (audited, not from prior report)

**Git Root:** `d:/novel/StoryOS`
**Branch:** `agent/phase-13-2-memory-repair`
**HEAD commit:** `ebca80b Document conservative DeepSeek token budget gate`

**0D4-A file tracking status (audited via `git status --short`):**
All 0D4-A produced files are untracked (`??`), confirming they were
added by Phase 0D4-A and are not pre-existing tracked files:

```
?? docs/design/simulator_branch_isolation_map.md
?? docs/design/simulator_narrative_turn_contract_map.md
?? docs/design/simulator_narrative_turn_state_machine.md
?? docs/planning/PHASE_0D4_A.md
?? docs/planning/PHASE_0D4_A_DELIVERY_REPORT.md
?? docs/planning/PHASE_0D4_IMPLEMENTATION_BRIEF.md
?? story-os-demo/core/contracts/narrative_turn.py
?? story-os-demo/system/narrative_branch_store.py
?? story-os-demo/system/narrative_turn_store.py
?? story-os-demo/tests/test_phase0d4a_narrative_turn_foundation.py
```

**Other modified tracked files in the working tree** are unrelated to
0D4-A (they pre-date this phase and belong to earlier phases such as
0D3/0C3/0B1 etc.). They are not touched by FIX-RC.

**Audited pre-FIX state of the actual code (not the prior report):**

| Question | Audited answer |
| --- | --- |
| Does the immutable writer use `os.replace`? | **Yes — directly.** Pre-FIX `_publish_immutable_json` did not exist; immutable records were written via a path that allowed `os.replace`-style replacement. Fixed in §4. |
| Does `archive_branch` / `restore_branch` overwrite the branch JSON? | **Pre-FIX:** branch identity and lifecycle were stored on the same JSON, so archive/restore mutated the branch record. Fixed in §5. |
| Does operation collision detection cover cross-branch / cross-timeline? | **Pre-FIX:** operation records were branch-local only (`narrative_turns/{timeline_id}/{branch_id}/operations/`); cross-branch collision was undetectable. Fixed in §7. |
| What is the transition replay ordering rule? | **Pre-FIX:** `iterdir()` order (filesystem-dependent) with `occurred_at` as the implicit ordering hint. Fixed in §8 to deterministic `sequence` ordering with previous-binding chain validation. |
| Are list inputs silently converted to tuples? | **Pre-FIX:** yes — `_to_tuple` accepted `list` and converted. Fixed in §6 to fail-closed. |

---

## 3. OWNER Decision Implementation Matrix (FIX-RC deltas)

| Decision | Status | Implementation |
| --- | --- | --- |
| Immutable publication must be create-if-absent (no `os.replace`) | ✅ | `_publish_immutable_json` in both stores uses `tempfile.mkstemp` + `fsync` + `os.link` (create-if-absent). `os.replace` is only used for mutable projections (`_atomic_write_json`). |
| Mutable projection must use expected-revision CAS + backup | ✅ | `_update_registry` enforces `expected_revision` equality, writes via `_atomic_write_json`, restores from `.bak` on failure. |
| Branch identity record is immutable; lifecycle is derived | ✅ | `NarrativeBranchIdentity` (immutable, no status) + `BranchLifecycleEvent` (append-only journal); `NarrativeBranch.lifecycle_status` is a derived projection. |
| `restore` = `archived → open` only (no auto-select) | ✅ | `restore_branch` appends a lifecycle event and never touches `active_branch_id`. |
| Archive active branch must specify replacement atomically | ✅ | `archive_branch` requires `replacement_branch_id` when archiving the active branch and updates the registry in the same call. |
| List input is fail-closed (no `list → tuple` conversion) | ✅ | `_require_tuple` and `_require_tuple_of_tuples` reject `list` / `dict` with `INVALID_TYPE`. |
| Operation authority is project-root | ✅ | `_operation_authority_path` writes authoritative record at `data/narrative_turn_operations/{operation_id}.json`; branch-local index is a rebuildable projection. |
| Transition ordering is by `sequence`, not `occurred_at` | ✅ | `append_transition` validates contiguous `sequence` + previous binding; `get_transitions` re-validates the chain on every read. |
| Concurrent sequence-slot writes use atomic create-if-absent | ✅ | Sequence-only filename `{sequence:08d}.json` + `_publish_immutable_json` → first writer's `os.link` wins; loser gets `TRANSITION_COLLISION`. |
| `blocked` is terminal; must create new Plan to take different action | ✅ | `_TERMINAL_STATES = {BLOCKED, COMMITTED, SUPERSEDED}`; `_LEGAL_TRANSITIONS` has no exit edge from `BLOCKED`. |

---

## 4. Fix 1 — Immutable publication vs mutable snapshot

### 4.1 `_publish_immutable_json` (in both stores)

Location:
- [story-os-demo/system/narrative_turn_store.py](file:///d:/novel/StoryOS/story-os-demo/system/narrative_turn_store.py) (`_publish_immutable_json`, lines 60-138)
- [story-os-demo/system/narrative_branch_store.py](file:///d:/novel/StoryOS/story-os-demo/system/narrative_branch_store.py) (`_publish_immutable_json`, lines 58-113)

Behavior:

| Scenario | Result |
| --- | --- |
| Target absent | `tempfile.mkstemp` (same dir) → write payload → `flush` → `fsync` → `os.link(temp, target)` → cleanup temp. Atomic create. |
| Target present, identical content | `os.link` raises `FileExistsError`; read existing; byte-equal → silent no-op (idempotent replay). |
| Target present, different content | `os.link` raises `FileExistsError`; read existing; not byte-equal → `IMMUTABLE_RECORD_EXISTS`. |
| `fsync` failure | `OSError` caught → `INVALID_FIELD` raised. No target created (link never reached). |
| `os.link` failure (non-FileExistsError) | `OSError` caught → `INVALID_FIELD` raised. **No fallback to direct write.** |
| Temp file cleanup | `finally` block **always** calls `temp_path.unlink()`; OSError swallowed. |
| Platform durability note | Documented in docstring: Windows NTFS does not guarantee directory entry persistence after file fsync; journal is rebuildable from append-only events. |

**Records published via `_publish_immutable_json`:**
- `NarrativeTurnPlan` — `plans/{turn_id}.json`
- `NarrativeActionValidation` — `validations/{validation_id}.json`
- `NarrativeTurnResult` — `results/{turn_id}.json`
- `NarrativeTurnTransition` — `transitions/{turn_id}/{sequence:08d}.json`
- Project-root operation authority — `narrative_turn_operations/{operation_id}.json`
- `NarrativeBranchIdentity` — `branches/{timeline_id}/branches/{branch_id}.json`
- `BranchLifecycleEvent` — `branches/{timeline_id}/lifecycle_events/{branch_id}/{sequence:08d}_{event_id}.json`
- Registry events — `branches/{timeline_id}/registry_events/{event_id}.json`

### 4.2 `_atomic_write_json` (mutable projection only)

Used **only** for:
- `registry.json` snapshot (active branch pointer)
- Branch-local operation index (rebuildable from project-root authority)

Never used for any record listed in §4.1. Enforced by
`test_os_replace_not_used_for_immutable_records` which monkeypatches
`os.replace` to raise `AssertionError` and confirms a Plan append still
succeeds without invoking it.

---

## 5. Fix 2 — Branch lifecycle immutability

### 5.1 Storage layout

```
data/branches/{timeline_id}/
  branches/{branch_id}.json                    ← immutable identity (published once)
  lifecycle_events/{branch_id}/
    {sequence:08d}_{event_id}.json             ← append-only lifecycle journal
  registry.json                                ← mutable projection (CAS + backup)
  registry_events/{event_id}.json              ← append-only registry events
```

### 5.2 `NarrativeBranchIdentity` (immutable creation record)

Fields: `schema_version`, `branch_id`, `project_id`, `timeline_id`,
`parent_branch_id`, `created_from_turn_id`, `display_name`,
`created_at`, `fingerprint`. **No `lifecycle_status`, no `archived_at`.**

`test_branch_creation_record_never_changes` archives and restores a
branch and asserts the identity file bytes are unchanged.

### 5.3 `BranchLifecycleEvent` (append-only journal)

Fields: `schema_version`, `event_id`, `sequence`, `branch_id`,
`project_id`, `timeline_id`, `from_status`, `to_status`,
`operation_id`, `occurred_at`, `previous_event_fingerprint`,
`record_fingerprint`.

Legal transitions: `open → archived` and `archived → open`.

Chain integrity (verified on every read by `_read_lifecycle_events`):
- `sequence` must be contiguous (0, 1, 2, …); gaps/duplicates raise `LIFECYCLE_EVENT_CHAIN_CORRUPT`.
- `previous_event_fingerprint` must equal the previous event's `record_fingerprint`; mismatch raises `LIFECYCLE_EVENT_CHAIN_CORRUPT`.

### 5.4 `NarrativeBranch` (derived projection)

`lifecycle_status` and `archived_at` are derived by replaying the
lifecycle event journal (`_derive_lifecycle_status`). The dataclass
carries them for read convenience only; they are **never** persisted on
the immutable identity record.

### 5.5 `active_branch_id` rules

- Multiple `open` branches can coexist per timeline.
- Only one `active_branch_id` per timeline registry.
- `select_branch` rejects archived branches (`BRANCH_NOT_ACTIVE`).
- `archive_branch` on the active branch requires `replacement_branch_id`; the registry update happens in the same call (atomic from the caller's perspective).
- `restore_branch` does **not** auto-select the restored branch — verified by `test_restore_does_not_auto_select`.

---

## 6. Fix 3 — Strict input types (fail-closed)

### 6.1 Validators

Location: [story-os-demo/core/contracts/narrative_turn.py](file:///d:/novel/StoryOS/story-os-demo/core/contracts/narrative_turn.py)

```python
def _require_tuple(value: Any, field_name: str) -> tuple:
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        raise NarrativeTurnError(INVALID_TYPE, f"{field_name} must be a tuple, not list; list input is rejected")
    raise NarrativeTurnError(INVALID_TYPE, f"{field_name} must be a tuple, not {type(value).__name__}")

def _require_tuple_of_tuples(value: Any, field_name: str) -> tuple[tuple[Any, ...], ...]:
    if isinstance(value, dict):
        raise NarrativeTurnError(INVALID_TYPE, f"{field_name} must be a tuple of tuples, not dict; dict input is rejected")
    if isinstance(value, list):
        raise NarrativeTurnError(INVALID_TYPE, f"{field_name} must be a tuple of tuples, not list; list input is rejected")
    if not isinstance(value, tuple):
        raise NarrativeTurnError(INVALID_TYPE, f"{field_name} must be a tuple of tuples, not {type(value).__name__}")
    return value
```

`object.__setattr__` is used in `__post_init__` to coerce validated
tuples back onto the frozen dataclass without violating immutability.

### 6.2 Bool / int discipline

`_validate_int` uses `type(value) is not int` (not `isinstance`) so
`bool` is rejected. `test_bool_does_not_pass_as_int` and
`test_bool_not_int` verify this.

### 6.3 Coverage matrix

| Field | Accepted | Rejected (fail-closed) |
| --- | --- | --- |
| `forbidden_patterns: tuple[str, ...]` | `tuple` | `list`, `dict`, `set`, other |
| `feasibility_pipeline: tuple[str, ...]` | `tuple` | `list`, `dict`, `set`, other |
| `required_conditions: tuple[str, ...]` | `tuple` | `list`, `dict`, `set`, other |
| `unavailable_reasons: tuple[str, ...]` | `tuple` | `list`, `dict`, `set`, other |
| `blocking_reasons: tuple[str, ...]` | `tuple` | `list`, `dict`, `set`, other |
| `consequence_flags: tuple[str, ...]` | `tuple` | `list`, `dict`, `set`, other |
| `recommended_actions: tuple[NarrativeActionOption, ...]` | `tuple` | `list`, `dict`, `set`, other |
| `expected_costs: tuple[tuple[str, str], ...]` | `tuple` of `tuple` | `list`, `dict`, `list[list]`, other |
| `expected_risks: tuple[tuple[str, str], ...]` | `tuple` of `tuple` | `list`, `dict`, `list[list]`, other |
| `cost_explanation: tuple[tuple[str, str], ...]` | `tuple` of `tuple` | `list`, `dict`, `list[list]`, other |
| `risk_explanation: tuple[tuple[str, str], ...]` | `tuple` of `tuple` | `list`, `dict`, `list[list]`, other |
| `state_delta_proposal: tuple[tuple[str, Any], ...]` | `tuple` of `tuple` | `list`, `dict`, `list[list]`, other |
| `max_length: int` | `int` (not `bool`) | `bool`, `float`, other |
| `chapter_id: int` | `int` (not `bool`) | `bool`, `float`, other |
| `deterministic_order: int` | `int` (not `bool`) | `bool`, `float`, other |
| `sequence: int` | `int` (not `bool`) | `bool`, `float`, other |

---

## 7. Fix 4 — Full-scope operation collision

### 7.1 Project-root authority

Location: [story-os-demo/system/narrative_turn_store.py](file:///d:/novel/StoryOS/story-os-demo/system/narrative_turn_store.py) (`record_operation`, lines 629-697)

```
data/narrative_turn_operations/{operation_id}.json   ← authoritative
data/narrative_turns/{timeline_id}/{branch_id}/operations/{operation_id}.json  ← branch-local index (rebuildable)
```

Authoritative record fields: `operation_id`, `project_id`,
`timeline_id`, `branch_id`, `turn_id`, `operation_type`,
`payload_fingerprint`, `result_record_path` (relative only),
`created_at`.

### 7.2 Collision rules

| Scenario | Result |
| --- | --- |
| Same `operation_id` + identical scope/turn/type/fingerprint | idempotent replay (silent no-op) |
| Same `operation_id` + different `branch_id` | `OPERATION_COLLISION` (cross-branch) |
| Same `operation_id` + different `timeline_id` | `OPERATION_COLLISION` (cross-timeline) |
| Same `operation_id` + different `turn_id` | `OPERATION_COLLISION` (cross-turn) |
| Same `operation_id` + different `payload_fingerprint` | `OPERATION_COLLISION` (different payload) |
| Project isolation | provided by `ProjectContext.data_dir`; `project_id` still stored and verified on read |

`result_record_path` is always relative (e.g.
`narrative_turns/{timeline_id}/{branch_id}/plan/{turn_id}.json`); absolute
paths are never persisted. Verified by
`test_operation_record_does_not_store_absolute_paths`.

### 7.3 Corruption handling

`get_operation` reads from project-root authority and re-validates
`project_id`. A corrupt JSON record (simulated via monkeypatched
`_load_json` raising `NarrativeTurnError`) propagates as
`NarrativeTurnError` — verified by `test_corrupt_operation_record_fail_closed`.

---

## 8. Fix 5 — Transition deterministic ordering and concurrency

### 8.1 Contract fields

`NarrativeTurnTransition` now includes:
- `sequence: int` — contiguous per turn (0, 1, 2, …)
- `previous_transition_id: str | None` — `None` only for `sequence=0`
- `previous_transition_fingerprint: str | None` — `None` only for `sequence=0`

### 8.2 Storage path

```
data/narrative_turns/{timeline_id}/{branch_id}/transitions/{turn_id}/{sequence:08d}.json
```

Filename is **sequence-only** (e.g. `00000000.json`). This forces two
concurrent writers racing the same next-sequence slot to collide on the
same path, so `_publish_immutable_json` atomically resolves first-wins.

### 8.3 Append validation (`append_transition`)

| Check | Failure code |
| --- | --- |
| `sequence` != `len(existing)` | `TRANSITION_SEQUENCE_COLLISION` |
| `previous_transition_id` != last transition's `transition_id` | `TRANSITION_PREVIOUS_MISMATCH` |
| `previous_transition_fingerprint` != last transition's `record_fingerprint` | `TRANSITION_PREVIOUS_MISMATCH` |
| `from_state` != last transition's `to_state` | `TRANSITION_STALE_FROM_STATE` |
| First transition (`sequence=0`) with non-null previous binding | `TRANSITION_PREVIOUS_MISMATCH` |
| Non-first transition with null previous binding | `TRANSITION_PREVIOUS_MISMATCH` |
| Idempotent replay (same `transition_id` + same fingerprint) | silent no-op |
| Same `transition_id` + different fingerprint | `TRANSITION_COLLISION` |
| Concurrent same-sequence write with different content | `TRANSITION_COLLISION` (via `IMMUTABLE_RECORD_EXISTS` from `_publish_immutable_json`) |

### 8.4 Read validation (`get_transitions`)

On every read:
1. Sort by `sequence` (not `occurred_at`).
2. Verify `sequence` is contiguous (0, 1, 2, …).
3. Verify `previous_transition_id` chain matches actual previous transition's `transition_id`.
4. Verify `previous_transition_fingerprint` chain matches actual previous transition's `record_fingerprint`.

Any break raises `TRANSITION_SEQUENCE_COLLISION` or
`TRANSITION_PREVIOUS_MISMATCH` fail-closed.

### 8.5 `occurred_at` is audit-only

`test_out_of_order_timestamp_does_not_affect_state` appends a chain
with non-monotonic `occurred_at` values and verifies that current state
derivation depends only on `sequence`. This makes the system robust to
clock skew across processes.

---

## 9. Document consistency fixes

### 9.1 [simulator_narrative_turn_contract_map.md](file:///d:/novel/StoryOS/docs/design/simulator_narrative_turn_contract_map.md)

- Removed all "list → tuple conversion" language.
- Added §5 Strict type discipline (FIX-RC) table.
- Split §1.6 into `NarrativeBranchIdentity` (immutable) + `BranchLifecycleEvent` (journal) + `NarrativeBranch` (derived projection).
- Added `sequence`, `previous_transition_id`, `previous_transition_fingerprint` to `NarrativeTurnTransition` (§1.7).
- Added §8 Operation authority (FIX-RC) explaining project-root vs branch-local index.

### 9.2 [simulator_narrative_turn_state_machine.md](file:///d:/novel/StoryOS/docs/design/simulator_narrative_turn_state_machine.md)

- Added `sequence` and `previous binding` columns to §2 Legal transitions.
- Added `OPERATION_COLLISION`, `TRANSITION_SEQUENCE_COLLISION`,
  `TRANSITION_PREVIOUS_MISMATCH`, `TRANSITION_STALE_FROM_STATE` rows to
  §3 Illegal transitions.
- Added sequence-corruption and previous-binding-corruption rows to §4 Recovery.
- Clarified in §5 that `blocked` is terminal; must create a new Plan to take a different action.
- Clarified in §6 that in-flight Plans on branch switch enter `superseded` (not "abandoned").
- Updated §7 transition journal path to `{sequence:08d}.json` and documented chain integrity verification.
- Added §7 Operation Records subsection (project-root authority + relative paths only).
- Updated §8 Concurrency rules to explain sequence-based first-wins and audit-only `occurred_at`.

### 9.3 [simulator_branch_isolation_map.md](file:///d:/novel/StoryOS/docs/design/simulator_branch_isolation_map.md)

- Updated §2.1 storage partitioning to show `branches/`, `lifecycle_events/`, `narrative_turn_operations/`.
- Rewrote §2.2 to split immutable identity record from derived projection; lifecycle is replayed from journal.
- Updated §2.5 Branch operations: archive/restore append lifecycle events (never overwrite identity); restore does not auto-select.
- Updated §2.6 Canon interaction: `included_in_chapter` / `committed` are transition journal entries, NOT flags on Turn records.
- Updated §2.7 Switching context: in-flight Plans enter `superseded` (not "abandoned").

---

## 10. Test coverage

### 10.1 Focused tests

File: [story-os-demo/tests/test_phase0d4a_narrative_turn_foundation.py](file:///d:/novel/StoryOS/story-os-demo/tests/test_phase0d4a_narrative_turn_foundation.py)

**Total: 96 passed, 0 failed, 0 skipped** (pytest exit code 0)

| Class | Tests | Coverage |
| --- | --- | --- |
| `TestContractValidation` | 14 | schema_version, bool/int, empty strings, malformed IDs, malformed hashes, timezone-naive datetime, invalid enums, frozen immutability, action count/order, duplicate IDs/intents, validation XOR, lifecycle consistency |
| `TestStrictTypes` | 13 | list rejected for every tuple field; dict rejected for tuple-of-tuples; tuple accepted; bool rejected as int; unknown enum rejected; serialized shape stability |
| `TestScopeBinding` | 2 | project mismatch, scope.assert_matches |
| `TestPathContainment` | 2 | path traversal, absolute path |
| `TestTurnStore` | 9 | append plan/validation/result/transition, duplicate plan, current state, list plans, record operation, operation collision |
| `TestStateJournal` | 4 | legal transitions (full chain planned→committed), illegal transition, terminal state, transition idempotency |
| `TestImmutablePublication` | 10 | first append, identical replay, conflicting duplicate, target never overwritten, `os.replace` not used, temp cleanup on success, temp cleanup on collision, fsync failure fail-closed, hard-link failure fail-closed, existing content preserved |
| `TestBranchLifecycle` | 21 | create root/child, multiple open branches, select, switch, archive inactive, reject archive active without replacement, archive with replacement, restore, reject selecting archived, parent self, missing parent, revision conflict, identity never changes, archive appends event, restore appends event, derived deterministically, restore does not auto-select, selecting archived rejected, active archive without replacement rejected, active archive with replacement atomic, event chain corruption fail-closed, lifecycle event chain previous binding |
| `TestOperationAuthority` | 7 | same operation replay, cross-branch collision, cross-timeline collision, cross-turn collision, different payload collision, no absolute paths, corrupt record fail-closed |
| `TestTransitionOrdering` | 10 | sequence increments, duplicate sequence rejected, missing sequence rejected, out-of-order timestamp does not affect state, previous ID mismatch, previous fingerprint mismatch, stale from_state, concurrent first-wins, journal replay deterministic, journal corruption fail-closed |
| `TestImmutableFingerprint` | 2 | plan fingerprint, transition fingerprint |

### 10.2 Test-to-requirement traceability

| Requirement (§10.1–10.5 of the brief) | Tests |
| --- | --- |
| §10.1 first append succeeds | `test_first_append_succeeds` |
| §10.1 identical replay succeeds | `test_identical_replay_succeeds` |
| §10.1 conflicting duplicate rejected | `test_conflicting_duplicate_rejected` |
| §10.1 concurrent create first-wins | `test_concurrent_next_transition_first_wins` (for transitions); `test_hard_link_failure_fail_closed` (link path) |
| §10.1 immutable target never overwritten | `test_immutable_target_never_overwritten`, `test_existing_content_preserved_on_collision` |
| §10.1 `os.replace` not used for immutable | `test_os_replace_not_used_for_immutable_records` |
| §10.1 write failure leaves no partial target | `test_fsync_failure_fail_closed`, `test_hard_link_failure_fail_closed` |
| §10.1 existing content preserved | `test_existing_content_preserved_on_collision` |
| §10.1 temp cleanup | `test_temp_cleanup_on_success`, `test_temp_cleanup_on_collision` |
| §10.1 fsync failure fail-closed | `test_fsync_failure_fail_closed` |
| §10.1 hard-link/exclusive-create failure fail-closed | `test_hard_link_failure_fail_closed` |
| §10.2 branch creation record never changes | `test_branch_creation_record_never_changes` |
| §10.2 archive appends event | `test_archive_appends_event` |
| §10.2 restore appends event | `test_restore_appends_event` |
| §10.2 lifecycle derived deterministically | `test_lifecycle_derived_deterministically` |
| §10.2 restore does not automatically select | `test_restore_does_not_auto_select` |
| §10.2 multiple open branches allowed | `test_multiple_open_branches` |
| §10.2 selecting archived rejected | `test_selecting_archived_rejected` |
| §10.2 active archive without replacement rejected | `test_active_archive_without_replacement_rejected` |
| §10.2 active archive with replacement atomic | `test_active_archive_with_replacement_atomic` |
| §10.2 event chain corruption fail-closed | `test_event_chain_corruption_fail_closed` |
| §10.2 lifecycle operation replay/collision | `test_lifecycle_event_chain_previous_binding` |
| §10.3 list rejected for every tuple field | 7 `test_list_rejected_*` tests |
| §10.3 dict/nested mutation isolation | `test_dict_rejected_for_tuple_of_tuples`, `test_external_dict_mutation_does_not_change_contract` |
| §10.3 bool/int | `test_bool_does_not_pass_as_int`, `test_bool_not_int` |
| §10.3 enum/schema | `test_unknown_enum_value_rejected`, `test_schema_version_required` |
| §10.3 serialized shape stability | `test_serialized_shape_stability` |
| §10.4 same operation replay | `test_same_operation_replay` |
| §10.4 cross-branch collision | `test_cross_branch_collision` |
| §10.4 cross-timeline collision | `test_cross_timeline_collision` |
| §10.4 cross-turn collision | `test_cross_turn_collision` |
| §10.4 different payload collision | `test_different_payload_collision` |
| §10.4 corrupt operation record fail-closed | `test_corrupt_operation_record_fail_closed` |
| §10.5 sequence increments | `test_sequence_increments` |
| §10.5 duplicate sequence | `test_duplicate_sequence_rejected` |
| §10.5 missing sequence | `test_missing_sequence_rejected` |
| §10.5 out-of-order timestamp does not affect state | `test_out_of_order_timestamp_does_not_affect_state` |
| §10.5 previous ID mismatch | `test_previous_id_mismatch_rejected` |
| §10.5 previous fingerprint mismatch | `test_previous_fingerprint_mismatch_rejected` |
| §10.5 concurrent next transition first-wins | `test_concurrent_next_transition_first_wins` |
| §10.5 stale from_state | `test_stale_from_state_rejected` |
| §10.5 journal replay deterministic | `test_journal_replay_deterministic` |

---

## 11. Associated regression (audited commands and results)

All commands run from `d:/novel/StoryOS/story-os-demo` with `python -m pytest`. Exit codes are pytest's.

### 11.1 B1-FIX reconciliation / atomic store regression

```
python -m pytest tests/test_phase0d3c4b1_conservative_budget.py -v
```

| Metric | Value |
| --- | --- |
| Passed | 45 |
| Failed | 0 |
| Skipped | 0 |
| Warnings | 1 (Starlette/httpx deprecation, unrelated) |
| Exit code | 0 |

Covers: `ReconciliationStore` atomic write, fsync durability, partial-target prevention, symlink/reparse-point rejection (monkeypatched), bool/int confusion, canonical fingerprint validation.

### 11.2 Planning Control / Rolling Window preview-confirm-replay regression

```
python -m pytest tests/test_planning_control.py tests/test_planning_rolling_window.py tests/test_planning_rolling_lifecycle.py tests/test_planning_rolling_production.py -v
```

| Metric | Value |
| --- | --- |
| Passed | 25 |
| Failed | 0 |
| Skipped | 0 |
| Warnings | 1 |
| Exit code | 0 |

Covers: lazy isolation, conflicts/locks/version restore, API contract, slot create/edit/cancel/blueprint adoption, stale detection, roll-forward preview/confirm/replay, reanchor, refresh, project isolation, optimistic revision conflict, audit failure pending state, frontend lifecycle contract.

### 11.3 ProjectContext / dual-project isolation regression

```
python -m pytest tests/test_phase0c2_project_clone.py tests/test_phase0b2_dual_project_isolation.py tests/test_phase0a_verification.py tests/test_frontend_request_isolation.py -v
```

| Metric | Value |
| --- | --- |
| Passed | 47 |
| Failed | 0 |
| Skipped | 0 |
| Warnings | 0 |
| Exit code | 0 |

Covers: whitelist copy exclusions, state transformation, vector isolation, failure injection, resource release, agents/creative-loop/analytics/author-memory isolation, no cross-project pollution, static path guard integration, content dedup, cross-process idempotency, post-commit compensation, frontend request isolation.

### 11.4 0D4-P / 0D4-A static contract guard

```
python -m pytest tests/test_static_path_guard.py -v
```

| Metric | Value |
| --- | --- |
| Passed | 3 |
| Failed | 0 |
| Skipped | 0 |
| Warnings | 0 |
| Exit code | 0 |

Covers: no hardcoded `data/` paths in production code, no module-level `ProjectContext` caching, web routes use request-level context.

### 11.5 Focused 0D4-A tests (post-FIX)

```
python -m pytest tests/test_phase0d4a_narrative_turn_foundation.py -v
```

| Metric | Value |
| --- | --- |
| Passed | 96 |
| Failed | 0 |
| Skipped | 0 |
| Warnings | 1 |
| Exit code | 0 |

### 11.6 Python compileall + AST parse

```
python -m compileall -q core/contracts/narrative_turn.py system/narrative_turn_store.py system/narrative_branch_store.py tests/test_phase0d4a_narrative_turn_foundation.py
python -c "import ast; [ast.parse(open(p, encoding='utf-8').read(), p) for p in [...]]"
python -c "from core.contracts.narrative_turn import ...; from system.narrative_turn_store import ...; from system.narrative_branch_store import ...; print('imports_ok')"
```

| Metric | Value |
| --- | --- |
| compileall exit code | 0 |
| ast.parse | ok |
| Runtime imports | ok |

### 11.7 Lint / static check

`pyflakes` is not installed in the TRAE SOLO CN sandbox (confirmed:
`No module named pyflakes`). The repository's primary static guard is
`tests/test_static_path_guard.py` (§11.4), which is the project's
authoritative lint-equivalent for path-safety and module-level context
discipline. That guard passes.

### 11.8 Git status / diff inspection

```
git status --short -- <0D4-A file list>
```

All 0D4-A produced files remain untracked (`??`), confirming they are
new files added by Phase 0D4-A and not modifications to pre-existing
tracked files.

Pre-existing tracked-file modifications in the working tree (e.g.
`story-os-demo/commands.py`, `story-os-demo/main.py`,
`story-os-demo/web/routes.py`, etc.) belong to earlier phases and are
**not** touched by FIX-RC. No Git write operations were performed.

---

## 12. Security boundary verification

Verified by `Grep` against the three FIX-RC source files
(`core/contracts/narrative_turn.py`,
`system/narrative_turn_store.py`,
`system/narrative_branch_store.py`).

| Boundary | Required | Verified |
| --- | --- | --- |
| Provider calls | 0 | ✅ no `provider` / `Provider` references in stores; contracts file has none |
| Network calls | 0 | ✅ no `requests.` / `urllib` / `httpx` / `http.client` / `socket` references |
| Real tokens / cost | 0 | ✅ no token or cost accounting code invoked |
| Canon writes | 0 | ✅ `canon_revision` appears only as a string field on `NarrativeTurnPlan`; no `RevisionService` / `ChapterCommitService` invocation |
| Chroma writes | 0 | ✅ no `chroma` / `Chroma` references |
| NarrativeMemory writes | 0 | ✅ no `narrative_memory` / `NarrativeMemory` references |
| Real project writes | 0 | ✅ all tests use `tempfile.TemporaryDirectory()` via `temp_project` fixture |
| Production UI changes | 0 | ✅ no `web/` or `static/` files modified |
| Phase 0D4-B entered | no | ✅ only 0D4-A foundation files touched; no Planner / feasibility / API / UI / NarrativeMemory / Chroma / chapter-committer code added |

---

## 13. Acceptance criteria

| Criterion | Status | Evidence |
| --- | --- | --- |
| immutable record 无覆盖窗口 | ✅ | `_publish_immutable_json` + `test_immutable_target_never_overwritten` + `test_os_replace_not_used_for_immutable_records` |
| Branch 生命周期为 append-only | ✅ | `BranchLifecycleEvent` journal + `test_branch_creation_record_never_changes` + `test_archive_appends_event` + `test_restore_appends_event` |
| list 输入 fail-closed | ✅ | `_require_tuple` / `_require_tuple_of_tuples` + 7 `test_list_rejected_*` tests + `test_dict_rejected_for_tuple_of_tuples` |
| operation collision 覆盖跨 branch/timeline | ✅ | project-root authority + `test_cross_branch_collision` + `test_cross_timeline_collision` + `test_cross_turn_collision` + `test_different_payload_collision` |
| transition sequence 确定且并发 first-wins | ✅ | sequence-only filename + `_publish_immutable_json` + `test_concurrent_next_transition_first_wins` + `test_journal_replay_deterministic` |
| focused 测试通过 | ✅ | 96 passed, 0 failed |
| 所有关联回归通过 | ✅ | reconciliation 45 passed; planning 25 passed; project-context 47 passed; static guard 3 passed |
| 文档事实一致 | ✅ | contract map / state machine / branch isolation map all updated to match code |
| Git 状态准确 | ✅ | all 0D4-A files untracked; pre-existing modifications are unrelated and untouched |
| 所有安全边界保持为 0 | ✅ | see §12 |

---

## 14. Conclusion

All acceptance criteria are satisfied. Phase 0D4-A-FIX-RC is **PASSED**.
Phase 0D4-A is **SEALED**. Phase 0D4-B remains **NOT ENTERED**.

```
Phase 0D4-A-FIX-RC: PASSED
Phase 0D4-A: SEALED
Narrative Turn foundation: IMPLEMENTED
Phase 0D4-B: NOT ENTERED
```
