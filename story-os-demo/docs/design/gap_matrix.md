# Gap Matrix — Phase 0D6-P

## Audit Date
Phase 0D6-P — 2026-07-28

## Severity Definitions
- **P0**: authority bypass / data corruption / scope pollution
- **P1**: blocks reliable cross-chapter loop
- **P2**: product or UX limitation
- **P3**: documentation or low-risk consistency

## Gap Matrix

| # | Gap | Severity | Current behavior | Required behavior | Authority impact | Proposed phase |
|---|-----|----------|------------------|------------------|------------------|----------------|
| 1 | Next Chapter resolve | P0 | `next_chapter_available` determined by file existence only (`chapter_{N+1:03d}.md`), no planning/registry resolution | Resolve next chapter via planning + file existence + branch state triple-check | SimulatorLoopStateService, planning_service | 0D6-A |
| 2 | Chapter creation | P0 | No Simulator-safe chapter creation exists. Traditional Mode uses legacy `chapter_committer.py` | Create chapter via shared authority with idempotent operation, initial version, initial Canon | New shared ChapterCreate authority | 0D6-A |
| 3 | Chapter selection | P1 | Chapter selected via URL + state.json, no cross-chapter carry-forward | Chapter selection should persist branch context across chapter transitions | Context Navigator, state.json | 0D6-C |
| 4 | Initial source Version | P0 | `get_selected_version()` creates `chapter_versions.json` on read (HIDDEN_MUTATION). New chapter has empty version list | Initial version creation via explicit mutation, not read side-effect | VersionManager hardening, VersionWriterFacade | 0D6-A |
| 5 | Initial Canon | P0 | `active_canon()` auto-initializes Canon from chapter file on read (HIDDEN_MUTATION). `read_active_canon()` is pure read | Initial Canon created only via explicit commit, never read side-effect | RevisionService hardening | 0D6-A |
| 6 | Branch carry-forward | P1 | Branch is Timeline-scoped, `active_branch_id` persists across chapters. No explicit cross-chapter carry-forward logic needed | Branch continues across chapter changes; registry_revision acts as CAS fence | NarrativeBranchStore, BranchLifecycleService | 0D6-D |
| 7 | Memory carry-forward | P1 | Memory invalidated on Canon change (`_mark_derived_stale`). No explicit cross-chapter snapshot | Narrative Memory should carry forward via explicit snapshot at commit time | NarrativeMemoryService, commit post-tasks | 0D6-D |
| 8 | Vector readiness | P1 | Vector scoped by project/timeline/branch/canon. Stale vectors block operations via `BranchVectorNotReady` | Vector should be rebuilt for new chapter's initial Canon; stale vector should allow browsing but block mutations | VectorIndexLifecycle, commit post-tasks | 0D6-D |
| 9 | Planning cursor | P2 | `planning_service.sync_next_plan()` writes `next_chapter_plan.json`. No automatic cursor advancement on commit | Planning cursor should advance as part of commit durable result | planning_service, ChapterCommitService | 0D6-B |
| 10 | Warning semantics | P2 | `COMMITTED_WITH_WARNINGS` exists but semantics are unclear for next-chapter navigation | Define which warnings block next chapter: vector=block, memory=warn, planning=warn | ChapterCommitService warnings | 0D6-B |
| 11 | Traditional sharing | P1 | Traditional and Simulator share same codebase but different UI modes. No shared chapter pointer authority | Shared chapter selection authority; mode-aware UI isolation | Context Navigator, mode-aware state | 0D6-C |
| 12 | URL navigation | P1 | `nextChapter()` uses `pushState` to change chapter_id. No backend validation | URL navigation should validate chapter existence + branch scope + Canon readiness | Context Navigator, URL validation | 0D6-C |
| 13 | Recovery | P1 | Recovery via CommitRunStore replay. `SimulatorLoopStateService.build()` has KeyError: 'revision' bug | Recovery should handle all failure modes; branch manifest parsing must be robust | CommitRunStore, SimulatorLoopStateService | 0D6-D |
| 14 | Scope isolation | P0 | Branch isolation verified by fixture. `NarrativeScope` enforces project/timeline/branch scope | Cross-chapter scope must also enforce branch isolation for all artifacts | NarrativeScope, CompilationScope | 0D6-D |

## Summary

| Severity | Count | Gaps |
|----------|-------|------|
| P0 | 5 | #1 Next Chapter resolve, #2 Chapter creation, #4 Initial source Version, #5 Initial Canon, #14 Scope isolation |
| P1 | 6 | #3 Chapter selection, #6 Branch carry-forward, #7 Memory carry-forward, #8 Vector readiness, #11 Traditional sharing, #12 URL navigation, #13 Recovery |
| P2 | 2 | #9 Planning cursor, #10 Warning semantics |
| **Total** | **14** | |

## Phase Grouping

| Phase | Gaps | Severity Range |
|-------|------|----------------|
| 0D6-A | #1, #2, #4, #5 | P0 |
| 0D6-B | #9, #10, #13 | P1-P2 |
| 0D6-C | #3, #11, #12 | P1 |
| 0D6-D | #6, #7, #8, #13, #14 | P0-P1 |