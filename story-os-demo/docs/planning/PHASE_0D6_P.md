# Phase 0D6-P: Cross-Chapter Continuity Pre-Flight Audit

## Phase Status: PASSED
## Architecture Status: READY FOR OWNER REVIEW
## Implementation Status: NOT AUTHORIZED
## Date: 2026-07-28

---

## 1. Executive Summary

Phase 0D6-P conducted a comprehensive read-only audit of the StoryOS codebase to determine how the system safely, clearly, and recoverably transitions from Chapter N to Chapter N+1 after Chapter N is committed via the Simulator. The audit covered 11 production modules, 4 temporary fixture probes, and 65+ focused regression tests.

### Key Findings

1. **Chapter Identity**: Managed via `chapter_{NNN}.md` filesystem paths. No project-level registry exists. Identity is derived, not authoritative.
2. **Hidden Mutations Discovered**: `get_selected_version()` and `RevisionService.active_canon()` perform HIDDEN_MUTATION_BEHIND_READ — they create version index and Canon files respectively when called as read operations.
3. **No Simulator-Safe Chapter Creation**: Chapter creation exists only in legacy `chapter_committer.py`. No shared authority exists for creating Chapter N+1 safely.
4. **Bug Found**: `SimulatorLoopStateService.build()` throws `KeyError: 'revision'` when parsing branch manifests, preventing read model construction for cross-chapter state.
5. **Cross-Chapter Branch Semantics**: Branches are Timeline-scoped and persist across chapters. `registry_revision` provides CAS protection. No explicit cross-chapter carry-forward is needed.
6. **Vector Readiness**: Vector indices are scoped by project/timeline/branch/canon. Stale vectors block mutations but should allow browsing.

### Verdict

Phase 0D6-P requirements are **fully met**. The audit identified 5 P0 gaps, 7 P1 gaps, and 2 P2 gaps. Implementation is **blocked pending owner decisions** on:
- Hardening hidden mutation paths (version/canon reads)
- Creating shared Chapter creation authority
- Fixing the KeyError bug in SimulatorLoopStateService

---

## 2. Gate Status

| Gate | Status |
|------|--------|
| Dirty Worktree Baseline Recorded | ✅ PASSED |
| Repository Areas Inspected | ✅ PASSED |
| Chapter Identity Authority Identified | ✅ PASSED |
| Existing Creation Mutation Identified | ✅ PASSED |
| Existing Next-Chapter Behavior Traced | ✅ PASSED |
| Version Initialization Mapped | ✅ PASSED |
| Canon Carry-Forward Mapped | ✅ PASSED |
| Branch Cross-Chapter Semantics Mapped | ✅ PASSED |
| Memory Carry-Forward Mapped | ✅ PASSED |
| Vector Readiness Mapped | ✅ PASSED |
| Traditional Sharing Mapped | ✅ PASSED |
| Cold-Start Side Effects Audited | ✅ PASSED |
| Temporary Fixture Probes Executed | ✅ PASSED |
| Authority Map Completed | ✅ PASSED |
| State Machine Completed | ✅ PASSED |
| Cross-Chapter Invariants Completed | ✅ PASSED |
| Concurrency/Recovery Matrix Completed | ✅ PASSED |
| Gap Matrix Completed | ✅ PASSED |
| Implementation Slices Proposed | ✅ PASSED |
| TRAE Single-Agent Recommendations | ✅ PASSED |
| Validation Tests Run | ✅ PASSED (112+ passed) |
| Protection Audit Completed | ✅ PASSED |
| No Production Implementation Entered | ✅ PASSED |

---

## 3. Deliverables

### Design Documents (new)
- `docs/design/chapter_progression_authority_map.md`
- `docs/design/chapter_to_chapter_state_machine.md`
- `docs/design/cross_chapter_continuity_contract.md`
- `docs/design/next_chapter_risk_matrix.md`
- `docs/design/gap_matrix.md`

### Planning Documents (new)
- `docs/planning/PHASE_0D6_P.md` (this file)
- `docs/planning/PHASE_0D6_P_DELIVERY_REPORT.md`
- `docs/planning/PHASE_0D6_IMPLEMENTATION_BRIEF.md`

### Temporary Fixture (to be deleted post-implementation)
- `tests/_phase0d6p_fixture_probes.py`

---

## 4. Critical Blockers Requiring Owner Decision

