# Phase 0D4-E-P — Branch Lifecycle, NarrativeMemory Migration & Chroma Retrieval Isolation Preflight

> Status: **PASSED**
>
> Phase 0D4-E-P: **AUTHORIZED**
>
> Phase 0D4-E implementation: **NOT ENTERED / NOT AUTHORIZED**
>
> Phase 0D4-F: **NOT ENTERED**

This document is a read-only baseline. No Branch API was implemented, no
legacy file was migrated, no Chroma data was written or deleted, and no
production code or test file was changed for this preflight.

## 1. Executive Summary

The repository has a real, append-only `NarrativeBranchStore` with create,
select, archive, restore, registry projection, lifecycle journals, and an
active-archive-with-replacement recovery record. It is an internal store only:
there are no HTTP endpoints for those operations.

Phase 0D4-D introduced a branch-scoped Narrative Turn state and event path,
but it is not a complete NarrativeMemory migration. The existing
`NarrativeMemoryService` still writes and reads flat paths under
`data/narrative_memory/`, including `state/current.json` and chapter-only event
files. The read-only Turn Context Binder deliberately does not read that legacy
flat state.

The lifecycle-aware vector module is `system.vector_index_lifecycle`. It
isolates project, timeline, canon revision, and active/archived status through
metadata and filters, but it has no `branch_id` dimension. The older
`system.vector_memory` API still creates the same `storyos_memory` collection,
uses unscoped metadata, and remains callable from production repair code.

Therefore the preflight passes as a fact baseline, but E1, E2, and E3 must
remain separate implementation stages. Cross-branch retrieval and memory
leakage are P0 blockers for branch-aware production behavior.

## 2. Current Branch Lifecycle

### Store methods

| Operation | Store method | Current behavior | HTTP endpoint | Assessment |
|---|---|---|---|---|
| create | `NarrativeBranchStore.create_branch` | Immutable identity record; optional parent; rejects duplicate path and archived parent | None | Internal only; no caller operation id |
| select | `NarrativeBranchStore.select_branch` | Requires expected registry revision; rejects archived branch; updates active branch | None | CAS-style revision check, but no public API |
| archive | `NarrativeBranchStore.archive_branch` | Inactive branch archives directly; active branch requires replacement; active replacement has operation phases | None | Lifecycle rules exist; external idempotency is absent |
| restore | `NarrativeBranchStore.restore_branch` | Appends archived → open event; keeps current active branch unchanged | None | Restore is not select and does not auto-activate |

### Authority and paths

- Registry authority: `data/branches/{timeline_id}/registry.json`.
- Registry journal: `data/branches/{timeline_id}/registry_events/`.
- Branch identity: `data/branches/{timeline_id}/branches/{branch_id}.json`.
- Lifecycle journal: `data/branches/{timeline_id}/lifecycle_events/{branch_id}/`.
- Active-archive operation records: `data/branch_operations/{operation_id}.json`.
- The registry `active_branch_id` is the active-branch authority for a
  timeline; `lifecycle_status` is derived from the branch lifecycle journal.

### Rules observed

- Multiple open branches are allowed.
- An archived branch cannot be selected.
- An active branch cannot be archived without a replacement branch.
- The implementation does not enforce “at least one open branch” as a general
  invariant; it prevents archiving the active branch without replacement.
- Path components are validated and containment is checked.
- Immutable identity, append-only lifecycle events, atomic JSON publication,
  registry journal chaining, and recovery phases are present.
- `create_branch`, `select_branch`, and `restore_branch` do not expose a
  stable caller-supplied operation id. `archive_branch` generates one
  internally for the active-replacement path.
- The store uses expected revision checks and atomic file replacement, but no
  process-wide registry lock was found around the full read/validate/write/
  journal sequence. This remains a concurrency risk for E1.

## 3. Path Authority Inventory

