# Next Chapter Risk Matrix — Chapter Progression Concurrency Scenarios

> **Generated:** 2026-07-28
> **Scope:** Chapter N+1 creation, progression, and recovery concurrency
> **Audit basis:** `ChapterCommitService`, `CommitRunStore`, `BranchLifecycleService`, `VersionManager`, `RevisionService`

---

## 1. Overview

This document enumerates every concurrency scenario that can occur during Chapter N+1 progression. Each scenario is classified by severity (P0 — critical data loss risk, P1 — data integrity risk, P2 — user experience risk) and specifies the required **CAS (Compare-And-Swap)** fingerprint, **durable recovery** mechanism, **fail-closed** behavior, and **forbidden duplicate** guard.

### Authority Model

The Chapter progression system rests on four authority layers:

| Layer | Authority | Durability |
|---|---|---|
| **Lock** | `ChapterCommitService._lock` (process-level) + `BranchLifecycleService._registry_lock` (filesystem-level) | In-process + filesystem `.lock` directory with PID+nonce owner |
| **CAS Fingerprint** | `operation_id` + `chapter_id` + `source_hash` | Embedded in `CommitRun` record and phase file |
| **Durable Result** | `CommitRunStore` — filesystem journal under `data/commit_runs/` | Permanent JSON files, cross-process readable |
| **Phase Marker** | Operation phase file under `data/branch_operations/{operation_id}.phase.json` | Temporary, recoverable from durable result |

### Severity Definitions

| Level | Definition | Example |
|---|---|---|
| **P0** | Simultaneous writes can cause data loss or corruption without recovery | Two create requests for same chapter |
| **P1** | Concurrent operations can cause stale state, lost writes, or inconsistent views | Branch switch during creation, Canon revision change |
| **P2** | User-facing inconsistency or unnecessary retry; no data loss | Browser refresh during creation, back/forward navigation |

---

## 2. Concurrency Scenarios

### Scenario 1: create vs create (Severity: P0)

**Two simultaneous requests to create Chapter N+1.**

| Dimension | Value |
|---|---|
| **Expected Winner** | First-writer-wins via `ChapterCommitService._lock` |
| **Required CAS** | `chapter_id` + `operation_id` + `source_hash` |
| **Durable Recovery** | `CommitRunStore` replay by `commit_key` (SHA-256 of `project_id:chapter_id:source_hash:source_version_id:commit`) |
| **Fail-Closed Behavior** | Second creation returns `CommitStatus.ALREADY_COMMITTED` (when identical source) or `CommitStatus.FAILED` (when conflicting source); `_check_idempotency()` detects existing `CommitRun` with matching `source_hash` |
| **Forbidden Duplicate** | Duplicate `chapter_id` + `operation_id` combination; `CommitRunStore.find_by_chapter_and_hash()` must return at most one run |

**Mechanism:** `commit_chapter()` acquires `self._lock` (line 71 of `chapter_commit_service.py`). Inside the lock, `_check_idempotency()` first queries `CommitRunStore.load(commit_key)` and `CommitRunStore.find_by_chapter_and_hash()`. If a matching run exists, `_handle_existing_run()` returns `ALREADY_COMMITTED`. The `commit_key` is deterministically generated from `project_id`, `chapter_id`, `source_hash`, and `source_version_id`, so identical content always produces the same key, enabling safe replay.

---

### Scenario 2: create vs existing Chapter appears (Severity: P1)

**Chapter N+1 is created by Traditional Mode while Simulator resolves.**

| Dimension | Value |
|---|---|
| **Expected Winner** | Existing chapter wins (filesystem is authority) |
| **Required CAS** | Chapter file existence check (`data/chapters/chapter_NNN.md`) |
| **Durable Recovery** | Re-read chapter state via `_phase_a_preflight()` + filesystem scan |
| **Fail-Closed Behavior** | `_phase_c_prepare()` detects existing chapter file, appends warning "正式章节文件已存在，本次将覆盖。"; creation proceeds but preserves existing as rollback snapshot |
| **Forbidden Duplicate** | Overwriting existing chapter without explicit user intent; the snapshot mechanism in `_create_snapshot()` ensures rollback capability |

