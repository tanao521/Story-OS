# Phase 0D6-B

Status: PASSED & SEALED
Owner Seal Date: 2026-07-28

The historical implementation-status line immediately below is retained for
stage history only; it is not the current phase status.

## Cross-Chapter Readiness Aggregation & Next Narrative Turn Start Authority

Status: AUTHORIZED — IMPLEMENTATION IN PROGRESS

Phase 0D6-A remains sealed. This phase adds a backend-only Simulator
coordination boundary; it does not alter Chapter publication, Turn
confirmation, Candidate, Review, Commit, Canon, Chroma, Provider, or UI
authority.

## Authority Contract

## Lifecycle Operation Resolution Contract

`ChapterLifecycleService.resolve_next_chapter()` is the sealed pure-read
resolver, but its current projection does not expose a lifecycle operation ID
and derives `next_chapter_id` as `current_chapter_id + 1`. The 0D6-B
implementation therefore needs an explicit, verifiable association from that
resolver projection to exactly one immutable Chapter lifecycle claim, durable
result, and `completed` phase. A readiness reader must not choose an operation
by directory order, mtime, lexical name, or largest ID. Multiple completed
operations with conflicting claims/results/assets are
`BLOCKED_LIFECYCLE_CONFLICT`; orphan, malformed, or mismatched claim/result/
phase records are `BLOCKED_CORRUPT_AUTHORITY`.

The claim, result, phase, published Chapter, Version index, Canon index, and
resolver projection must agree on project, main timeline, previous Chapter,
active Branch, successor Chapter, operation ID, and durable fingerprints.
Result-without-phase and phase-without-result are incomplete lifecycle facts;
GET readiness never repairs them.

## Client Assertion Contract

POST `project_id`, `timeline_id`, `branch_id`, `previous_chapter_id`,
`successor_chapter_id`, and `expected_readiness_fingerprint` are only
optimistic scope/freshness assertions. The server recomputes fresh readiness,
resolves the authoritative successor, compares every client assertion, and
only then creates the immutable start claim. Client successor or source fields
never select lifecycle operations, Version, Canon, or Turn identity.

## Initial Turn Identity Contract

An initial Turn is identified by the existing `NarrativeTurnStore` plan's
project/timeline/branch/chapter/turn/context fields and its append-only
transition journal. There is no separate `turn_index=1` field. The first
durable transition is sequence `0`, `planned -> awaiting_action`; later
sequences belong to the same `turn_id`. A plan without a transition is partial
and recoverable, while a transition without a valid plan, duplicate initial
plans, a broken chain, or a plan/transition scope/chapter mismatch is corrupt
and fails closed. The start claim and result bind the plan and transition
fingerprints; they do not create a second Turn identity.

## Plan and Transition Recovery Contract

The start coordinator uses the following durable phases:

```text
claimed
plan_published
awaiting_action_transition_published
result_published
completed
```

Each phase is written only after its corresponding effect. Replay must inspect
the actual plan and transition store, complete a missing effect exactly once,
and refuse to overwrite corrupt partial state. A durable result is accepted
only when its claim, plan fingerprint, transition fingerprint, scope, chapter,
and Turn status validate. A result without `completed` phase may repair only
that phase after validation; a phase without its effect is not skippable.

## Branch Archive Blocking Contract

Branch archive uses the existing Chapter timeline authority lock followed by
the Branch registry lock. It then scans only progression claims bound to the
same project, timeline, and target Branch. Claim-only, plan-published,
transition-published, result-pending, corrupt, or result-without-completed-phase
operations block archive. A result with a validated completed phase does not.
Sibling branches and other scopes do not block the archive. Corrupt operation
records fail closed; archive never silently ignores them.

## Optimistic Readiness Fence

GET readiness is an optimistic, pure projection. POST start reacquires the
authority locks, recomputes all readiness inputs, compares client assertions
and the expected fingerprint, verifies that no initial Turn exists, then
creates its claim. Any drift returns a safe readiness-changed code and writes
no Turn. The GET projection has zero filesystem diff, including no lock,
owner, cache, repair, operation, phase, or result artifacts.

