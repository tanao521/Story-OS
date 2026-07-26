# Phase 0D4-B — Delivery Report (including 0D4-B-FIX-RC and 0D4-B-FIX-RC-FV)

> Phase: 0D4-B
> Title: Deterministic Narrative Turn Planner, Action Feasibility & Read-Only Preview
> Status: **SEALED**
> Date: 2026-07-25

## 1. Executive Summary

Phase 0D4-B delivers the deterministic, read-only planning layer for
Narrative Turn. All four core components are implemented with strict
separation of concerns and comprehensive test coverage.

Phase 0D4-B-FIX-RC closed 6 issues from the PARTIALLY PASSED verdict:
cold-start read-only enforcement, complete context fingerprint,
deep-immutability closure, strict canonical serialization, branch-state
isolation, and documentation/test-count consistency.

Phase 0D4-B-FIX-RC-FV locked 4 fact-verification issues: branch-state
path authority, custom action length single source of truth, missing vs
invalid distinction, and test-count self-verification.

**Status: SEALED — all acceptance criteria met, all 6 FIX-RC issues closed, all 4 FIX-RC-FV facts locked.**

## 2. Deliverables

### 2.1 Core implementation (4 modules + 1 contract)

| Module | Lines | Purpose |
| --- | --- | --- |
| `system/narrative_turn_context.py` | ~750 | Context Binder + deep-immutable snapshot + strict canonical fingerprint + cold-start read-only |
| `system/narrative_turn_planner.py` | ~260 | Deterministic planner (3 recommended actions) |
| `system/narrative_action_feasibility.py` | ~420 | 14-step feasibility pipeline + custom action normalization |
| `system/narrative_turn_preview.py` | ~180 | Read-only qualitative preview |
| `core/contracts/narrative_turn_preview.py` | ~80 | Preview DTO + fingerprint utility |

### 2.2 Tests

| File | Count |
| --- | --- |
| `tests/test_phase0d4b_narrative_turn_planner.py` | 124 focused tests (85 original + 26 FIX-RC + 13 FIX-RC-FV) |

### 2.3 Documentation

| Document | Path |
| --- | --- |
| Planner design doc | `docs/design/simulator_narrative_turn_planner.md` |
| Feasibility design doc | `docs/design/simulator_action_feasibility.md` |
| Phase document | `docs/planning/PHASE_0D4_B.md` |
| Delivery report | `docs/planning/PHASE_0D4_B_DELIVERY_REPORT.md` |
| Implementation brief | `docs/planning/PHASE_0D4_IMPLEMENTATION_BRIEF.md` |

## 3. Acceptance Criteria Verification

### 3.1 Functional requirements

| Criterion | Status | Evidence |
| --- | --- | --- |
| Context binding is strict (fail-closed) | ✅ PASS | 16 context tests including all error codes |
| Exactly 3 deterministic actions | ✅ PASS | Planner tests verify count, order, uniqueness |
| Action IDs are stable | ✅ PASS | Same-input-same-ID tests for turn_id + action_id |
| Options have semantic distinction | ✅ PASS | Unique intent + different categories tests |
| Custom action not executed as command | ✅ PASS | Normalization tests + security tests |
| Feasibility produces 4 statuses | ✅ PASS | All 4 statuses verified in feasibility tests |
| Insufficient evidence → requires_clarification | ✅ PASS | Ambiguous target/object tests |
| Preview is fully read-only | ✅ PASS | No-store-writes test + code audit |
| NarrativeTurnStore.append not called | ✅ PASS | Integration test verifies no append_plan call |

### 3.2 FIX-RC closure criteria

| Criterion | Status | Evidence |
| --- | --- | --- |
| Cold-start read-only (no file writes by `bind()`) | ✅ PASS | `TestColdStartReadOnly` (6 tests) — filesystem snapshot before/after |
| Complete context fingerprint (18 authority inputs) | ✅ PASS | `TestCompleteFingerprint` (4 tests) — each input change alters fingerprint |
| Deep immutability (no mutable references in Snapshot) | ✅ PASS | `TestDeepImmutability` (5 tests) — mutation after bind has no effect |
| Strict canonical serialization (no `default=str`) | ✅ PASS | `TestStrictCanonicalSerialization` (7 tests) — NaN/Path/set rejected |
| Branch state isolation (no legacy flat path) | ✅ PASS | `TestBranchStateIsolation` (4 tests) — branch-scoped only |
| Documentation/test count consistency | ✅ PASS | All documents reflect 124 focused + accurate regression counts |

### 3.2.1 FIX-RC-FV closure criteria

| Criterion | Status | Evidence |
| --- | --- | --- |
| Branch-state path authority (single authorized path) | ✅ PASS | `TestFactLockBranchStatePath` (2 tests) — code & doc use branch-scoped path |
| Custom action length single source of truth (200) | ✅ PASS | `TestFactLockCustomActionLength` (6 tests) — constant == policy == doc |
| Missing vs invalid distinction (no silent masking) | ✅ PASS | `TestFactLockMissingVsInvalid` (4 tests) — distinct limitation codes |
| Test-count self-verification | ✅ PASS | `TestFactLockTestCount` (1 test) — `pytest --collect-only` matches doc |