| Data type | Current path | Scope | Writers | Readers | Legacy / unscoped path | Migration need |
|---|---|---|---|---|---|---|
| Branch registry | `data/branches/{timeline}/registry.json` | project/timeline | Branch Store | Branch Store, Context Binder | None found for registry | E1 API exposure and lock contract |
| Branch identity | `data/branches/{timeline}/branches/{branch}.json` | project/timeline/branch | Branch Store | Branch Store, Context Binder | None found | E1 API exposure |
| Branch lifecycle events | `data/branches/{timeline}/lifecycle_events/{branch}/` | project/timeline/branch | Branch Store | Branch Store | None found | E1 API exposure |
| Turn branch events | `data/narrative_turn/events/{timeline}/{branch}/` | project/timeline/branch | Narrative Turn Service | Turn Service/tests | Old `data/narrative_turns/...` paths are compatibility history only | E2 bridge contract |
| Turn branch state | `data/narrative_memory/state/{timeline}/{branch}/current.json` | project/timeline/branch | Narrative Turn Service | Turn Context Binder | `data/narrative_memory/state/current.json` | E2 migration boundary |
| NarrativeMemory events | `data/narrative_memory/events/chapter_{n}.json` | project/chapter; no timeline or branch | NarrativeMemoryService | NarrativeMemoryService and routes | Same path is the current authority | E2 copy-not-move migration |
| NarrativeMemory projection | `data/narrative_memory/state/*.json`, `timeline.json` | project-global | NarrativeMemoryService | NarrativeMemoryService and routes | `state/current.json` is flat | E2 branch-aware projection |
| NarrativeMemory snapshots | `data/narrative_memory/snapshots/chapter_{n}.json` | project/chapter | NarrativeMemoryService | NarrativeMemoryService | No branch dimension | E2 branch scope required |
| Retrieval history / overrides | `data/narrative_memory/retrieval/`, `overrides/` | project-global | NarrativeMemoryService | NarrativeMemoryService/routes | No branch dimension | E2 policy decision required |
| Vector manifest | `data/chroma/index_manifest_{timeline}.json` | project/timeline | vector lifecycle | vector lifecycle/health | `data/memory/vector_index_report.json` from legacy module | E3 manifest unification |
| Chroma DB | `data/chroma/` | project-local directory | `vector_index_lifecycle`, legacy `vector_memory` | both modules | Same collection name in both APIs | E3 single lifecycle authority |

No legacy flat branch state is read by `NarrativeTurnContextBinder`; it fails
closed when branch state is missing or invalid. That is safe for Turn Context,
but it does not migrate or isolate the older NarrativeMemory routes.

## 4. NarrativeMemory Inventory

`system/narrative_memory_service.py` is still the legacy authority. It:

- extracts events from active canon into `data/narrative_memory/events/`;
- confirms or invalidates events in place;
- projects confirmed events into flat state files and `timeline.json`;
- writes snapshots, conflicts, overrides, and retrieval history without
  timeline or branch identifiers;
- exposes overview, events, timeline, extract, confirm, project, snapshot,
  preview, override, and preflight routes through `web/routes.py`.

The D-RC1 branch state projection is a separate path and must not be treated as
proof that NarrativeMemory migration is complete. There is currently no
branch-aware NarrativeMemory event schema, no branch-aware projection rebuild,
and no branch selector parameter on the legacy NarrativeMemory endpoints.

## 5. Chroma Lifecycle Inventory

### Lifecycle-aware module

`system/vector_index_lifecycle.py` is the intended newer authority. It uses
`VectorClientManager`, a project-local `data/chroma` directory, one collection
named `storyos_memory`, and metadata containing `project_id`, `timeline_id`,
`source_type`, `canon_status`, and optional `canon_revision_id`.

Available operations include chapter/summary/character/world indexing,
`search_similar`, delete by chapter/revision/timeline/project, stale/archive
marking, rebuild, and collection stats. Queries retrieve broadly and then
enforce project/timeline/active-canon checks in application code. There is no
`branch_id` metadata or branch filter.

### Legacy module

`system/vector_memory.py` still exposes:

- `build_or_update_index(data_dir)`;
- `search_similar(query, data_dir, max_results)`;
- `is_available(data_dir)` and `collection_stats(data_dir)`.

It directly creates `PersistentClient`, uses the same `storyos_memory`
collection, and writes chapter/source metadata without project, timeline,
branch, or canon filters. It also writes the legacy vector report and may update
`data/state.json`.

`system/memory_repair_service.py` still imports the legacy builder in
`initialize_vector_index` before invoking the lifecycle rebuild path. This is a
legacy API residue and must be removed or explicitly quarantined in E3.

## 6. Retrieval Entry Inventory

