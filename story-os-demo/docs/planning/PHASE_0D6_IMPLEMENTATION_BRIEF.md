# Phase 0D6 Implementation Brief

## Verdict: Phase 0D6-P PASSED — Implementation Blocked Pending Owner Decisions

## Slice Proposals

### Phase 0D6-A: Shared Chapter Lifecycle Authority

- **Objective**: Create shared authority for Chapter identity resolution and creation, with hardened version/Canon initialization
- **Authority owner**: New shared ChapterAuthority (or harden existing RevisionService + VersionManager)
- **Allowed files**: `system/chapter_authority.py` (new), `system/version_manager.py` (harden `get_selected_version`), `system/revision_service.py` (harden `active_canon`)
- **Forbidden changes**: No production frontend, no API changes, no commit path changes
- **Mutation budget**: 1 new module, 2 hardened modules
- **Provider/network budget**: 0
- **Focused tests**: chapter creation idempotency, version/canon not created on read, scope isolation
- **Browser evidence**: Not required (backend-only phase)
- **Entry gate**: Phase 0D6-P PASSED
- **Exit gate**: Chapter creation idempotent, read paths are pure, version/canon initialized only by mutation
- **TRAE reasoning**: medium-high
- **Agent strategy**: single Agent

### Phase 0D6-B: Chapter Progression Read Model and Readiness Projection

- **Objective**: Fix `SimulatorLoopStateService.build()` KeyError bug, add chapter progression projection
- **Authority owner**: `SimulatorLoopStateService`
- **Allowed files**: `system/simulator_loop_state.py`, `system/chapter_projection.py` (new)
- **Forbidden changes**: No frontend, no API changes
- **Mutation budget**: 1 new projection module, 1 bug fix
- **Provider/network budget**: 0
- **Focused tests**: branch manifest parsing, chapter_projection readiness, KeyError fix regression
- **Entry gate**: 0D6-A PASSED
- **Exit gate**: KeyError fixed, chapter readiness projection correct
- **TRAE reasoning**: medium
- **Agent strategy**: single Agent

### Phase 0D6-C: Next Chapter Production UI and URL Navigation

- **Objective**: Wire existing completion view to next chapter resolution, add URL validation
- **Authority owner**: Frontend + Context Navigator
- **Allowed files**: `web/static/simulator-candidate-review.js`, `web/static/simulator-usable-loop.js`, `web/static/simulator-context-navigator.js`
- **Forbidden changes**: No backend mutations, no provider calls
- **Mutation budget**: UI-only changes
- **Provider/network budget**: 0
- **Focused tests**: URL validation, chapter resolution display, disabled state correctness
- **Browser evidence**: Required (Chromium two-chapter loop)
- **Entry gate**: 0D6-B PASSED
- **Exit gate**: Two-chapter usable loop in browser
- **TRAE reasoning**: medium
- **Agent strategy**: single Agent

### Phase 0D6-D: Cross-Chapter Branch/Memory/Vector Continuity and Recovery

- **Objective**: Ensure Branch, Memory, Vector carry-forward across chapters
- **Authority owner**: `NarrativeBranchStore`, `NarrativeMemoryService`, `VectorIndexLifecycle`
- **Allowed files**: `system/narrative_branch_store.py`, `system/narrative_memory_service.py`, `system/vector_index_lifecycle.py`
- **Forbidden changes**: No frontend
- **Mutation budget**: Recovery-only additions
- **Provider/network budget**: 0
- **Focused tests**: Branch carry-forward, Memory snapshot, Vector rebuild on chapter transition
- **Entry gate**: 0D6-C PASSED
- **Exit gate**: Cross-chapter isolation verified
- **TRAE reasoning**: medium-high
- **Agent strategy**: single Agent

### Phase 0D6-RC: Real Chromium Two-Chapter Usable-Loop Acceptance

- **Objective**: Browser-level acceptance of complete two-chapter loop
- **Authority owner**: All 0D6 authorities
- **Allowed files**: test fixtures only
- **Forbidden changes**: All production code frozen
- **Mutation budget**: 0
- **Provider/network budget**: 0
- **Focused tests**: Full browser acceptance
- **Browser evidence**: Mandatory
- **Entry gate**: 0D6-D PASSED
- **Exit gate**: Browser acceptance checklist complete
- **TRAE reasoning**: medium-high
- **Agent strategy**: single Agent