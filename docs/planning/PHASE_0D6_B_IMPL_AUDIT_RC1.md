# Phase 0D6-B-IMPL-AUDIT-RC1

## Stage Purpose

This is a read-only inventory and authority-gap audit of the implementation
already present in the dirty Story OS worktree. It does not repair production
code, tests, routes, DTOs, configuration, dependencies, or UI. Phase 0D6-A is
audited as sealed authority and remains unchanged.

## Worktree Baseline

Audit root: `D:/novel/StoryOS/story-os-demo`.

The audit began with a dirty worktree containing 38 tracked changed files and
many untracked Phase 0D4/0D5/0D6 files. Relevant pre-existing 0D6-B files were
the two cross-chapter services, the progression route, the progression test,
the modified application/schema registration, and the Branch lifecycle archive
hook. No reset, restore, stash, clean, delete, checkout, commit, add, push,
merge, or rebase operation was performed.

## Changed File Inventory

### Pre-existing 0D6-B production changes audited

- `story-os-demo/system/cross_chapter_readiness_service.py`
- `story-os-demo/system/cross_chapter_turn_start_service.py`
- `story-os-demo/system/narrative_branch_lifecycle_service.py`
- `story-os-demo/web/chapter_progression_routes.py`
- `story-os-demo/web/schemas.py`
- `story-os-demo/web/app.py`

The sealed Chapter lifecycle and Turn/Branch foundations were also audited at
their existing changed paths. The broad dirty worktree includes unrelated
historical changes outside this audit scope.

### Pre-existing 0D6-B test changes audited

- `story-os-demo/tests/test_phase0d6b_authority.py`

### Documents created by this audit

- `docs/planning/PHASE_0D6_B_IMPL_AUDIT_RC1.md`
- `docs/planning/PHASE_0D6_B_IMPL_AUDIT_RC1_DELIVERY_REPORT.md`

## Readiness Call Graph

```text
GET /api/chapter-progression/readiness
  -> web.chapter_progression_routes.readiness
  -> CrossChapterReadinessService.readiness
  -> ChapterLifecycleService._completion_authority
  -> ChapterLifecycleService._branch_authority
  -> NarrativeBranchStore.get_branch
  -> CrossChapterReadinessService._lifecycle_candidates
  -> ChapterLifecycleService.resolve_next_chapter
  -> NarrativeTurnContextBinder.bind
       -> selected Version/source, Canon, planning, branch context
  -> NarrativeTurnStore.list_plans/get_plan/get_current_state
  -> readiness DTO/fingerprint
```

The route and service perform no writes in the tested READY and blocked cases.
The resolver itself is pure read. However, `_lifecycle_candidates` scans the
operation directory and chooses `sorted(matching, key=lambda x: x[0])[0]` after
only checking that all matching operations point to one successor. The sealed
resolver does not return an operation ID, so the association is inferred by a
second directory scan rather than supplied by the resolver.

## Start Call Graph

```text
POST /api/chapter-progression/start-turn
  -> ChapterProgressionStartRequest validation
  -> CrossChapterTurnStartService.start_turn
  -> timeline authority lock
  -> BranchLifecycleService._registry_lock
  -> cross-chapter operation lock
  -> fresh readiness
  -> immutable chapter_progression operation claim + claimed phase
  -> NarrativeTurnContextBinder.bind
  -> NarrativeTurnPlanner.build_plan
  -> NarrativeTurnStore.append_plan
  -> plan_published phase
  -> NarrativeTurnService._append_transition_safe
       -> NarrativeTurnStore.append_transition
  -> turn_started phase
  -> NarrativeActionFeasibility.validate_recommended
  -> NarrativeTurnPreviewService.preview_recommended
  -> chapter_progression result
  -> completed phase
```

The client successor is compared with the fresh server projection before the
claim. The initial plan is scoped to project/timeline/branch/chapter and the
transition is scoped to the same `turn_id`. No confirmation, Candidate,
Review, Commit, Canon, Chroma, Chapter, or Version mutation was observed.

The durable phases currently present are `claimed`, `plan_published`,
`turn_started`, and `completed`; there is no separate durable
`awaiting_action_transition_published` or `result_published` phase.

## Archive Call Graph

```text
BranchLifecycleService.archive
  -> ChapterLifecycleService.timeline_authority_lock
  -> BranchLifecycleService._registry_lock
  -> ChapterLifecycleService.assert_branch_archive_safe
  -> CrossChapterTurnStartService.assert_branch_archive_safe
  -> Branch registry archive mutation
```

The lock order is consistent with the sealed Chapter/archive order. The
progression scan is scoped by timeline and branch within the current project
context, but its predicate treats any existing `.result.json` as complete and
does not require a valid completed phase or result/claim validation.