### 3.3 Security boundaries

| Boundary | Status | Evidence |
| --- | --- | --- |
| Provider calls: 0 | ✅ PASS | Code audit (no Provider imports) + security test |
| Network calls: 0 | ✅ PASS | Network monkeypatch canary tests (4) |
| Real tokens/cost: 0 | ✅ PASS | No Provider, no network |
| Canon writes: 0 | ✅ PASS | No Canon write paths in 0D4-B code; reads `canon_versions/chapter_NNN/index.json` directly |
| Chroma writes: 0 | ✅ PASS | No Chroma imports |
| NarrativeMemory writes: 0 | ✅ PASS | Reads branch-scoped state only; never writes |
| Branch lifecycle writes: 0 | ✅ PASS | `bind()` reads branch info via journal events; no `_create_registry_if_missing` |
| NarrativeTurnStore writes: 0 | ✅ PASS | `append_plan` never called |
| Production UI changes: 0 | ✅ PASS | No web/ routes or templates modified |
| HTTP route changes: 0 | ✅ PASS | No `web/routes.py` changes |
| New dependencies: 0 | ✅ PASS | No new imports outside stdlib + existing modules |
| Git write operations: 0 | ✅ PASS | No add/commit/push/reset/clean/stash/rebase executed |

### 3.4 Determinism guarantees

| Property | Status | Evidence |
| --- | --- | --- |
| Same context → same fingerprint | ✅ PASS | `test_same_context_same_fingerprint` |
| Same context → same plan | ✅ PASS | `test_same_input_same_plan` |
| Same context → same action_ids | ✅ PASS | `test_stable_action_ids` |
| Clock injection doesn't change IDs | ✅ PASS | `test_clock_does_not_change_ids` |
| Planner revision changes IDs | ✅ PASS | `test_planner_revision_changes_ids` |
| Same input → same validation | ✅ PASS | Integration determinism test |
| Same input → same preview fingerprint | ✅ PASS | Integration determinism test |
| Mutating original data after bind → no fingerprint change | ✅ PASS | `TestDeepImmutability` (5 tests) |
| Same dict with different insertion order → same fingerprint | ✅ PASS | `test_key_order_invariant` |

## 4. Test Results

### 4.1 Focused tests (0D4-B + 0D4-B-FIX-RC + 0D4-B-FIX-RC-FV)

```
124 passed
======
Original 0D4-B (85):
  TestContextBinder:               16 passed
  TestDeterministicPlanner:        17 passed
  TestRecommendedFeasibility:       6 passed
  TestCustomActionNormalization:   14 passed
  TestCustomActionFeasibility:     10 passed
  TestReadOnlyPreview:              9 passed
  TestSecurityBoundaries:           8 passed
  TestIntegrationReadOnlyFlow:      5 passed

FIX-RC additions (26):
  TestColdStartReadOnly:                6 passed
  TestDeepImmutability:                 5 passed
  TestStrictCanonicalSerialization:     7 passed
  TestBranchStateIsolation:             4 passed
  TestCompleteFingerprint:              4 passed

FIX-RC-FV additions (13):
  TestFactLockBranchStatePath:          2 passed
  TestFactLockCustomActionLength:       6 passed
  TestFactLockMissingVsInvalid:         4 passed
  TestFactLockTestCount:                1 passed
```

Command:
```
cd story-os-demo
python -m pytest tests/test_phase0d4b_narrative_turn_planner.py -v
```
Exit code: 0

### 4.2 Regression tests

| Suite | File | Count | Passed | Failed | Skipped | Warnings | Exit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0D4-A foundation | test_phase0d4a_narrative_turn_foundation.py | 138 | 138 | 0 | 0 | 0 | 0 |
| ProjectContext isolation | test_phase0b2_dual_project_isolation.py | 15 | 15 | 0 | 0 | 0 | 0 |
| Vector isolation | test_phase0c1_vector_isolation.py | 28 | 28 | 0 | 0 | 0 | 0 |
| Static path guard | test_static_path_guard.py | 3 | 3 | 0 | 0 | 0 | 0 |
| Planning rolling window | test_planning_rolling_window.py | 5 | 5 | 0 | 0 | 1 | 0 |
| Planning control | test_planning_control.py | 3 | 3 | 0 | 0 | 1 | 0 |
| Version manager | test_version_manager.py | 8 | 8 | 0 | 0 | 0 | 0 |
| Revision service | test_revision_service.py | 4 | 4 | 0 | 0 | 0 | 0 |
| Commit selected version | test_commit_selected_version.py | 3 | 3 | 0 | 0 | 0 | 0 |
| Planning dependencies | test_planning_dependencies.py | 7 | 7 | 0 | 0 | 1 | 0 |
| **Non-0D4-A total** | | **76** | **76** | **0** | **0** | **3** | **0** |

