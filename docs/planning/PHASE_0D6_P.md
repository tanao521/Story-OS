# Phase 0D6-P — Chapter-to-Chapter Continuation Preflight

Status: **PASSED**
Phase 0D6 Architecture: **READY FOR OWNER REVIEW**
Phase 0D6 implementation: **BLOCKED**
Phase 0D6-A: **NOT ENTERED**

## Scope

This phase performed read-only architecture inspection, isolated temporary
fixture probes, contract design, and implementation planning. It made no
production implementation change.

## Gate finding

Existing Commit, Branch, Turn, Candidate, Review, Memory, Vector, Version and
Canon authorities are fully identified and mapped. Safe Chapter progression
cannot yet be implemented because:

1. **No consumed project-level Chapter lifecycle registry is authoritative.**
   Chapter identity is encoded as integer file paths. `chapter_index.json`
   exists but is not consumed. Planning has a second `chapter_id` identity.
2. **File discovery, Planning identity, `state.current_chapter`, and
   Traditional `current_target_chapter()` express different chapter meanings.**
3. **Chapter creation is distributed across planning/draft/version/commit
   writers and has no exactly-once create result.**
4. **Compatibility reads create side effects.** `get_selected_version()`
   writes a versions index; `active_canon()` creates Canon, index and audit.
5. **Initial Canon and Branch State carry-forward policy for Chapter N+1
   is not defined by an existing authority.**
6. **`SimulatorLoopStateService.build()` has a manifest parsing bug**
   (`KeyError: 'revision'`) that blocks cross-chapter readiness projection.

These findings match the mandatory implementation-blocking conditions.

## Fixture probe results (2026-07-28)

Three temporary isolated fixtures (A/B/C) with SHA-256 before/after
manifests, all deleted after use:

| Probe | Fixture A (exists) | Fixture B (absent) | Fixture C (branch) | Classification |
|---|---|---|---|---|
| `list_versions(2)` | 0 delta | 0 delta | 0 delta | PURE_READ |
| `get_selected_version(2)` | **+1 file** | **+1 file** | **+1 file** | HIDDEN_MUTATION_BEHIND_READ |
| `read_active_canon(2)` | 0 delta | 0 delta | 0 delta | PURE_READ |
| `active_canon(2)` | **+3 files** | Error | Error | LEGACY_READ_WITH_SIDE_EFFECT |
| `SimulatorLoopStateService.build()` | KeyError | KeyError | KeyError | PURE_READ (bug) |
| `load_planning()` | 0 delta | 0 delta | 0 delta | PURE_READ |

## Required owner decisions

1. Canonical Chapter lifecycle identity (integer path vs Planning `chapter_id`)?
2. Shared Chapter creation owner and exactly-once contract?
3. `state.current_chapter` semantics (last committed vs currently opened)?
4. Initial Canon policy for Chapter N+1?
5. Cross-chapter Branch State transition and CAS inputs?
6. Prohibit `get_selected_version()` and `active_canon()` for resolve/browse?
7. Fix `SimulatorLoopStateService.build()` manifest parsing bug?

## Design documents

- `docs/design/chapter_progression_authority_map.md`
- `docs/design/chapter_to_chapter_state_machine.md`
- `docs/design/cross_chapter_continuity_contract.md`
- `docs/design/next_chapter_risk_matrix.md`

## Delivery report

- `docs/planning/PHASE_0D6_P_DELIVERY_REPORT.md`
- `docs/planning/PHASE_0D6_IMPLEMENTATION_BRIEF.md`

Stop here. Do not enter 0D6-A until owner decisions are recorded.