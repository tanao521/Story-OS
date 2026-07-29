# Phase 0D6-P Delivery Report

## 1. Executive Summary

Phase 0D6-P is **PASSED**. All audit tasks, fixture probes, design documents,
and validation checks are complete. The Chapter progression authority map,
state machine, cross-chapter continuity contract, and risk matrix are
delivered. Phase 0D6 implementation remains **BLOCKED** and requires **owner
decisions** on Chapter identity, creation, pointer semantics, initial Canon,
and cross-chapter Branch State transition.

## 2. Gate Status

```text
Phase 0D4: SEALED
Phase 0D5: SEALED
Phase 0D6-P: PASSED
Phase 0D6 Architecture: READY FOR OWNER REVIEW
Phase 0D6 implementation: BLOCKED
Phase 0D6-A: NOT ENTERED
Phase 0E: NOT ENTERED
Provider Live: NOT ENTERED
```

## 3. Dirty Worktree Baseline

Baseline recorded via `git status --short` (2026-07-28):

**Modified files (34):**
- `commands.py`, `core/contracts/narrative_turn.py`
- `system/chapter_commit_service.py`, `system/context_assembly_service.py`,
  `system/context_builder.py`, `system/job_handlers.py`, `system/memory_health.py`,
  `system/memory_repair_service.py`, `system/narrative_branch_store.py`,
  `system/narrative_turn_context.py`, `system/narrative_turn_service.py`,
  `system/narrative_turn_store.py`, `system/project_clone_service.py`,
  `system/revision_service.py`, `system/status_dashboard.py`, `system/story_qa.py`,
  `system/vector_client_manager.py`, `system/vector_index_lifecycle.py`,
  `system/vector_index_schema.py`
- `tests/_rc2_browser_fixture_server.py`, `tests/test_memory_repair_service.py`,
  `tests/test_phase0c2_project_clone.py`, `tests/test_phase0d4a_narrative_turn_foundation.py`
- `web/app.py`, `web/narrative_turn_routes.py`, `web/narrative_turn_wire.py`,
  `web/routes.py`, `web/static/simulator-narrative-turn.js`,
  `web/static/simulator-panel-review.css`, `web/templates/index.html`
- `../docs/planning/PHASE_0D4_A.md`, `../docs/planning/PHASE_0D4_D.md`,
  `../docs/planning/PHASE_0D4_D_DELIVERY_REPORT.md`,
  `../docs/planning/PHASE_0D4_IMPLEMENTATION_BRIEF.md`

**Untracked files (135+):** All 0D4/0D5/0D6 planning docs, design docs,
test files, and source files from phases 0D4-E through 0D6-P.

## 4. Repository Areas Inspected

| Area | Files |
|---|---|
| Chapter identity | `core/project_context.py`, `version_manager.py`, `revision_service.py` |
| Planning | `system/planning_service.py`, `core/next_chapter_planner.py` |
| Version/Source | `system/version_manager.py`, `web/routes.py` (selected version) |
| Canon/Revision | `system/revision_service.py`, `system/chapter_commit_service.py` |
| Commit boundary | `system/chapter_commit_service.py`, `system/narrative_chapter_compiler.py` |
| Branch semantics | `system/narrative_branch_store.py`, `system/narrative_branch_lifecycle_service.py` |
| Turn/History/Candidate | `system/narrative_turn_store.py`, `system/narrative_turn_service.py`, `system/narrative_chapter_compiler.py` |
| Narrative Memory | `system/branch_narrative_memory_service.py`, `system/memory_repair_service.py`, `system/context_assembly_service.py` |
| Vector/Chroma | `system/vector_index_lifecycle.py`, `system/vector_client_manager.py` |
| Traditional sharing | `web/routes.py`, `web/app.py`, Traditional chapter routes |
| Completion UI | `web/static/simulator-candidate-review.js`, `web/static/simulator-usable-loop.js` |
| Read model | `system/simulator_loop_state.py`, `web/simulator_state_routes.py` |
| Focused tests | 65 tests across 0D5-B/C, 0D4-F, commit, revision, protection, static-path |

## 5. Chapter Identity Authority

### 5.1 Identity model

- **Canonical identity**: Positive integer `chapter_number` encoded into
  `data/chapters/chapter_NNN.md`, version directories (`chapter_NNN/`),
  Canon directories (`chapter_NNN/`), and summary filenames.
- **Secondary identity**: Planning `chapter_id` (opaque string like
  `plan-ch2`) coexists with `chapter_number`. `NarrativeTurnContextBinder._find_chapter_plan()`
  accepts either.
- **`chapter_index.json`**: Created by `ensure_project_structure()` but not
  consumed by any production read path.
- **`state.current_chapter`**: Persisted in `data/state.json`, written by
  `ChapterCommitService` after commit. Represents last committed chapter, not
  currently opened chapter.

