# Chapter Progression Authority Map

## Purpose

This document maps the existing authorities for each concern involved in Chapter progression from Chapter N to Chapter N+1. It identifies ownership, scope, mutation boundaries, and recovery mechanisms for each concern.

## Audit Date

Phase 0D6-P — 2026-07-28

## Fixture-Verified Side Effects

| Read Operation | File Created | Severity |
|----------------|-------------|----------|
| `get_selected_version(chapter_id=N)` | `data/versions/chapter_{N}_versions.json` | P1 - HIDDEN_MUTATION_BEHIND_READ |
| `RevisionService.active_canon(chapter_id=N)` | `data/canon_versions/chapter_{N}/index.json` + `canon_v001.md` + `data/audit/revision_audit.json` | P0 - HIDDEN_MUTATION_BEHIND_READ |
| `RevisionService.read_active_canon(chapter_id=N)` | None | PURE_READ |
| `list_versions(chapter_id=N)` | None | PURE_READ |
| `load_planning()` | None | PURE_READ |
| `SimulatorLoopStateService.build()` | None (but has KeyError bug) | BUG - KeyError: 'revision' |

## Authority Map Table

| # | Concern | Existing Authority | Scope | Mutation Owner | Recovery Owner | Evidence References | Decision |
|---|---------|-------------------|-------|-----------------|----------------|---------------------|----------|
| 1 | Chapter Identity | `VersionManager.format_chapter_id()` (`f"{chapter_id:03d}"`); `project_context.chapters_dir` | `project/timeline` | None (filesystem-derived) | Filesystem scan (`os.listdir`) | `chapter_{NNN}.md` files on disk; `version_manager.py:format_chapter_id()` | **REUSE_AS_IS** — Identity is filesystem-derived, no registry needed; read-only, deterministic, lossy only on file deletion |
| 2 | Chapter Creation | `core/chapter_committer.py` (legacy); `core/next_chapter_planner.py` (plan generation); `system/planning_service.py:sync_next_plan()` | `project` | `ChapterCommitService.commit_chapter()`; `chapter_committer.py:commit_chapter()` | `planning_service.sync_next_plan()` regenerates plan | `next_chapter_planner.py` generates from `state.current_chapter + 1`; no dedicated Chapter create authority for Simulator mode | **REQUIRES_EXISTING_MUTATION_WIRING** — Creation is split across planner + committer; Simulator path lacks dedicated creation authority |
| 3 | Chapter Selection | `state.json.current_chapter`; URL `?chapter=N` query param; `planning_service` | `project` | `state.json` updates (via planning/selection flow) | `planning_service` overview rebuild | `web/templates/index.html` reads `state.json`; `simulator-candidate-review.js` uses URL `pushState` for `nextChapter()` | **REUSE_AS_IS** — Selection is state-driven, serializable, and recoverable from `state.json` |
| 4 | Source Version | `VersionManager`; `VersionWriterFacade` for writes | `chapter` | `VersionWriterFacade.write_version()` | `load_versions_index()` rebuilds from `chapter_{N}_versions.json` | `get_selected_version()` → `load_versions_index()` → **calls `save_versions_index()`** creating `chapter_{N}_versions.json` on READ | **REQUIRES_AUTHORITY_HARDENING** — `get_selected_version()` performs hidden write; `list_versions()` is already pure read but `get_selected_version()` must be split into pure-read + explicit-create |
| 5 | Active Canon | `RevisionService.active_canon()`; `RevisionService.read_active_canon()` (pure) | `chapter` | `RevisionService.create_and_apply_revision()` | `RevisionService.restore_canon()` reverts to prior revision | `active_canon()` → `_canon_index()` → **auto-initializes** `canon_versions/chapter_{N}/index.json` + `canon_v001.md` + `audit/revision_audit.json` on READ; `read_active_canon()` is pure projection | **REQUIRES_AUTHORITY_HARDENING** — `active_canon()` has P0 hidden mutation; must be split into `ensure_canon_exists()` (explicit write) and `get_active_canon()` (pure read) |
| 6 | Branch Continuity | `NarrativeBranchStore` (Timeline-scoped) | `timeline` | `BranchLifecycleService` (create/archive/restore) | `registry_revision` CAS replay | Branch registry records `registry_revision` for optimistic concurrency; lifecycle events logged | **REUSE_AS_IS** — Branches are timeline-scoped with proper CAS and event-sourced recovery |
| 7 | Branch State | `NarrativeBranchStore.registry` | `timeline/branch` | `BranchLifecycleService.archive_branch()` / `restore_branch()` | Registry event journal replay | Branch registry entries carry `registry_revision`; recovery via replaying lifecycle events | **REUSE_AS_IS** — State is journal-backed, replayable, and CAS-protected |
| 8 | Turn History | `NarrativeTurnStore`; `narrative_turn_service.confirm()` | `project/timeline/branch/chapter` | `narrative_turn_service.confirm()` (append-only) | Immutable journal scan | Turn records are immutable once confirmed; history rebuilt via linear scan | **REUSE_AS_IS** — Turn history is append-only, immutable, and fully replayable |
| 9 | Candidate | `NarrativeChapterCompiler.compile_candidate()` | `project/timeline/branch/chapter/source/canon/registry` | `compile_candidate()` (creates candidate snapshot) | Recompile from turn history | `CompilationScope` carries `source_version`, `canon_revision`, `registry_revision`; candidate is a deterministic projection | **REUSE_AS_IS** — Candidate is a deterministic, replayable compilation from immutable inputs |
| 10 | Review | `NarrativeCandidateReviewService` | `project/timeline/branch/chapter/candidate` | Review decision (approve/reject) | First-writer-wins durable record | Review records are persisted with fingerprint validation; duplicate reviews are idempotent | **REUSE_AS_IS** — Review is a durable, fingerprint-validated decision record |
| 11 | Commit Completion | `ChapterCommitService.commit_chapter()` | `chapter` | `commit_chapter()` (finalizes chapter, advances state) | `CommitRunStore` replay | Commit creates `chapter_{NNN}.md`, advances `state.json.current_chapter`, triggers post-tasks | **REUSE_AS_IS** — Commit is the chapter-scoped write barrier; replayable from commit run store |
| 12 | Memory Carry-Forward | `NarrativeMemoryService`; `MemoryRepairService` | `project/timeline/branch/chapter` | Commit post-tasks (memory extraction, carry-forward) | `memory_repair_service.diagnose()` + `repair()` | `narrative_memory_service.py` manages events + state; `memory_repair_service.py` handles diagnostics | **REQUIRES_EXISTING_MUTATION_WIRING** — Memory carry-forward runs as post-commit task but lacks explicit authority boundary; needs wiring into commit lifecycle |
| 13 | Vector Readiness | `VectorIndexLifecycle.index_scoped_records()` | `project/timeline/branch/canon` | `index_scoped_records()` (creates/refreshes vector index) | `sync_branch_index()` rebuilds from source | Vector indices are scoped by `project/timeline/branch/canon_revision`; stale vectors can block operations | **REQUIRES_EXISTING_MUTATION_WIRING** — Vector index lifecycle is not tied to commit; needs explicit trigger on canon commit/selection |
| 14 | Traditional Selected Version | `VersionManager.select_version()` | `chapter` | `select_version()` (updates selection) | `load_versions_index()` reloads from disk | `web/templates/index.html` has `data-storyos-mode="traditional"` toggle; Traditional mode shares same `VersionManager` but different UI flow | **REQUIRES_AUTHORITY_HARDENING** — Same hidden mutation as Concern #4; `select_version()` path must use pure-read versions index + explicit write for selection |