**Mechanism:** Before core commit, `_phase_c_prepare()` checks `self._chapter_path(chapter_id).exists()` and records a warning. `_create_snapshot()` preserves pre-existing files. If Traditional Mode creates the chapter between preflight and core commit, the snapshot captures the Traditional version, and the Simulator write overwrites it. Traditional Mode does NOT have access to `ChapterCommitService` lock, so the race is between a locked commit and an unlocked filesystem write. The filesystem remains the ultimate authority: if the Traditional file appears first on disk, the Simulator's snapshot captures it; if the Simulator commits first, Traditional's write overwrites and triggers a snapshot warning.

---

### Scenario 3: create vs active Branch switch (Severity: P1)

**User switches active branch during Chapter N+1 creation.**

| Dimension | Value |
|---|---|
| **Expected Winner** | Branch switch blocked during creation by `BranchLifecycleService._registry_lock` |
| **Required CAS** | `registry_revision` check (expected registry revision captured at operation claim) |
| **Durable Recovery** | Re-resolve branch scope after acquisition; `_request_payload()` includes `expected_registry_revision` |
| **Fail-Closed Behavior** | If `registry_revision` changed, `BranchLifecycleService.select()` raises `NarrativeTurnError.BRANCH_OPERATION_STALE_REVISION`; creation side must verify branch hasn't changed via `_assert_scope()` |
| **Forbidden Duplicate** | Cross-branch creation — chapter writes must not span branch boundaries |

**Mechanism:** `BranchLifecycleService.select()` acquires `_registry_lock` (filesystem-level `.lock` directory with PID+nonce owner inside `_locks_dir`). `ChapterCommitService` operates within a branch context (`ProjectContext`) but does not acquire the registry lock. The branch switch operation captures `expected_registry_revision` at operation claim time (line 324 of `narrative_branch_lifecycle_service.py`). If the registry revision changes during chapter creation, the branch switch is stale and fails. Conversely, if branch switch completes first, the subsequent chapter creation must verify branch scope matches.

---

### Scenario 4: create vs Branch archive (Severity: P2)

**Branch is archived during Chapter N+1 creation.**

| Dimension | Value |
|---|---|
| **Expected Winner** | Archive blocked during creation via `BranchLifecycleService._registry_lock` |
| **Required CAS** | Branch lifecycle status check (`BranchLifecycleStatus.ARCHIVED`) |
| **Durable Recovery** | Re-check branch lifecycle via `store.get_branch()` and inspect `lifecycle_status` |
| **Fail-Closed Behavior** | If branch is archived, creation fails with `BRANCH_ARCHIVED` error; `RevisionService.create_and_apply_revision()` checks branch status before Canon write |
| **Forbidden Duplicate** | Creating chapter on archived branch; `BranchLifecycleService.create()` blocks parent branch archive |

**Mechanism:** `BranchLifecycleService.archive()` acquires `_registry_lock` and checks `branch.lifecycle_status == BranchLifecycleStatus.ARCHIVED`. If the branch was already archived, it completes idempotently via `_complete(recovery_performed=True)`. The Chapter creation path must verify the branch is not archived before commit. After acquisition, the archive operation checks `expected_registry_revision` — if the creation's branch write updated the registry, the archive fails with stale revision.

---

### Scenario 5: create vs Planning update (Severity: P2)

**Planning is updated during Chapter N+1 creation.**

| Dimension | Value |
|---|---|
| **Expected Winner** | Latest planning wins (planning is non-authoritative advisory) |
| **Required CAS** | None needed (planning is advisory, not a gate) |
| **Durable Recovery** | Re-read planning via `PlanningService.load_planning()` after creation completes |
| **Fail-Closed Behavior** | Creation uses result over planning; planning cursor is updated in `_phase_e_post_commit()` via `_update_planning_anchor()` |
| **Forbidden Duplicate** | None — planning updates are idempotent and overwritable |

**Mechanism:** `PlanningService.load_planning()` is a PURE_READ with nondeterministic normalization (in-memory ID/timestamp fill, see `chapter_progression_authority_map.md`). Planning is treated as advisory metadata, not a concurrency gate. The `_update_planning_anchor()` post-commit task marks the planning anchor as changed after successful commit, ensuring the planning system learns of the new chapter. Even if planning is updated during creation, the commit result is authoritative and planning is re-read afterward.