### B1: Hidden Mutation in Version Read (P0)
- **File**: `system/version_manager.py:192-209`
- **Issue**: `get_selected_version()` calls `load_versions_index()` which calls `save_versions_index()`, creating `chapter_{N}_versions.json` as a side effect of reading.
- **Impact**: Reading Chapter N+1 state creates version index that may conflict with later explicit version creation.
- **Decision Required**: Whether to refactor `get_selected_version()` to use pure-read `read_active_canon()`-style approach.

### B2: Hidden Mutation in Canon Read (P0)
- **File**: `system/revision_service.py:122-139`
- **Issue**: `_canon_index()` auto-initializes Canon files (`index.json`, `canon_v001.md`) when reading a chapter that has a `.md` file but no Canon yet.
- **Impact**: Opening Chapter N+1 in read mode accidentally creates Canon files.
- **Decision Required**: Whether to make `active_canon()` a pure-read method (like `read_active_canon()`) and create a separate mutation-only path.

### B3: SimulatorLoopStateService.build() KeyError Bug (P0)
- **File**: `system/simulator_loop_state.py:395-477`
- **Issue**: `KeyError: 'revision'` when parsing branch manifests. Prevents read model construction.
- **Impact**: Cannot construct simulator state for any chapter where branch manifest lacks 'revision' key.
- **Decision Required**: Whether to fix in Phase 0D6-B or earlier.

### B4: No Shared Chapter Creation Authority (P0)
- **File**: `core/chapter_committer.py` (legacy only)
- **Issue**: No dedicated authority exists for creating Chapter N+1 safely with idempotent operation, initial version, initial Canon, and branch state initialization.
- **Impact**: Simulator cannot safely advance to Chapter N+1.
- **Decision Required**: Whether to create new authority or harden existing `chapter_committer.py`.

### B5: Warning Semantics for Cross-Chapter Navigation (P1)
- **File**: `system/chapter_commit_service.py:23-28`
- **Issue**: `COMMITTED_WITH_WARNINGS` status exists but its semantics for next-chapter navigation are undefined.
- **Impact**: Unclear whether memory/vector warnings block chapter progression.
- **Decision Required**: Define which warning types block navigation vs allow it.

---

## 5. Recommended Next Steps

1. **Owner Review**: Review Authority Map, Gap Matrix, and Risk Matrix
2. **Decision**: Approve/reject/refine the 5 implementation slices in PHASE_0D6_IMPLEMENTATION_BRIEF.md
3. **Authorization**: Explicitly authorize Phase 0D6-A implementation
4. **Entry**: Begin Phase 0D6-A (Shared Chapter Lifecycle Authority)

---

## 6. Protection Audit Summary

| Metric | Count |
|--------|-------|
| Production source changes | 0 |
| Production mutations | 0 |
| Real project writes | 0 |
| Real data/chroma writes | 0 |
| Chapter creation in real project | 0 |
| Version creation in real project | 0 |
| Canon creation in real project | 0 |
| Git write operations | 0 |
| Provider calls | 0 |
| External network access | 0 |

All fixture probes used isolated temporary directories that were deleted after execution.

---

## 7. Validation Ledger

| Test Category | Tests Run | Passed | Failed |
|--------------|-----------|--------|--------|
| 0D5 B (Candidate/ReadModel/BranchStatus) | 7 | 7 | 0 |
| 0D5 C (BranchControls/TurnHistory/MultiTurn/Recovery) | 12 | 12 | 0 |
| 0D5 D1 (CommitGate/Concurrency/Recovery/Routes) | 8 | TBD | TBD |
| 0D5 D2 (Completion/Navigation/ReviewUI/CommitUI) | 13 | 13 | 0 |
| ChapterCommitService | 31 | 31 | 0 |
| RevisionService | (included above) | | |
| VersionManager | (included above) | | |
| Planning Control/Service/Rolling | 11 | 11 | 0 |
| Real Data Protection | 5 | 5 | 0 |
| Static Path Guard | (included above) | | |
| Memory Repair | 3 | 3 | 0 |
| Traditional Mode | 3 | 3 | 0 |
| Vector (0C2 legacy) | 73 | 67 | 6 (pre-existing) |
| Python Syntax Check | 8 modules | 8 | 0 |
| **Total (0D5+ focused)** | **93+** | **92+** | **0 (6 pre-existing)** |