### 5.2 Audit answers

1. **Chapter unique identity**: Integer chapter number encoded in file paths.
2. **ID/number/folder correspondence**: `chapter_NNN` format is consistent
   across chapters, versions, Canon, and summaries.
3. **Current chapter authority**: `state.current_chapter` is the persisted
  authority; `chapter_progression.current_chapter` is derived read model.
4. **Project-level Chapter registry**: `chapter_index.json` exists but is
   **not consumed** by any navigation or Simulator path.
5. **Chapter number gaps**: Not validated. Gaps are structurally possible.
6. **Rename/delete/archive/reorder**: `planning_service.reorder()` blocks
  committed chapters. No rename/archive authority exists.
7. **Traditional vs Simulator chapter identity**: Both share the same
   integer-path encoding but use different resolution strategies.
8. **Implicit `chapter_number + 1` assumption**: `current_target_chapter()`
   falls back to `state.current_chapter + 1`. `SimulatorLoopStateService.build()`
   checks `chapter_NNN.md` file existence.
9. **Read auto-creation**: `get_selected_version()` creates versions index
   (confirmed via fixture). `active_canon()` creates Canon artifacts
   (confirmed via fixture). Both are **HIDDEN_MUTATION** paths.
10. **Shared next-chapter service**: No shared service exists. Traditional
    uses `current_target_chapter()`, Simulator uses file existence check.

### 5.3 Authoritative files

| File | Class/Function | Input | Output | Side effects | Authority scope |
|---|---|---|---|---|---|
| `core/project_context.py` | `ProjectContext` (dataclass) | Project root path | All path constants | None | Project |
| `core/project_context.py` | `get_project_context()` | Root path | `ProjectContext` | None | Project |
| `system/version_manager.py` | `format_chapter_id()` | Integer | `chapter_NNN` string | None | Utility |
| `system/version_manager.py` | `get_selected_version()` | chapter_id, data_dir | Version dict | **Creates `chapter_NNN_versions.json`** | Chapter |
| `system/revision_service.py` | `active_canon()` | chapter_id | Canon dict | **Creates Canon+index+audit** | Chapter |
| `system/revision_service.py` | `read_active_canon()` | chapter_id | Canon dict or None | None | Chapter |
| `system/simulator_loop_state.py` | `SimulatorLoopStateService.build()` | project/timeline/chapter/branch | `SimulatorLoopState` | None (but has KeyError bug) | Cross-chapter read |

## 6. Existing Chapter Creation

### 6.1 Traditional Mode creation paths

| Path | Classification | Evidence |
|---|---|---|
| `VersionWriterFacade` writes chapter-local files | EXPLICIT_MUTATION | Creates `drafts/edited/manual` version files |
| `commands.py` chapter creation | EXPLICIT_MUTATION | Legacy command handler |
| `ChapterCommitService.commit_chapter()` | EXPLICIT_MUTATION | Creates chapter file, summary, updates `state.json` |
| `planning_service.sync_next_plan()` | EXPLICIT_MUTATION | Writes `next_chapter_plan.json` |
| `current_target_chapter()` | PURE_READ | Resolves next chapter target without creation |

### 6.2 Audit answers

1. **Traditional chapter creation**: Via `commands.py`, version writers, and
   commit. No dedicated create endpoint.
2. **Backend route/service**: `POST /api/planning/next-chapter` saves next
   plan. No chapter creation route exists.
3. **Operation ID/idempotency**: Only commit operations have operation IDs
   and idempotency. Chapter creation lacks these.
4. **Frontend-only creation**: Traditional may create version files via
   UI-initiated writes.
5. **Planning helper implicit creation**: `sync_next_plan()` writes plan
   data but not chapter files.
6. **Auto-create initial Version**: No explicit auto-creation. May happen
   via version writer facade.
7. **Auto-create Canon revision**: Via `RevisionService.create_and_apply_revision()`
   during commit.
8. **Change selected version**: `select_version()` mutates versions index.
9. **Initialize Branch State**: Via Turn projection during confirmation.
10. **Safe Simulator reuse**: **NOT SAFE** — no exactly-once operation, no
    operation ID, no concurrency control.

### 6.3 Classification

| Capability | Classification |
|---|---|
| Version file creation | REUSE_WITH_ADAPTER (safe explicit write) |
| Chapter file creation during commit | REUSE_AS_IS (part of commit, not standalone) |
| Planning next-plan sync | REUSE_WITH_ADAPTER |
| Initial source version creation | REQUIRES_HARDENING (needs explicit, not read-triggered) |
| Initial Canon creation | REQUIRES_HARDENING (must not use `active_canon()` read path) |
| Full chapter lifecycle (create+init+select+canon+branch) | **REQUIRES_NEW_DURABLE_AUTHORITY** |

## 7. Planning Lifecycle