---

### Scenario 6: create vs Canon revision change (Severity: P1)

**Canon is revised during Chapter N+1 creation.**

| Dimension | Value |
|---|---|
| **Expected Winner** | Canon change wins via first-writer-wins on `canon_revision_id` |
| **Required CAS** | `canon_revision_id` check (captured at `_phase_d_core_commit()` via `RevisionService.create_and_apply_revision()`) |
| **Durable Recovery** | Re-resolve Canon context; `RevisionService.active_canon()` returns latest Canon revision |
| **Fail-Closed Behavior** | If Canon was revised between source resolution and core commit, the creation uses the latest Canon revision ID; stale Canon is rejected by comparing `canon_revision_id` |
| **Forbidden Duplicate** | Using stale Canon revision; the Canon index under `data/canon_versions/chapter_NNN/canon_index.json` is the single source of truth |

**Mechanism:** `_phase_d_core_commit()` invokes `RevisionService.create_and_apply_revision()` which returns a `canon_revision_id`. This ID is stored in `CommitRun.canon_revision_id`. If a concurrent Canon revision change occurs (via `RevisionService.create_and_apply_revision()` on the same chapter), the latest Canon wins because the commit captures the revision ID at the moment of write. Stale Canon carry-forward is forbidden: the creation must verify that the Canon revision it captured matches the current Canon index.

---

### Scenario 7: create vs selected version change (Severity: P2)

**Selected version is changed during Chapter N+1 creation.**

| Dimension | Value |
|---|---|
| **Expected Winner** | Creation captures version at start via `source_version_id` + `source_hash` |
| **Required CAS** | `source_version_id` + fingerprint (content hash via `_hash_content()`) |
| **Durable Recovery** | Re-select version via `VersionManager.select_version()` if creation is retried |
| **Fail-Closed Behavior** | Creation uses captured version; if version was changed, the `source_hash` differs and creates a new `commit_key`, preventing collision |
| **Forbidden Duplicate** | None — different selection produces different `source_hash`, which produces different `commit_key`, enabling independent commits |

**Mechanism:** `_phase_b_source_resolution()` captures `source_version_id` and computes `source_hash` via SHA-256 of content. These are embedded in the `commit_key`. If the selected version changes, the new selection produces a different `source_hash`, yielding a different `commit_key`. The `_check_idempotency()` query matches on `source_hash`, so a changed version is treated as a genuinely new creation, not a duplicate. The creation uses the version resolved at the time `commit_chapter()` was called.

---

### Scenario 8: response loss after Chapter creation (Severity: P1)

**Client loses connection after creation succeeds but before response is received.**

| Dimension | Value |
|---|---|
| **Expected Winner** | Durable commit result exists in `CommitRunStore` |
| **Required CAS** | `operation_id` (mapped to `commit_key`) |
| **Durable Recovery** | Re-read `CommitRunStore` by `operation_id` → `commit_key` mapping; `CommitRunStore.load(commit_id)` returns stored run |
| **Fail-Closed Behavior** | Never re-creates existing chapter; `_check_idempotency()` detects completed run and returns `ALREADY_COMMITTED` |
| **Forbidden Duplicate** | Duplicate creation — the same `operation_id` must always resolve to the same commit result |

**Mechanism:** The `CommitRun` is saved to `CommitRunStore` at two critical points: (1) after `_phase_c_prepare()` creates the `CommitRun` record (line 125-132), and (2) after `_phase_d_core_commit()` succeeds (line 157-162). Both writes use `self.run_store.save(commit_run)` which writes to `data/commit_runs/{commit_id}.json`. On retry, the client resends with the same `operation_id`, producing the same `commit_key`. `_check_idempotency()` finds the existing `CommitRun` and `_handle_existing_run()` returns `ALREADY_COMMITTED` with the complete `CommitResult`. The `CommitRunStore` ensures exactly-once semantics across process restarts.

---

### Scenario 9: durable result exists but phase missing (Severity: P1)

**Commit succeeded but phase file (`.phase.json`) is lost or corrupted.**