| Entry point | Caller | Lifecycle API | Project filter | Timeline filter | Branch filter | Canon filter | Risk |
|---|---|---|---:|---:|---:|---:|---|
| `system.context_builder` vector retrieval | context builder | `vector_index_lifecycle.search_similar` | Yes | Hard-coded `main` | No | Active canon | P0 cross-branch ambiguity |
| `system.story_qa.search_vector_memory_if_available` | Ask Story | `vector_index_lifecycle.search_similar` | Yes | Hard-coded `main` | No | Active canon | P0 cross-branch ambiguity |
| `commands.index_vault_command` | CLI | `rebuild_project_index` | Yes | `main` | No | Indexed source | E3 branch omission |
| `ChapterCommitService._index_chroma` | commit post-task | lifecycle `index_chapter/index_summary` | Yes | `main` | No | Canon revision | E3 branch omission |
| `RevisionService.apply` | canon apply | lifecycle `index_chapter` | Yes | `main` | No | Canon revision | E3 branch omission |
| `memory_repair_service.initialize_vector_index` | Web repair | imports legacy builder; then lifecycle rebuild | Mixed | `main` | No | Mixed | P1 legacy bypass risk |
| `vector_memory.build_or_update_index` | Legacy callers/API | Direct Chroma | No | No | No | No | P0 leakage if called |
| Direct `PersistentClient` / collection calls | vector modules | Direct Chroma | Module-dependent | Module-dependent | No | Module-dependent | P1 policy bypass |

All retrieval entry points currently lack a mandatory branch argument and a
branch filter. Inactive and archived are therefore not equivalent to branch
visibility: the current lifecycle filter applies to canon status, not branch
lifecycle.

## 7. Archive / Restore Semantics

| Data | Archive behavior | Restore behavior | Current implementation | Gap |
|---|---|---|---|---|
| Branch registry | Registry/lifecycle journal update; active branch requires replacement | Appends open event; does not activate | Branch Store | No HTTP contract; no Chroma/Memory coupling |
| NarrativeMemory events | No branch archive behavior | No branch restore behavior | Flat event files remain readable | E2 must define visibility and copy-not-move migration |
| Branch state | Turn state path remains on disk; Binder blocks archived branch | No branch state rebind contract | D-RC1 Binder rejects archived branch | E2 restore policy needed |
| Chroma records | Chapter archive marks canon records archived/deletes from query path | Canon restore creates/updates canon index and reindexes chapter | Chapter/timeline only | No branch archive or restore filter |
| Vector manifest | Timeline manifest count is updated | Rebuild updates timeline manifest | Lifecycle module | No branch counts or branch revision |
| Retrieval visibility | Archived canon records are excluded | Active canon can become searchable again | Canon-based only | Branch archived must be excluded independently |

`inactive + open` means an open branch that is not selected; it is not
archived. Current Turn Context can bind an inactive open branch only when its
branch state exists and its lifecycle is open, while the legacy NarrativeMemory
and vector paths have no equivalent branch distinction.

## 8. Legacy API Findings

| API / pattern | Classification | Evidence | Required action |
|---|---|---|---|
| `vector_memory.build_or_update_index` | Must migrate or quarantine | Still public; imported by `MemoryRepairService` | E3 only; forbid new callers |
| `vector_memory.search_similar` | Must migrate or quarantine | Direct unscoped query API remains callable | E3 only; remove from production paths |
| Direct `PersistentClient` | Must be lifecycle-owned | Present in both vector modules; manager exists separately | E3 single client/collection owner |
| Direct collection `query/add/delete` | Must be lifecycle-owned | Present in both vector implementations | E3 wrapper policy and mandatory scope |
| `memory_repair_service` legacy import | Must migrate | Import remains even though lifecycle rebuild is used later | E3 cleanup and regression guard |
| `story_qa` / `context_builder` lifecycle calls | Legal but incomplete | They use lifecycle module | E2/E3 add branch-aware contract |

No legacy vector API may be called by new E1/E2 code. Existing legacy callers
must remain read-only or be removed only under explicit E3 authorization.

## 9. Concurrency and Windows Lock Findings

- D-RC1 Turn Service has explicit operation and branch transaction locks, but
  those locks do not cover Branch Store registry mutation.
- Branch Store uses atomic replace and a revision check, but the complete
  registry event + projection sequence is not protected by a cross-process
  lock.
- Active archive replacement has a recoverable operation record; create,
  select, and restore do not have equivalent caller-visible idempotency.
