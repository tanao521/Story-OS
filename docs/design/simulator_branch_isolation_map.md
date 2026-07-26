# Simulator Branch Isolation Map

> Phase 0D4-A implementation artifact.  Store implemented in
> `system/narrative_branch_store.py`.
>
> **Phase 0D4-A-FIX-RC** revises this map to reflect the separation
> between the immutable branch identity record and the append-only
> lifecycle event journal, the rule that `restore` does NOT auto-select,
> and the rule that in-flight Plans enter `superseded` (not "abandoned")
> on branch switch.

**OWNER Decisions Applied:**
- Branch `lifecycle_status` ("open"/"archived") separated from `active_branch_id` in registry
- One timeline can have multiple open branches
- One active_branch_id per timeline registry
- archived branch cannot be selected as active
- **(FIX-RC)** Branch identity record is immutable; lifecycle status is a
  derived projection replayed from the append-only lifecycle event journal
- **(FIX-RC)** `restore` means `archived → open` only; it does NOT
  auto-select the branch as active
- **(FIX-RC)** In-flight Plans on the old branch enter `superseded` via
  the transition machinery on branch switch — never silently "abandoned"
- **(FIX-RC)** `included_in_chapter` / `committed` are transition
  journal entries, NOT flags on the Turn record

## 1. Current isolation state (audited)

| Layer | Project isolation | Timeline isolation | Branch isolation |
| --- | --- | --- | --- |
| `ProjectContext` | ✅ project root | ❌ no `timeline_id` | ❌ no `branch_id` |
| `data/` file paths | ✅ project-scoped | ❌ flat `data/chapters/`, `data/summaries/` | ❌ none |
| `RevisionService` canon | ✅ project-scoped | ❌ `data/canon_versions/chapter_NNN/` | ❌ none |
| `NarrativeMemoryService` events | ✅ project-scoped | ❌ `data/narrative_memory/events/chapter_NNN.json` | ❌ none |
| `vector_index_lifecycle` | ✅ manifest-enforced | ✅ `timeline_id` parameter | ❌ assumes single timeline |
| `vector_memory.build_or_update_index` (legacy) | ❌ no filter | ❌ no filter | ❌ no filter |
| Panel run records | ✅ `project_id` field | ✅ `timeline_id` field | ❌ no `branch_id` |
| Live audit records | ✅ `project_id` field | ✅ `timeline_id` field | ❌ no `branch_id` |
| `ChapterCommitService` | ✅ project-scoped | ❌ writes to global `data/chapters/` | ❌ none |

**Conclusion:** Branch isolation **does not exist**.  Timeline isolation is
partial (metadata + panel runs + new vector lifecycle, but not file paths
or canon or narrative memory).

## 2. Target isolation model

### 2.1 Storage partitioning

```
data/
├── chapters/                          ← global Canon (only committed chapters)
├── summaries/                         ← global Canon summaries
├── canon_versions/                    ← global Canon revisions
├── narrative_memory/
│   ├── events/
│   │   └── {timeline_id}/
│   │       └── {branch_id}/
│   │           └── chapter_NNN.json   ← branch-local events
│   ├── state/
│   │   └── {timeline_id}/
│   │       └── {branch_id}/
│   │           └── current.json       ← branch-local projected state
│   └── snapshots/
│       └── {timeline_id}/
│           └── {branch_id}/
│               └── chapter_NNN.json   ← branch-local snapshots
├── narrative_turns/
│   └── {timeline_id}/
│       └── {branch_id}/
│           ├── plans/{turn_id}.json
│           ├── validations/{validation_id}.json
│           ├── results/{turn_id}.json
│           ├── transitions/{turn_id}/{sequence:08d}.json   ← FIX-RC sequence-only filename
│           └── operations/{operation_id}.json              ← branch-local index (rebuildable)
├── narrative_turn_operations/
│   └── {operation_id}.json            ← FIX-RC project-root operation authority
├── branches/
│   └── {timeline_id}/
│       ├── branches/
│       │   └── {branch_id}.json              ← immutable branch IDENTITY record
│       ├── lifecycle_events/
│       │   └── {branch_id}/
│       │       └── {sequence:08d}.json       ← append-only lifecycle journal (FIX-RC2: sequence-only)
│       ├── registry.json                     ← mutable projection of active pointer
│       └── registry_events/
│           └── {sequence:08d}.json           ← append-only registry events (FIX-RC2: sequence-only)
├── branch_operations/                        ← FIX-RC2: project-root operation tracking (not timeline-isolated)
│   ├── {operation_id}.json                   ← main operation record (mutable projection)
│   ├── {operation_id}_registry_updated.json  ← immutable phase marker
│   ├── {operation_id}_lifecycle_appended.json ← immutable phase marker
│   └── {operation_id}_completed.json         ← immutable phase marker
└── chroma/                            ← vector index (manifest-enforced)
```