## Lifecycle Resolution Audit

| Finding | Classification | Evidence |
|---|---|---|
| Resolver is invoked | A | `CrossChapterReadinessService.readiness` calls `resolve_next_chapter` |
| Resolver returns lifecycle operation ID | C | `resolve_next_chapter` returns status/next ID, not operation ID |
| Secondary operation directory scan exists | D | `_lifecycle_candidates` scans `chapter_lifecycle/operations` |
| Lexical operation selection exists | D | `sorted(matching, key=lambda x: x[0])[0]` |
| Conflicting successor IDs fail closed | A | successor set size is checked |
| Multiple same-successor authority conflicts fail closed | D | same-successor operations are not compared; first sorted operation is chosen |
| Claim/result/phase association is fully verified | D | operation ID, claim request/result identity, and resolver operation identity are not all cross-checked |
| Result without phase | D | candidate is marked incomplete, but orphan result/phase records are not independently classified |
| Phase without result | D | claim is incomplete; orphan phase is not detected as corrupt |
| Corrupt result fingerprint | A | outcome fingerprint is checked when a claim is encountered |
| Published assets and resolver agree | A | resolver status and successor ID/assets are compared |

This is the primary authority conflict: the implementation has a second
authority selector beside the sealed resolver. It must not be resolved by
mtime, directory order, or operation ID ordering.

## Client Assertion Audit

The DTO validates operation ID, project/timeline/branch IDs, previous and
successor Chapter IDs, and a SHA-256 readiness fingerprint. The service
recomputes readiness and rejects a successor or fingerprint mismatch before
claim publication. This is authority-consistent for the covered path.

The missing explicit safe-code distinction is `TURN_START_READINESS_CHANGED`
versus the current `TURN_START_SOURCE_CHANGED`; this is a documentation/status
gap, not evidence that the client became the authority.

## Readiness Status Matrix Audit

Implemented codes include `READY_TO_START_TURN`, `TURN_ALREADY_STARTED`,
completion blockers, lifecycle not-created/incomplete/conflict, successor
visibility/assets blockers, branch blockers, scope/timeline blockers, source
missing, and corrupt authority. GET returns a no-store business envelope and
the focused tests verify zero filesystem diff.

Missing or collapsed distinctions:

- planning missing/stale are generally surfaced through source/binder failure;
- source changed and Canon changed are primarily start-time freshness failures;
- existing Turn corruption has no dedicated `BLOCKED_EXISTING_TURN_CORRUPT` code;
- incomplete start uses an additional `BLOCKED_TURN_START_INCOMPLETE` code not
  included in the original matrix;
- HTTP business-code mapping is route-local and not a shared safe error DTO.

## Initial Turn Identity Audit

The real store uses `NarrativeTurnPlan` fields for project, timeline, branch,
chapter, `turn_id`, source/context/planning/Canon fingerprints, and the plan
fingerprint. `NarrativeTurnTransition` repeats scope and `turn_id`, carries
`operation_id`, and enforces sequence `0` for the first transition. There is no
separate turn ordinal/index.

The implementation correctly filters plans by successor chapter and scope and
creates `planned -> awaiting_action`. It does not persist a plan operation ID
inside the plan record; the association lives in the progression claim/result
and transition operation ID. Multiple plans for the same successor are reduced
to the lexically first valid plan instead of being declared a conflict. A
transition-only or plan/transition mismatch is not covered by the current
focused tests.

## Plan/Transition Recovery Audit

Covered behavior:

- claim crash leaves a claim and replay can continue;
- plan publication response loss does not publish a second plan;
- result response loss repairs a missing completed phase;
- same operation replay is byte-stable;
- different request conflicts.

Gaps:

- no dedicated phase after transition publication;
- no fault hook between transition effect and phase;
- no validation that an existing result's fingerprint, plan fingerprint,
  transition fingerprint, scope, and status all agree before replay;
- no explicit phase-without-effect repair/fail-closed matrix;
- no duplicate initial transition or duplicate initial plan corruption tests.

## Archive Blocking Audit

The archive hook is inside the existing timeline and registry locks, so the
Chapter create/archive lock order remains intact. It detects claim-only and
plan/transition-pending operations when no result exists, and corrupt claim
JSON fails closed.

It does not currently require `completed` phase when a result exists. Thus a
progression result with a missing completed phase can be archived without
recovery, contrary to the contract. The scan also does not validate result
fingerprint, claim binding, or operation type before allowing completion.

## Filesystem Boundary Audit

Focused tests verify GET zero-diff and successful start creates one progression
claim/phase/result, one plan, and one transition. No Chapter, Version, Canon,
Branch registry, Candidate, Review, Commit, Chroma, or Obsidian mutation was
observed.