- Windows SQLite/Chroma locking remains relevant because both vector modules
  can open the same `data/chroma` path and collection independently.
- No live lock experiment was performed in this preflight; doing so would
  require writing temporary Chroma state and belongs to E-RC.

## 10. Security Boundary Findings

### Cross-branch leakage

Branch A events and state are isolated in D-RC1 Turn paths, but legacy
NarrativeMemory events/projections are flat and vector metadata has no branch
field. A branch-aware caller that reaches either legacy path can therefore see
another branch's material. This is a P0 boundary and blocks implementation
completion.

### Inactive versus archived

The Branch Store distinguishes them correctly. The legacy retrieval stack does
not carry either state, and Chroma only filters canon status. E2/E3 must make
branch lifecycle a mandatory visibility input.

### Uncommitted Turn

An uncommitted Turn is not Canon and is not written by `NarrativeTurnService`
to the canonical NarrativeMemory or Chroma paths. Its branch-local Turn event
and state artifacts are separate D-RC1 artifacts. Whether those artifacts may
be queried as short-term branch memory is not currently specified and must be
an explicit E2 contract; default recommendation is **not retrievable as
Canon** and **not indexed in Chroma**.

### Canon authority

`RevisionService` and `ChapterCommitService` remain the Canon authorities.
Branch lifecycle or retrieval changes must not bypass them.

## 11. Existing Test Coverage

Read-only inspection found coverage for:

- project/timeline/canon Chroma isolation, stale/archive behavior, rebuild,
  delete, restore, and client cleanup in `test_phase0c1_vector_isolation.py`
  and `test_phase0c1_recovery.py`;
- Branch Store lifecycle, append-only journals, archive replacement,
  recovery, path validation, and registry consistency in
  `test_phase0d4a_narrative_turn_foundation.py`;
- D-RC1 branch state, event, operation, recovery, and filesystem contracts in
  `test_phase0d4_*.py`;
- static path and real-data protection in `test_static_path_guard.py` and
  `test_real_data_protection.py`.

Missing coverage for E:

- Branch lifecycle HTTP endpoints and idempotency;
- branch-aware NarrativeMemory copy-not-move migration;
- branch-aware vector metadata and mandatory branch query filter;
- legacy vector API prohibition in production callers;
- archive/restore visibility across Memory and Chroma;
- cross-process Branch Store lock behavior;
- real browser branch lifecycle and Chroma lock acceptance.

## 12. Risk Matrix

| Risk | Level | Files / functions | Current behavior | Correct behavior | Blocks implementation? | Recommended stage | Recommended test |
|---|---|---|---|---|---:|---|---|
| Cross-branch Memory/vector leakage | P0 | `narrative_memory_service.py`, `vector_index_lifecycle.py`, `context_builder.py`, `story_qa.py` | Flat Memory and no branch metadata/filter | Every read/write/query carries project/timeline/branch/canon scope | Yes | E2/E3 | Two branches with mutually exclusive event/vector sentinels |
| Legacy vector bypass | P1 | `vector_memory.py`, `memory_repair_service.py` | Direct same-collection unscoped API remains callable | Lifecycle-only Chroma access | Yes | E3 | Static import/call guard plus temporary-index runtime test |
| Branch HTTP gap | P1 | `web/routes.py`, `narrative_turn_routes.py` | No create/select/archive/restore endpoints | Explicit scoped, idempotent, conflict-safe endpoints | Yes | E1 | API matrix with replay and stale revision cases |
| Registry race | P1 | `narrative_branch_store.py` | Atomic files but no full cross-process lock | Lock + journal/projection CAS transaction | Yes | E1 | Two-process select/archive stress on Windows temp root |
| Archive/restore retrieval drift | P1 | Branch Store, Memory, vector lifecycle | Branch lifecycle is not coupled to Memory/Chroma visibility | Archive hides branch; restore applies explicit reindex policy | Yes | E2/E3 | Archive/restore matrix with query assertions |
| Flat legacy migration ambiguity | P1 | `narrative_memory_service.py` | Chapter-only files have no branch provenance | Copy-not-move with explicit legacy scope and audit | Yes | E2 | Migration dry-run and collision/rollback test |
| Hard-coded `main` retrieval | P2 | `context_builder.py`, `story_qa.py`, commit/index callers | Timeline is fixed; branch omitted | Scope must be supplied by caller | Yes | E3 | Static and runtime scope propagation test |
| Documentation/test gap | P2 | E preflight and future E tests | No E lifecycle contract tests | Add stage-specific contract and browser tests | No | E1/E2/E3 | Focused stage suites |