### 7.1 Findings

- `planning_service.load_planning()` reads `story_planning.json` or legacy
  blueprint. Fills missing IDs and timestamps in memory (nondeterministic
  normalization).
- `planning_service.save_planning()` writes planning version and current
  planning.
- `planning_service.sync_next_plan()` writes `next_chapter_plan.json` with
  `chapter_id` and `planning_source`.
- `planning_service.overview()` returns `current_chapter`, chapter count,
  active threads, unresolved foreshadowing.
- `planning_service.reorder()` blocks `status == committed` chapters.
- `web/routes.current_target_chapter()`: reads `next_chapter_plan.json.chapter_id`
  first, falls back to `state.current_chapter + 1`.

### 7.2 Audit answers

1. **Planning as Chapter identity authority**: **No**. Planning is an advisory
   projection, not the lifecycle authority.
2. **Planning current/next**: Derived values, not authoritative.
3. **Chapter Commit advances Planning cursor**: **No direct advance**; commit
   writes `state.current_chapter` which `current_target_chapter()` reads.
4. **When next chapter plan generated**: Via `sync_next_plan()` — explicit
   mutation.
5. **Planning reads create data**: `load_planning()` normalizes in memory
   only; probe showed 0 file delta.
6. **Planning update authority**: `save_planning()` and `sync_next_plan()`
   are explicit mutations without operation/recovery authority.
7. **Simulator sharing Planning**: Simulator reads planning via
   `NarrativeTurnContextBinder._find_chapter_plan()` but does not write it.
8. **Planning vs directory conflict**: Planning is file-based; directory
   discovery is separate. When they disagree, there is no defined winner.
9. **Chapter missing, Planning exists**: `current_target_chapter()` would
   return the Planning target; actual chapter file may not exist.
10. **Chapter exists, Planning missing**: Directory scan discovers the chapter;
    `current_target_chapter()` falls back to `state.current_chapter + 1`.

## 8. Version and Source Lifecycle

### 8.1 Findings

- `version_manager.list_versions()`: PURE_READ (probe: 0 delta). Scans
  `drafts/edited/manual` and `selected` metadata.
- `version_manager.get_selected_version()`: **HIDDEN_MUTATION** (probe: +1 file).
  Calls `load_versions_index()` which creates `chapter_NNN_versions.json`.
- `version_manager.select_version()`: EXPLICIT_MUTATION. Updates
  `versions["selected"]` and saves index.
- `version_manager.format_chapter_id()`: Utility, no side effects.
- `version_manager.version_label`: `{source_type}_v{version:03d}` format
  (e.g., `manual_v001`).
- Chapter N+1 has no initial source version authority; empty chapter is allowed.

### 8.2 Audit answers

1. **Chapter N+1 initial source creator**: No existing authority. Must be
   created by the future Chapter create operation.
2. **Empty Chapter allowed**: **Yes**. `list_versions()` returns empty
  drafts/edited/manual arrays.
3. **`manual_v001` auto-creation**: **No**. May be created explicitly via
   version writer, or implicitly via `get_selected_version()` (which is
   FORBIDDEN for next-chapter paths).
4. **Creation trigger**: `get_selected_version()` creates index on read
   (FORBIDDEN). Must use explicit mutation only.
5. **Version label scope**: Chapter-local only.
6. **Selected version storage**: `chapter_NNN_versions.json` → `selected` field.
7. **Simulator source selection**: Should use explicit Chapter N+1 source,
   not `get_selected_version()` compatibility path.
8. **Auto-select**: Must not auto-select. Explicit user or operation decision.
9. **Cross-chapter version mutation**: Initialization of N+1 must not modify
   N's selected version.
10. **Shared authority**: Traditional and Simulator share the same version
    files but may resolve differently.

## 9. Canon and Revision Lifecycle

### 9.1 Findings

- Canon is **chapter-local**. `data/canon_versions/chapter_NNN/index.json`.
- `RevisionService.read_active_canon()`: PURE_READ. Returns active Canon
  metadata or None.
- `RevisionService.active_canon()`: **LEGACY_READ_WITH_SIDE_EFFECT**. Creates
  Canon content, index, and audit when a chapter file exists without Canon.
  Probe: +3 files on Fixture A, error on Fixture B (no chapter file).
- `RevisionService.create_and_apply_revision()`: EXPLICIT_MUTATION. Creates
  new Canon revision, updates active pointer.
- Chapter N Commit produces a chapter-local Canon revision.
- Chapter N+1 has **no defined initial Canon source**. The Turn binder reads
  same-chapter Canon only.

### 9.2 Audit answers

1. **Canon scope**: **Chapter-local**. Not timeline- or project-level.
2. **Chapter N Commit Canon scope**: Chapter N only.
3. **Chapter N+1 initial Canon**: **Must be defined by owner decision**.
4. **Canon auto-creation on read**: `active_canon()` does this (FORBIDDEN).
5. **Next chapter context bind**: Must bind Chapter N+1's own Canon, not
   Chapter N's. Cross-chapter Canon read is for background only.