## Readiness Status Matrix

| Code | Ready | Meaning | Replay/HTTP |
|---|---:|---|---|
| `READY_TO_START_TURN` | true | All sealed authorities validate | replayable / 200 |
| `TURN_ALREADY_STARTED` | false | Valid initial Turn exists | read-only existing Turn / 200 |
| `BLOCKED_PREVIOUS_CHAPTER_NOT_COMPLETE` | false | Completion authority absent/invalid | retry / 200 |
| `BLOCKED_COMPLETION_RECOVERY_REQUIRED` | false | Completion requires recovery | retry / 200 |
| `BLOCKED_LIFECYCLE_NOT_CREATED` | false | No verifiable lifecycle operation | retry / 200 |
| `BLOCKED_LIFECYCLE_INCOMPLETE` | false | Claim/effect/result not durable-complete | retry / 200 |
| `BLOCKED_LIFECYCLE_CONFLICT` | false | Conflicting completed authorities | safe error / 200 |
| `BLOCKED_SUCCESSOR_NOT_VISIBLE` | false | Resolver/assets disagree | retry / 200 |
| `BLOCKED_SUCCESSOR_ASSETS_INCOMPLETE` | false | Version or Canon incomplete | retry / 200 |
| `BLOCKED_BRANCH_NOT_ACTIVE` / `BLOCKED_BRANCH_ARCHIVED` | false | Branch cannot start | retry / 200 |
| `BLOCKED_PLANNING_MISSING` / `BLOCKED_PLANNING_STALE` | false | Planning authority invalid | retry / 200 |
| `BLOCKED_SOURCE_MISSING` / `BLOCKED_SOURCE_CHANGED` | false | Successor source drift | retry / 200 |
| `BLOCKED_CANON_CHANGED` | false | Active Canon drift | retry / 200 |
| `BLOCKED_SCOPE_MISMATCH` / `BLOCKED_TIMELINE_UNSUPPORTED` | false | Request outside authority | safe error / 200 |
| `BLOCKED_EXISTING_TURN_CORRUPT` / `BLOCKED_CORRUPT_AUTHORITY` | false | Existing records cannot be verified | safe error / 200 |

### Previous Chapter Completion

The only completion fact is the existing durable
`data/chapter_commits/commit_NNN.json` authority, with the completion statuses
accepted by the sealed Chapter lifecycle service. Missing, malformed,
scope-invalid, or recovery-required completion fails closed. Chapter text,
Candidate state, Review display state, browser state, and inferred numbering
are not completion facts.

### Successor Chapter

The successor identity comes only from one immutable
`ChapterLifecycleService` operation claim paired with its durable result. The
claim must bind the requested previous Chapter, authoritative `main` timeline,
and active Branch; the result must identify the published successor. The
aggregator never derives the successor by scanning Chapter files or by adding
one to a current value.

A claim without a durable result is
`BLOCKED_LIFECYCLE_INCOMPLETE`. A durable result is accepted only when the
result, immutable claim, completion phase, published Chapter, initialized
Version index, initialized Canon index, and lifecycle resolver projection
agree.

### Branch

Readiness binds the project ID, `main` timeline, active Branch ID, Branch
registry revision, canonical registry SHA-256, and lifecycle status. Missing,
inactive, archived, corrupt, changed, or scope-mismatched Branch authority
fails closed.

The global lock order for start is:

1. Chapter project/timeline authority lock;
2. Branch registry lock;
3. cross-chapter start operation lock;
4. Narrative Turn component-local immutable publication.

Branch archive takes the first two locks in the same order and rejects an
incomplete cross-chapter start bound to the target Branch.

### Planning, Source, and Canon