## 13. Recommended Phase Split

### Phase 0D4-E1 — Branch Lifecycle HTTP API

- Add create/select/archive/restore endpoints only.
- Define request-scoped project/timeline/branch and caller operation id.
- Add idempotency, expected registry revision, path containment, and
  cross-process registry locking.
- Do not migrate NarrativeMemory and do not mutate Chroma.

### Phase 0D4-E2 — NarrativeMemory branch-aware migration

- Define branch-aware event, projection, snapshot, override, and retrieval
  history schemas.
- Copy legacy files; do not move or delete them.
- Require explicit legacy scope and provenance for copied records.
- Keep uncommitted Turn artifacts out of Canon and out of Chroma; decide
  separately whether short-term branch retrieval is allowed.

### Phase 0D4-E3 — Chroma metadata isolation

- Add mandatory `branch_id` metadata and query filter.
- Make lifecycle module the sole production Chroma entry point.
- Define archive visibility and restore re-index behavior.
- Remove/quarantine legacy `vector_memory` callers and add static guards.
- Add Windows lock and cross-project/timeline/branch sentinel tests.

### Phase 0D4-E-RC — Integrated acceptance

- Cross-branch leakage, archive/restore, repair/recovery, Windows lock,
  legacy API guard, full related regression, and real browser lifecycle.
- No RC work is authorized by this preflight.

## 14. Model / Reasoning / Agent Recommendation

| Stage | Model | Reasoning | Agents |
|---|---|---|---:|
| E-P | Luna | Medium | 1 |
| E1 | Luna or Terra | Medium | 1 |
| E2 | Terra | Medium | 1 |
| E3 | Terra | Medium-high | 1 |
| E-RC | Terra high, or short read-only Sol audit | High | 1 |

This preflight was executed as a single-agent read-only audit, as required by
the phase specification. No provider or external network call was made.

## 15. Files Read

- `system/narrative_branch_store.py`
- `system/narrative_turn_service.py`
- `core/contracts/narrative_turn.py`
- `web/narrative_turn_routes.py`
- `web/routes.py`
- `system/narrative_memory_service.py`
- `system/narrative_turn_context.py`
- `system/memory_repair_service.py`
- `system/context_assembly_service.py`
- `system/vector_index_lifecycle.py`
- `system/vector_memory.py`
- `system/vector_client_manager.py`
- `system/vector_index_schema.py`
- relevant Branch, vector, real-data-protection, and static-guard tests
- `docs/planning/PHASE_0D4_IMPLEMENTATION_BRIEF.md`
- repository `AGENTS.md` instructions

## 16. Commands Run

Read-only/static commands included targeted `rg`, `Get-Content`, and
`Select-String` inventories for branch methods, routes, paths, vector calls,
and tests.

The following existing tests ran against temporary project roots. The test
fixtures block writes to the checked-out `data/` and block real Chroma paths:

```text
python -m pytest tests/test_phase0c1_vector_isolation.py \
  tests/test_phase0c1_recovery.py tests/test_static_path_guard.py -q
41 passed in 13.88s
```

No server was started, no provider was contacted, and no real project,
Obsidian vault, or Chroma database was modified.

## 17. Git Status

The preflight added only this report and updated the authorization brief. All
pre-existing D-RC1 working-tree changes, including the user's `.rc3_ibr/`
directory, were preserved. No `git add`, commit, push, reset, clean, stash, or
branch switch was performed.

## 18. Final Verdict

```text
Phase 0D4-E-P: PASSED
Branch lifecycle authority: MAPPED
NarrativeMemory paths: MAPPED
Chroma lifecycle: MAPPED
Retrieval entry points: MAPPED
Archive/restore behavior: MAPPED
Legacy vector APIs: MAPPED
Cross-branch risks: IDENTIFIED (P0/P1)
Implementation stages: DEFINED (E1/E2/E3/E-RC)
Phase 0D4-E implementation: NOT ENTERED
```

The repository is ready for a separately authorized E1 implementation, but
this preflight does not authorize any implementation or data migration.