**Key rule:** `data/chapters/`, `data/summaries/`, `data/canon_versions/`
remain **global Canon** — only written by `ChapterCommitService`.  Branch
content lives under `narrative_turns/` and `narrative_memory/events/{timeline_id}/{branch_id}/`.

### 2.2 Branch identity vs derived projection (FIX-RC)

The branch record is split into two layers:

#### 2.2.1 Immutable identity record

`data/branches/{timeline_id}/branches/{branch_id}.json` — published once
via `_publish_immutable_json` and **never overwritten**:

```json
{
  "schema_version": "1.0",
  "branch_id": "branch_main",
  "project_id": "my_project",
  "timeline_id": "main",
  "parent_branch_id": null,
  "created_from_turn_id": null,
  "display_name": "Main",
  "created_at": "2026-07-24T00:00:00+00:00",
  "fingerprint": "abc123..."
}
```

Note: there is **no** `lifecycle_status` and **no** `archived_at` on the
identity record. Lifecycle is derived (see §2.2.2).

#### 2.2.2 Append-only lifecycle event journal

`data/branches/{timeline_id}/lifecycle_events/{branch_id}/{sequence:08d}.json` (FIX-RC2: sequence-only filename; `event_id` lives inside the JSON):

```json
{
  "schema_version": "1.0",
  "event_id": "evt_abc123",
  "sequence": 0,
  "branch_id": "branch_main",
  "project_id": "my_project",
  "timeline_id": "main",
  "from_status": "open",
  "to_status": "archived",
  "operation_id": null,
  "occurred_at": "2026-07-24T10:00:00+00:00",
  "previous_event_fingerprint": null,
  "record_fingerprint": "def456..."
}
```

Legal lifecycle transitions: `open → archived` and `archived → open`.
The current status is derived deterministically by replaying the event
journal (last event's `to_status`). Chain integrity (`sequence`
contiguous + `previous_event_fingerprint` matching) is verified on every
read; any break raises `LIFECYCLE_EVENT_CHAIN_CORRUPT` fail-closed.

#### 2.2.3 Registry (mutable projection of active pointer)

`data/branches/{timeline_id}/registry.json`:

```json
{
  "schema_version": "1.0",
  "project_id": "my_project",
  "timeline_id": "main",
  "active_branch_id": "branch_main",
  "revision": "rev_abc123",
  "created_at": "2026-07-24T00:00:00+00:00",
  "updated_at": "2026-07-24T10:00:00+00:00"
}
```

The registry is a mutable projection (uses `os.replace` with
expected-revision comparison). It can always be rebuilt from the
append-only `registry_events/` journal.

**Registry Events (append-only, FIX-RC2):**
`data/branches/{timeline_id}/registry_events/{sequence:08d}.json` (sequence-only filename; `event_id` lives inside the JSON):

```json
{
  "event_id": "event_abc123",
  "event_type": "branch_selected",
  "project_id": "my_project",
  "timeline_id": "main",
  "payload": { "branch_id": "branch_main" },
  "occurred_at": "2026-07-24T10:00:00+00:00"
}
```

**Key Rules (FIX-RC):**
- `lifecycle_status` is **derived** from the lifecycle event journal —
  it is NOT a field on the immutable branch identity record.
- `active_branch_id`: points to one open branch per timeline.
- Multiple open branches can coexist on the same timeline.
- archived branch cannot be selected as active.
- `restore` means `archived → open` ONLY; it does NOT auto-select the
  restored branch as active.
- Archive of the active branch must specify an open replacement;
  the operation is a **recoverable multi-file operation** (see §2.3)
  tracked via `data/branch_operations/` (project-root scope), ensuring
  partial failures can be recovered and `active_branch_id` never points
  to an archived branch.
- Root branch has `parent_branch_id: null`.
- Non-root branches must have valid `parent_branch_id`.

### 2.3 Recoverable multi-file operations (FIX-RC2)

Active branch archive with replacement is a **multi-file operation** that
spans the lifecycle event journal and the registry. As of FIX-RC2, this
operation uses a **four-phase recoverable protocol** tracked in a
`BranchOperationRecord`, rather than relying on "same method call = atomic".

**Operation type:** `active_archive_with_replacement`