6. **Read previous chapter facts**: Via Branch Narrative Memory events and
   chapter summaries, not Canon.
7. **Canon summary/aggregate**: No aggregate exists.
8. **Active revision switch during N+1 init**: Must be prevented by explicit
   creation authority.
9. **`committed_with_warnings` as completion**: **Yes** for 0D5 Completion.
   Cannot authorize next Turn without typed warning classification.
10. **Commit recovery after next chapter resolution**: Durable commit result
    must remain authoritative.

## 10. Commit-to-Completion Boundary

### 10.1 Chain

```text
Candidate approved
  → NarrativeChapterCommitService.commit_candidate()
  → ChapterCommitService.commit_chapter()
    → Phase A: preflight (scope, fingerprint, review freshness)
    → Phase B: source resolution
    → Phase C: Canon revision activation
    → Phase D: commit execution (write Canon, chapter file, summary, state)
    → Phase E: post-commit (memory, vector, warnings)
  → Durable commit result (stored in commit_operations/{op_id}.result.json)
  → Simulator read model detects completion
  → Completion view rendered
  → "Start next chapter" button enabled (if next chapter file exists)
```

### 10.2 Audit answers

1. **Chapter completion authority**: `ChapterCommitService.commit_chapter()`
   with durable commit result.
2. **Durable commit result scope**: Full scope (project/timeline/branch/chapter/source/candidate)
   with fingerprints.
3. **Completion states**: `committed`, `committed_with_warnings`,
   `already_committed`.
4. **`committed_with_warnings` navigation**: **Allowed** for navigation but
   not for Turn start without typed warning resolution.
5. **Memory warning block**: **Yes** for Turn start (memory stale).
6. **Vector warning block**: **Yes** for Turn start (vector not ready).
7. **`recovery-required` block**: **Yes** for all navigation and creation.
8. **Next chapter resolver binding**: Must bind to commit result ID and
   fingerprint for CAS.
9. **Chapter progression marker**: `state.current_chapter` is the marker.
10. **Completion "next chapter absent"**: Button disabled, no backend target.

## 11. Branch Cross-Chapter Semantics

### 11.1 Findings

- Branch identity is **timeline-global** (not chapter-scoped).
  Path: `data/branches/{timeline_id}/registry.json`.
- Branch registry contains `active_branch_id`, `registry_revision`, and
  branch entries with lifecycle status.
- Branch projected state (`narrative_memory/state/{timeline}/{branch}/current.json`)
  is also timeline/branch scoped with a mutable `chapter` field.
- `NarrativeBranchStore._read_registry_projection()` reads registry and
  returns `active_branch_id` and `registry_revision`.
- `SimulatorLoopStateService._branch()` reads branch manifest for vector
  readiness, matching `branch_lifecycle_status`.
- No existing CAS transition advances branch state from chapter N to N+1.

### 11.2 Audit answers

1. **Branch scope**: **Timeline-level**. Not project- or chapter-level.
2. **Same branch_id across chapters**: **Yes**. Branch identity persists
   across chapter changes.
3. **Branch registry chapter record**: **No**. Registry is timeline-scoped,
   not chapter-scoped.
4. **Continue active Branch or create new**: **Reuse active Branch** per
   existing structure. No new branch creation for chapter switch.
5. **Archive/restore history chapters**: Archive/restore affects branch
   lifecycle, not chapter history.
6. **Branch A Chapter N+1 reads Branch A Chapter N**: Via branch-scoped
   Narrative Memory events and projected state.
7. **Branch A/B state isolation**: **Maintained** via branch-scoped paths.
   Branch B state is never read when Branch A is active.
8. **Active Branch pointer across chapter switch**: **Should remain** —
   branch is timeline-global.
9. **Browse non-active Branch Start Next Chapter**: **Must use active Branch**
   per existing semantics.
10. **Registry revision as CAS fence**: **Yes**. `registry_revision` is the
    existing freshness fence for branch operations.

## 12. Turn/History/Candidate Scoping

### 12.1 Artifact scope table

| Artifact | Project | Timeline | Branch | Chapter | Source | Candidate | Operation | Fingerprint |
|---|---|---|---|---|---|---|---|---|
| Turn Plan | ✓ | ✓ | ✓ | ✓ | ✓ | | ✓ | ✓ |
| Turn Result | ✓ | ✓ | ✓ | ✓ | ✓ | | ✓ | ✓ |
| Transition | ✓ | ✓ | ✓ | ✓ | | | ✓ | ✓ |
| History | ✓ | ✓ | ✓ | ✓ | | | | |
| Candidate | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Review | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Commit | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