| Dimension | Value |
|---|---|
| **Expected Winner** | Durable result (`CommitRun`) is source of truth |
| **Required CAS** | `operation_id` + `commit_id` |
| **Durable Recovery** | Read `CommitRunStore.load(commit_id)` directly; skip phase check if durable result is `completed` or `completed_with_warnings` |
| **Fail-Closed Behavior** | Always prefer durable result; if `CommitRun.status` is `completed`, treat as success regardless of phase file state |
| **Forbidden Duplicate** | Re-committing completed chapter; `_handle_existing_run()` returns cached result without re-executing |

**Mechanism:** `BranchLifecycleService._claim()` (line 290-360) loads the phase file via `_load_json(self._phase_path(operation_id))`. If the phase file is missing or corrupted, `_load_json` returns `{}` (line 381 of `narrative_branch_lifecycle_service.py`). The `_claim()` method then compares the phase's `canonical_request_fingerprint` against the request fingerprint — if the phase is empty, the fingerprint comparison skips. However, the durable `CommitRun` remains valid. The `BranchLifecycleService._replay()` method (line 377-382) reads the phase file but the replay response is derived from the registry and branch store, not the phase file. For Chapter creation specifically, `CommitRunStore` is the durable authority — the phase file is an auxiliary progress marker that can be reconstructed from the `CommitRun`.

---

### Scenario 10: refresh during creation (Severity: P2)

**User refreshes browser during Chapter N+1 creation.**

| Dimension | Value |
|---|---|
| **Expected Winner** | Creation continues on server (server-side operation is stateless from client perspective) |
| **Required CAS** | `operation_id` for replay; `commit_key` for idempotency check |
| **Durable Recovery** | Replay `operation_id` → query `CommitRunStore`; if commit is in progress, poll `CommitRunStore.load(commit_id)` until completion |
| **Fail-Closed Behavior** | Refresh shows "creation in progress" via `CommitRun.status`; `CommitRunStore.list_all()` returns in-progress runs |
| **Forbidden Duplicate** | None — refresh is read-only from the server perspective; it does not trigger a new create |

**Mechanism:** The client-side refresh maps to a GET request on the commit status endpoint. The server queries `CommitRunStore` for the current `commit_id` (derived from `operation_id`). If the `CommitRun` exists with `status` in (`core_committed`, `completed_with_warnings`, or `completed`), the client receives the current status and polls for completion. The `_handle_existing_run()` method handles all states: `core_committed` triggers post-commit resume, `completed` returns `ALREADY_COMMITTED`. The `ChapterCommitService` never initiates a new create on refresh — it only observes existing state.

---

### Scenario 11: Back/Forward during creation (Severity: P2)

**User navigates browser back/forward during Chapter N+1 creation.**

| Dimension | Value |
|---|---|
| **Expected Winner** | Creation continues server-side; navigation does not cancel or alter the operation |
| **Required CAS** | `operation_id` (stable across navigation) |
| **Durable Recovery** | Re-read state from `CommitRunStore`; `_check_idempotency()` is idempotent |
| **Fail-Closed Behavior** | Navigation does not cancel creation; returning to the page restores creation status from `CommitRunStore` |
| **Forbidden Duplicate** | None — navigation events are client-side only; server is unaffected |

**Mechanism:** Browser back/forward navigation is a client-side concern. The server-side `ChapterCommitService` operation is in-process (under `self._lock`) and progresses independently. When the user returns to the creation page, the frontend queries the commit status by `operation_id`. The `CommitRunStore` preserves the operation state regardless of browser navigation. If the creation completed while the user was away, the status endpoint returns `ALREADY_COMMITTED`. If it is still in progress, it returns `core_committed` or `completed_with_warnings`. There is no path where browser navigation can cancel a in-flight server-side commit.

---

### Scenario 12: open existing next Chapter while creation runs (Severity: P1)

**User opens existing Chapter N+1 while creation runs.**