**Four phases (REGISTRY-FIRST safe order):**

| Phase | Action | Side effects | Recovery if interrupted |
| --- | --- | --- | --- |
| 1. `intent` | `_write_operation_phase(operation_id, intent_payload)` — publish operation record with phase=`intent` | none (bookkeeping only) | resume into `registry_updated` |
| 2. `registry_updated` | `_create_registry_if_missing`; verify `from_active == target_branch_id`; verify replacement exists and is `open`; `_update_registry` (CAS active pointer → replacement using `expected_registry_revision`); `_append_registry_event(event_type="branch_archived", from=target, to=replacement)`; publish `{operation_id}_registry_updated.json` immutable marker; `_atomic_write_json` main record → `registry_updated` | active pointer flipped to replacement; registry event appended | if `{operation_id}_registry_updated.json` exists → resume into `lifecycle_appended`; else re-enter `registry_updated` |
| 3. `lifecycle_appended` | `_derive_lifecycle_status(target)` (check if target already archived); if not archived `_append_lifecycle_event(target, OPEN → ARCHIVED)`; publish `{operation_id}_lifecycle_appended.json` immutable marker; `_atomic_write_json` main record → `lifecycle_appended` | lifecycle event appended for target (idempotent — skipped if already archived) | if `{operation_id}_lifecycle_appended.json` exists → resume into `completed`; else re-enter `lifecycle_appended` |
| 4. `completed` | Publish `{operation_id}_completed.json` immutable marker; `_atomic_write_json` main record → `completed` | none (bookkeeping only) | idempotent; re-mark `completed` |

**Recovery protocol (REGISTRY-FIRST safe order):**
1. On store startup / before any branch operation, scan
   `data/branch_operations/` for incomplete operations (phase != `completed`).
2. For each incomplete operation, resume from the next phase by inspecting
   the immutable phase markers present on disk:
   - If `{operation_id}_completed.json` exists → already done.
   - Else if `{operation_id}_lifecycle_appended.json` exists → resume into `completed`.
   - Else if `{operation_id}_registry_updated.json` exists → resume into `lifecycle_appended`.
   - Else → resume into `registry_updated` (only the `intent` phase is written).
3. Each side-effect phase is idempotent: the registry CAS retries with
   the recorded `expected_registry_revision`; the lifecycle append is
   conditional on `_derive_lifecycle_status(target)` not already being
   `archived`.
4. Publish the corresponding immutable phase marker **before** advancing
   the main record's `phase` field, so a crash between marker publication
   and main-record update is recovered deterministically by observing
   the marker.

**Operation record paths (project-root scope, not timeline-isolated):**
- `data/branch_operations/{operation_id}.json` — main operation record (mutable projection)
- `data/branch_operations/{operation_id}_registry_updated.json` — immutable phase marker
- `data/branch_operations/{operation_id}_lifecycle_appended.json` — immutable phase marker
- `data/branch_operations/{operation_id}_completed.json` — immutable phase marker

**Key rules:**
- The operation record is the **source of truth for progress**, not the
  method call frame. A crash mid-operation can be recovered.
- All side-effect phases (registry CAS + event append, lifecycle append)
  are individually atomic and idempotent.
- The `registry.json` snapshot remains rebuildable from the registry
  event journal at all times (`_rebuild_registry_from_journal` replays
  events in ascending `sequence` order, using `to_active_branch_id` and
  `resulting_revision` to reconstruct the projection).
- **Safe invariant (REGISTRY-FIRST order):** `active_branch_id` never
  points to an archived branch in any observable or recoverable state:
  - After `intent`, before `registry_updated`: active = target (still open) — safe.
  - After `registry_updated`, before `lifecycle_appended`: active = replacement (open), target still open — safe.
  - After `lifecycle_appended`: active = replacement (open), target = archived — safe.

### 2.4 Query filter rules (mandatory)

Every read/write MUST filter by:

1. `project_id` (from `ProjectContext`)
2. `timeline_id` (from context binding)
3. `branch_id` (from active branch or explicit target)

**No cross-branch reads** except:
- Branch registry itself (lists all branches for switch/archive).
- Explicit branch comparison view (future; not in 0D4 first version).

### 2.4 Chroma isolation

| Operation | API | Filter |
| --- | --- | --- |
| Index chapter | `vector_index_lifecycle.index_chapter()` | `project_id`, `timeline_id`, `canon_revision_id` |
| Index summary | `vector_index_lifecycle.index_summary()` | same |
| Query | `vector_index_lifecycle.query()` (must add) | `project_id`, `timeline_id`, `branch_id` (for branch-local events) |
| Legacy `vector_memory.build_or_update_index()` | **DEPRECATED — must not be called for branch scenarios** | none (unsafe) |