### 12.2 Audit answers

1. **Chapter N+1 inherits old Turn operations**: **No**. Turn IDs are
   branch+chapter scoped.
2. **Chapter N+1 inherits old Candidates**: **No**. Candidate scope includes
   chapter; old Candidates fail scope match.
3. **Chapter N+1 inherits old Reviews**: **No**. Review binds to Candidate
   which is chapter-scoped.
4. **Chapter N+1 inherits old Commit operations**: **No**. Commit scope
   includes chapter.
5. **Old Candidate URL in new Chapter**: **Fail closed** — scope mismatch.
6. **Old History read-only browsing**: **Yes**. History is immutable,
   filtered by chapter.
7. **New Chapter default History empty**: **Yes**. History is chapter-scoped.

### 12.3 Frontend cleanup on chapter switch

- `turn_id`: Cleared via `push({turn_id: null, ...})` in `nextChapter()`.
- `candidate_id`: Cleared via `push({candidate_id: null, ...})`.
- `review view`: Reset via `render()` after URL change.
- `commit view`: Reset via `render()` after URL change.
- `preview/action`: Cleared via `push({action_id: null, ...})`.
- `operation identity`: New operation IDs generated per operation.
- `recovery state`: Read model re-reads recovery state.

## 13. Narrative Memory Carry-Forward

### 13.1 Findings

- `branch_narrative_memory_service.py` manages:
  - `events()`: Chapter-scoped event retrieval (`events/chapter_*.json`)
  - `append_event()`: Writes events with `source_version_id`, `canon_revision_id`
  - `confirm_event()`: State transitions with immutable transitions
  - `snapshot()`: Chapter state snapshots with `source_event_fingerprints`
  - `project_state()`: Branch-global projected state (0D4-D authority)
- `context_assembly_service.py` merges `canon_memory`, `chapter_summaries`,
  `retrieved_memories`, `narrative_state` and computes `chapter_number = current_chapter + 1`.
- `memory_repair_service.py`: Memory repair authority.

### 13.2 Audit answers

1. **Chapter Commit state updates**: Branch events, projected state,
   chapter summaries, legacy memory index.
2. **Sync vs post-task**: Event writes are sync; vector indexing is post-task.
3. **Post-task**: Vector indexing, memory repair.
4. **Character/relationship/location/time/foreshadowing**: Managed by
   Narrative Memory services and projected state.
5. **Chapter N+1 Context Binder reads**: Branch State, Planning, world,
   characters, rolling window, dependencies. Does not compose prior chapter
   Branch events/snapshot into formal carry-forward.
6. **Branch Narrative State cross-chapter**: **Branch-global** (not
   chapter-scoped). Contains mutable `chapter` field.
7. **Narrative Memory branch isolation**: **Strictly branch-isolated**.
8. **Canon vs Memory conflict**: Canon is authoritative for committed facts;
   Memory is authoritative for narrative state.
9. **Carry-forward snapshot**: `snapshot()` exists but no formal carry-forward
   composition exists.
10. **派生读取路径**: `context_assembly_service.py` → `CanonMemoryAdapter.read()`
    → `NarrativeMemoryService.events()`.
11. **Memory stale navigation**: **Allowed** (read-only).
12. **Memory stale Turn confirmation**: **Not allowed** (stale guard).

## 14. Vector/Chroma Readiness

### 14.1 Findings

- `vector_index_lifecycle.py`:
  - `_load_verified_manifest()`: Validates `vector_ready=True`,
    `branch_lifecycle_status=open`, project/timeline/branch/Canon match,
    integrity fingerprint. Throws `BranchVectorNotReady` on failure.
  - `index_scoped_records()`: Branch-aware write; deletes old scope, adds new,
    writes `vector_ready=True` manifest with `source_fingerprints`,
    `index_revision`, `last_completed_operation_id`.
  - `search_scoped()`: Calls `_load_verified_manifest()` before search;
    filters by project/timeline/branch/Canon/lifecycle.
  - `sync_branch_index()`: Handles archive/rebuild/restore/repair.
- `vector_client_manager.py`: Creates/reuses Chroma `PersistentClient` and
  `storyos_memory` collection.
- `SimulatorLoopStateService._branch()`: Reads branch manifest for
  vector readiness without probing Chroma.

### 14.2 Audit answers

1. **Vector state after Chapter Commit**: Ready (if commit post-task
   succeeded) or stale (if warning).
2. **`committed_with_warnings` vector**: May include vector stale warning.
3. **Next chapter resolver vector dependency**: Should not depend on vector
   for resolution (vector is advisory).
