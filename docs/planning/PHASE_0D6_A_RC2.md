# Phase 0D6-A-RC2: Shared Chapter Lifecycle Authority Seal Closure

## Status

**PASSED — READY TO SEAL**

Phase 0D6-B remains **NOT AUTHORIZED**.

## Stage Goal and Authority Baseline

RC2 closes the RC1 blockers without entering readiness aggregation, cross-chapter
Turn work, Provider work, or UI progression.  RC1's immutable operation claim,
staging-first publication, eight-point recovery, exactly-once Version/Canon
initialization, and pure-read behavior remain authoritative.

## Implementation Invariants

- One immutable lifecycle claim binds project, main timeline, current/successor
  chapter, active branch authority, planning authority, and completion
  authority.
- Branch authority includes active branch identity, registry revision,
  canonical registry hash, and lifecycle status.
- Planning authority includes exact file-byte SHA-256, declared revision, and
  chapter identity.
- Completion authority includes exact commit-result byte SHA-256, status,
  commit ID, source version identity, and Canon revision identity.
- Replay of an incomplete operation revalidates all three authorities.
- A completed durable result is historical and byte-stable; later branch
  lifecycle changes do not rewrite it.
- Publication performs an adjacent final authority fence.

## Branch Archive Concurrency Contract

Chapter create and branch archive acquire the shared lock in this order:

1. project/timeline Chapter authority lock;
2. Chapter successor lock or Branch registry lock;
3. component-local Version/Canon locks.

Archive fails closed while an operation bound to the target branch lacks a
durable lifecycle result.  Archive-first makes a stale create fail before
mutation.  Create-first may complete, after which archive has a later,
non-contradictory durable order.  Crash/retry preserves the same ordering.

## Planning Freshness Contract

`data/next_chapter_plan.json` must exist, decode as an object, and retain the
byte hash/revision/chapter identity captured in the claim.  Content change,
revision change, deletion, replacement, claim-time race, or replay-time drift
returns `PLANNING_STALE` before publication.

## Completion Authority Contract

The existing `data/chapter_commits/commit_NNN.json` remains the sole completion
fact.  Lifecycle code does not repair or reinterpret it.  Deletion, corruption,
scope mismatch, status transition, source identity change, or byte replacement
fails closed.  `committed_with_warnings` remains an allowed initial status.

## Filesystem Allowlist

Successful creation may add only:

- `data/chapter_lifecycle/operations/<operation>.json`
- `data/chapter_lifecycle/operations/<operation>.phase.json`
- `data/chapter_lifecycle/operations/<operation>.result.json`
- `data/chapters/chapter_<successor>.md`
- `data/versions/chapter_<successor>_versions.json`
- `data/canon_versions/chapter_<successor>/canon_v001.md`
- `data/canon_versions/chapter_<successor>/index.json`

Staging, atomic temp files, lock directories, and owner files are transient and
must be absent after terminal success.  Initialization failures remove partial
Version/Canon assets.  A result-publication failure retains a complete,
recoverable publication and blocks branch archive until replay.

## Scope Isolation Contract

- Project identity must match the bound `ProjectContext`.
- Chapter publication is project-global and therefore restricted to the
  authoritative `main` timeline.  Other timelines fail before mutation.
- The active branch is bound by immutable authority; sibling branch files are
  outside the mutation allowlist.
- Previous chapter text, Version, Canon, commit authority, planning, other
  projects, Chroma, and Obsidian are immutable.

## Route, DTO, and Adapter Authority Contract

`GET/POST /api/chapter-lifecycle/next` is the production backend boundary.
`ChapterLifecycleCreateRequest` validates a stable caller-provided operation
ID and scope before service mutation.  Traditional and Simulator adapters are
thin delegates to the same `ChapterLifecycleService`; they do not resolve
successors, claim operations, initialize assets, or perform freshness checks.
The caller source is deliberately excluded from lifecycle semantics so the
same operation/request through both adapters returns the same durable result.

ChapterCommitService remains the authority for committing chapter content; it
was not modified and is not duplicated by lifecycle adapters.

## Recovery Contract

- A phase is recorded only after its durable action.
- Missing effects are never skipped.
- Pre-publication faults rewind partial Version/Canon assets to staging.
- Publication-without-result replays without a second chapter publication.
- Result-without-completed-phase repairs only the phase marker.
- Incomplete replay revalidates branch, planning, and completion authority.
- Completed replay returns the immutable historical result.
- Stale/corrupt owner locks are reclaimed; owner-write failure removes the
  newly-created lock directory.

## Test Matrix

RC2 covers:

- archive-first, create-first, six incomplete create phases, crash/retry, and a
  barrier-synchronized create/archive race;
- planning content/revision/delete/replace and threaded change races;
- completion bytes/delete/corruption/status/warning and threaded change races;
- success allowlist diff, replay/conflict zero-diff, component failures,
  durable-result failure recovery, residue cleanup, and cross-project/timeline
  isolation;
- Traditional/Simulator adapter replay, route replay, invalid DTO, and
  operation conflict;
- retained RC1 read-purity, eight-point recovery, exactly-once, warning, and
  previous-chapter immutability cases.

## Seal Gate

RC2 is ready for Owner seal because the focused RC2/RC1 suite, 0D5 authority
regression, branch lifecycle regression, Version/Planning regression, real-data
guard, and static-path guard all pass with zero external or real-data effects.

## Non-Goals

- No Phase 0D6-B readiness aggregation.
- No cross-chapter Turn start.
- No Provider, network, Chroma, Obsidian, Candidate, Review, or production UI
  authority changes.
- No Git write operation or dependency change.