**Migration plan:** `memory_repair_service.py` must be updated to call
`vector_index_lifecycle` instead of the legacy API before 0D4-E.  This is
recorded as a risk, not fixed in 0D4-P.

### 2.5 Branch operations (FIX-RC)

| Operation | Effect | Reversibility |
| --- | --- | --- |
| Create branch | publishes immutable identity record; appends `branch_created` registry event; parent's Turns up to branch point are inherited (read-only) | irreversible (identity record is immutable) |
| Switch active branch | updates `active_branch_id` in registry via expected-revision CAS; appends `branch_selected` registry event; all subsequent reads/writes go to new branch | reversible (switch back) |
| Archive branch | **appends** `open → archived` lifecycle event (never overwrites identity record); archive of active branch is a **recoverable multi-file operation** (see §2.3) — not "same call therefore atomic" — with four-phase REGISTRY-FIRST protocol tracked in `data/branch_operations/` (project-root scope) | reversible (restore) |
| Restore branch | **appends** `archived → open` lifecycle event; does NOT auto-select as active (active pointer unchanged) | reversible (re-archive) |
| Merge branch | **NOT SUPPORTED in first version** | n/a |

### 2.6 Canon interaction

| Event | Effect on global Canon | Effect on branch |
| --- | --- | --- |
| Turn confirmed | **none** | branch-local event log + state delta |
| Chapter compiled from branch | **none** (compile produces a candidate version) | `included_in_chapter` transition appended to journal — **NOT a flag on the Turn record** |
| `ChapterCommitService.commit_chapter()` | **Canon revision created** (global) | `committed` transition appended to journal — **NOT a flag on the Turn record**; branch becomes the "source of truth" for that chapter |
| Another branch commits same chapter | second commit creates a new canon revision (append-only); first branch's commit is not overwritten | each branch can independently commit; Canon keeps all revisions with `active` flag |

### 2.7 Switching context (FIX-RC)

When the user switches branch:

1. URL updates `branch_id` parameter.
2. Context navigator reloads with new branch.
3. All in-flight Turn plans for the old branch enter `superseded` via
   the normal transition machinery (terminal lifecycle end-state,
   retained as read-only history). They are **never** silently
   "abandoned" — that would leave the journal with an ambiguous
   non-terminal state.
4. The new branch's Turn history is loaded.
5. Chroma queries are re-issued with the new `branch_id` filter.

**No silent active-timeline mutation.** Branch switch is always explicit
and URL-visible.

**Registry rebuildability (FIX-RC2):** The `registry.json` snapshot is a
mutable projection that can always be **rebuilt deterministically from
the registry event journal** by replaying events in ascending `sequence`
order. If the snapshot is lost or corrupted, it is reconstructed from
the append-only journal.

## 3. Risk: legacy vector_memory bypass

**Current state:** `system/memory_repair_service.py:121` calls
`vector_memory.build_or_update_index()`, which scans all of
`data/chapters/` with no `timeline_id` or `project_id` filter.

**Impact in a branch world:** If branch A has uncommitted Turn-derived
chapter drafts in a branch-local path (not `data/chapters/`), the legacy
indexer would not touch them — **but** if a branch mistakenly writes to
`data/chapters/` before commit, the legacy indexer would index it into
the global collection, leaking branch content into the main timeline's
retrieval context.

**Mitigation (for 0D4-E, not 0D4-P):**
1. Branch-local content must NEVER be written to `data/chapters/`.
2. `memory_repair_service.py` must migrate to `vector_index_lifecycle`.
3. A static guard test should forbid `vector_memory.build_or_update_index` calls in new code.

## 4. Migration compatibility

| Existing data | Location | Branch-aware? | Action needed |
| --- | --- | --- | --- |
| Existing `data/chapters/` | global | n/a (global Canon) | none — these are committed Canon |
| Existing `data/narrative_memory/events/` | flat `chapter_NNN.json` | ❌ | migrate to `events/main/branch_main/chapter_NNN.json` on first branch-aware read |
| Existing panel runs | `project_id`+`timeline_id` only | partial | no `branch_id`; treat as `branch_main` by default |
| Existing canon revisions | `data/canon_versions/` | global | none — Canon is global |

**Migration rule:** First branch-aware access to a project with legacy
flat event files performs a one-time copy (not move) into
`events/main/branch_main/`.  Legacy files are preserved until OWNER
authorizes cleanup.