4. **Turn Planner vector dependency**: Should use vector with proper scoping.
5. **Vector stale browse**: **Allowed** (read-only).
6. **Vector stale Turn start**: **Not allowed** (readiness gate).
7. **Cross-chapter retrieval scope**: Project/timeline/branch/Canon filter.
8. **Mandatory filtering**: Project, timeline, branch, Canon, branch lifecycle.
9. **Chapter filter**: **Exact filter** (not history range).
10. **Pollution prevention**: Branch lifecycle + Canon revision filters
    prevent cross-branch/future-chapter contamination.

## 15. Traditional Mode Sharing

### 15.1 Findings

- Traditional and Simulator share **filesystem artifacts** (chapters, versions,
  Canon, planning).
- Traditional target: `current_target_chapter()` → `next_chapter_plan.chapter_id`
  or `state.current_chapter + 1`.
- Simulator target: `chapter_progression.next_chapter_available` (file
  existence check).
- Both use `data/chapters/chapter_NNN.md` as chapter identity.
- `web/routes.py` Traditional routes handle chapter list, selection, creation,
  version management, generation, review.

### 15.2 Audit answers

1. **Traditional next chapter entry**: **Yes** — via planning and
   `current_target_chapter()`.
2. **Simulator reuse Traditional entry**: **Should not** — different resolution
   strategy. Shared resolver needed.
3. **Shared Chapter pointer**: **Should** — both modes operate on the same
   `state.current_chapter` and chapter files.
4. **Shared selected version**: **Yes** — same version files and index.
5. **Simulator enter N+1 change Traditional current**: **Should not** — mode
   isolation required.
6. **Traditional return after Simulator**: Should show last Traditional state.
7. **Simulator overwrite Traditional draft**: **Must not** — separate
   creation paths.
8. **Traditional quality review vs Simulator readiness**: **Should be independent**
   — different review authorities.
9. **Simulator approval isolation**: **Yes** — separate review authority.
10. **URL isolation**: Mode is determined by URL `mode=simulator` vs default.

## 16. Completion Next-Chapter Behavior

### 16.1 Full trace

```text
HTML: [data-start-next-chapter] button in simulator-candidate-review.js
  → onClick handler (simulator-candidate-review.js:57)
  → nextChapter() (simulator-candidate-review.js:56)
  → Checks chapter_progression.next_chapter_available
  → If true: push({chapter_id: next_chapter_id, candidate_id: null,
         turn_id: null, action_id: null, view: "narrative-turn"})
  → window.history.pushState() + popstate event
  → loadState() on popstate
  → No API call, no backend request, no filesystem write
```

### 16.2 Classification

**EXISTING_NEXT_CHAPTER_NAVIGATION**

- Current text: "Open the next chapter explicitly" (when available)
- Disabled condition: `!complete.next_chapter_available`
- Disabled title: "Next-chapter navigation is not available from the backend."
- Target: URL parameter `chapter_id = chapter_id + 1`
- Pure read: **Yes** — no API call
- Implicit write: **No** — no filesystem or state mutation

### 16.3 Missing next chapter behavior

- Button disabled
- Title: "Next-chapter navigation is not available from the backend."
- No creation flow triggered
- User sees Completion view without next-chapter navigation path

## 17. Cold-Start Side Effects

### 17.1 Classified paths

| Read path | Classification | Evidence (fixture probe) |
|---|---|---|
| `SimulatorLoopStateService.build()` | PURE_READ (with bug) | 0 delta; KeyError: 'revision' on manifest |
| `list_versions()` | PURE_READ | 0 delta on all 3 fixtures |
| `get_selected_version()` | **HIDDEN_MUTATION_BEHIND_READ** | +1 file: `chapter_NNN_versions.json` |
| `read_active_canon()` | PURE_READ | 0 delta on all 3 fixtures |
| `active_canon()` | **LEGACY_READ_WITH_SIDE_EFFECT** | +3 files: Canon+index+audit |
| `load_planning()` | PURE_READ (nondeterministic normalization) | 0 delta; in-memory only |
| `BranchMemoryService.retrieval_history(selected=None)` | PURE_READ | Returns stored entries |
| `BranchMemoryService.retrieval_history(selected=...)` | EXPLICIT_MUTATION | Appends retrieval history |

### 17.2 Policy

**FORBIDDEN for next-chapter resolve/browse:**
- `get_selected_version()` — creates versions index on read
- `active_canon()` — creates Canon artifacts on read
- `BranchMemoryService.retrieval_history(selected=...)` — appends history

**ALLOWED (PURE_READ only):**
- `SimulatorLoopStateService.build()` — with manifest bug fix
- `list_versions()`
- `read_active_canon()`
- `load_planning()`
- `BranchMemoryService.retrieval_history(selected=None)`

## 18. Temporary Fixture Findings

### Fixture A: Next chapter exists (3 probes)