Commands run (each with exit code 0):
```
python -m pytest tests/test_phase0d4a_narrative_turn_foundation.py --no-header -q
python -m pytest tests/test_phase0b2_dual_project_isolation.py --no-header -q
python -m pytest tests/test_phase0c1_vector_isolation.py --no-header -q
python -m pytest tests/test_static_path_guard.py --no-header -q
python -m pytest tests/test_planning_rolling_window.py --no-header -q
python -m pytest tests/test_planning_control.py --no-header -q
python -m pytest tests/test_version_manager.py --no-header -q
python -m pytest tests/test_revision_service.py --no-header -q
python -m pytest tests/test_commit_selected_version.py --no-header -q
python -m pytest tests/test_planning_dependencies.py --no-header -q
```

Warnings are Starlette `httpx` deprecation warnings unrelated to 0D4-B code.

### 4.3 Static checks

| Check | Command | Result |
| --- | --- | --- |
| compileall | `python -m compileall system/narrative_turn_context.py system/narrative_turn_planner.py system/narrative_action_feasibility.py system/narrative_turn_preview.py core/contracts/narrative_turn.py core/contracts/narrative_turn_preview.py` | Passed (exit 0) |
| AST parse | `python -c "import ast; [ast.parse(...)]"` (7 files) | Passed |
| Runtime imports | `python -c "from system.narrative_turn_context import ...; ..."` | Passed |
| Cold-start no-diff | `TestColdStartReadOnly` (6 tests) | Passed |
| No absolute paths in output | Security test | Passed |
| No raw exception leak | Security test | Passed |

## 5. Known Limitations

1. **Keyword-based action extraction**: The feasibility engine uses
   exact/substring keyword matching for verb and entity extraction.
   It does not perform semantic understanding. Unrecognized input
   returns `requires_clarification`.

2. **Qualitative preview only**: Preview output is descriptive and
   qualitative. It does not generate narrative prose, compute
   probabilities, or predict specific numeric outcomes.

3. **v1 candidate coverage**: The planner generates 8 categories of
   candidates from structured evidence. Highly domain-specific or
   unusual action types may not be represented.

4. **Branch state requires 0D4-E**: Branch-scoped state at
   `data/narrative_memory/state/{timeline_id}/{branch_id}/current.json`
   is not yet created by any existing module (0D4-E scope). Until then,
   `branch_state_revision` is `None` with `BRANCH_STATE_UNAVAILABLE`
   limitation — the binder does not fall back to legacy flat state.

## 6. Boundary Audit

### 6.1 Files modified by 0D4-B / 0D4-B-FIX-RC

New files only (no modifications to 0D4-A sealed code):

```
story-os-demo/core/contracts/narrative_turn_preview.py
story-os-demo/system/narrative_turn_context.py
story-os-demo/system/narrative_turn_planner.py
story-os-demo/system/narrative_action_feasibility.py
story-os-demo/system/narrative_turn_preview.py
story-os-demo/tests/test_phase0d4b_narrative_turn_planner.py
docs/design/simulator_narrative_turn_planner.md
docs/design/simulator_action_feasibility.md
docs/planning/PHASE_0D4_B.md
docs/planning/PHASE_0D4_B_DELIVERY_REPORT.md
docs/planning/PHASE_0D4_IMPLEMENTATION_BRIEF.md
```

### 6.2 Files NOT modified (as required)

- `web/routes.py` — unchanged
- `web/templates/index.html` — unchanged
- `web/static/*` — unchanged
- `core/contracts/narrative_turn.py` — unchanged (0D4-A sealed)
- `system/narrative_turn_store.py` — unchanged (0D4-A sealed)
- `system/narrative_branch_store.py` — unchanged (0D4-A sealed)

## 7. Authorization Status

```
Phase 0D4-P: PASSED
Phase 0D4-A: SEALED
Phase 0D4-B-FIX-RC: ACCEPTED
Phase 0D4-B-FIX-RC-FV: PASSED
Phase 0D4-B: SEALED
Phase 0D4-C: NOT ENTERED
Phase 0D4-D: NOT ENTERED
Phase 0D4-E: NOT ENTERED
Phase 0D4-F: NOT ENTERED
```

## 8. Next Phase Readiness

Before entering 0D4-C or 0D4-D, the following prerequisites from 0D4-B
are satisfied:

- ✅ Context snapshot with deterministic fingerprint (18 authority inputs)
- ✅ Cold-start read-only binder (no file writes)
- ✅ Deep-immutable snapshot (recursive freeze)
- ✅ Strict canonical serialization (no `default=str`)
- ✅ Branch-state isolation (branch-scoped only)
- ✅ Deterministic 3-action plan generation
- ✅ 14-step feasibility pipeline with 4 statuses
- ✅ Custom action normalization + validation
- ✅ Read-only qualitative preview
- ✅ Stable IDs for turn, action, validation, preview
- ✅ Comprehensive test coverage (124 focused + 214 regression tests)
- ✅ Phase 0D4-B SEALED — 0D4-C authorized (not entered)