The existing `NarrativeTurnContextBinder` is the semantic authority. It reads
the actual planning inputs used by Turn planning, selected successor source,
active Canon, rolling window, dependencies, schedule, and Branch state, then
produces their stable context fingerprint. The readiness projection binds the
selected source version ID, source fingerprint, Canon revision, planning
revision, and full Turn context fingerprint.

The start claim freezes those identities plus the lifecycle result hash and
Branch authority. An incomplete replay re-runs readiness and requires the same
authority fingerprint. Drift fails closed as `TURN_START_SOURCE_CHANGED`; it
never silently adopts new inputs.

### Existing Turn

The existing `NarrativeTurnStore` plan directory is the sole plan store. A
valid plan for the successor in the bound scope means
`TURN_ALREADY_STARTED`. Corrupt plan authority fails closed. No second initial
Turn is permitted.

## Readiness Contract

`CrossChapterReadinessService.readiness()` is a pure read. It creates no
directory, lock owner, operation, phase, result, Chapter, Version, Canon, Turn,
Candidate, Review, or repair artifact. Repeated reads of one filesystem
snapshot are deterministically equivalent.

The safe DTO contains:

- project, timeline, Branch, previous and successor identities;
- `readiness_code`, `ready_to_start_turn`, and granular blocking reasons;
- one deterministic `authority_fingerprint`;
- lifecycle operation ID;
- existing Turn ID and status when present;
- safe source, Canon, planning, and Branch identity fields needed for an
  optimistic start fence.

It never exposes absolute paths, lock owners, temporary names, credentials,
tracebacks, or raw exceptions.

## Start Contract

`CrossChapterTurnStartService.start_turn()` is invoked only by explicit POST:

```text
fresh readiness
  -> immutable start claim
  -> existing context/planner/feasibility/preview/store authority
  -> durable start result
  -> completed phase
```

The caller supplies a stable operation ID and the expected readiness
fingerprint. The immutable claim binds the request and every readiness
authority input. Same operation plus same request replays the byte-stable
durable result. Same operation plus a different request returns
`OPERATION_CONFLICT`.

The delegated Turn work uses `NarrativeTurnContextBinder`,
`NarrativeTurnPlanner`, `NarrativeActionFeasibility`,
`NarrativeTurnPreviewService`, and `NarrativeTurnStore`. It publishes exactly
one initial plan, one legal `planned -> awaiting_action` transition, and stores
the deterministic read-only preview in the start result. It does not confirm
an action, append a Turn result, project Branch state, compile a Candidate,
approve Review, commit a Chapter, update Canon/Chroma, create another Chapter,
or change Branch lifecycle.

Recovery records a phase only after its durable effect. A plan published
before response/result loss is reused by replay. A durable result without a
completed phase repairs only the phase. Completed results are historical and
are returned without reinterpretation.

## Filesystem Boundary

Readiness allows no diff.

Successful start may add only:

- `data/chapter_progression/operations/<operation>.json`
- `data/chapter_progression/operations/<operation>.phase.json`
- `data/chapter_progression/operations/<operation>.result.json`
- `data/narrative_turn/plans/main/<branch>/<turn>.json`
- `data/narrative_turn/transitions/main/<branch>/<turn>/...json`

Lock directories and atomic temporary files are transient and must not remain
after terminal success.

## HTTP Boundary

- `GET /api/chapter-progression/readiness` is no-store and pure read.
- `POST /api/chapter-progression/start-turn` is the only start entry.

The POST DTO binds operation, project, timeline, Branch, previous/successor
Chapter IDs, and expected readiness fingerprint. Routes perform validation and
safe error mapping but do not resolve successors or write Turn data directly.

This is Simulator-only backend behavior. Traditional behavior and all
production frontend files remain unchanged.

## Non-Goals

- No automatic Turn start.
- No progression UI.
- No Provider or external network call.
- No multi-timeline Chapter storage.
- No modification of sealed Chapter lifecycle semantics.
- No next phase authorization.

## RC1 Implementation Status