| Probe | Files changed | Key finding |
|---|---|---|
| `list_versions(2)` | 0 | Pure read |
| `get_selected_version(2)` | **+1** | Created `chapter_002_versions.json` |
| `read_active_canon(2)` | 0 | Pure read, returned null |
| `active_canon(2)` | **+3** | Created Canon, index, audit |
| `SimulatorLoopStateService.build()` | 0 | KeyError: 'revision' |
| `load_planning()` | 0 | Pure read |
| **Total** | **4** | |

### Fixture B: Next chapter absent

| Probe | Files changed | Key finding |
|---|---|---|
| `list_versions(2)` | 0 | Pure read |
| `get_selected_version(2)` | **+1** | Created `chapter_002_versions.json` |
| `read_active_canon(2)` | 0 | Pure read, returned null |
| `active_canon(2)` | Error | "No active canon version" — no chapter file |
| `SimulatorLoopStateService.build()` | 0 | KeyError: 'revision' |
| `load_planning()` | 0 | Pure read |
| **Total** | **1** | |

### Fixture C: Branch isolation

Same as Fixture B pattern. Branch A/B isolation maintained via branch-scoped
paths. Branch B archived state does not leak into Branch A context.

### Fixture D: Completion warning variants

Not probed via temporary fixture; classified via code audit:
- `committed_with_warnings`: Terminal for Completion, not for Turn start
- `memory stale`: Navigation allowed, Turn blocked
- `vector stale`: Navigation allowed, Turn blocked
- `recovery required`: Navigation and Turn blocked

All fixtures deleted after probe. No real project or Chroma data touched.

## 19. Authority Map

See `docs/design/chapter_progression_authority_map.md`.

## 20. State Machine

See `docs/design/chapter_to_chapter_state_machine.md`.

## 21. Cross-Chapter Invariants

See `docs/design/cross_chapter_continuity_contract.md`.

## 22. Concurrency and Recovery Matrix

See `docs/design/next_chapter_risk_matrix.md`.

## 23. Gap Matrix

| Gap | Severity | Phase |
|---|---|---|
| Next chapter resolution | P1 | 0D6-A after owner decision |
| Chapter creation | **P0** | Owner decision + new authority |
| Current chapter selection | P1 | Owner decision |
| Initial source version | P1 | 0D6-A after decision |
| Initial Canon | **P0** | Owner decision |
| Branch carry-forward | P1 | 0D6-B |
| Memory carry-forward | P1 | 0D6-B |
| Vector readiness | P1 | 0D6-B (with bug fix) |
| Planning cursor | P1 | Owner decision |
| Completion warnings | P1 | 0D6-B |
| Traditional sharing | P1 | 0D6-A |
| URL navigation | P2 | 0D6-C |
| Recovery | **P0** | 0D6-A |
| Scope isolation | **P0** | 0D6-RC |

## 24. Proposed 0D6 Slices

### Phase 0D6-A: Chapter Lifecycle Authority

- **Objective**: Shared Chapter creation/resolution authority with exactly-once semantics
- **Authority owner**: New durable authority or hardened existing
- **Allowed files**: New system service + wire contract
- **Forbidden**: Canon, Branch, Turn mutation
- **Mutation budget**: Chapter identity + version + Canon initialization
- **Provider budget**: Zero
- **Focused tests**: Creation idempotency, concurrency, recovery, scope isolation
- **Browser evidence**: Completion → next chapter navigation
- **Entry gate**: Owner decisions recorded
- **Exit gate**: Creation idempotent, concurrent-safe, recovery-verified
- **TRAE reasoning**: medium-high
- **Agent strategy**: single Agent

### Phase 0D6-B: Progression Read Model

- **Objective**: Read model for Chapter readiness, Branch carry-forward, Vector/Canon/Memory projections
- **Authority owner**: Existing read adapters
- **Allowed files**: Read model + adapters
- **Forbidden**: New mutations
- **Mutation budget**: Read-only adapters
- **Provider budget**: Zero
- **Focused tests**: Read adapter correctness, projection integrity
- **Browser evidence**: Next chapter readiness display
- **Entry gate**: 0D6-A passed
- **Exit gate**: All readiness projections verified
- **TRAE reasoning**: medium
- **Agent strategy**: single Agent

### Phase 0D6-C: Product Navigation

- **Objective**: Next Chapter UI, URL navigation, Completion view wiring
- **Authority owner**: Frontend + routes
- **Allowed files**: JS, HTML, routes
- **Forbidden**: Backend authority changes
- **Mutation budget**: Frontend state management
- **Provider budget**: Zero
- **Focused tests**: Frontend contract, URL isolation, mode isolation
- **Browser evidence**: Real Chromium navigation test
- **Entry gate**: 0D6-B passed
- **Exit gate**: Two-chapter usable loop
- **TRAE reasoning**: medium
- **Agent strategy**: single Agent

### Phase 0D6-D: Continuity and Recovery