The successful allowlist is therefore substantially correct. The unresolved
boundary is partial-state interpretation: a result/phase mismatch may be
treated as terminal by archive, and malformed orphan phase/result files are not
always surfaced as corrupt authority by readiness.

## 0D6-A Regression Audit

The Chapter lifecycle resolver, completion/planning/branch authority checks,
main-timeline restriction, timeline authority lock, and archive integration
remain present. The progression archive query is additive and does not rewrite
Chapter lifecycle claim/result/phase schemas or Chapter publication semantics.
The focused 0D6-A and Branch/Turn regression passed, so this audit found no
evidence of a sealed semantic regression. The archive false-terminal behavior
is a 0D6-B gap requiring repair, not permission to alter 0D6-A.

## Test Coverage Matrix

| Area | Covered | Gap |
|---|---|---|
| readiness pure read | yes | blocked-state full zero-diff matrix |
| lifecycle resolution | partial | multiple same-successor conflicts, orphan records |
| client assertions | partial | explicit scope/status-code matrix |
| status matrix | partial | planning/source/Canon/existing-corrupt distinctions |
| initial Turn identity | partial | ordinal absence, duplicate/corrupt plan/transition |
| plan recovery | partial | phase/effect permutations |
| transition recovery | no | no dedicated fault matrix |
| same-operation replay | yes | result integrity validation |
| operation conflict | yes | — |
| start/start race | yes | external Turn writer race |
| start/archive race | partial | result-without-phase case |
| planning/source/Canon drift | no focused cases | required |
| cross-scope isolation | partial | required matrix |
| filesystem allowlist | partial | corrupt partial state |
| 0D6-A regression | yes | — |
| real/static guards | not rerun in this audit | use prior phase evidence |

## Validation Ledger

| Validation | Passed | Failed | Skipped | Exit |
|---|---:|---:|---:|---:|
| Modified 0D6-B Python `py_compile` | 6 modules | 0 | 0 | 0 |
| `tests/test_phase0d6b_authority.py` | 10 | 0 | 0 | 0 |
| 0D6-A + Branch + Narrative Turn focused regression | 259 | 0 | 0 | 0 |

No full-suite rerun was required by this audit prompt. The earlier broad run
in the same worktree reported 2,239 passed, 33 failed, 7 skipped; those broad
failures are retained as evidence and were not repaired here.

## Authority Gap Matrix

### P0

- Lifecycle authority is selected by a secondary directory scan and lexical
  ordering when the sealed resolver does not supply an operation ID.
- Multiple completed same-successor operations with differing claims can be
  silently reduced to one result.
- Existing start result replay does not validate its binding to plan,
  transition, claim, scope, or result fingerprint.

### P1

- Archive treats result-without-completed-phase as terminal.
- Plan/transition partial states lack explicit phase/effect recovery protocol.
- External initial Turn creation is not serialized by the progression lock.
- Orphan/corrupt phase/result records are not uniformly classified.

### P2

- Status code matrix and safe error mapping need documentation and focused
  route coverage.
- Initial Turn ordinal/operation association is implicit rather than explicitly
  documented in the durable DTO contract.

## Repair Plan

1. P0 — Add one authoritative lifecycle-resolution adapter or durable operation
   reference returned/verified by the sealed resolver; reject all conflicting
   claim/result/phase associations. Repair locations: the cross-chapter
   readiness service and focused authority tests. 0D6-A impact: must remain
   additive and requires owner review if sealed resolver output changes.
2. P0 — Validate progression result, claim, plan, transition, scope, chapter,
   operation, and fingerprints before replay. Repair location: start service
   and store-facing tests. 0D6-A impact: none if no Chapter semantics change.
3. P1 — Split plan publication, transition publication, result publication,
   and completed phases with deterministic fault/replay hooks. Repair location:
   start service/tests. 0D6-A impact: none.
4. P1 — Make archive block any target-bound claim lacking a validated result
   and completed phase, while ignoring sibling scopes. Repair location: shared
   archive query/start service. 0D6-A impact: preserve existing Chapter check
   and lock order; owner decision only if shared helper changes.
5. P1 — Add external Turn-writer concurrency protection or a documented
   shared component lock. Repair location: Turn/start boundary. 0D6-A impact:
   none, but requires owner approval because it touches Turn authority.
6. P2 — Complete status matrix, safe error mapping, and filesystem/cross-scope
   test coverage. Repair locations: docs/routes/tests.

## Non-Goals

No cleanup, rollback, production repair, test repair, UI work, Provider,
network, Chroma, Obsidian, Candidate, Review, Commit, multi-timeline creation,
Git write, or next-phase work occurred.
