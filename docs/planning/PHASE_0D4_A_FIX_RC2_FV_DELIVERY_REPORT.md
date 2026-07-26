# Phase 0D4-A-FIX-RC2-FV Delivery Report

> Status: **PASSED**
> Date: 2026-07-25
> Authorization: Phase 0D4-A-FIX-RC2-FV (Final Code-to-Document Fact Verification)
> Execution environment: TRAE Work CN / SOLO Coder / 单 Agent

---

## 0. Final Acceptance

```text
Phase 0D4-A-FIX-RC2-FV: PASSED
Phase 0D4-A-FIX-RC2: ACCEPTED
Phase 0D4-A: SEALED
Narrative Turn foundation: IMPLEMENTED
Phase 0D4-B: NOT ENTERED
```

The acceptance is grounded in the evidence below: real code symbols,
real path/schema/order, real test output, and authoritative document
state. No report was trusted as the answer; every claim was rebuilt
from the actual source files listed in §1.

---

## 1. Files audited (read in full, not from any prior report)

### 1.1 Production code

- [story-os-demo/core/contracts/narrative_turn.py](file:///d:/novel/StoryOS/story-os-demo/core/contracts/narrative_turn.py)
- [story-os-demo/system/narrative_turn_store.py](file:///d:/novel/StoryOS/story-os-demo/system/narrative_turn_store.py)
- [story-os-demo/system/narrative_branch_store.py](file:///d:/novel/StoryOS/story-os-demo/system/narrative_branch_store.py)

### 1.2 Tests

- [story-os-demo/tests/test_phase0d4a_narrative_turn_foundation.py](file:///d:/novel/StoryOS/story-os-demo/tests/test_phase0d4a_narrative_turn_foundation.py)

### 1.3 Authoritative documents (verified clean of legacy facts)

- [docs/design/simulator_branch_isolation_map.md](file:///d:/novel/StoryOS/docs/design/simulator_branch_isolation_map.md)
- [docs/design/simulator_narrative_turn_state_machine.md](file:///d:/novel/StoryOS/docs/design/simulator_narrative_turn_state_machine.md)
- [docs/design/simulator_narrative_turn_contract_map.md](file:///d:/novel/StoryOS/docs/design/simulator_narrative_turn_contract_map.md)
- [docs/planning/PHASE_0D4_A.md](file:///d:/novel/StoryOS/docs/planning/PHASE_0D4_A.md)
- [docs/planning/PHASE_0D4_IMPLEMENTATION_BRIEF.md](file:///d:/novel/StoryOS/docs/planning/PHASE_0D4_IMPLEMENTATION_BRIEF.md)

### 1.4 Historical documents (top-banner verified as superseded)

- [docs/planning/PHASE_0D4_A_DELIVERY_REPORT.md](file:///d:/novel/StoryOS/docs/planning/PHASE_0D4_A_DELIVERY_REPORT.md) — `HISTORICAL INITIAL DELIVERY / SUPERSEDED BY PHASE_0D4-A-FIX-RC2`
- [docs/planning/PHASE_0D4_A_FIX_RC_DELIVERY_REPORT.md](file:///d:/novel/StoryOS/docs/planning/PHASE_0D4_A_FIX_RC_DELIVERY_REPORT.md) — `HISTORICAL FIX-RC1 DELIVERY / SUPERSEDED BY PHASE_0D4-A-FIX-RC2`
- [docs/planning/PHASE_0D4_A_FIX_RC2_DELIVERY_REPORT.md](file:///d:/novel/StoryOS/docs/planning/PHASE_0D4_A_FIX_RC2_DELIVERY_REPORT.md) — current authoritative RC2 report

---

## 2. Active archive real execution order (function-call level)

Audited in [story-os-demo/system/narrative_branch_store.py](file:///d:/novel/StoryOS/story-os-demo/system/narrative_branch_store.py), method `_active_archive_with_replacement` (lines 827–905) and `_resume_active_archive_with_replacement` (lines 905–1055).

### 2.1 Real function call sequence

| Step | Phase | Real function calls (in order) | File:line |
| --- | --- | --- | --- |
| 1 | INTENT | `_make_operation_payload(phase=INTENT, …)` → `_write_operation_phase(operation_id, intent_payload)` (publishes `data/branch_operations/{operation_id}.json` via `_publish_immutable_json`) | 884–897 |
| 2 | INTENT→REGISTRY_UPDATED | `_create_registry_if_missing(timeline_context)` → verify `from_active == target_branch_id` → verify replacement not archived → `_update_registry(timeline_context, expected_revision, {"active_branch_id": replacement_branch_id, …})` (**switches active pointer FIRST**) → `_append_registry_event(event_type="branch_archived", from_active_branch_id=target, to_active_branch_id=replacement, expected_revision, resulting_revision, operation_id)` → `_publish_immutable_json({operation_id}_registry_updated.json, …)` → `_atomic_write_json(op_path, …)` (mutable projection) | 920–969 |
| 3 | REGISTRY_UPDATED→LIFECYCLE_APPENDED | `_derive_lifecycle_status(target)` (idempotent check) → if not archived: `_append_lifecycle_event(target, OPEN→ARCHIVED, operation_id)` (**archives target AFTER active pointer moved**) → `_publish_immutable_json({operation_id}_lifecycle_appended.json, …)` → `_atomic_write_json(op_path, …)` | 989–1019 |
| 4 | LIFECYCLE_APPENDED→COMPLETED | `_publish_immutable_json({operation_id}_completed.json, …)` → `_atomic_write_json(op_path, …)` | 1039–1055 |

### 2.2 Recovery entry points (one per failure point)

| Failure point | Observable state at failure | Recovery entry | Safe? |
| --- | --- | --- | --- |
| During INTENT publish | No operation record yet | Caller retries with same `operation_id`; fresh INTENT write | ✅ active still points to target (OPEN) |
| After INTENT, before REGISTRY_UPDATED | `op.phase == INTENT`, active still on target | `_resume_active_archive_with_replacement` enters at `if op.phase == INTENT` (line 920) | ✅ active on target (OPEN) |
| After `_update_registry`, before `_append_registry_event` | active already on replacement, no event yet | Recovery re-enters at INTENT block; `_update_registry` is CAS-idempotent (same expected_revision fails → caller reads fresh revision); event journal rebuilds from sequence | ✅ active on replacement (OPEN) |
| After `_append_registry_event`, before REGISTRY_UPDATED marker | active on replacement, event appended, marker missing | Re-enter INTENT block: `_update_registry` rejected by CAS (revision already advanced) → caller reads fresh revision and resumes; event journal is the source of truth | ✅ active on replacement (OPEN) |
| After REGISTRY_UPDATED, before LIFECYCLE_APPENDED | active on replacement, target still OPEN | `_resume_active_archive_with_replacement` enters at `if op.phase == REGISTRY_UPDATED` (line 989) | ✅ active on replacement (OPEN); target OPEN but not pointed to |
| After `_append_lifecycle_event`, before LIFECYCLE_APPENDED marker | active on replacement, target ARCHIVED, marker missing | Re-enter REGISTRY_UPDATED block: `_derive_lifecycle_status` returns ARCHIVED → skips re-append, reuses last event fingerprint | ✅ active on replacement; target ARCHIVED but not pointed to |
| After LIFECYCLE_APPENDED, before COMPLETED | active on replacement, target ARCHIVED, marker missing | `_resume_active_archive_with_replacement` enters at `if op.phase == LIFECYCLE_APPENDED` (line 1039) | ✅ active on replacement; target ARCHIVED but not pointed to |

### 2.3 Invariant proof

> **`active_branch_id` never points to an archived branch in any observable or recoverable state.**

- Before REGISTRY_UPDATED: `active_branch_id == target_branch_id` and `target.lifecycle_status == OPEN`. ✅
- After REGISTRY_UPDATED, before LIFECYCLE_APPENDED: `active_branch_id == replacement_branch_id` (replacement verified OPEN at entry); target still OPEN. ✅
- After LIFECYCLE_APPENDED: `active_branch_id == replacement_branch_id`; target ARCHIVED but **not pointed to**. ✅
- After COMPLETED: same as above. ✅

The real code implements the recommended **REGISTRY-FIRST** safe order:

```text
INTENT
→ verify target/replacement
→ _update_registry (active pointer → replacement)
→ _append_registry_event
→ REGISTRY_UPDATED marker
→ _append_lifecycle_event (target OPEN→ARCHIVED)
→ LIFECYCLE_APPENDED marker
→ COMPLETED marker
```

No production code change was required for ordering — the code already
implemented the safe order. Only documents were corrected to match.

---

## 3. BranchOperation path — single authoritative layout

Audited in [story-os-demo/system/narrative_branch_store.py](file:///d:/novel/StoryOS/story-os-demo/system/narrative_branch_store.py), method `_branch_operations_path` (lines 190–195).

### 3.1 Real implementation

```python
def _branch_operations_path(self) -> Path:
    # ``self._project_root`` is already ``data_dir`` (= root / "data"),
    # so branch operations live at ``data/branch_operations/`` (project-root scope).
    path = self._project_root / "branch_operations"
    _validate_path_containment(self._project_root, path)
    return path
```

### 3.2 Authoritative path (single source of truth)

```text
data/branch_operations/{operation_id}.json                       ← main record (mutable projection)
data/branch_operations/{operation_id}_registry_updated.json      ← immutable phase marker
data/branch_operations/{operation_id}_lifecycle_appended.json    ← immutable phase marker
data/branch_operations/{operation_id}_completed.json             ← immutable phase marker
```

### 3.3 Verification matrix

| Question | Real answer |
| --- | --- |
| Is operation scoped by timeline? | **No** — project-root scope (`data/branch_operations/`). `operation_id` collision is detected project-wide. |
| What is the collision scope of `operation_id`? | **Project-wide** across branches, timelines, turns, payloads. |
| Which directory does the recovery scanner read? | `_branch_operations_path()` returns `data/branch_operations/`; marker files are siblings of the main record. |
| Is the path constrained by project root? | **Yes** — `_validate_path_containment(self._project_root, path)` enforces resolved-path containment. |
| Are absolute paths stored? | **No** — operation records store only `operation_id` and relative layout; paths are reconstructed from `self._project_root`. |
| Where are marker files? | Same directory as main record: `data/branch_operations/{operation_id}_*.json`. |
| How is a corrupted projection rebuilt? | From the three immutable phase markers (`_registry_updated`, `_lifecycle_appended`, `_completed`), each published via `_publish_immutable_json` (create-if-absent). |

### 3.4 Document synchronization

All documents now use the single path `data/branch_operations/{operation_id}*.json`. No document retains the alternate `data/branches/{timeline_id}/branch_operations/` layout. Verified by static doc-contract test `test_branch_operation_path_matches_authoritative_layout` and `test_phase_document_paths_match_store_constants`.

---

## 4. RegistryEvent contract — explicit-field schema (Plan A)

Audited in [story-os-demo/core/contracts/narrative_turn.py](file:///d:/novel/StoryOS/story-os-demo/core/contracts/narrative_turn.py) (`RegistryEvent` dataclass) and [story-os-demo/system/narrative_branch_store.py](file:///d:/novel/StoryOS/story-os-demo/system/narrative_branch_store.py) (`_append_registry_event` lines 267–330, `_read_registry_events` lines 206–265).

### 4.1 Real dataclass schema

```python
@dataclass(frozen=True)
class RegistryEvent:
    schema_version: str
    event_id: str
    sequence: int                          # 0, 1, 2, ...; contiguous per timeline
    project_id: str
    timeline_id: str
    event_type: str                        # "branch_created"|"branch_selected"|"branch_archived"
    from_active_branch_id: str | None      # active pointer before this event
    to_active_branch_id: str | None        # active pointer after this event
    expected_revision: str                 # CAS revision read before applying
    resulting_revision: str                # CAS revision written after applying
    operation_id: str | None               # bound branch operation, if any
    occurred_at: str                       # ISO8601 UTC (audit only; not ordering key)
    previous_event_id: str | None          # chain binding; None for sequence=0
    previous_event_fingerprint: str | None # chain binding; None for sequence=0
    record_fingerprint: str                # sha256 of all fields except this one
```

### 4.2 Schema is explicit-field, not generic payload

The contract uses **Plan A** (explicit fields). `from_active_branch_id`,
`to_active_branch_id`, `expected_revision`, `resulting_revision` are
**first-class required fields** on the dataclass and in the serialized
JSON. They are NOT optional dict keys inside a `payload` blob.

### 4.3 Deterministic rebuild uses required revision fields

`_rebuild_registry_from_journal` (audited) replays events in `sequence`
order and applies `from_active_branch_id` → `to_active_branch_id` +
`resulting_revision` to reconstruct the registry snapshot. Because
these fields are required (not optional), rebuild is deterministic and
does not depend on unvalidated dict keys.

### 4.4 Serialization / chain validation

| Property | Real enforcement |
| --- | --- |
| schema_version | `SCHEMA_VERSION` constant, validated on read |
| event_type | Literal set: `branch_created`, `branch_selected`, `branch_archived` |
| sequence | Contiguous from 0; gap/duplicate → `REGISTRY_EVENT_CHAIN_CORRUPT` |
| project_id / timeline_id | Validated as path components (`^[A-Za-z0-9_-]+$`) |
| from/to active branch | Required fields (may be `None` only when semantically valid) |
| expected/resulting revision | Required strings; CAS enforced by `_update_registry` |
| operation binding | `operation_id` field (nullable) |
| previous chain | `previous_event_id` + `previous_event_fingerprint`; mismatch → `REGISTRY_EVENT_CHAIN_CORRUPT` |
| record fingerprint | sha256 of all fields except `record_fingerprint`; canonical JSON (`sort_keys=True, ensure_ascii=False`) |
| deterministic serialization | `_canonical_json` (sorted keys, UTF-8, 2-space indent) |
| filename | `registry_events/{sequence:08d}.json` (sequence-only, no event_id) |

Verified by `test_registry_event_serialized_schema_matches_contract` and `test_registry_rebuild_uses_required_revision_fields`.

---

## 5. Document corrections applied during FV

### 5.1 `PHASE_0D4_A.md`

- Status header updated to `Phase 0D4-A-FIX-RC2: PASSED` / `Phase 0D4-A: SEALED` / `Phase 0D4-B: NOT ENTERED`.
- Added §4.3 "Path constants (authoritative)" — flat list of all real paths, asserted by static doc-contract test `test_phase_document_paths_match_store_constants`.
- All paths now match store constants:
  - `data/narrative_turns/{timeline_id}/{branch_id}/transitions/{turn_id}/{sequence:08d}.json`
  - `data/branches/{timeline_id}/lifecycle_events/{branch_id}/{sequence:08d}.json`
  - `data/branches/{timeline_id}/registry_events/{sequence:08d}.json`
  - `data/narrative_turn_operations/{operation_id}.json` (Turn operation authority)
  - `data/branch_operations/{operation_id}*.json` (Branch operation authority)
- Immutable publication documented as `_publish_immutable_json` + `os.link` (create-if-absent).
- Registry mutable projection documented as `_atomic_write_json` + expected-revision CAS + `.bak` recovery.
- Recursive state delta documented as `tuple[tuple[str, FrozenValue], ...]` with `_recursive_freeze`.
- Recovery protocol documented with four phases and seven recovery entry points.

### 5.2 `PHASE_0D4_A_DELIVERY_REPORT.md` (initial, historical)

- Top banner: `HISTORICAL INITIAL DELIVERY / SUPERSEDED BY PHASE_0D4-A-FIX-RC2 / NOT AUTHORITATIVE FOR CURRENT IMPLEMENTATION`.
- Explicit list of superseded facts retained only as history:
  - `os.replace` for immutable write → replaced by `_publish_immutable_json` + `os.link`
  - `list → tuple` conversion → replaced by fail-closed `_require_tuple`
  - `{transition_id}.json` filename → replaced by `{sequence:08d}.json`
  - `{event_id}.json` registry filename → replaced by `{sequence:08d}.json`
  - mutable branch lifecycle → replaced by append-only lifecycle event journal
  - 46 passed → replaced by 138 passed

### 5.3 `PHASE_0D4_A_FIX_RC_DELIVERY_REPORT.md` (RC1, historical)

- Top banner: `HISTORICAL FIX-RC1 DELIVERY / SUPERSEDED BY PHASE_0D4-A-FIX-RC2`.

### 5.4 `PHASE_0D4_IMPLEMENTATION_BRIEF.md`

- Replaced `Turn records flagged included_in_chapter → committed` with:
  ```text
  append included_in_chapter transition
  → append committed transition after ChapterCommitService succeeds
  ```
  Turn record itself remains immutable.
- Environment unified to `TRAE Work CN / SOLO Coder / 单 Agent`. No Luna/Terra/Tai Codex model aliases remain.

### 5.5 `simulator_branch_isolation_map.md`

- Active archive order rewritten to REGISTRY-FIRST (matches §2 of this report).
- Branch operation path unified to `data/branch_operations/{operation_id}*.json`.
- Registry event JSON example updated to the full explicit-field schema (§4.1).
- Lifecycle/registry sequence-only paths corrected.
- Recovery marker paths corrected.
- Removed the unsafe phase table that conflicted with the active-pointer invariant; replaced with the four-phase REGISTRY-FIRST table.

### 5.6 `simulator_narrative_turn_state_machine.md`

- Immutable Turn record documented.
- Sequence transition journal documented (`{sequence:08d}.json` + previous binding).
- Project-root Turn operation authority documented (`data/narrative_turn_operations/{operation_id}.json`).
- `included_in_chapter` / `committed` documented as transitions only (Turn record stays immutable).
- Branch operation section references real paths and real execution order.

### 5.7 `simulator_narrative_turn_contract_map.md`

- `RegistryEvent` dataclass updated to the explicit-field schema (§4.1).
- `BranchOperationRecord` phase enum updated to `INTENT / REGISTRY_UPDATED / LIFECYCLE_APPENDED / COMPLETED`.
- Phase names and execution order aligned with code.
- `state_delta_proposal` documented as `tuple[tuple[str, FrozenValue], ...]` with `_recursive_freeze` validator.

---

## 6. Fact-locking tests added

Class `TestFactLockingFixRC2FV` in [story-os-demo/tests/test_phase0d4a_narrative_turn_foundation.py](file:///d:/novel/StoryOS/story-os-demo/tests/test_phase0d4a_narrative_turn_foundation.py).

| Test | Locks | Result |
| --- | --- | --- |
| `test_active_archive_switches_registry_before_archiving_target` | REGISTRY-FIRST order: when `_append_lifecycle_event` is monkeypatched to fail, `active_branch_id` has already switched to replacement and target remains OPEN | PASSED |
| `test_active_pointer_never_targets_archived_branch_after_each_failure_point` | After each of the seven failure points (§2.2), `active_branch_id` never equals an archived branch | PASSED |
| `test_branch_operation_path_matches_authoritative_layout` | Operation record + three phase markers live at `data/branch_operations/{operation_id}*.json`; path is project-root, not timeline-scoped | PASSED |
| `test_registry_event_serialized_schema_matches_contract` | Serialized JSON contains all explicit fields (Plan A); no generic `payload` field | PASSED |
| `test_registry_rebuild_uses_required_revision_fields` | Rebuild consumes `from_active_branch_id`, `to_active_branch_id`, `expected_revision`, `resulting_revision` as required fields | PASSED |
| `test_phase_document_paths_match_store_constants` | `PHASE_0D4_A.md` §4.3 contains the exact path literals used by the stores | PASSED |

---

## 7. Verification runs

### 7.1 0D4-A focused tests

```text
cd d:\novel\StoryOS\story-os-demo
python -m pytest tests/test_phase0d4a_narrative_turn_foundation.py -v
============================ 138 passed in 12.70s =============================
```

Breakdown:
- Contract validation (strict types, frozen, enums)
- Immutable publication (create-if-absent, idempotent replay, collision)
- Branch lifecycle (append-only events, derived projection)
- Operation authority (project-root, cross-scope collision)
- Transition ordering (sequence, previous binding, concurrent first-wins)
- `TestLifecycleConcurrency` — sequence-only filenames, concurrent first-wins
- `TestBranchOperationRecovery` — active archive recovery, invariant
- `TestRegistryRebuild` — journal replay, snapshot recovery, chain corruption
- `TestRecursiveStateDelta` — nested mutation isolation, fail-closed
- `TestFactLockingFixRC2FV` — six new fact-locking tests

### 7.2 Active archive recovery (subset)

All `TestBranchOperationRecovery` tests pass:
- `test_active_archive_completes_successfully`
- `test_retry_after_intent_phase_succeeds`
- `test_retry_after_registry_update_succeeds`
- `test_failure_after_registry_before_lifecycle_recovery`
- `test_recovery_does_not_create_second_archive_event`
- `test_concurrent_archive_operations_conflict`
- `test_replacement_archived_during_operation`
- `test_expected_registry_revision_stale`
- `test_same_operation_id_different_replacement`
- `test_invariant_active_never_points_to_archived`
- `test_operation_record_persists_all_phases`

### 7.3 Registry rebuild (subset)

All `TestRegistryRebuild` tests pass:
- `test_registry_events_sequence_ordered`
- `test_rebuild_registry_from_events`
- `test_deleted_registry_snapshot_recovery`
- `test_corrupt_registry_snapshot_recovery`
- `test_event_gap_fail_closed`
- `test_duplicate_sequence_fail_closed`
- `test_previous_fingerprint_mismatch_fail_closed`
- `test_non_monotonic_timestamps`
- `test_concurrent_selection_first_wins`
- `test_projection_journal_mismatch_fail_closed`

### 7.4 Recursive state delta (subset)

All `TestRecursiveStateDelta` tests pass:
- `test_nested_dict_mutation_isolation`
- `test_nested_list_rejected`
- `test_nested_dict_inside_tuple`
- `test_nan_infinity_rejected`
- `test_unsupported_custom_object_rejected`
- `test_excessive_nesting_rejected`
- `test_deterministic_key_order`
- `test_same_semantic_value_same_fingerprint`

### 7.5 B1-FIX store regression + Planning Control / Rolling Window + ProjectContext isolation + static path guard

```text
cd d:\novel\StoryOS\story-os-demo
python -m pytest tests/test_phase0d3c4b1_conservative_budget.py tests/test_planning_control.py tests/test_planning_rolling_window.py tests/test_phase0c1_vector_isolation.py tests/test_static_path_guard.py -q
160 passed, 2 skipped, 1 warning in 27.34s
```

The single warning is an unrelated Starlette/httpx deprecation from
`fastapi.testclient`; it does not touch 0D4-A code.

### 7.6 compileall

```text
python -m compileall core/contracts/narrative_turn.py system/narrative_turn_store.py system/narrative_branch_store.py
# exit 0, no output
```

### 7.7 AST parse

```text
python -c "import ast; [ast.parse(open(p, encoding='utf-8').read()) for p in ['core/contracts/narrative_turn.py', 'system/narrative_turn_store.py', 'system/narrative_branch_store.py']]; print('AST parse OK')"
AST parse OK
```

### 7.8 Runtime imports

```text
python -c "from core.contracts.narrative_turn import NarrativeTurnPlan, RegistryEvent, BranchOperationPhase; from system.narrative_turn_store import NarrativeTurnStore; from system.narrative_branch_store import NarrativeBranchStore; print('Imports OK')"
Imports OK
```

### 7.9 Document old-fact search (authoritative docs)

Searched the five authoritative documents for the seven forbidden patterns:

```text
FIX-RC2 Status: IN PROGRESS
transitions/{turn_id}/{transition_id}.json
registry_events/{event_id}.json
immutable + os.replace
Turn records flagged included_in_chapter
Turn records flagged committed
same method call therefore atomic
```

Result: **0 matches** in
- `docs/planning/PHASE_0D4_A.md`
- `docs/planning/PHASE_0D4_IMPLEMENTATION_BRIEF.md`
- `docs/design/simulator_branch_isolation_map.md`
- `docs/design/simulator_narrative_turn_state_machine.md`
- `docs/design/simulator_narrative_turn_contract_map.md`

### 7.10 Historical reports (allowed to retain old facts, must be bannered)

Matches were found only in the three historical reports, all of which
carry the required superseded banner at the top:

- `PHASE_0D4_A_DELIVERY_REPORT.md` — banner lines 3–7; old paths at lines 168, 177 are inside the explicitly-superseded §6.
- `PHASE_0D4_A_FIX_RC_DELIVERY_REPORT.md` — banner lines 3–7.
- `PHASE_0D4_A_FIX_RC2_DELIVERY_REPORT.md` — uses the forbidden phrases only in "Before:" / "❌ Removed:" contexts (lines 173, 311–314), documenting what was changed, not what is authoritative.

This complies with §10 of the FV authorization: historical reports may
retain old facts if their tops are clearly marked as superseded.

---

## 8. Security boundaries

| Boundary | Verified value | Evidence |
| --- | --- | --- |
| Provider calls | 0 | `grep` for `requests/httpx/aiohttp/socket/urllib/chromadb/openai/anthropic/http.client` in `narrative_turn.py`, `narrative_turn_store.py`, `narrative_branch_store.py` → no matches (only `_canonical_json` helper matches the pattern `canonical`, which is a JSON serializer, not a provider) |
| Network | 0 | Same grep — no network primitives |
| Real tokens/cost | 0 | No provider calls → no tokens consumed |
| Canon writes | 0 | `canon_revision` appears only as a string field name on `NarrativeTurnPlan` (read-only metadata); no Canon store writes |
| Chroma writes | 0 | No `chromadb` imports or references in any audited file |
| NarrativeMemory writes | 0 | No `narrative_memory` references in any audited file |
| Real project writes | 0 | All tests use `tempfile.TemporaryDirectory()` via `temp_project` fixture; no access to `story-os-demo/data/` |
| Production UI changes | 0 | No UI files modified; git status shows only 0D4-A code/docs/test files (all untracked `??`) |
| Phase 0D4-B entered | No | No Planner / feasibility / API / UI / NarrativeMemory / Chroma code added |

### 8.1 `os.replace` usage audit

`os.replace` appears in the audited code only in mutable-projection paths, never for immutable records:

- `narrative_turn_store.py:161` — inside `_atomic_write_json` (mutable projection only)
- `narrative_branch_store.py:126` — inside `_atomic_write_json` (mutable projection only)
- `narrative_branch_store.py:435,441` — registry `.bak` backup/restore for `_update_registry` CAS recovery

All immutable records (`NarrativeTurnPlan`, `NarrativeActionValidation`,
`NarrativeTurnResult`, `NarrativeTurnTransition`, `NarrativeBranchIdentity`,
`BranchLifecycleEvent`, `RegistryEvent`, branch operation phase markers,
Turn operation authority) are published via `_publish_immutable_json`
(`tempfile.mkstemp` + `fsync` + `os.link` create-if-absent). This is
enforced by `test_os_replace_not_used_for_immutable_records`.

### 8.2 Git status

All 0D4-A produced files are untracked (`??`), confirming they were
added by Phase 0D4-A and are not pre-existing tracked files. The few
modified tracked files (`M`) are unrelated to 0D4-A (they pre-date this
phase and belong to earlier phases such as 0D3/0C3/0B1). No Git write
operations (add/commit/push/reset/clean/stash/rebase) were performed.

---

## 9. Decision records

| # | Decision | Rationale |
| --- | --- | --- |
| 1 | No production code change for active archive ordering | Real code already implements REGISTRY-FIRST safe order; only documents needed correction. |
| 2 | Use explicit-field RegistryEvent schema (Plan A) | Real dataclass already uses explicit fields; deterministic rebuild requires `from/to_active_branch_id` + `expected/resulting_revision` as first-class fields, not optional dict keys. |
| 3 | Branch operations are project-root scoped, not timeline-scoped | `operation_id` collision must be detected project-wide; layout `data/branch_operations/{operation_id}*.json` matches real `_branch_operations_path`. |
| 4 | Historical reports retained with superseded banners | Per §10 of FV authorization, old facts may remain in historical reports if tops are clearly marked. |
| 5 | Static doc-contract test (`test_phase_document_paths_match_store_constants`) | Prevents path drift between code and `PHASE_0D4_A.md` without relying on human memory. |
| 6 | FV report is the new authoritative document | Supersedes any conflicting statement in earlier reports; in case of conflict, code + this report win. |

---

## 10. Completion criteria

All criteria from §12 of the FV authorization are met:

- ✅ Real code uses REGISTRY-FIRST safe order (active pointer invariant holds at every failure point).
- ✅ RegistryEvent can deterministically rebuild the registry (explicit required fields + sequence chain).
- ✅ BranchOperation path is unified to `data/branch_operations/{operation_id}*.json`.
- ✅ All three design documents match real code (paths, phases, schema, order).
- ✅ `PHASE_0D4_A.md` updated to SEALED with real path constants.
- ✅ Initial delivery report bannered as superseded.
- ✅ Implementation Brief updated for transition-based `included_in_chapter` / `committed`.
- ✅ Six fact-locking tests added and passing.
- ✅ All focused tests pass (138).
- ✅ All regression tests pass (160 passed, 2 skipped).
- ✅ compileall / AST parse / runtime imports OK.
- ✅ Authoritative documents contain zero forbidden legacy phrases.
- ✅ All security boundaries at 0.
- ✅ Phase 0D4-B not entered.

---

## 11. Conclusion

```text
Phase 0D4-A-FIX-RC2-FV: PASSED
Phase 0D4-A-FIX-RC2: ACCEPTED
Phase 0D4-A: SEALED
Narrative Turn foundation: IMPLEMENTED
Phase 0D4-B: NOT ENTERED
```

The Narrative Turn foundation is now sealed with code, tests, and all
authoritative documents in full factual agreement. Phase 0D4-B remains
unauthorized and was not entered.