| Dimension | Value |
|---|---|
| **Expected Winner** | Existing chapter navigation is allowed (read path); creation continues on server |
| **Required CAS** | `chapter_id` + branch verification (scope check via `_assert_scope()`) |
| **Durable Recovery** | Read chapter state via `_chapter_path(chapter_id).exists()`; navigation reads are PURE_READ |
| **Fail-Closed Behavior** | Cross-branch navigation is blocked by `BranchLifecycleService._assert_scope()`; same-branch navigation reads existing chapter without mutation |
| **Forbidden Duplicate** | Cross-branch navigation; reading a chapter from one branch while creating on another is blocked |

**Mechanism:** Opening an existing chapter is a PURE_READ operation — it does not write to the filesystem. The chapter file at `data/chapters/chapter_NNN.md` is read by `ChapterCommitService._phase_a_preflight()` and `_phase_c_prepare()`. If the chapter already exists (e.g., created by Traditional Mode or a prior commit), the read path sees it. The `_phase_c_prepare()` warns "正式章节文件已存在，本次将覆盖。" The creation path and navigation path are independent: navigation is read-only and cannot interfere with the locked commit. Branch scope is enforced by `_assert_scope()` which verifies the branch exists and the project is correct.

---

### Scenario 13: Traditional creates Chapter while Simulator resolves (Severity: P1)

**Traditional Mode creates Chapter N+1 while Simulator resolves.**

| Dimension | Value |
|---|---|
| **Expected Winner** | Traditional creation wins (filesystem-first); Simulator detects existing chapter and adapts |
| **Required CAS** | Chapter file existence (`data/chapters/chapter_NNN.md`) + `source_hash` comparison |
| **Durable Recovery** | Simulator re-reads chapter state via `_phase_b_source_resolution()` and `_phase_c_prepare()` |
| **Fail-Closed Behavior** | Simulator uses existing chapter; if Traditional created the same content, Simulator returns `ALREADY_COMMITTED`; if different content, Simulator overwrites with snapshot |
| **Forbidden Duplicate** | Duplicate creation — Traditional and Simulator must not both independently create the same chapter identity |

**Mechanism:** Traditional Mode writes chapter files directly via `DataStore.write_markdown()` without going through `ChapterCommitService._lock`. Simulator's `commit_chapter()` acquires the lock first. The race is:

1. If Traditional completes before Simulator acquires the lock → Simulator's `_phase_c_prepare()` sees existing file, takes snapshot, and proceeds with overwrite (with warning).
2. If Simulator acquires the lock first → Traditional's write happens outside the lock, Simulator's snapshot captures pre-existing state (which may be empty or Traditional's partial write), and the committed result is the Simulator's version.
3. If Traditional uses identical content → Same `source_hash` → Same `commit_key` → `CommitRunStore.find_by_chapter_and_hash()` may find Traditional's record, returning `ALREADY_COMMITTED`.

The `CommitRunStore` is the tiebreaker: if Traditional also writes a `CommitRun`, the Simulator's idempotency check finds it and avoids duplication.

---

## 3. Composite Risk Matrix

| # | Scenario | Severity | Winner | CAS Fingerprint | Recovery Source | Fail-Closed | Forbidden Duplicate |
|---|---|---|---|---|---|---|---|
| 1 | create vs create | **P0** | First-writer-wins | `chapter_id` + `operation_id` + `source_hash` | `CommitRunStore` | `ALREADY_COMMITTED` | duplicate `chapter_id`+`operation_id` |
| 2 | create vs chapter appears | **P1** | Existing chapter (filesystem) | chapter file existence | Snapshot + re-read | Warn + overwrite | overwriting without intent |
| 3 | create vs branch switch | **P1** | Switch blocked | `registry_revision` | Re-resolve scope | `STALE_REVISION` | cross-branch creation |
| 4 | create vs branch archive | **P2** | Archive blocked | `lifecycle_status` | Re-check lifecycle | `BRANCH_ARCHIVED` | archived branch creation |
| 5 | create vs planning update | **P2** | Planning (advisory) | None | Re-read planning | Creation > planning | none |
| 6 | create vs Canon revision | **P1** | Canon change | `canon_revision_id` | Re-resolve Canon | Stale Canon rejected | stale Canon carry-forward |
| 7 | create vs version change | **P2** | Creation (captured) | `source_version_id` + hash | Re-select version | Use captured version | none |
| 8 | response loss after creation | **P1** | Durable result | `operation_id` | `CommitRunStore.load()` | Never re-create | duplicate via same `operation_id` |
| 9 | durable result exists, phase missing | **P1** | Durable result | `operation_id` + `commit_id` | `CommitRunStore` directly | Prefer durable | re-committing completed |
| 10 | refresh during creation | **P2** | Creation continues | `operation_id` | Poll `CommitRunStore` | Show "in progress" | none |
| 11 | back/forward during creation | **P2** | Creation continues | `operation_id` | Re-read state | Navigation neutral | none |
| 12 | open existing next chapter | **P1** | Both allowed | `chapter_id` + branch verify | Read state only | Block cross-branch | cross-branch nav |
| 13 | Traditional creates while Simulator resolves | **P1** | Traditional (filesystem) | Chapter file + hash | Re-read + snapshot | Use existing | duplicate creation |

---

## 4. Implementation Checklist

For each scenario, the following code paths must be verified:

### Lock Path Verification

- [ ] `ChapterCommitService.commit_chapter()` acquires `self._lock` before any state mutation
- [ ] `BranchLifecycleService` acquires `_registry_lock` before any registry mutation
- [ ] Both locks are reentrant-safe (nested acquisition would deadlock)

### CAS Verification

- [ ] `commit_key` generation is deterministic from `project_id:chapter_id:source_hash:source_version_id`
- [ ] `_check_idempotency()` queries both `CommitRunStore.load(commit_key)` and `CommitRunStore.find_by_chapter_and_hash()`
- [ ] `_request_payload()` captures `expected_registry_revision` at operation claim

### Durable Recovery Verification

- [ ] `CommitRunStore.save()` is called after every state-changing operation
- [ ] `CommitRunStore.load()` is the authoritative recovery path (not phase file)
- [ ] `_handle_existing_run()` handles all `CommitRun.status` values correctly

### Fail-Closed Verification

- [ ] `_phase_a_preflight()` rejects invalid chapter IDs and missing project roots
- [ ] `_phase_c_prepare()` detects and warns about existing chapter files
- [ ] `BranchLifecycleService._claim()` rejects operation ID collisions via fingerprint mismatch
- [ ] All error paths return `CommitResult` with `CommitStatus.FAILED` (never partial success)

---

## 5. Testing Requirements

| # | Scenario | Test Type | Fixture |
|---|---|---|---|
| 1 | create vs create | Concurrent process test | Two `commit_chapter()` calls with identical `operation_id` |
| 2 | create vs chapter appears | Sequential state mutation test | Write chapter file between preflight and commit |
| 3 | create vs branch switch | Interleaved operation test | `BranchLifecycleService.select()` during `commit_chapter()` |
| 4 | create vs branch archive | Interleaved operation test | `BranchLifecycleService.archive()` during `commit_chapter()` |
| 5 | create vs planning update | Background mutation test | `PlanningService.load_planning()` mutation during commit |
| 6 | create vs Canon revision | Sequential state mutation test | `RevisionService.create_and_apply_revision()` during commit |
| 7 | create vs version change | Sequential state mutation test | `VersionManager.select_version()` during commit |
| 8 | response loss after creation | Restart recovery test | Kill process after `_phase_d_core_commit()`, replay `operation_id` |
| 9 | durable result, phase missing | File corruption test | Delete `.phase.json` after commit, replay `operation_id` |
| 10 | refresh during creation | Polling test | Query status while `CommitRun.status == "core_committed"` |
| 11 | back/forward during creation | Client simulation test | Cancel request, re-query status |
| 12 | open existing next chapter | Read-write isolation test | Read chapter N+1 while commit runs |
| 13 | Traditional vs Simulator | Dual-writer test | Traditional write path + `ChapterCommitService` simultaneously |

---

## 6. Reference Architecture

### Key Classes

| Class | File | Role |
|---|---|---|
| `ChapterCommitService` | `system/chapter_commit_service.py` | Chapter commit lifecycle (lock, idempotency, phases) |
| `CommitRunStore` | `system/commit_run_store.py` | Durable commit run journal (cross-process recovery) |
| `CommitRun` | `system/commit_run_store.py` | Commit run data class (status, post-commit, warnings) |
| `BranchLifecycleService` | `system/narrative_branch_lifecycle_service.py` | Branch registry lifecycle (lock, claim, phase) |
| `VersionManager` | `system/version_manager.py` | Version selection and archival |
| `RevisionService` | `system/revision_service.py` | Canon revision management |
| `NextChapterPlanner` | `core/next_chapter_planner.py` | Next chapter plan generation |

### CAS Flow Diagram

```
Request arrives
    │
    ▼
┌─────────────────────────┐
│  Generate commit_key    │  key = SHA256(project:chapter:hash:version_id:commit)
└─────────────────────────┘
    │
    ▼
┌─────────────────────────┐
│  Check CommitRunStore   │  load(commit_key) → find_by_chapter_and_hash()
└─────────────────────────┘
    │
    ├── Found → return ALREADY_COMMITTED (Scenario 8, 9)
    │
    └── Not Found
         │
         ▼
    ┌─────────────────────────┐
    │  Acquire _lock           │  process-level mutex
    └─────────────────────────┘
         │
         ▼
    ┌─────────────────────────┐
    │  Phase A: Preflight     │  validate chapter_id, project root
    └─────────────────────────┘
         │
         ▼
    ┌─────────────────────────┐
    │  Phase B: Source Resolve │  read version → compute source_hash
    └─────────────────────────┘
         │
         ▼
    ┌─────────────────────────┐
    │  Re-check idempotency   │  (lock acquired, safe to re-check)
    └─────────────────────────┘
         │
         ▼
    ┌─────────────────────────┐
    │  Phase C: Prepare       │  build chapter, snapshot existing
    └─────────────────────────┘
         │
         ▼
    ┌─────────────────────────┐
    │  Phase D: Core Commit   │  Canon + chapter + state + memory
    └─────────────────────────┘
         │
         ▼
    ┌─────────────────────────┐
    │  Save CommitRun         │  durable journal write
    └─────────────────────────┘
         │
         ▼
    ┌─────────────────────────┐
    │  Phase E: Post-Commit   │  context + chroma + version archive
    └─────────────────────────┘
         │
         ▼
    Release _lock → return CommitResult
```

### Recovery Flow Diagram

```
Client retries with same operation_id
    │
    ▼
Map operation_id → commit_key (deterministic)
    │
    ▼
┌─────────────────────────┐
│  CommitRunStore.load()   │  read durable journal
└─────────────────────────┘
    │
    ├── Not Found → Create new commit (lock, phases, commit)
    │
    ├── Found, status="failed"
    │       │
    │       ▼
    │   Return FAILED → client may retry with same or different content
    │
    ├── Found, status="core_committed"
    │       │
    │       ▼
    │   Resume post-commit tasks via _resume_post_commit_from_run()
    │
    └── Found, status="completed" or "completed_with_warnings"
            │
            ▼
        Return ALREADY_COMMITTED with full CommitResult
```

---

## 7. Cold-Start Classification (Audit Evidence from 2026-07-28 Fixture Probe)

| Operation | Classification | Severity | Impact on Chapter Progression |
|---|---|---|---|
| `SimulatorLoopStateService.build()` | PURE_READ (KeyError bug) | **P1** | Crashes on branch manifests lacking `revision` key |
| `NarrativeTurnContextBinder.bind()` | PURE_READ | Safe | No mutation side effects |
| `list_versions()` | PURE_READ | Safe | 0 file delta |
| `get_selected_version()` | **HIDDEN_MUTATION_BEHIND_READ** | **P1** | Writes `chapter_NNN_versions.json` as side effect |
| `RevisionService.read_active_canon()` | PURE_READ | Safe | 0 file delta |
| `RevisionService.active_canon()` | **LEGACY_READ_WITH_SIDE_EFFECT** | **P0** | Creates Canon+index+audit on read |
| `planning_service.load_planning()` | PURE_READ (nondeterministic) | Safe | In-memory ID/timestamp fill only |

**Policy:** `get_selected_version()` and `active_canon()` are **FORBIDDEN** for next-chapter resolve/browse paths. Both create production mutations as side effects of reads.

---

*This matrix is a living document. Each code change to `ChapterCommitService`, `CommitRunStore`, or `BranchLifecycleService` must be verified against the scenarios above.*