RC1 is implemented and ready for owner review. It replaces ambiguous
lifecycle record selection with exact-one bundle validation, makes durable
start replay validate the initial plan and first transition, shares initial
Turn arbitration with Narrative Turn confirmation, and requires that complete
terminal bundle before Branch archive. See `PHASE_0D6_B_RC1.md` and its
delivery report for the recovery and validation contract.

## FV1 Verification Status

FV1 is **PARTIALLY PASSED — RC2 REQUIRED** and is not a seal. Verification
found three genuine gaps: scope-aware classification of orphan lifecycle
artifacts, fail-closed handling when a plan phase exists without its effect,
and rejection of result-only progression artifacts during archive. See
`PHASE_0D6_B_FV1.md` and `PHASE_0D6_B_FV1_DELIVERY_REPORT.md` for evidence and
the minimal RC2 scope. Phase 0D6-A remains sealed.

## RC2 Implementation Status

RC2 fixes all three FV1 defects within the authorized scope: shared
scope-aware orphan classification, fail-closed phase-without-effect replay,
and all-artifact progression archive scanning. The RC2 focused and associated
regression gates are green. Phase 0D6-B is **PASSED — READY FOR FV2**; it is
not itself a seal for the entire 0D6 program. See
`PHASE_0D6_B_RC2.md` and `PHASE_0D6_B_RC2_DELIVERY_REPORT.md`.

## FV2 Verification Status

FV2 independently revalidated RC1/FV1/RC2 scope, recovery, archive, route, and
filesystem contracts. Focused and associated gates passed: 71, 259, and 105
respectively. The broad comparison changed from the known 2239/33/7 baseline
to 2299/34/7, but the baseline lacks failure-file identities; therefore the
result is **PARTIALLY PASSED — BROAD COMPARISON INCOMPLETE**, not an automatic
owner seal. See `PHASE_0D6_B_FV2.md` and
`PHASE_0D6_B_FV2_DELIVERY_REPORT.md`. Phase 0D6-A remains sealed.

## RC4 Compatibility Status

RC4 closed the five RC3 uncertain rows. The minimal narrative arbitration fix
restored the 0D4-D first-writer contract without weakening exactly-once or
shared-lock semantics. The final broad result is `2283 passed, 50 failed, 7
skipped`; the two RC3 narrative/concurrency nodes are RC3-only and no new node
entered the set. Phase 0D6-B is **PASSED — READY FOR OWNER SEAL** pending owner
action. See `PHASE_0D6_B_RC4.md` and
`PHASE_0D6_B_BROAD_FAILURE_MANIFEST_RC4.md`. Phase 0D6-A remains sealed.

## RC3 Attribution Status

RC3 created the complete current broad failure manifest and performed the
allowed attribution reruns. The final broad result is `2281 passed, 52 failed,
7 skipped`; five narrative/locking/route failures remain intentionally
uncertain, and the historical `2239/33/7` record has no node identities. The
status is **PARTIALLY PASSED — ATTRIBUTION INCOMPLETE**, not an owner seal. See
`PHASE_0D6_B_RC3.md` and `PHASE_0D6_B_BROAD_FAILURE_MANIFEST.md`. Phase 0D6-A
remains sealed.

## Owner Seal Status

Phase 0D6-B was owner-sealed on 2026-07-28 after RC4 restored the 0D4-D
first-writer compatibility contract and the RC3-to-RC4 broad failure node-set
comparison showed no new failure nodes.

Final evidence:

- 0D6-B focused: 71 passed.
- 0D4-D post-fix: 5/5 isolated and 3/3 combined with 0D4-E2.
- Final broad: 2283 passed, 50 failed, 7 skipped.
- RC3-to-RC4: intersection 50, RC3-only 2, RC4-only 0.

Broad suite remains non-green and is explicitly preserved as accepted evidence;
it is not represented as full-repository health. Phase 0D6-A remains sealed.
Later phases and Provider Live remain unauthorized. See
`PHASE_0D6_B_SEAL.md` and `PHASE_0D6_B_SEAL_DELIVERY_REPORT.md`.