## Cross-Cutting Concerns

### Hidden Mutations (Critical)

Two read operations perform silent writes that violate the authority boundary:

1. **`VersionManager.get_selected_version()`** calls `load_versions_index()` which calls `save_versions_index()`. Any read of the selected version triggers creation of `data/versions/chapter_{N}_versions.json` if it does not exist.
   - **Risk**: Concurrent reads create race conditions; reads have side effects that cannot be predicted by callers.
   - **Fix**: Split into `get_selected_version()` (pure read from existing index) and `ensure_versions_index()` (explicit initialization).

2. **`RevisionService.active_canon()`** calls `_canon_index()` which auto-initializes Canon files (`index.json`, `canon_v001.md`, `revision_audit.json`) if a chapter file exists but no Canon index exists.
   - **Risk**: P0 — reading active Canon creates 3 files + audit trail; recovery may be inconsistent if initialization partially completes.
   - **Fix**: Split into `get_active_canon()` (pure read) and `initialize_canon()` (explicit write with transactional guarantees).

### Bug: `SimulatorLoopStateService.build()`

Fixture evidence confirms a `KeyError: 'revision'` in the Simulator loop state builder. This affects the compilation scope assembly for Simulator mode.

### Shared Codebase / Dual Mode

Traditional Mode and Simulator Mode share the same backend services but differ in UI flow (`data-storyos-mode="traditional"`). All authorities listed above apply to both modes unless explicitly noted (Concern #14 is Traditional-mode specific for selection flow).

### Vector Staleness

Vector indices are scoped by `project/timeline/branch/canon_revision`. Stale vectors (e.g., from a previous canon revision) can block chapter progression. The `VectorIndexLifecycle` service must be triggered explicitly on canon selection or commit — it currently lacks this wiring.

## Recovery Mechanisms Summary

| Concern | Primary Recovery | Fallback |
|---------|-----------------|----------|
| Chapter Identity | Filesystem scan | — |
| Chapter Creation | `planning_service.sync_next_plan()` | Manual `chapter_committer.commit_chapter()` |
| Chapter Selection | `state.json` re-read | URL `?chapter=N` override |
| Source Version | `load_versions_index()` re-read | Re-create versions index via explicit write |
| Active Canon | `RevisionService.restore_canon()` | Re-initialize via `initialize_canon()` (after hardening) |
| Branch Continuity | `registry_revision` CAS retry | Branch lifecycle replay |
| Branch State | Registry event journal replay | — |
| Turn History | Immutable journal linear scan | — |
| Candidate | Recompile from turn history | — |
| Review | First-writer-wins durable record | Re-review with new fingerprint |
| Commit Completion | `CommitRunStore` replay | — |
| Memory Carry-Forward | `memory_repair_service.diagnose()` → `repair()` | Re-run commit post-tasks |
| Vector Readiness | `sync_branch_index()` rebuild | Full re-index from source |
| Traditional Selected Version | `load_versions_index()` re-read | Re-select via `select_version()` |