- **Objective**: Cross-chapter Branch/Memory/Vector continuity, recovery
- **Authority owner**: Cross-cutting adapters
- **Allowed files**: Adapters, recovery hooks
- **Forbidden**: Core authority changes
- **Mutation budget**: Read-only + recovery
- **Provider budget**: Zero
- **Focused tests**: Cross-chapter isolation, recovery verification
- **Browser evidence**: Recovery UI
- **Entry gate**: 0D6-C passed
- **Exit gate**: All continuity invariants held
- **TRAE reasoning**: medium-high
- **Agent strategy**: single Agent

### Phase 0D6-RC: Real Chromium Acceptance

- **Objective**: Two-chapter usable loop acceptance
- **Authority owner**: All
- **Allowed files**: All (if needed)
- **Forbidden**: New scope
- **Mutation budget**: Full stack
- **Provider budget**: Zero (real data only)
- **Focused tests**: E2E, browser
- **Browser evidence**: Full two-chapter loop
- **Entry gate**: 0D6-D passed
- **Exit gate**: Real Chromium two-chapter acceptance
- **TRAE reasoning**: medium-high
- **Agent strategy**: single Agent

## 25. Model/Reasoning/Agent Recommendations

| Phase | TRAE reasoning | Agent strategy | Rationale |
|---|---|---|---|
| Owner design closure | medium-high | single Agent | Cross-module authority decisions |
| 0D6-A | medium-high | single Agent | Exactly-once lifecycle authority |
| 0D6-B | medium | single Agent | Read adapter wiring |
| 0D6-C | medium | single Agent | UI routing and state |
| 0D6-D | medium-high | single Agent | Cross-chapter continuity/recovery |
| 0D6-RC | medium-high | single Agent | Critical acceptance |

## 26. Validation Ledger

| Full command | Collected | Passed | Failed | Skipped | Warnings | Exit |
|---|---|---|---|---|---|---|
| `test_phase0d5b_*.py + test_phase0d5c_*.py` | 19 | 19 | 0 | 0 | 0 | 0 |
| `test_chapter_commit_service.py + test_revision_service.py` | 20 | 20 | 0 | 0 | 0 | 0 |
| `test_real_data_protection.py + test_static_path_guard.py + test_review_gate.py` | 12 | 12 | 0 | 0 | 0 | 0 |
| `test_phase0d4f_*.py` | 14 | 14 | 0 | 0 | 0 | 0 |
| **Total** | **65** | **65** | **0** | **0** | **0** | **0** |
| Fixture probe scripts (3 fixtures) | 3 | 3 | 0 | 0 | 0 | 0 |
| **Fixture SHA-256 probes** | **18** | **18** | 0 | 0 | 2 expected side-effect findings | 0 |

Category labels overlap and are not additive.

## 27. Protection and Filesystem Audit

### Before/after hash verification

- `story-os-demo/data` digest before/after validation: unchanged
- `data/chroma` digest before/after validation: unchanged
- All probe roots were temporary and deleted

### Operations verified as zero

```text
Provider calls: 0
External network: 0
Production source changes: 0
Production mutations: 0
Real project writes: 0
Real data/chroma writes: 0
Chapter creation in real project: 0
Version creation in real project: 0
Canon creation in real project: 0
Git write operations: 0
```

### Git status unchanged

`git status --short` before and after was identical. All probe files were
temporary and deleted.

## 28. Final Verdict

```text
Phase 0D6-P: PASSED
Phase 0D6 Architecture: READY FOR OWNER REVIEW
Phase 0D6 implementation: BLOCKED
OWNER DECISION REQUIRED
Phase 0D6-A: NOT ENTERED
```

### Completion criteria met

- [x] Chapter identity authority identified
- [x] Existing creation mutation identified
- [x] Existing next-chapter behavior traced
- [x] Version initialization mapped
- [x] Canon carry-forward mapped
- [x] Branch cross-chapter semantics mapped
- [x] Memory carry-forward mapped
- [x] Vector readiness mapped
- [x] Traditional sharing mapped
- [x] Cold-start side effects audited (fixture-verified)
- [x] Authority Map completed
- [x] State Machine completed
- [x] Invariants completed
- [x] Concurrency/recovery matrix completed
- [x] P0/P1 gaps listed
- [x] Implementation slices proposed
- [x] TRAE single-Agent recommendations included
- [x] No production implementation entered

### Blocking conditions

These conditions **block Phase 0D6 implementation**, not Phase 0D6-P:

- Chapter identity authority unclear (must be resolved by owner)
- Chapter creation hidden behind read (must be prohibited)
- Canon carry-forward source unclear (must be defined)
- Branch cross-chapter semantics contradictory (must be resolved)
- Traditional and Simulator use conflicting Chapter authorities (must be unified)
- Next Chapter requires frontend-generated identity (must be backend-issued)
- Cold-start read mutates production state (must be prohibited)

Stop here. Do not enter 0D6-A.